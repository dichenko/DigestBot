"""
Скрипт для создания Telegram MTProto-сессии (Telethon).

Запуск:
    pip install telethon
    python setup_session.py

Что нужно:
    1. API_ID и API_HASH — получить на https://my.telegram.org/apps
    2. Номер телефона, привязанный к Telegram-аккаунту

Процесс:
    1. Введи API_ID
    2. Введи API_HASH
    3. Введи номер телефона (с +, например +79161234567)
    4. Введи код подтверждения из Telegram
    5. Если есть облачный пароль — введи его

После успешного входа создастся файл user_session.session.
"""

import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = input("API_ID: ").strip()
API_HASH = input("API_HASH: ").strip()
PHONE = input("Phone number (+79161234567): ").strip()
SESSION_NAME = os.getenv("TELEGRAM_USER_SESSION", "user_session")


async def main():
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"\n✅ Сессия создана: {SESSION_NAME}.session")
    print(f"   Аккаунт: @{me.username} (ID: {me.id})")
    print(f"\nДобавь OWNER_TELEGRAM_ID={me.id} в .env если этот же аккаунт — владелец бота.")
    await client.disconnect()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
