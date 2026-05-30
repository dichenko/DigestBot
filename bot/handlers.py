from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Digest, Filter, Post, User
from bot.digest import generate_digest
from bot.classifier import classify_posts
from bot.reader import reader

logger = logging.getLogger(__name__)

router = Router()


def _is_owner(message: types.Message | types.CallbackQuery) -> bool:
    u = message.from_user
    return u is not None and u.id == config.owner_id


async def _ensure_user(user_id: int) -> None:
    async with async_session() as session:
        existing = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        if not existing.scalar_one_or_none():
            session.add(User(telegram_id=user_id))
            await session.commit()


# --- States ---

class AddChannelState(StatesGroup):
    waiting_for_link = State()


class AddFilterState(StatesGroup):
    waiting_for_value = State()


# --- Main menu ---

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📬 Сгенерировать дайджест")],
            [KeyboardButton(text="📋 Мои каналы"), KeyboardButton(text="➕ Добавить канал")],
            [KeyboardButton(text="🔧 Фильтры"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


# --- /start ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    await _ensure_user(message.from_user.id)
    await message.answer(
        "Привет! Я бот для создания дайджестов из Telegram-каналов.\n\n"
        "Что умею:\n"
        "• Собираю посты из выбранных каналов\n"
        "• Фильтрую шум и рекламу\n"
        "• Выделяю важное\n"
        "• Присылаю дайджест утром и вечером\n\n"
        "Используй кнопки внизу, чтобы управлять.",
        reply_markup=main_menu_kb(),
    )


# --- Add channel ---

@router.message(F.text == "➕ Добавить канал")
async def add_channel_prompt(message: types.Message, state: FSMContext):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    await state.set_state(AddChannelState.waiting_for_link)
    await message.answer(
        "Отправь ссылки на каналы (можно несколько через запятую, пробел или с новой строки).\n"
        "Примеры:\n"
        "• https://t.me/durov\n"
        "• @durov\n"
        "• Пачкой: @durov, @somechannel\n"
        "  https://t.me/channel1\n"
        "  @channel2\nt.me/channel3",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@router.message(AddChannelState.waiting_for_link)
async def add_channel_receive(message: types.Message, state: FSMContext):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return

    raw = message.text.strip()
    usernames = _parse_usernames(raw)

    if not usernames:
        await message.answer(
            "Не нашёл ни одного канала в сообщении. Попробуй ещё раз.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    added: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for i, username in enumerate(usernames):
        if i > 0:
            await asyncio.sleep(0.5)
        try:
            entity = await reader.client.get_entity(username)
        except Exception:
            failed.append(username)
            continue

        channel_title = getattr(entity, "title", username)

        async with async_session() as session:
            existing = await session.execute(
                select(Channel).where(
                    Channel.user_id == message.from_user.id,
                    Channel.channel_username == username,
                )
            )
            if existing.scalar_one_or_none():
                skipped.append(username)
                continue

            ch = Channel(
                user_id=message.from_user.id,
                channel_username=username,
                channel_title=channel_title,
                channel_link=f"https://t.me/{username}",
            )
            session.add(ch)
            await session.commit()

        added.append(f"• {channel_title} (@{username})")

    response_parts: list[str] = []
    if added:
        response_parts.append(f"✅ Добавлено ({len(added)}):\n" + "\n".join(added))
    if skipped:
        response_parts.append(f"⏭️ Уже были ({len(skipped)}): " + ", ".join(f"@{u}" for u in skipped))
    if failed:
        response_parts.append(f"❌ Не найдены ({len(failed)}): " + ", ".join(f"@{u}" for u in failed))
    if not response_parts:
        response_parts.append("Ничего не изменилось.")

    await message.answer("\n\n".join(response_parts), reply_markup=main_menu_kb())
    await state.clear()


def _parse_usernames(text: str) -> list[str]:
    """Extract unique channel usernames from arbitrary text."""
    import re

    seen: set[str] = set()
    result: list[str] = []

    pattern = re.compile(
        r"(?:https?://)?t\.me/([a-zA-Z][\w]{3,31})"
        r"|@([a-zA-Z][\w]{3,31})",
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        username = (match.group(1) or match.group(2)).lower()
        if username and username not in seen:
            seen.add(username)
            result.append(username)

    # Also try bare usernames (single words that look like channel names)
    if not result:
        for word in text.split():
            word = word.strip("@ ").lower()
            if re.match(r"^[a-zA-Z][\w]{3,31}$", word):
                if word not in seen:
                    seen.add(word)
                    result.append(word)

    return result


# --- My channels ---

@router.message(F.text == "📋 Мои каналы")
async def my_channels(message: types.Message):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    async with async_session() as session:
        result = await session.execute(
            select(Channel).where(Channel.user_id == message.from_user.id)
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("У тебя пока нет добавленных каналов.")
        return

    kb = await _build_channels_keyboard(message.from_user.id)
    await message.answer(
        "Твои каналы. Нажми на канал, чтобы включить/выключить, ❌ чтобы удалить.",
        reply_markup=kb.as_markup(),
    )


async def _build_channels_keyboard(user_id: int) -> InlineKeyboardBuilder:
    async with async_session() as session:
        result = await session.execute(
            select(Channel).where(Channel.user_id == user_id)
        )
        channels = result.scalars().all()
    kb = InlineKeyboardBuilder()
    for ch in channels:
        status = "✅" if ch.is_active else "⏸️"
        kb.row(
            InlineKeyboardButton(
                text=f"{status} {ch.channel_title or ch.channel_username}",
                callback_data=f"ch_toggle:{ch.id}",
            ),
            InlineKeyboardButton(text="❌", callback_data=f"ch_delete:{ch.id}"),
        )
    return kb


@router.callback_query(F.data.startswith("ch_toggle:"))
async def toggle_channel(callback: types.CallbackQuery):
    if not _is_owner(callback):
        await callback.answer("Доступ запрещён.")
        return
    ch_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ch = await session.get(Channel, ch_id)
        if ch and ch.user_id == callback.from_user.id:
            ch.is_active = not ch.is_active
            await session.commit()
            status = "включён" if ch.is_active else "приостановлен"
            await callback.answer(f"Канал {status}.")
        else:
            await callback.answer("Канал не найден.")

    kb = await _build_channels_keyboard(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("ch_delete:"))
async def delete_channel(callback: types.CallbackQuery):
    if not _is_owner(callback):
        await callback.answer("Доступ запрещён.")
        return
    ch_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ch = await session.get(Channel, ch_id)
        if ch and ch.user_id == callback.from_user.id:
            await session.delete(ch)
            await session.commit()
            await callback.answer("Канал удалён.")
        else:
            await callback.answer("Канал не найден.")

    kb = await _build_channels_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.as_markup())
    except Exception:
        await callback.message.edit_text("У тебя пока нет добавленных каналов.")


# --- Filters ---

@router.message(F.text == "🔧 Фильтры")
async def filters_menu(message: types.Message):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.user_id == message.from_user.id)
        )
        filters = result.scalars().all()

    ignore_list = [f for f in filters if f.type == "ignore"]
    highlight_list = [f for f in filters if f.type == "highlight"]

    text = "🔧 **Фильтры**\n\n"
    text += "🚫 **Игнорируемые темы:**\n"
    text += "\n".join(f"• {f.value}" for f in ignore_list) if ignore_list else "  (пусто)"
    text += "\n\n⭐ **Важные темы:**\n"
    text += "\n".join(f"• {f.value}" for f in highlight_list) if highlight_list else "  (пусто)"

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="➕ Добавить игнор-тему", callback_data="f_add:ignore"),
        InlineKeyboardButton(text="➕ Добавить хайлайт-тему", callback_data="f_add:highlight"),
    )
    kb.row(
        InlineKeyboardButton(text="🗑 Удалить тему", callback_data="f_delete_menu"),
    )

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("f_add:"))
async def filter_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not _is_owner(callback):
        await callback.answer("Доступ запрещён.")
        return
    ftype = callback.data.split(":")[1]
    await state.update_data(filter_type=ftype)
    await state.set_state(AddFilterState.waiting_for_value)
    label = "игнорируемую" if ftype == "ignore" else "важную"
    await callback.message.answer(f"Отправь {label} тему (одно слово или фразу):")
    await callback.answer()


