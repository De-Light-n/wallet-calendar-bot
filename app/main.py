"""Entry point: starts FastAPI and mounts the Telegram bot webhook."""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bot.handlers import router as bot_router
from app.channels.routes import router as channels_router
from app.core.config import settings
from app.database.session import init_db

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    description="Personal AI assistant for Google Calendar and expense tracking via Telegram.",
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(channels_router)

# ---------------------------------------------------------------------------
# Telegram bot setup
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = settings.telegram_bot_token
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = settings.webhook_url  # e.g. https://yourdomain.com


@app.on_event("startup")
async def on_startup() -> None:
    """Initialise database and register Telegram webhook on startup."""
    init_db()

    if not TELEGRAM_TOKEN:
        return  # Skip bot setup in environments without a token (e.g. tests)

    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(bot_router)

    if WEBHOOK_URL:
        await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")

    # Attach the aiogram webhook handler to the FastAPI app
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Delete the Telegram webhook on shutdown (optional)."""
    if not TELEGRAM_TOKEN:
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.delete_webhook()
    await bot.session.close()
