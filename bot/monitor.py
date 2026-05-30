from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging

from sqlalchemy import select, desc

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Post, User
from bot.extractor import apply_hard_filters, process_features, _log_event
from bot.reader import reader
from bot.scoring import calculate_score

logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(1)


async def monitor_loop() -> None:
    logger.info("Monitor loop started (interval=%d min)", config.monitor_interval_minutes)

    while True:
        async with SEMAPHORE:
            try:
                await run_monitor_cycle()
            except Exception:
                logger.exception("Monitor cycle failed")

        await asyncio.sleep(config.monitor_interval_minutes * 60)


async def run_monitor_cycle() -> None:
    logger.info("Monitor cycle start")

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_active.is_(True))
        )
        users = result.scalars().all()

    if not users:
        logger.warning("No active users found")
        return

    for user in users:
        await _monitor_user(user)


async def _monitor_user(user: User) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Channel).where(
                Channel.user_id == user.id,
                Channel.is_active.is_(True),
            )
        )
        channels = result.scalars().all()

    if not channels:
        return

    total_new = 0
    total_sent = 0

    for i, ch in enumerate(channels):
        if i > 0:
            await asyncio.sleep(1.5)

        new_posts = await _fetch_new_posts(ch, user)
        total_new += new_posts

        sent = await _process_channel_posts(ch, user)
        total_sent += sent

    logger.info(
        "Monitor: user=%d channels=%d new=%d sent=%d",
        user.telegram_id, len(channels), total_new, total_sent,
    )


async def _fetch_new_posts(ch: Channel, user: User) -> int:
    since_id = ch.last_seen_message_id
    if since_id is None:
        since_id = 0

    raw_posts = await reader.fetch_posts(ch.channel_address, since=None, limit=config.max_posts_per_run)

    new_count = 0
    max_id = ch.last_seen_message_id or 0

    async with async_session() as session:
        for rp in raw_posts:
            existing = await session.execute(
                select(Post).where(
                    Post.channel_id == ch.id,
                    Post.telegram_message_id == rp["message_id"],
                )
            )
            if existing.scalar_one_or_none():
                continue

            text_hash = hashlib.sha256((rp["text"] or "").encode()).hexdigest()
            post = Post(
                channel_id=ch.id,
                telegram_message_id=rp["message_id"],
                source_url=rp["link"],
                text=rp["text"],
                text_hash=text_hash,
                published_at=rp["date"],
                processing_status="new",
            )
            session.add(post)
            new_count += 1

            if rp["message_id"] > max_id:
                max_id = rp["message_id"]

        if max_id > (ch.last_seen_message_id or 0):
            ch.last_seen_message_id = max_id

        ch.last_checked_at = datetime.datetime.now(datetime.timezone.utc)
        await session.commit()

    if new_count > 0:
        logger.info("Fetched %d new posts from %s", new_count, ch.channel_address)

    return new_count


async def _process_channel_posts(ch: Channel, user: User) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(Post)
            .where(
                Post.channel_id == ch.id,
                Post.processing_status.in_(["new", "feature_extracted", "scored"]),
                Post.sent_at.is_(None),
            )
            .order_by(Post.id)
        )
        posts = result.scalars().all()

    sent = 0

    for post in posts:
        if post.processing_status == "new":
            skipped = await apply_hard_filters(post)
            if skipped:
                continue

            await process_features(post, ch.channel_address)

            async with async_session() as session:
                p = await session.get(Post, post.id)
                if p and p.processing_status == "feature_extracted" and p.features_json:
                    post.processing_status = p.processing_status
                    post.features_json = p.features_json

        if post.processing_status in ("feature_extracted", "scored") and post.features_json:
            score = await calculate_score(post, ch, user)

            if score >= user.score_threshold:
                await _send_post(post, ch, user, score)
                sent += 1

    return sent


async def _send_post(post: Post, ch: Channel, user: User, score: int) -> None:
    from bot.main import bot

    features = post.features_json or {}
    summary = features.get("summary", "")
    reasoning = features.get("reasoning", "")
    channel_addr = features.get("channel_address", ch.channel_address)
    source_url = post.source_url or f"https://t.me/{ch.channel_address}/{post.telegram_message_id}"

    text = (
        f"🔥 *Полезная новость*\n\n"
        f"*Источник:* @{channel_addr}\n"
        f"*Оценка:* {score}/100\n"
    )
    if summary:
        text += f"\n*Краткое резюме:*\n{summary}\n"
    if reasoning:
        text += f"\n*Почему показал:*\n{reasoning}\n"
    text += f"\n[Открыть источник]({source_url})"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 Больше такого", callback_data=f"f:m:{post.id}"),
                InlineKeyboardButton(text="👎 Меньше такого", callback_data=f"f:l:{post.id}"),
                InlineKeyboardButton(text="⭐ Очень важно", callback_data=f"f:v:{post.id}"),
                InlineKeyboardButton(text="🗑 Скрывать такое", callback_data=f"f:h:{post.id}"),
            ]
        ]
    )

    try:
        await bot.send_message(
            user.telegram_id, text,
            parse_mode="Markdown", disable_web_page_preview=True,
            reply_markup=kb,
        )
        logger.info("Sent post %d to user %d (score=%d)", post.id, user.telegram_id, score)

        async with async_session() as session:
            p = await session.get(Post, post.id)
            if p:
                p.processing_status = "sent"
                p.sent_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
    except Exception:
        logger.exception("Failed to send post %d to user %d", post.id, user.telegram_id)