@router.message(AddFilterState.waiting_for_value)
async def filter_add_receive(message: types.Message, state: FSMContext):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    data = await state.get_data()
    ftype = data.get("filter_type", "ignore")
    value = message.text.strip()

    async with async_session() as session:
        f = Filter(user_id=message.from_user.id, type=ftype, value=value)
        session.add(f)
        await session.commit()

    await message.answer(f"Тема «{value}» добавлена в {'игнор' if ftype == 'ignore' else 'хайлайты'}.")
    await state.clear()


@router.callback_query(F.data == "f_delete_menu")
async def filter_delete_menu(callback: types.CallbackQuery):
    if not _is_owner(callback):
        await callback.answer("Доступ запрещён.")
        return
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.user_id == callback.from_user.id)
        )
        filters = result.scalars().all()

    if not filters:
        await callback.answer("Нет тем для удаления.")
        return

    kb = InlineKeyboardBuilder()
    for f in filters:
        prefix = "🚫" if f.type == "ignore" else "⭐"
        kb.row(
            InlineKeyboardButton(
                text=f"{prefix} {f.value}",
                callback_data=f"f_del:{f.id}",
            )
        )

    await callback.message.answer("Выбери тему для удаления:", reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("f_del:"))
async def filter_delete(callback: types.CallbackQuery):
    if not _is_owner(callback):
        await callback.answer("Доступ запрещён.")
        return
    f_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        f = await session.get(Filter, f_id)
        if f and f.user_id == callback.from_user.id:
            await session.delete(f)
            await session.commit()
            await callback.answer("Тема удалена.")
        else:
            await callback.answer("Тема не найдена.")

    await callback.message.edit_reply_markup(reply_markup=callback.message.reply_markup)


# --- Manual digest ---

@router.message(F.text == "📬 Сгенерировать дайджест")
async def manual_digest(message: types.Message):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    await message.answer("Собираю посты из каналов...")

    collected = await reader.collect_posts_for_user(message.from_user.id)
    await message.answer(f"Собрано новых постов: {collected}\nКлассифицирую...")

    await classify_posts(message.from_user.id)

    digest = await generate_digest(message.from_user.id, manual=True)

    if digest is None or not digest.content:
        await message.answer("Нет полезных постов за этот период.")
        return

    await message.answer(digest.content, parse_mode="Markdown", disable_web_page_preview=True)

    async with async_session() as session:
        d = await session.get(Digest, digest.id)
        if d:
            d.sent_at = d.sent_at or d.created_at
            await session.commit()


# --- Settings ---

@router.message(F.text == "⚙️ Настройки")
async def settings(message: types.Message):
    if not _is_owner(message):
        await message.answer("Доступ запрещён.")
        return
    async with async_session() as session:
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        u = user.scalar_one_or_none()

    if not u:
        await message.answer("Пользователь не найден.")
        return

    text = (
        "⚙️ **Настройки**\n\n"
        f"Часовой пояс: {u.timezone}\n"
        f"Утренний дайджест: {u.morning_digest_time}\n"
        f"Вечерний дайджест: {u.evening_digest_time}\n"
    )
    await message.answer(text, parse_mode="Markdown")
