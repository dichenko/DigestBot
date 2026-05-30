from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Dispatcher

from bot.bot_instance import bot
from bot.config import config
from bot.db import engine
from bot.handlers import router
from bot.models import Base
from bot.reader import reader
from bot.monitor import monitor_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(router)


async def on_startup() -> None:
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        sys.exit(1)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await reader.start()
    asyncio.create_task(monitor_loop())

    logger.info("Bot started (monitor interval=%d min)", config.monitor_interval_minutes)


async def on_shutdown() -> None:
    await reader.stop()
    await engine.dispose()
    logger.info("Bot stopped")


async def main() -> None:
    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
