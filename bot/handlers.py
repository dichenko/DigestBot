from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, desc

from bot.config import config
from bot.db import async_session
from bot.models import Channel, Post, User, UserFeedback, UserPreference
from bot.reader import reader

logger = logging.getLogger(__name__)

router = Router()


FEEDBACK_WEIGHTS = {
    "more_like_this": 1,
    "less_like_this": -1,
    "very_important": 3,
    "hide_similar": -3,
}

FEEDBACK_LABELS = {
    "m": "more_like_this",
    "l": "less_like_this",
    "v": "very_important",
    "h": "hide_similar",
}

FEEDBACK_CONFIRM = {
    "more_like_this": "Учту: буду чаще показывать похожее.",
    "less_like_this": "Учту: буду реже показывать похожее.",
    "very_important": "Отмечено как очень важное.",
    "hide_similar": "Учту: похожее буду скрывать.",
}

CHANNEL_FEEDBACK_DELTAS = {
    "more_like_this": 1,
    "less_like_this": -1,
    "very_important": 2,
    "hide_similar": -2,
}


def _is_owner(msg: types.Message | types.CallbackQuery) -> bool:
    u = msg.from_user
    return u is not None and u.id == config.owner_id


def _ensure_owner(msg: types.Message | types.CallbackQuery) -> bool:
    if not _is_owner(msg):
        if isinstance(msg, types.Message):
            asyncio.ensure_future(msg.answer("Доступ запрещён."))
        else:
            asyncio.ensure_future(msg.answer("Доступ запрещён."))
        return False
    return True


async def _ensure_user(telegram_id: int) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        u = result.scalar_one_or_none()
        if not u:
            u = User(telegram_id=telegram_id)
            session.add(u)
            await session.commit()
            await session.refresh(u)
        return u


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои каналы"), KeyboardButton(text="➕ Добавить канал")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


# --- States ---

class AddChannelState(StatesGroup):
    waiting_for_link = State()


# --- /start ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if not _ensure_owner(message):
        return
    await _ensure_user(message.from_user.id)
    await message.answer(
        "Привет! Я мониторю Telegram-каналы и присылаю только полезные посты.\n\n"
        "Управление:\n"
        "/channels — список каналов\n"
        "/add_channel — добавить канал\n"
        "/status — статистика\n"
        "/preferences — мои предпочтения\n"
        "/last_scores — последние оценки\n"
        "/threshold 75 — изменить порог\n"
        "/settings — настройки",
        reply_markup=main_menu_kb(),
    )


# --- Add channel ---

def _parse_usernames(text: str) -> list[str]:
    import re
    seen: set[str] = set()
    result: list[str] = []
    pattern = re.compile(r"(?:https?://)?t\.me/([a-zA-Z][\w]{3,31})|@([a-zA-Z][\w]{3,31})", re.IGNORECASE)
    for match in pattern.finditer(text):
        username = (match.group(1) or match.group(2)).lower()
        if username and username not in seen:
            seen.add(username)
            result.append(username)
    if not result:
        for word in text.split():
            word = word.strip("@ ").lower()
            if re.match(r"^[a-zA-Z][\w]{3,31}$", word):
                if word not in seen:
                    seen.add(word)
                    result.append(word)
    return result


@router.message(F.text == "➕ Добавить канал")
@router.message(Command("add_channel"))
async def add_channel_prompt(message: types.Message, state: FSMContext):
    if not _ensure_owner(message):
        return
    await state.set_state(AddChannelState.waiting_for_link)
    await message.answer(
        "Отправь ссылки на каналы (можно несколько через запятую, пробел или с новой строки).\n"
        "Примеры:\n"
        "• @durov\n"
        "• https://t.me/durov\n"
        "• Пачкой: @ch1, @ch2, t.me/ch3",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@router.message(AddChannelState.waiting_for_link)
async def add_channel_receive(message: types.Message, state: FSMContext):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)
    raw = message.text.strip()
    usernames = _parse_usernames(raw)

    if not usernames:
        await message.answer("Не нашёл каналов. Попробуй ещё раз.", reply_markup=main_menu_kb())
        await state.clear()
        return

    added, skipped, failed = [], [], []

    for i, username in enumerate(usernames):
        if i > 0:
            await asyncio.sleep(0.5)
        try:
            entity = await reader.client.get_entity(username)
        except Exception:
            failed.append(username)
            continue

        title = getattr(entity, "title", username)
        addr = username

        async with async_session() as session:
            existing = await session.execute(
                select(Channel).where(
                    Channel.user_id == user.id,
                    Channel.channel_address == addr,
                )
            )
            if existing.scalar_one_or_none():
                skipped.append(username)
                continue

            ch = Channel(
                user_id=user.id,
                channel_username=username,
                channel_title=title,
                channel_link=f"https://t.me/{username}",
                channel_address=addr,
            )
            session.add(ch)
            await session.commit()

            # Seed last_seen_message_id to avoid old history
            try:
                latest = await reader.client.get_messages(entity, limit=1)
                if latest and latest[0]:
                    ch.last_seen_message_id = latest[0].id
                    await session.commit()
            except Exception:
                pass

        added.append(f"• {title} (@{username})")

    parts = []
    if added:
        parts.append(f"✅ Добавлено ({len(added)}):\n" + "\n".join(added))
    if skipped:
        parts.append(f"⏭️ Уже были ({len(skipped)}): " + ", ".join(f"@{u}" for u in skipped))
    if failed:
        parts.append(f"❌ Не найдены ({len(failed)}): " + ", ".join(f"@{u}" for u in failed))
    if not parts:
        parts.append("Ничего не изменилось.")

    await message.answer("\n\n".join(parts), reply_markup=main_menu_kb())
    await state.clear()


