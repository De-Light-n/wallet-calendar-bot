"""Authenticated dashboard API: link codes, transactions, calendar, settings."""
from __future__ import annotations

import logging
import zoneinfo

import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.auth.link_codes import generate_link_code
from app.core.config import settings
from app.database.models import User
from app.database.session import get_db
from app.integrations.fx import SUPPORTED_BASE_CURRENCIES, is_supported_base_currency
from app.tools.calendar_tool import list_upcoming_events
from app.tools.finance_tool import list_recent_transactions, summarize_transactions

router = APIRouter(prefix="/api", tags=["api"])
logger = logging.getLogger(__name__)

_LINK_SUPPORTED_CHANNELS = {"telegram", "slack", "discord"}


def _telegram_bot_url() -> str | None:
    """Build a t.me deep link if TELEGRAM_BOT_USERNAME is set."""
    username = os.getenv("TELEGRAM_BOT_USERNAME")
    return f"https://t.me/{username}" if username else None


def _channel_install_payload(channel: str, code: str) -> tuple[str | None, str]:
    """Return (bot_url, instructions) for the given channel.

    bot_url is an env-driven install / open link; None when not configured.
    instructions is a short user-facing hint shown next to the code.
    """
    if channel == "telegram":
        return (
            _telegram_bot_url(),
            f"Відкрий бот у Telegram і напиши: /link {code}",
        )
    if channel == "slack":
        return (
            os.getenv("SLACK_INSTALL_URL") or None,
            f"Напиши боту в Slack DM (або тегни в каналі): /link {code}",
        )
    # discord
    return (
        os.getenv("DISCORD_INSTALL_URL") or None,
        f"Напиши боту в Discord DM (або в каналі з ним): /link {code}",
    )


@router.post("/link-codes")
async def create_link_code(
    payload: dict | None = Body(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    channel = ((payload or {}).get("channel") or "telegram").lower()
    if channel not in _LINK_SUPPORTED_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")
    if not settings.is_channel_enabled(channel):
        raise HTTPException(status_code=404, detail=f"Channel disabled: {channel}")

    link = generate_link_code(db, user)
    bot_url, instructions = _channel_install_payload(channel, link.code)
    return {
        "code": link.code,
        "expires_at": link.expires_at.isoformat(),
        "channel": channel,
        "bot_url": bot_url,
        "instructions": instructions,
    }


@router.get("/me/transactions")
async def get_recent_transactions(
    limit: int = Query(default=10, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = await list_recent_transactions(db, user_id=user.id, limit=limit)
    spreadsheet_url = None
    if user.google_spreadsheet_id:
        spreadsheet_url = (
            f"https://docs.google.com/spreadsheets/d/{user.google_spreadsheet_id}/edit"
        )
    return {"items": items, "spreadsheet_url": spreadsheet_url}


@router.get("/me/finance/summary")
async def get_finance_summary(
    months: int = Query(default=12, ge=1, le=36),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated finance data for charts: per-category and per-month totals."""
    return await summarize_transactions(db, user_id=user.id, months=months)


@router.get("/me/calendar/upcoming")
async def get_upcoming_events(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    result = await list_upcoming_events(db, user_id=user.id, limit=limit)
    return {"items": result.get("events", [])}


@router.get("/me/calendar/range")
async def get_calendar_range(
    from_: str = Query(alias="from"),
    to: str = Query(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Events between two dates for a month grid view.

    `from` / `to` are inclusive YYYY-MM-DD strings. Calendar uses [start, end)
    semantics, so we keep this client-friendly and let list_upcoming_events
    handle the timezone conversion.
    """
    result = await list_upcoming_events(
        db,
        user_id=user.id,
        limit=250,
        time_min=from_,
        time_max=to,
    )
    return {"items": result.get("events", [])}


@router.get("/me/base-currency")
async def get_base_currency(
    user: User = Depends(current_user),
) -> dict:
    """Return the user's chosen base currency + the list of supported codes."""
    return {
        "base_currency": user.base_currency,
        "supported": list(SUPPORTED_BASE_CURRENCIES),
    }


@router.put("/me/base-currency")
async def update_base_currency(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change the user's base currency.

    Doesn't touch existing transactions — old rows keep whatever Base Amount
    was frozen at write time. New transactions will convert into the new base.
    To rewrite the entire ledger in the new currency, the user has to either
    run /new_sheet or wait for the optional backfill script.
    """
    code = ((payload or {}).get("currency") or "").upper().strip()
    if not is_supported_base_currency(code):
        supported = ", ".join(SUPPORTED_BASE_CURRENCIES)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported currency: {code or '<empty>'}. Supported: {supported}",
        )

    previous = user.base_currency
    user.base_currency = code
    db.commit()
    logger.info(
        "Base currency changed | user_id=%s %s->%s", user.id, previous, code
    )
    return {"base_currency": user.base_currency, "previous": previous}


@router.post("/me/chat")
async def chat_with_agent(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Send a chat message to the AI agent (web frontend channel).

    Bypasses the orchestrator's get_or_create_user_for_channel because the
    user is already resolved via the session cookie — no need to spin up an
    anonymous channel-account.
    """
    text = ((payload or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="`text` is required")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Message too long (max 4000 chars)")

    # Lazy import to keep the API module light at startup.
    from app.agent.llm_client import run_agent
    from app.core.context import AgentRequestContext

    context = AgentRequestContext(
        channel="web",
        external_user_id=str(user.id),
        timezone=user.timezone or "UTC",
    )
    logger.info(
        "Web chat | user_id=%s text_len=%s",
        user.id,
        len(text),
    )
    try:
        response = await run_agent(
            user_message=text,
            user_id=user.id,
            db_session=db,
            context=context,
        )
    except Exception as exc:
        logger.exception("Web chat agent run failed | user_id=%s: %s", user.id, exc)
        raise HTTPException(
            status_code=500,
            detail="Сталася помилка під час обробки. Спробуй ще раз.",
        ) from exc

    return {"response": response or "(порожня відповідь)"}


@router.put("/me/timezone")
async def update_timezone(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    tz = (payload or {}).get("timezone")
    if not isinstance(tz, str) or not tz:
        raise HTTPException(status_code=400, detail="`timezone` is required")
    try:
        zoneinfo.ZoneInfo(tz)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz}") from exc

    previous_tz = user.timezone
    user.timezone = tz
    db.commit()
    logger.info(
        "Timezone changed | user_id=%s %s->%s", user.id, previous_tz, tz
    )
    return {"timezone": user.timezone}
