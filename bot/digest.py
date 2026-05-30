from __future__ import annotations

import datetime
import logging
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Digest, Filter, Post

PROMPTS_DIR = Path(__file__).parent / "prompts"

logger = logging.getLogger(__name__)


async def generate_digest(user_id: int, manual: bool = False) -> Digest | None:
    async with async_session() as session:
        since_result = await session.execute(
            select(Digest)
            .where(Digest.user_id == user_id)
            .order_by(Digest.created_at.desc())
            .limit(1)
        )
        last_digest = since_result.scalar_one_or_none()
        since = last_digest.period_end if last_digest else datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc
        )

        result = await session.execute(
            select(Post)
            .join(Post.channel)
            .options(selectinload(Post.channel))
            .where(
                Channel.user_id == user_id,
                Post.classification.in_(["normal", "highlight"]),
                Post.summary.is_(None),
            )
        )
        posts = result.scalars().all()

    if not posts:
        logger.info("No unsummarized posts for user %d", user_id)
        return None

    highlight_posts = [p for p in posts if p.classification == "highlight"]
    normal_posts = [p for p in posts if p.classification == "normal"]

    highlight_kw = await _load_highlight_filters(user_id)
    content = await _generate_text(highlight_posts, normal_posts, highlight_kw)

    skipped = await _count_skipped(user_id)

    if skipped > 0:
        content += f"\n\n---\n_Пропущено {skipped} постов: реклама, спам, нерелевантный контент._"

    period_start = since
    period_end = datetime.datetime.now(datetime.timezone.utc)

    async with async_session() as session:
        digest = Digest(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            content=content,
        )
        session.add(digest)

        for p in posts:
            db_post = await session.get(Post, p.id)
            if db_post:
                db_post.summary = "digested"

        await session.commit()
        await session.refresh(digest)

    return digest


async def _load_highlight_filters(user_id: int) -> list[str]:
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.user_id == user_id, Filter.type == "highlight")
        )
        return [f.value for f in result.scalars().all()]


async def _count_skipped(user_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(Post)
            .join(Post.channel)
            .where(Channel.user_id == user_id, Post.classification == "ignore")
        )
        return len(result.scalars().all())


async def _generate_text(
    highlight_posts: list[Post],
    normal_posts: list[Post],
    highlight_kw: list[str],
) -> str:
    posts_text_parts: list[str] = []

    for p in highlight_posts:
        channel_name = p.channel.channel_title or p.channel.channel_username
        text = p.text or ""
        link = p.post_link or ""
        posts_text_parts.append(
            f"[HIGHLIGHT] Channel: {channel_name}\nLink: {link}\nText: {text[:2000]}"
        )

    for p in normal_posts:
        channel_name = p.channel.channel_title or p.channel.channel_username
        text = p.text or ""
        link = p.post_link or ""
        posts_text_parts.append(
            f"Channel: {channel_name}\nLink: {link}\nText: {text[:1000]}"
        )

    if not posts_text_parts:
        return "Нет постов для дайджеста."

    highlights_formatted = ", ".join(highlight_kw) if highlight_kw else "не заданы"
    posts_block = "\n\n---\n\n".join(posts_text_parts[:30])

    template = (PROMPTS_DIR / "digest.md").read_text(encoding="utf-8")
    prompt = template.format(
        highlight_topics=highlights_formatted,
        posts_block=posts_block,
    )

    client = AsyncOpenAI(
        api_key=config.deepseek_key, base_url="https://api.deepseek.com/v1"
    )

    response = await client.chat.completions.create(
        model=config.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=3000,
    )

    return response.choices[0].message.content or "Не удалось сгенерировать дайджест."
