from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError
from sqlalchemy import select

from bot.config import config
from bot.db import async_session
from bot.models import Post, Channel, ProcessingLog

PROMPTS_DIR = Path(__file__).parent / "prompts"

logger = logging.getLogger(__name__)

STOP_WORDS = re.compile(
    r"(giveaway|розыгрыш|конкурс|победитель|приз|win\s+a\s+prize|subscribe\s+to|подпишись)",
    re.IGNORECASE,
)
ONLY_LINKS_PATTERN = re.compile(r"^(https?://\S+[\s\n]*)+$", re.IGNORECASE)
ONLY_EMOJI_PATTERN = re.compile(r"^[\U0001F300-\U0001FAFF\s]+$")

RETRY_DELAY = 2


def hard_filter(post: Post) -> tuple[bool, str | None]:
    text = post.text.strip() if post.text else ""

    if not text:
        return True, "empty_text"
    if len(text) < config.min_post_length:
        return True, "too_short"
    if ONLY_LINKS_PATTERN.match(text):
        return True, "only_links"
    if ONLY_EMOJI_PATTERN.match(text):
        return True, "only_emoji"
    if STOP_WORDS.search(text):
        return True, "stop_words"

    return False, None


async def apply_hard_filters(post: Post) -> bool:
    skipped, reason = hard_filter(post)
    if skipped:
        async with async_session() as session:
            p = await session.get(Post, post.id)
            if p:
                p.processing_status = "skipped_hard_filter"
                p.skip_reason = reason
                await session.commit()
        logger.info("Post %d skipped: %s", post.id, reason)
    return skipped


async def _log_event(post_id: int | None, level: str, event: str, details: dict | None = None) -> None:
    async with async_session() as session:
        session.add(ProcessingLog(post_id=post_id, level=level, event=event, details_json=details))
        await session.commit()


async def extract_features(post: Post, channel_address: str) -> dict | None:
    template = (PROMPTS_DIR / "features.md").read_text(encoding="utf-8")
    prompt = template.format(
        channel_address=channel_address,
        post_text=(post.text or "")[:5000],
    )

    client = AsyncOpenAI(api_key=config.deepseek_key, base_url="https://api.deepseek.com/v1")

    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=config.deepseek_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content or ""
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            features = json.loads(raw)
            features["channel_address"] = channel_address
            return features
        except RateLimitError:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("Invalid JSON from LLM for post %d, retrying", post.id)
                await asyncio.sleep(RETRY_DELAY)
            else:
                logger.error("Invalid JSON from LLM for post %d after retry", post.id)
                await _log_event(post.id, "ERROR", "llm_invalid_json", {"raw": raw[:500]})
        except Exception as e:
            logger.error("LLM error for post %d: %s", post.id, e)
            await _log_event(post.id, "ERROR", "llm_error", {"error": str(e)})
            break

    return None


async def process_features(post: Post, channel_address: str) -> None:
    features = await extract_features(post, channel_address)

    async with async_session() as session:
        p = await session.get(Post, post.id)
        if not p:
            return

        if features is None:
            p.processing_status = "failed"
            await session.commit()
            return

        p.features_json = features
        p.processing_status = "feature_extracted"
        await session.commit()

    logger.info("Features extracted for post %d", post.id)
