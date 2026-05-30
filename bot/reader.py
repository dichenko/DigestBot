from __future__ import annotations

import asyncio
import datetime
import logging

from telethon import TelegramClient, errors
from telethon.tl.types import Message, PeerChannel

from bot.config import config

logger = logging.getLogger(__name__)

CHANNEL_FETCH_DELAY = 2.0
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
                    logger.debug("Reached old messages at @%s", channel_username)
                    break

                link = ""
                if isinstance(msg.peer_id, PeerChannel):
                    link = f"https://t.me/{channel_username}/{msg.id}"
                elif msg.chat and hasattr(msg.chat, "username") and msg.chat.username:
                    link = f"https://t.me/{msg.chat.username}/{msg.id}"

                posts.append({
                    "message_id": msg.id,
                    "text": msg.text or msg.message or "",
                    "link": link,
                    "date": msg_date,
                })
        except errors.FloodWaitError as e:
            logger.warning("Flood wait %ds while reading @%s", e.seconds, channel_username)
        except Exception as e:
            logger.error("Error fetching posts from @%s: %s", channel_username, e)

        logger.info("Fetched %d raw posts from @%s", len(posts), channel_username)
        return posts


reader = PostReader()
