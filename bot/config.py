from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass
class Config:
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    owner_id: int = field(default_factory=lambda: int(_env("OWNER_TELEGRAM_ID") or 0))

    api_id: int = field(default_factory=lambda: int(_env("TELEGRAM_API_ID") or 0))
    api_hash: str = field(default_factory=lambda: _env("TELEGRAM_API_HASH"))
    session_name: str = field(
        default_factory=lambda: _env("TELEGRAM_USER_SESSION", "user_session")
    )

    deepseek_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-chat"))

    db_type: str = field(default_factory=lambda: _env("DB_TYPE", "sqlite"))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "data/digest_bot.db"))
    db_host: str = field(default_factory=lambda: _env("DB_HOST", "localhost"))
    db_port: int = field(default_factory=lambda: int(_env("DB_PORT") or 5432))
    db_username: str = field(default_factory=lambda: _env("DB_USERNAME", ""))
    db_password: str = field(default_factory=lambda: _env("DB_PASSWORD", ""))
    db_name: str = field(default_factory=lambda: _env("DB_NAME", "digest_bot"))

    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Europe/Moscow"))
    morning_time: str = field(default_factory=lambda: _env("MORNING_DIGEST_TIME", "09:00"))
    evening_time: str = field(default_factory=lambda: _env("EVENING_DIGEST_TIME", "19:00"))

    @property
    def database_url(self) -> str:
        if self.db_type == "postgresql":
            return (
                f"postgresql+asyncpg://{self.db_username}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path.resolve()}"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.bot_token:
            errors.append("BOT_TOKEN is not set")
        if not self.api_id:
            errors.append("TELEGRAM_API_ID is not set")
        if not self.api_hash:
            errors.append("TELEGRAM_API_HASH is not set")
        if not self.owner_id:
            errors.append("OWNER_TELEGRAM_ID is not set")
        if not self.deepseek_key:
            errors.append("DEEPSEEK_API_KEY is not set")
        return errors


config = Config()
