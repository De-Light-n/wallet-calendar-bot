"""Entry point: starts FastAPI and mounts the Telegram bot webhook."""
from __future__ import annotations

# Load .env BEFORE importing anything that reads settings (config.py is eagerly evaluated).
from dotenv import load_dotenv

load_dotenv()

import logging  # noqa: E402
import re  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.api.me import router as api_router  # noqa: E402
from app.auth.routes import router as auth_router  # noqa: E402
from app.bot.handlers import router as bot_router  # noqa: E402
from app.channels.discord_bot import start_discord_bot, stop_discord_bot  # noqa: E402
from app.channels.routes import router as channels_router  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database.session import init_db  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    description="Personal AI assistant for Google Calendar and expense tracking via Telegram.",
    version=settings.app_version,
)

# Session middleware MUST be added before any route that reads request.session.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key or "dev-insecure-key-replace-me",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 30,  # 30 days
)

# CORS: when frontend runs through Vite proxy this is unused, but keeping it
# permissive for the configured frontend origin lets the SPA call the API
# directly (with cookies) if it ever runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_app_url] if settings.web_app_url else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(channels_router)

# ---------------------------------------------------------------------------
# Telegram bot setup
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = settings.telegram_bot_token
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = settings.webhook_url  # e.g. https://yourdomain.com

_TELEGRAM_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")


def _is_valid_telegram_token(token: str) -> bool:
    return bool(token and _TELEGRAM_TOKEN_RE.match(token))


def _webhook_skip_reason() -> str | None:
    """Return a human-friendly reason for skipping webhook registration."""
    if not _is_valid_telegram_token(TELEGRAM_TOKEN):
        return "invalid or missing TELEGRAM_BOT_TOKEN"
    if not WEBHOOK_URL:
        return "WEBHOOK_URL is empty"

    parsed = urlparse(WEBHOOK_URL)
    hostname = (parsed.hostname or "").lower()

    if parsed.scheme != "https":
        return f"WEBHOOK_URL must use https, got '{parsed.scheme or '<empty>'}'"
    if not hostname or hostname in {"localhost", "127.0.0.1", "::1"}:
        return f"WEBHOOK_URL host '{hostname or '<empty>'}' is local"
    if "your-domain" in hostname or "example.com" in hostname:
        return "WEBHOOK_URL still points to a placeholder domain"

    # Telegram accepts webhook ports 443, 80, 88, 8443.
    if parsed.port is not None and parsed.port not in {443, 80, 88, 8443}:
        return f"WEBHOOK_URL port {parsed.port} is not allowed by Telegram"

    return None


def _webhook_configured() -> bool:
    return _webhook_skip_reason() is None


@app.on_event("startup")
async def on_startup() -> None:
    """Initialise database and (optionally) register the Telegram webhook."""
    init_db()
    logger.info("Database initialized")

    await start_discord_bot()

    skip_reason = _webhook_skip_reason()
    if skip_reason is not None:
        logger.info(
            "Skipping Telegram webhook setup: %s (WEBHOOK_URL=%s)",
            skip_reason,
            WEBHOOK_URL or "<empty>",
        )
        # Local development or test runs use bot.py (long-polling) instead.
        return

    logger.info("Registering Telegram webhook at %s%s", WEBHOOK_URL, WEBHOOK_PATH)
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(bot_router)

    await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    logger.info("Telegram webhook registration completed")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Delete the Telegram webhook on shutdown (only if it was registered)."""
    await stop_discord_bot()

    if not _webhook_configured():
        return
    logger.info("Deleting Telegram webhook from %s%s", WEBHOOK_URL, WEBHOOK_PATH)
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Telegram webhook deleted")
