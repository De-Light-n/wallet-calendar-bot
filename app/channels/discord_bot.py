"""Discord Gateway bot: listens for messages and replies in the same channel.

Uses discord.py's Client (websocket Gateway), which is the official inbound path
for real-time bot messaging. The HTTP webhook in routes.py is a separate
generic-relay endpoint and is not used by this client.

Bot setup checklist (https://discord.com/developers/applications):
- Create an Application + Bot user; copy the bot token to DISCORD_BOT_TOKEN.
- Under "Bot" enable the **Message Content Intent** (privileged) — without it
  on_message receives empty content for guild messages.
- Generate an OAuth2 invite URL with scopes `bot applications.commands` and the
  permissions: View Channels, Send Messages, Read Message History.
"""
from __future__ import annotations

import asyncio
import logging
import re

import discord

from app.auth.link_codes import LinkCodeError, consume_link_code
from app.core.config import settings
from app.core.context import AgentRequestContext
from app.database.session import SessionLocal

logger = logging.getLogger(__name__)

_LINK_PREFIX = "/link"
_CURRENCY_PREFIX = "/currency"
# Strips a leading `<@123456789>` mention so the agent doesn't see itself addressed.
_MENTION_PATTERN = re.compile(r"^<@!?\d+>\s*")

_client: discord.Client | None = None
_runner_task: asyncio.Task[None] | None = None


def _build_intents() -> discord.Intents:
    """Minimum intents needed to receive DMs and guild messages."""
    intents = discord.Intents.default()
    intents.message_content = True  # privileged — must also be enabled in dev portal
    intents.dm_messages = True
    intents.guild_messages = True
    return intents


def _create_client() -> discord.Client:
    client = discord.Client(intents=_build_intents())

    @client.event
    async def on_ready() -> None:
        user = client.user
        logger.info(
            "Discord bot connected | id=%s name=%s guilds=%s",
            getattr(user, "id", None),
            getattr(user, "name", None),
            len(client.guilds),
        )

    @client.event
    async def on_message(message: discord.Message) -> None:
        await _handle_message(client, message)

    return client


async def _handle_message(client: discord.Client, message: discord.Message) -> None:
    # Anti-loop: never react to bot/system messages, including ourselves.
    if message.author.bot or message.author.system:
        return

    me = client.user
    text = (message.content or "").strip()
    if not text:
        return

    # In guild channels, only respond when explicitly addressed: either via
    # mention or a reply to the bot. DMs always get a response.
    is_dm = isinstance(message.channel, discord.DMChannel)
    mentioned = bool(me and me in message.mentions)
    if not is_dm and not mentioned:
        return

    text = _MENTION_PATTERN.sub("", text).strip()
    if not text:
        return

    external_user_id = str(message.author.id)
    logger.info(
        "Discord message | user=%s channel=%s dm=%s text_len=%s",
        external_user_id,
        message.channel.id,
        is_dm,
        len(text),
    )

    if text.lower().startswith(_LINK_PREFIX):
        await _handle_link_command(message=message, text=text)
        return

    if text.lower().startswith(_CURRENCY_PREFIX):
        await _handle_currency_command(message=message, text=text)
        return

    # Defer the heavy LLM import until first message so module import is fast.
    from app.agent.orchestrator import process_user_message

    with SessionLocal() as db:
        context = AgentRequestContext(
            channel="discord",
            external_user_id=external_user_id,
            message_id=str(message.id),
        )
        try:
            response = await process_user_message(
                db=db,
                context=context,
                user_message=text,
            )
        except Exception as exc:
            logger.exception(
                "Discord process_user_message failed | user=%s: %s",
                external_user_id,
                exc,
            )
            response = "Сталася неочікувана помилка під час обробки. Спробуй ще раз."

    await _safe_reply(message, response)


