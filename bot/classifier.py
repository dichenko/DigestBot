from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError
from sqlalchemy import select

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Filter, Post

PROMPTS_DIR = Path(__file__).parent / "prompts"

logger = logging.getLogger(__name__)

PRE_FILTER_MIN_LENGTH = 50
PRE_FILTER_ONLY_LINKS_PATTERN = re.compile(
    r"^(https?://\S+[\s\n]*)+$", re.IGNORECASE
)
LLM_CALL_DELAY = 0.5
LLM_MAX_RETRIES = 3
LLM_BACKOFF_BASE = 2.0
API_SEMAPHORE = asyncio.Semaphore(3)


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.deepseek_key, base_url="https://api.deepseek.com/v1"
    )


async def _load_filters(user_id: int) -> dict[str, list[str]]:
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.user_id == user_id)
        )
        rows = result.scalars().all()

    ignore: list[str] = []
    highlight: list[str] = []
    for f in rows:
        if f.type == "ignore":
            ignore.append(f.value)
        elif f.type == "highlight":
            highlight.append(f.value)
    return {"ignore": ignore, "highlight": highlight}


def _pre_filter(text: str, ignore_keywords: list[str]) -> str | None:
    if not text or len(text.strip()) < PRE_FILTER_MIN_LENGTH:
        return "ignore"
    if PRE_FILTER_ONLY_LINKS_PATTERN.match(text.strip()):
        return "ignore"
    text_lower = text.lower()
    for kw in ignore_keywords:
        if kw.lower() in text_lower:
            return "ignore"
    return None


async def classify_posts(user_id: int) -> None:
    filters_data = await _load_filters(user_id)
    ignore_kw = filters_data["ignore"]
    highlight_kw = filters_data["highlight"]

    async with async_session() as session:
        result = await session.execute(
            select(Post)
            .join(Post.channel)
            .where(Channel.user_id == user_id, Post.classification.is_(None))
        )
        unclassified = result.scalars().all()

    if not unclassified:
        return

    client = _build_client()

    for i, post in enumerate(unclassified):
        pre_result = _pre_filter(post.text or "", ignore_kw)
        if pre_result == "ignore":
            async with async_session() as session:
                p = await session.get(Post, post.id)
                if p:
                    p.classification = "ignore"
                    await session.commit()
            continue

        if not highlight_kw and not ignore_kw:
            async with async_session() as session:
                p = await session.get(Post, post.id)
                if p:
                    p.classification = "normal"
                    await session.commit()
            continue

        if i > 0:
            await asyncio.sleep(LLM_CALL_DELAY)

        async with API_SEMAPHORE:
            try:
                cls_result = await _llm_classify(client, post.text or "", ignore_kw, highlight_kw)
            except Exception as e:
                logger.error("LLM classify error for post %d: %s", post.id, e)
                cls_result = {"classification": "normal", "reason": "classification error"}

        async with async_session() as session:
            p = await session.get(Post, post.id)
            if p:
                p.classification = cls_result.get("classification", "normal")
                await session.commit()


async def _llm_classify(
    client: AsyncOpenAI, text: str, ignore_topics: list[str], highlight_topics: list[str]
) -> dict:
    template = (PROMPTS_DIR / "classify.md").read_text(encoding="utf-8")
    prompt = template.format(
        ignore_topics="\n".join(f"- {t}" for t in ignore_topics) if ignore_topics else "none",
        highlight_topics="\n".join(f"- {t}" for t in highlight_topics) if highlight_topics else "none",
        post_text=text[:3000],
    )

    for attempt in range(LLM_MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model=config.deepseek_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
            raw = response.choices[0].message.content or "{}"
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(raw)
        except RateLimitError:
            wait = LLM_BACKOFF_BASE ** (attempt + 1)
            logger.warning("DeepSeek rate limit, retrying in %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
        except json.JSONDecodeError:
            return {"classification": "normal", "reason": "parse error"}
        except Exception:
            if attempt == LLM_MAX_RETRIES - 1:
                raise
            await asyncio.sleep(LLM_BACKOFF_BASE ** (attempt + 1))

    return {"classification": "normal", "reason": "rate limit exhausted"}
