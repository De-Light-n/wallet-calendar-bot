#!/usr/bin/env python3
"""Standalone polling entry point for local development.

Runs the bot in long-polling mode — no webhook or ngrok needed.
Production deployments use app/main.py (webhook via FastAPI).

Usage:
    python bot.py
"""
import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher  # noqa: E402

from app.bot.handlers import router  # noqa: E402
from app.channels.discord_bot import start_discord_bot, stop_discord_bot  # noqa: E402
from app.core.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)


async def main() -> None:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    await start_discord_bot()
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        await stop_discord_bot()


if __name__ == "__main__":
    asyncio.run(main())
