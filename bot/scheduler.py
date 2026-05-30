from __future__ import annotations

import asyncio
import datetime
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import config
from bot.reader import reader
from bot.classifier import classify_posts
from bot.digest import generate_digest

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=config.timezone)


def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.strip().split(":")
    return int(parts[0]), int(parts[1])


async def _scheduled_digest_job() -> None:
    owner_id = config.owner_id
    logger.info("Scheduled digest job started for owner %d", owner_id)

    try:
        collected = await reader.collect_posts_for_user(owner_id)
        logger.info("Collected %d posts", collected)

        if collected > 0:
            await classify_posts(owner_id)

        digest = await generate_digest(owner_id)
        if digest and digest.content:
            from bot.main import bot
            await bot.send_message(
                owner_id, digest.content, parse_mode="Markdown", disable_web_page_preview=True
            )
            logger.info("Digest sent to owner %d", owner_id)
        else:
            from bot.main import bot
            await bot.send_message(
                owner_id, "Нет полезных постов за этот период."
            )
            logger.info("Empty digest notified to owner %d", owner_id)
    except Exception:
        logger.exception("Failed scheduled digest for owner %d", owner_id)


def start_scheduler() -> None:
    m_h, m_m = _parse_time(config.morning_time)
    e_h, e_m = _parse_time(config.evening_time)

    scheduler.add_job(
        _scheduled_digest_job,
        CronTrigger(hour=m_h, minute=m_m, timezone=config.timezone),
        id="morning_digest",
    )
    scheduler.add_job(
        _scheduled_digest_job,
        CronTrigger(hour=e_h, minute=e_m, timezone=config.timezone),
        id="evening_digest",
    )

    scheduler.start()
    logger.info("Scheduler started: morning=%s, evening=%s", config.morning_time, config.evening_time)
