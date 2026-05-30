from __future__ import annotations

import asyncio
import datetime
import logging

from telethon import TelegramClient, errors
from telethon.tl.types import Message, PeerChannel
from sqlalchemy import select, desc

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Digest, Post

logger = logging.getLogger(__name__)

CHANNEL_FETCH_DELAY = 2.0
RATE_LIMIT_BACKOFF = 30.0
MAX_RETRIES = 3


class PostReader:
    def __init__(self) -> None:
        self._client: TelegramClient | None = None

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise RuntimeError("Telethon client not started")
        return self._client

    async def start(self) -> None:
        self._client = TelegramClient(config.session_name, config.api_id, config.api_hash)
        await self._client.start()
        me = await self._client.get_me()
        logger.info("Telethon connected as @%s (ID: %d)", me.username, me.id)

    async def stop(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def _get_last_digest_time(self, user_id: int) -> datetime.datetime:
        async with async_session() as session:
            result = await session.execute(
                select(Digest)
                .where(Digest.user_id == user_id)
                .order_by(desc(Digest.period_end))
                .limit(1)
            )
            last = result.scalar_one_or_none()
        if last and last.period_end:
            return last.period_end
        return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    async def fetch_posts(
        self, channel_username: str, since: datetime.datetime | None = None, limit: int = 50
    ) -> list[dict]:
        logger.info("Fetching @%s (since=%s, limit=%d)", channel_username, since.isoformat() if since else "none", limit)

        for attempt in range(MAX_RETRIES):
            try:
                entity = await self.client.get_entity(channel_username)
                logger.info("Entity @%s resolved: type=%s", channel_username, type(entity).__name__)
                break
            except errors.FloodWaitError as e:
                wait = e.seconds + 5
                logger.warning("Flood wait %ds for @%s, attempt %d/%d", e.seconds, channel_username, attempt + 1, MAX_RETRIES)
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error("Failed to resolve @%s: %s (%s)", channel_username, type(e).__name__, e)
                return []
        else:
            logger.error("Exhausted retries for @%s", channel_username)
            return []

        posts: list[dict] = []
        try:
            async for msg in self.client.iter_messages(entity, limit=limit):
                if not isinstance(msg, Message):
                    continue
                if not msg.text and not msg.message:
                    continue

                msg_date = msg.date.replace(tzinfo=datetime.timezone.utc) if msg.date else None
                if since and msg_date and msg_date < since:
                    logger.debug("Reached old messages at @%s (msg date %s < since %s)", channel_username, msg_date, since)
                    break

                link = ""
                if isinstance(msg.peer_id, PeerChannel):
                    link = f"https://t.me/{channel_username}/{msg.id}"
                elif msg.chat and hasattr(msg.chat, "username") and msg.chat.username:
                    link = f"https://t.me/{msg.chat.username}/{msg.id}"

                posts.append(
                    {
                        "message_id": msg.id,
                        "text": msg.text or msg.message or "",
                        "link": link,
                        "date": msg_date,
                    }
                )
        except errors.FloodWaitError as e:
            logger.warning("Flood wait %ds while reading @%s", e.seconds, channel_username)
        except Exception as e:
            logger.error("Error fetching posts from @%s: %s (%s)", channel_username, type(e).__name__, e)

        logger.info("Fetched %d raw posts from @%s", len(posts), channel_username)
        return posts

    async def collect_posts_for_user(self, user_id: int) -> int:
        since = await self._get_last_digest_time(user_id)
        logger.info("Collecting posts for user %d since %s", user_id, since.isoformat())

        async with async_session() as session:
            result = await session.execute(
                select(Channel).where(
                    Channel.user_id == user_id, Channel.is_active.is_(True)
                )
            )
            channels = result.scalars().all()

        logger.info("Found %d active channels for user %d", len(channels), user_id)
        total_new = 0

        for i, ch in enumerate(channels):
            if i > 0:
                await asyncio.sleep(CHANNEL_FETCH_DELAY)

            raw_posts = await self.fetch_posts(ch.channel_username, since=since)
            new_for_channel = 0

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

                    post = Post(
                        channel_id=ch.id,
                        telegram_message_id=rp["message_id"],
                        text=rp["text"],
                        post_link=rp["link"],
                        published_at=rp["date"],
                    )
                    session.add(post)
                    new_for_channel += 1
                await session.commit()

            logger.info("Saved %d new posts from @%s (%s)", new_for_channel, ch.channel_username, ch.channel_title or "-")
            total_new += new_for_channel

        logger.info("Total: %d new posts for user %d", total_new, user_id)
        return total_new


reader = PostReader()
