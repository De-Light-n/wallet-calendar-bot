"""Telegram bot message handlers."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.agent.orchestrator import get_or_create_user_for_channel, process_user_message
from app.agent.stt import transcribe_audio
from app.auth.link_codes import LinkCodeError, consume_link_code
from app.bot.utils import download_telegram_file
from app.core.config import settings
from app.core.context import AgentRequestContext
from app.database.session import SessionLocal
from app.integrations.fx import SUPPORTED_BASE_CURRENCIES, is_supported_base_currency
from app.tools.finance_tool import reset_user_spreadsheet

router = Router()
logger = logging.getLogger(__name__)


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

    logger.info(
        "/start from telegram_id=%s username=%s",
        telegram_id,
        username,
    )
    _get_or_create_user(telegram_id, username, full_name)

    web_app_url = settings.web_app_url
    await message.answer(
        f"👋 Привіт, {full_name or username or 'друже'}!\n\n"
        "Я AI-асистент: записую витрати в твою Google-таблицю та створюю події в Google Calendar.\n\n"
        "Щоб почати:\n"
        f"1️⃣ Зареєструйся через Google: {web_app_url}\n"
        "2️⃣ На сторінці натисни «Підключити Telegram» — отримаєш код\n"
        "3️⃣ Напиши тут: <code>/link ТВІЙ_КОД</code>\n\n"
        "Після цього просто пиши або надсилай голосові: "
        "<i>«Витратив 150 грн на каву»</i> або <i>«Зустріч з Сашею завтра о 14:00»</i>.",
        parse_mode="HTML",
    )


@router.message(Command("link"))
async def handle_link(message: Message) -> None:
    """Bind this Telegram account to a registered web user via a short code."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Вкажи код після команди, наприклад: <code>/link ABC123XY</code>",
            parse_mode="HTML",
        )
        return

    code = parts[1].strip()
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    logger.info(
        "/link from telegram_id=%s username=%s code_len=%s",
        telegram_id,
        username,
        len(code),
    )

    with SessionLocal() as db:
        try:
            user = consume_link_code(
                db,
                code=code,
                channel="telegram",
                external_user_id=str(telegram_id),
                username=username,
                display_name=full_name,
            )
        except LinkCodeError as exc:
            logger.warning(
                "/link failed for telegram_id=%s: %s",
                telegram_id,
                exc,
            )
            await message.answer(f"❌ {exc}")
            return

    logger.info(
        "/link success: telegram_id=%s linked to user_id=%s email=%s",
        telegram_id,
        user.id,
        user.email,
    )
    await message.answer(
        f"✅ Telegram підключено до акаунта <b>{user.email or user.full_name or 'твого профілю'}</b>.\n\n"
        "Тепер пиши, що купив або яку зустріч додати — я все зроблю.",
        parse_mode="HTML",
    )


@router.message(Command("currency"))
async def handle_currency(message: Message) -> None:
    """Change the user's base currency. Usage: /currency USD"""
    from app.database.models import User

    telegram_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    supported = ", ".join(SUPPORTED_BASE_CURRENCIES)

    if len(parts) < 2 or not parts[1].strip():
        with SessionLocal() as db:
            user = db.query(User).filter_by(telegram_id=telegram_id).first()
            current = user.base_currency if user else "UAH"
        await message.answer(
            "Базова валюта — це те, в чому показуються підсумки в дашборді.\n\n"
            f"Зараз: <b>{current}</b>\n"
            f"Підтримувані: {supported}\n\n"
            "Зміни так: <code>/currency USD</code>",
            parse_mode="HTML",
        )
        return

    code = parts[1].strip().upper()
    if not is_supported_base_currency(code):
        await message.answer(
            f"❌ Валюта <b>{code}</b> не підтримується.\nПідтримувані: {supported}",
            parse_mode="HTML",
        )
        return

    with SessionLocal() as db:
        user = db.query(User).filter_by(telegram_id=telegram_id).first()
        if user is None:
            await message.answer("Спочатку напиши /start щоб зареєструватись.")
            return
        previous = user.base_currency
        user.base_currency = code
        db.commit()

    if previous == code:
        await message.answer(f"Базова валюта вже <b>{code}</b>.", parse_mode="HTML")
        return

    logger.info(
        "/currency change: telegram_id=%s %s->%s",
        telegram_id,
        previous,
        code,
    )
    await message.answer(
        f"✅ Базова валюта тепер <b>{code}</b> (було <b>{previous}</b>).\n\n"
        "Нові транзакції будуть конвертуватись у цю валюту.\n"
        "Щоб переключити і поточну Google-таблицю — натисни /new_sheet "
        "(стара залишиться в Drive).",
        parse_mode="HTML",
    )


