from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
SAFE_CHUNK_LENGTH = 4000


def _split_by_paragraphs(text: str, max_len: int = SAFE_CHUNK_LENGTH) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_len:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > max_len:
                for i in range(0, len(para), max_len):
                    chunks.append(para[i : i + max_len])
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


async def send_long_message(bot: Bot, chat_id: int, text: str, parse_mode: str = "Markdown", disable_web_page_preview: bool = True) -> int:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        msg = await bot.send_message(
            chat_id, text, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview
        )
        return 1

    chunks = _split_by_paragraphs(text)
    if not chunks:
        return 0

    for i, chunk in enumerate(chunks):
        prefix = f"({i + 1}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        try:
            await bot.send_message(
                chat_id,
                prefix + chunk,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception:
            await bot.send_message(
                chat_id,
                prefix + chunk,
                disable_web_page_preview=disable_web_page_preview,
            )

    return len(chunks)