# --- Channels list ---

@router.message(F.text == "📋 Мои каналы")
@router.message(Command("channels"))
async def channels_list(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)

    async with async_session() as session:
        result = await session.execute(
            select(Channel).where(Channel.user_id == user.id)
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("Нет каналов. Добавь через /add_channel.")
        return

    kb = InlineKeyboardBuilder()
    for ch in channels:
        status = "✅" if ch.is_active else "⏸️"
        kb.row(
            InlineKeyboardButton(
                text=f"{status} {ch.channel_title or ch.channel_address} (q={ch.channel_quality_weight})",
                callback_data=f"ch_rm:{ch.id}",
            ),
        )

    await message.answer("Твои каналы. Нажми чтобы удалить.", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("ch_rm:"))
async def remove_channel(callback: types.CallbackQuery):
    if not _ensure_owner(callback):
        return
    ch_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ch = await session.get(Channel, ch_id)
        if ch and ch.user_id == (await _ensure_user(callback.from_user.id)).id:
            await session.delete(ch)
            await session.commit()
            await callback.answer("Канал удалён.")
            await callback.message.edit_text("Канал удалён.")
        else:
            await callback.answer("Не найден.")


# --- Status ---

@router.message(F.text == "📊 Статус")
@router.message(Command("status"))
async def status(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)

    async with async_session() as session:
        total_posts = (await session.execute(select(Post).join(Post.channel).where(Channel.user_id == user.id))).scalars().all()
        sent = [p for p in total_posts if p.processing_status == "sent"]
        skipped = [p for p in total_posts if p.processing_status == "skipped_hard_filter"]
        failed = [p for p in total_posts if p.processing_status == "failed"]
        channels_result = await session.execute(select(Channel).where(Channel.user_id == user.id))
        channels = channels_result.scalars().all()

    text = (
        f"📊 **Статус**\n\n"
        f"Каналов: {len(channels)}\n"
        f"Постов собрано: {len(total_posts)}\n"
        f"Отправлено: {len(sent)}\n"
        f"Пропущено (фильтр): {len(skipped)}\n"
        f"Ошибок: {len(failed)}\n"
        f"Порог: {user.score_threshold}/100\n"
    )
    await message.answer(text)


# --- Settings ---

@router.message(F.text == "⚙️ Настройки")
@router.message(Command("settings"))
async def settings(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)
    text = (
        f"⚙️ Настройки\n\n"
        f"Порог отправки: {user.score_threshold}/100\n"
        f"Часовой пояс: {user.timezone}\n\n"
        f"/threshold 75 — изменить порог\n"
        f"/preferences — мои предпочтения\n"
        f"/last_scores — последние оценки"
    )
    await message.answer(text)


# --- Threshold ---

@router.message(Command("threshold"))
async def threshold(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(f"Текущий порог: {user.score_threshold}/100\nИспользуй: /threshold 75")
        return

    try:
        new_threshold = int(parts[1])
        new_threshold = max(0, min(100, new_threshold))
    except ValueError:
        await message.answer("Укажи число: /threshold 75")
        return

    async with async_session() as session:
        u = await session.get(User, user.id)
        if u:
            u.score_threshold = new_threshold
            await session.commit()

    await message.answer(f"Порог изменён: {new_threshold}/100")


# --- Preferences ---

@router.message(Command("preferences"))
async def preferences(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)

    async with async_session() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user.id).order_by(desc(UserPreference.weight))
        )
        prefs = result.scalars().all()

    if not prefs:
        await message.answer("Нет накопленных предпочтений.")
        return

    positive = [p for p in prefs if p.weight > 0][:10]
    negative = [p for p in prefs if p.weight < 0][-10:]

    text = "🧠 **Предпочтения**\n\n"
    if positive:
        text += "*Топ позитивных:*\n"
        for p in positive:
            text += f"  {p.feature_type}: {p.feature_value} +{p.weight}\n"
    if negative:
        text += "\n*Топ негативных:*\n"
        for p in negative:
            text += f"  {p.feature_type}: {p.feature_value} {p.weight}\n"

    await message.answer(text)