@router.message(Command("new_sheet"))
async def handle_new_sheet(message: Message) -> None:
    """Drop the current Google Sheet (if any) and create a fresh one with the latest dashboard."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    logger.info("/new_sheet from telegram_id=%s username=%s", telegram_id, username)

    _get_or_create_user(telegram_id, username, full_name)

    with SessionLocal() as db:
        user = get_or_create_user_for_channel(
            db,
            channel="telegram",
            external_user_id=str(telegram_id),
            username=username,
            full_name=full_name,
        )
        result = await reset_user_spreadsheet(db, user_id=user.id)

    if result["status"] != "ok":
        logger.warning(
            "/new_sheet failed for telegram_id=%s: %s",
            telegram_id,
            result.get("error"),
        )
        await message.answer(f"❌ {result.get('error', 'Не вдалося створити нову таблицю.')}")
        return

    old_id = result.get("old_spreadsheet_id")
    new_url = result["spreadsheet_url"]
    logger.info(
        "/new_sheet success: telegram_id=%s old_id=%s new_id=%s",
        telegram_id,
        old_id,
        result["spreadsheet_id"],
    )

    parts = [f"✅ Створено нову Google-таблицю:\n{new_url}"]
    if old_id:
        parts.append(
            f"\nСтара таблиця залишилась у твоєму Drive (id <code>{old_id}</code>) — "
            "видали її вручну, якщо більше не потрібна."
        )
    await message.answer("\n".join(parts), parse_mode="HTML")


@router.message(F.text)
async def handle_text(message: Message) -> None:
    """Handle plain text messages – pass them to the AI agent."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    text = message.text or ""
    logger.info(
        "Telegram text | telegram_id=%s username=%s message_id=%s len=%s",
        telegram_id,
        username,
        message.message_id,
        len(text),
    )

    _get_or_create_user(telegram_id, username, full_name)

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    with SessionLocal() as db:
        context = AgentRequestContext(
            channel="telegram",
            external_user_id=str(telegram_id),
            message_id=str(message.message_id),
        )
        try:
            response = await process_user_message(
                db=db,
                context=context,
                user_message=text,
            )
        except Exception as exc:
            logger.exception(
                "process_user_message failed | telegram_id=%s message_id=%s: %s",
                telegram_id,
                message.message_id,
                exc,
            )
            await message.answer(
                "Сталася неочікувана помилка під час обробки. Спробуй ще раз."
            )
            return

    logger.info(
        "Replying to telegram_id=%s message_id=%s response_len=%s",
        telegram_id,
        message.message_id,
        len(response or ""),
    )
    await message.answer(response)


@router.message(F.voice)
async def handle_voice(message: Message) -> None:
    """Handle voice messages – transcribe via Whisper then pass to the AI agent."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    voice = message.voice
    logger.info(
        "Telegram voice | telegram_id=%s username=%s message_id=%s "
        "duration=%s file_size=%s mime=%s",
        telegram_id,
        username,
        message.message_id,
        getattr(voice, "duration", None),
        getattr(voice, "file_size", None),
        getattr(voice, "mime_type", None),
    )

    _get_or_create_user(telegram_id, username, full_name)

    await message.bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

    bot = message.bot
    voice_file = await bot.get_file(message.voice.file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{voice_file.file_path}"

    audio_path: Path | None = None
    try:
        audio_path = await download_telegram_file(file_url, suffix=".ogg")
        logger.info(
            "Downloaded voice to %s (telegram_id=%s message_id=%s)",
            audio_path,
            telegram_id,
            message.message_id,
        )

        try:
            text = await transcribe_audio(audio_path)
        except Exception as exc:
            logger.exception(
                "STT failed | telegram_id=%s message_id=%s: %s",
                telegram_id,
                message.message_id,
                exc,
            )
            await message.answer(
                "Не вдалося розпізнати голосове повідомлення. Спробуй ще раз або напиши текстом."
            )
            return

        logger.info(
            "Transcribed voice | telegram_id=%s message_id=%s text_len=%s",
            telegram_id,
            message.message_id,
            len(text or ""),
        )
        await message.answer(f"🎤 Розпізнано: {text}")

        with SessionLocal() as db:
            context = AgentRequestContext(
                channel="telegram",
                external_user_id=str(telegram_id),
                message_id=str(message.message_id),
            )
            try:
                response = await process_user_message(
                    db=db,
                    context=context,
                    user_message=text,
                )
            except Exception as exc:
                logger.exception(
                    "process_user_message failed (voice) | telegram_id=%s "
                    "message_id=%s: %s",
                    telegram_id,
                    message.message_id,
                    exc,
                )
                await message.answer(
                    "Сталася неочікувана помилка під час обробки. Спробуй ще раз."
                )
                return

        await message.answer(response)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
