"""Single entry point: FastAPI + Telegram + Slack + Discord.

This module is the *only* runnable for the project. Run it with:

    uvicorn app.main:app --reload --port 8000

Everything starts inside this one process:
- FastAPI HTTP server (frontend API + Slack webhook + Telegram webhook on prod)
- Discord gateway client (persistent websocket, started as background task)
- Telegram bot:
    - Webhook mode if WEBHOOK_URL is set to a valid public HTTPS host
    - Otherwise long-polling as a background task (dev / no public URL)

Earlier we split this into uvicorn + bot.py because Discord was being started
in both places at once, causing duplicate event handling. Collapsing back to
one process resolves the race naturally — there is only one client now.
"""
from __future__ import annotations

# Load .env BEFORE importing anything that reads settings (config.py is eagerly evaluated).
from dotenv import load_dotenv

load_dotenv()

import asyncio  # noqa: E402
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

# Holds the long-polling background task in dev mode; used by shutdown to
# cancel it cleanly. None when polling isn't running (prod webhook mode or
# missing token).
_telegram_polling_task: asyncio.Task[None] | None = None
_telegram_polling_dispatcher: Dispatcher | None = None
_telegram_polling_bot: Bot | None = None


def _is_valid_telegram_token(token: str) -> bool:
    return bool(token and _TELEGRAM_TOKEN_RE.match(token))


def _webhook_skip_reason() -> str | None:
    """Return a human-friendly reason for skipping webhook registration.

    When this returns a non-None reason, we fall back to long-polling instead
    (provided the token itself is valid).
    """
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


async def _start_telegram_polling() -> None:
    """Start aiogram long-polling as a background task (dev / no public URL).

    Stays alive until shutdown cancels the task. Failures are logged so a
    Telegram outage doesn't cascade into uvicorn shutdown — Discord and the
    HTTP routes keep working independently.
    """
    global _telegram_polling_task, _telegram_polling_dispatcher, _telegram_polling_bot

    if not _is_valid_telegram_token(TELEGRAM_TOKEN):
        logger.info("Telegram polling skipped: token missing or invalid")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(bot_router)

    # If Telegram still has a registered webhook from a previous prod run, the
    # API rejects polling with 409 Conflict. Drop it before starting.
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        logger.warning("Failed to clear Telegram webhook before polling: %s", exc)

    async def _runner() -> None:
        try:
            await dp.start_polling(bot, allowed_updates=["message"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling crashed")
        finally:
            try:
                await bot.session.close()
            except Exception:
                logger.exception("Error closing Telegram bot session")

    _telegram_polling_task = asyncio.create_task(_runner(), name="telegram-polling")
    _telegram_polling_dispatcher = dp
    _telegram_polling_bot = bot
    logger.info("Telegram polling starting…")


async def _stop_telegram_polling() -> None:
    """Gracefully stop the polling background task (best-effort)."""
    global _telegram_polling_task, _telegram_polling_dispatcher, _telegram_polling_bot

    if _telegram_polling_dispatcher is not None:
        try:
            await _telegram_polling_dispatcher.stop_polling()
        except Exception:
            logger.exception("Error stopping Telegram dispatcher")

    if _telegram_polling_task is not None:
        try:
            await asyncio.wait_for(_telegram_polling_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            _telegram_polling_task.cancel()
        except Exception:
            logger.exception("Error awaiting Telegram polling task")

    _telegram_polling_task = None
    _telegram_polling_dispatcher = None
    _telegram_polling_bot = None


@app.on_event("startup")
async def on_startup() -> None:
    """Initialise database and start every channel inside this single process."""
    init_db()
    logger.info("Database initialized")

    # One-line snapshot of the enabled-channels matrix vs. what credentials are
    # actually present, so missing tokens are loud at startup instead of going
    # silent for each channel adapter individually.
    logger.info(
        "Startup config | enabled_channels=%s telegram_token=%s slack_token=%s "
        "discord_token=%s gemini_api=%s groq_api=%s webhook_url=%s",
        ",".join(settings.enabled_channels) or "<none>",
        "set" if settings.telegram_bot_token else "missing",
        "set" if settings.slack_bot_token else "missing",
        "set" if settings.discord_bot_token else "missing",
        "set" if settings.gemini_api_key else "missing",
        "set" if settings.groq_api_key else "missing",
        WEBHOOK_URL or "<empty>",
    )

    # Discord lives in this process now — see module docstring for the history
    # of the previous split.
    await start_discord_bot()

    skip_reason = _webhook_skip_reason()
    if skip_reason is not None:
        logger.info(
            "Telegram webhook not configured (%s) — falling back to long-polling",
            skip_reason,
        )
        await _start_telegram_polling()
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
    """Stop polling/Discord, delete the webhook if it was registered."""
    await _stop_telegram_polling()
    await stop_discord_bot()

    if not _webhook_configured():
        return
    logger.info("Deleting Telegram webhook from %s%s", WEBHOOK_URL, WEBHOOK_PATH)
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Telegram webhook deleted")
