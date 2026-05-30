from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Post, User, UserPreference

logger = logging.getLogger(__name__)

CONTENT_TYPE_DEFAULTS = {
    "tutorial": 10,
    "tool_release": 9,
    "case_study": 8,
    "analysis": 7,
    "news": 4,
    "announcement": 2,
    "opinion": 0,
    "personal_story": -5,
    "job_post": -8,
    "advertisement": -25,
    "meme": -30,
    "low_value_chat": -30,
    "other": 0,
}

TONE_DEFAULTS = {
    "serious": 5,
    "neutral": 2,
    "marketing": -8,
    "hype": -10,
    "humor": -12,
    "aggressive": -8,
    "low_quality": -20,
}

WEIGHT_MIN = -30
WEIGHT_MAX = 30


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


async def _get_preferences(user_id: int) -> dict[tuple[str, str], int]:
    async with async_session() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        prefs = result.scalars().all()
    return {(p.feature_type, p.feature_value): p.weight for p in prefs}


async def calculate_score(post: Post, channel: Channel, user: User) -> int:
    prefs = await _get_preferences(user.id)

    features = post.features_json or {}

    # topic_score
    topic_score = 0
    for topic in features.get("topics", []):
        topic_score += prefs.get(("topic", topic.lower()), 0)
    topic_score = clamp(topic_score, -20, 20)

    # entity_score
    entity_score = 0
    for entity in features.get("entities", []):
        entity_score += prefs.get(("entity", entity.lower()), 0)
    entity_score = clamp(entity_score, -15, 15)

    # content_type_score
    ct = (features.get("content_type") or "other").lower()
    ct_default = CONTENT_TYPE_DEFAULTS.get(ct, 0)
    ct_learned = prefs.get(("content_type", ct), 0)
    content_type_score = clamp(ct_default + ct_learned, -30, 20)

    # tone_score
    tone = (features.get("tone") or "neutral").lower()
    tone_default = TONE_DEFAULTS.get(tone, 0)
    tone_learned = prefs.get(("tone", tone), 0)
    tone_score = clamp(tone_default + tone_learned, -20, 10)

    # channel_score
    channel_addr = features.get("channel_address", "") or channel.channel_address
    channel_learned = prefs.get(("channel_address", channel_addr), 0)
    channel_score = clamp(channel.channel_quality_weight + channel_learned, -25, 25)

    # value_score
    value_score = (
        features.get("practical_value", 0) * 1.5
        + features.get("business_value", 0) * 1.2
        + features.get("technical_depth", 0) * 1.0
        + features.get("novelty", 0) * 0.8
    )
    value_score = clamp(int(value_score), 0, 35)

    # urgency_score
    urgency_score = clamp(int(features.get("urgency", 0) * 0.8), 0, 8)

    # penalties
    noise_penalty = int(features.get("noise_level", 0) * 2)
    ad_penalty = 30 if features.get("is_ad") else 0
    meme_penalty = 35 if features.get("is_meme_or_joke") else 0
    repost_penalty = 20 if features.get("is_repost_without_value") else 0

    score = (
        40
        + topic_score
        + entity_score
        + content_type_score
        + tone_score
        + channel_score
        + value_score
        + urgency_score
        - noise_penalty
        - ad_penalty
        - meme_penalty
        - repost_penalty
    )
    score = clamp(score, 0, 100)

    details = {
        "base": 40,
        "topic_score": topic_score,
        "entity_score": entity_score,
        "content_type_score": content_type_score,
        "tone_score": tone_score,
        "channel_score": channel_score,
        "value_score": value_score,
        "urgency_score": urgency_score,
        "noise_penalty": noise_penalty,
        "ad_penalty": ad_penalty,
        "meme_penalty": meme_penalty,
        "repost_penalty": repost_penalty,
        "final_score": score,
    }

    async with async_session() as session:
        p = await session.get(Post, post.id)
        if p:
            p.final_score = score
            p.score_details_json = details
            p.processing_status = "scored"
            await session.commit()

    if config.enable_debug_scoring:
        logger.info(
            "Score %d for post %d (%s/%s): %s",
            score, post.id, channel.channel_address or "?", features.get("content_type", "?"),
            json.dumps(details, ensure_ascii=False) if score >= 70 else f"{score}/100",
        )

    return score
