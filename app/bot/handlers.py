"""Telegram bot message handlers."""
from __future__ import annotations

from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.agent.orchestrator import get_or_create_user_for_channel, process_user_message
from app.agent.stt import transcribe_audio
from app.bot.utils import download_telegram_file
from app.core.config import settings
from app.core.context import AgentRequestContext
from app.database.session import SessionLocal

router = Router()


def _get_or_create_user(telegram_id: int, username: str | None, full_name: str | None) -> None:
    """Ensure the user exists in the database and is linked to Telegram."""
    with SessionLocal() as db:
        get_or_create_user_for_channel(
            db,
            channel="telegram",
            external_user_id=str(telegram_id),
            username=username,
            full_name=full_name,
        )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle the /start command – register user and send welcome message."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    _get_or_create_user(telegram_id, username, full_name)

    web_app_url = settings.web_app_url
    await message.answer(
        f"👋 Привіт, {full_name or username or 'друже'}!\n\n"
        "Я твій персональний асистент. Ось що я вмію:\n"
        "📅 Додавати події до Google Calendar\n"
        "💰 Записувати витрати до твого гаманця\n\n"
        "Просто напиши мені або надішли голосове повідомлення — "
        "я зрозумію і зроблю потрібну дію!\n\n"
        f"🔑 Для підключення Google Calendar: {web_app_url}",
    )


@router.message(lambda m: m.text is not None)
async def handle_text(message: Message) -> None:
    """Handle plain text messages – pass them to the AI agent."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    _get_or_create_user(telegram_id, username, full_name)

    await message.answer("⏳ Обробляю твій запит…")

    with SessionLocal() as db:
        context = AgentRequestContext(
            channel="telegram",
            external_user_id=str(telegram_id),
            message_id=str(message.message_id),
        )
        response = await process_user_message(
            db=db,
            context=context,
            user_message=message.text,
        )

    await message.answer(response)


@router.message(lambda m: m.voice is not None)
async def handle_voice(message: Message) -> None:
    """Handle voice messages – transcribe via Whisper then pass to the AI agent."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    _get_or_create_user(telegram_id, username, full_name)

    await message.answer("🎙️ Розпізнаю голосове повідомлення…")

    bot = message.bot
    voice_file = await bot.get_file(message.voice.file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{voice_file.file_path}"

    audio_path: Path | None = None
    try:
        audio_path = await download_telegram_file(file_url, suffix=".ogg")
        text = await transcribe_audio(audio_path)
        await message.answer(f'🗒️ Розпізнано: "{text}"\n\n⏳ Обробляю…')

        with SessionLocal() as db:
            context = AgentRequestContext(
                channel="telegram",
                external_user_id=str(telegram_id),
                message_id=str(message.message_id),
            )
            response = await process_user_message(
                db=db,
                context=context,
                user_message=text,
            )

        await message.answer(response)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