async def _handle_link_command(*, message: discord.Message, text: str) -> None:
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        await _safe_reply(
            message,
            "Вкажи код після команди. Наприклад: `/link ABC123XY`. "
            "Згенеруй код на сайті після входу через Google.",
        )
        return

    author = message.author
    username = getattr(author, "name", None)
    display_name = getattr(author, "global_name", None) or getattr(author, "display_name", None)

    with SessionLocal() as db:
        try:
            user = consume_link_code(
                db,
                code=code,
                channel="discord",
                external_user_id=str(author.id),
                username=username,
                display_name=display_name,
            )
        except LinkCodeError as exc:
            logger.warning(
                "Discord /link failed | user=%s reason=%s",
                author.id,
                exc,
            )
            await _safe_reply(message, f"❌ {exc}")
            return

    label = user.email or user.full_name or "твого профілю"
    logger.info(
        "Discord /link success | discord_user=%s linked_to user_id=%s",
        author.id,
        user.id,
    )
    await _safe_reply(
        message,
        f"✅ Discord підключено до акаунта **{label}**.\n"
        "Тепер пиши мені в DM або тегни в каналі — я запишу витрату чи створю подію.",
    )


async def _handle_currency_command(*, message: discord.Message, text: str) -> None:
    """Handle '/currency [CODE]' DM/mention command."""
    from app.database.models import ChannelAccount
    from app.integrations.fx import (
        SUPPORTED_BASE_CURRENCIES,
        is_supported_base_currency,
    )

    parts = text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    supported = ", ".join(SUPPORTED_BASE_CURRENCIES)
    external_user_id = str(message.author.id)

    with SessionLocal() as db:
        account = (
            db.query(ChannelAccount)
            .filter_by(channel="discord", external_user_id=external_user_id)
            .first()
        )
        user = account.user if account else None

        if not arg:
            current = user.base_currency if user else "UAH"
            await _safe_reply(
                message,
                f"Поточна базова валюта: **{current}**\n"
                f"Підтримувані: {supported}\n"
                "Зміни так: `/currency USD`",
            )
            return

        code = arg.upper()
        if not is_supported_base_currency(code):
            await _safe_reply(
                message,
                f"❌ Валюта **{code}** не підтримується.\nПідтримувані: {supported}",
            )
            return

        if user is None:
            await _safe_reply(
                message,
                "Спочатку прив'яжи акаунт: згенеруй код на сайті, "
                "потім напиши `/link ABC123XY`.",
            )
            return

        previous = user.base_currency
        if previous == code:
            await _safe_reply(message, f"Базова валюта вже **{code}**.")
            return

        user.base_currency = code
        db.commit()
        logger.info(
            "Discord /currency change | user_id=%s %s->%s", user.id, previous, code
        )

    await _safe_reply(
        message,
        f"✅ Базова валюта тепер **{code}** (було **{previous}**).\n"
        "Нові транзакції будуть конвертуватись у цю валюту. "
        "Щоб переключити Google-таблицю — натисни `/new_sheet`.",
    )


async def _safe_reply(message: discord.Message, text: str) -> None:
    """Send a reply, logging delivery failures instead of bubbling them up."""
    try:
        await message.channel.send(text)
    except discord.DiscordException as exc:
        logger.warning(
            "Discord reply failed | channel=%s err=%s",
            getattr(message.channel, "id", "?"),
            exc,
        )


async def start_discord_bot() -> None:
    """Start the Discord client as a long-lived background task.

    No-op when DISCORD_BOT_TOKEN is empty or the channel is disabled. Safe to
    call multiple times — only one client will run.
    """
    global _client, _runner_task

    if not settings.is_channel_enabled("discord"):
        logger.info("Discord channel disabled in ENABLED_CHANNELS — skipping bot start")
        return
    token = settings.discord_bot_token
    if not token:
        logger.info("DISCORD_BOT_TOKEN is empty — skipping Discord bot start")
        return
    if _runner_task is not None and not _runner_task.done():
        logger.debug("Discord bot already running — skipping duplicate start")
        return

    _client = _create_client()

    async def _runner() -> None:
        try:
            await _client.start(token)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Discord bot crashed")

    _runner_task = asyncio.create_task(_runner(), name="discord-bot")
    logger.info("Discord bot starting…")


async def stop_discord_bot() -> None:
    """Gracefully close the Discord client (best-effort)."""
    global _client, _runner_task
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            logger.exception("Error closing Discord client")
    if _runner_task is not None:
        try:
            await asyncio.wait_for(_runner_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            _runner_task.cancel()
        except Exception:
            logger.exception("Error awaiting Discord bot task")
    _client = None
    _runner_task = None
