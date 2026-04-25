"""Entry point: starts FastAPI and mounts the Telegram bot webhook."""
from __future__ import annotations

import os

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bot.handlers import router as bot_router
from app.database.session import init_db
from app.web.routes import router as web_router

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Wallet Calendar Bot",
    description="Personal AI assistant for Google Calendar and expense tracking via Telegram.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount web routes (login, OAuth, dashboard, index page)
app.include_router(web_router)

# ---------------------------------------------------------------------------
# Telegram bot setup
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://yourdomain.com


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
