from __future__ import annotations

import os
from dataclasses import dataclass, field

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
    session_name: str = field(default_factory=lambda: _env("TELEGRAM_USER_SESSION", "user_session"))

    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    postgres_password: str = field(default_factory=lambda: _env("POSTGRES_PASSWORD", ""))

    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "deepseek"))
    deepseek_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-chat"))

    monitor_interval_minutes: int = field(default_factory=lambda: int(_env("MONITOR_INTERVAL_MINUTES", "5")))
    default_score_threshold: int = field(default_factory=lambda: int(_env("DEFAULT_SCORE_THRESHOLD", "70")))
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Europe/Moscow"))
    max_posts_per_run: int = field(default_factory=lambda: int(_env("MAX_POSTS_PER_CHANNEL_PER_RUN", "20")))
    min_post_length: int = field(default_factory=lambda: int(_env("MIN_POST_LENGTH", "80")))
    enable_debug_scoring: bool = field(default_factory=lambda: _env("ENABLE_DEBUG_SCORING", "true").lower() == "true")

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
        if not self.database_url:
            errors.append("DATABASE_URL is not set")
        return errors


config = Config()