# --- Last scores ---

@router.message(Command("last_scores"))
async def last_scores(message: types.Message):
    if not _ensure_owner(message):
        return
    user = await _ensure_user(message.from_user.id)

    async with async_session() as session:
        result = await session.execute(
            select(Post)
            .join(Post.channel)
            .where(Channel.user_id == user.id, Post.final_score.isnot(None))
            .order_by(desc(Post.updated_at))
            .limit(10)
        )
        posts = result.scalars().all()

    if not posts:
        await message.answer("Нет оценённых постов.")
        return

    text = "📊 **Последние оценки**\n\n"
    for p in posts:
        features = p.features_json or {}
        ct = features.get("content_type", "?")
        status = p.processing_status
        emoji = {"sent": "📤", "scored": "📊"}.get(status, "❓")
        text += f"{emoji} {p.final_score} @{p.channel.channel_address} — {ct} — {status}\n"

    await message.answer(text)


# --- Feedback callbacks ---

@router.callback_query(F.data.startswith("f:"))
async def feedback_callback(callback: types.CallbackQuery):
    if not _ensure_owner(callback):
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка данных.")
        return

    short_code = parts[1]
    post_id = int(parts[2])
    feedback_type = FEEDBACK_LABELS.get(short_code)

    if not feedback_type:
        await callback.answer("Неизвестный тип.")
        return

    user = await _ensure_user(callback.from_user.id)
    weight = FEEDBACK_WEIGHTS[feedback_type]

    async with async_session() as session:
        post = await session.get(Post, post_id)
        if not post:
            await callback.answer("Пост не найден.")
            return

        existing = await session.execute(
            select(UserFeedback).where(
                UserFeedback.user_id == user.id,
                UserFeedback.post_id == post_id,
            )
        )
        fb = existing.scalar_one_or_none()

        if fb:
            fb.feedback_type = feedback_type
            fb.weight = weight
            fb.created_at = fb.created_at  # keep original
        else:
            session.add(UserFeedback(
                user_id=user.id,
                post_id=post_id,
                feedback_type=feedback_type,
                weight=weight,
            ))

        # Update preferences
        features = post.features_json or {}
        channel_addr = features.get("channel_address", "") or post.channel.channel_address

        await _update_preference(session, user.id, "channel_address", channel_addr, CHANNEL_FEEDBACK_DELTAS[feedback_type])

        for topic in features.get("topics", []):
            await _update_preference(session, user.id, "topic", topic.lower(), weight)
        for entity in features.get("entities", []):
            await _update_preference(session, user.id, "entity", entity.lower(), weight)

        ct = (features.get("content_type") or "").lower()
        if ct:
            await _update_preference(session, user.id, "content_type", ct, weight)

        tone = (features.get("tone") or "").lower()
        if tone:
            await _update_preference(session, user.id, "tone", tone, weight)

        # Update channel quality weight for strong signals
        if feedback_type in ("very_important", "hide_similar"):
            ch = await session.get(Channel, post.channel_id)
            if ch:
                delta = 1 if feedback_type == "very_important" else -1
                ch.channel_quality_weight = max(-15, min(15, ch.channel_quality_weight + delta))

        await session.commit()

    await callback.answer(FEEDBACK_CONFIRM[feedback_type])


async def _update_preference(session, user_id: int, ftype: str, fvalue: str, delta: int) -> None:
    result = await session.execute(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.feature_type == ftype,
            UserPreference.feature_value == fvalue,
        )
    )
    pref = result.scalar_one_or_none()

    if pref:
        pref.weight = max(-30, min(30, pref.weight + delta))
    else:
        session.add(UserPreference(
            user_id=user_id,
            feature_type=ftype,
            feature_value=fvalue,
            weight=max(-30, min(30, delta)),
        ))
