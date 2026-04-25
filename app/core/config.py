"""Centralized application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _parse_csv(value: str, *, default: list[str] | None = None) -> list[str]:
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Typed application settings with sensible defaults."""

    app_name: str
    app_version: str

    telegram_bot_token: str
    webhook_url: str
    web_app_url: str
    enabled_channels: list[str]

    slack_bot_token: str
    slack_signing_secret: str

    discord_bot_token: str
    discord_webhook_secret: str

    webchat_api_key: str

    openai_api_key: str
    openai_model: str
    gemini_api_key: str
    groq_api_key: str

    google_client_id: str
    google_client_secret: str
    google_project_id: str
    google_redirect_uri: str

    database_url: str
    secret_key: str

    def is_channel_enabled(self, channel: str) -> bool:
        return channel in self.enabled_channels


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load and cache settings from process environment."""
    return AppSettings(
        app_name="Wallet Calendar Bot",
        app_version="1.1.0",
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        webhook_url=os.getenv("WEBHOOK_URL", ""),
        web_app_url=os.getenv("WEB_APP_URL", "http://localhost:5173"),
        enabled_channels=_parse_csv(
            os.getenv("ENABLED_CHANNELS", "telegram,slack,discord,web"),
            default=["telegram", "slack", "discord", "web"],
        ),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        discord_webhook_secret=os.getenv("DISCORD_WEBHOOK_SECRET", ""),
        webchat_api_key=os.getenv("WEBCHAT_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        google_project_id=os.getenv("GOOGLE_PROJECT_ID", ""),
        google_redirect_uri=os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback",
        ),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres@localhost:5432/wallet_calendar",
        ),
        secret_key=os.getenv("SECRET_KEY", ""),
    )


settings = get_settings()
