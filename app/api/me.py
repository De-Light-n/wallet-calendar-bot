"""Authenticated dashboard API: link codes, transactions, calendar, settings.

All endpoints under ``/api`` rely on :func:`app.auth.dependencies.current_user`
to resolve the caller from the session cookie set by the OAuth callback.
Anonymous channel ingress lives in :mod:`app.channels.routes` instead.
"""
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
from app.tools.finance_tool import (
    list_recent_transactions,
    recalculate_base_amounts,
    reset_user_spreadsheet,
    summarize_transactions,
)

router = APIRouter(prefix="/api", tags=["api"])
logger = logging.getLogger(__name__)

_LINK_SUPPORTED_CHANNELS = {"telegram", "slack", "discord"}


def _telegram_bot_url() -> str | None:
    """Build a t.me deep link if TELEGRAM_BOT_USERNAME is set."""
    username = os.getenv("TELEGRAM_BOT_USERNAME")
    return f"https://t.me/{username}" if username else None


def _channel_install_payload(channel: str, code: str) -> dict[str, str | None]:
    """Return install metadata for the given channel.

    The frontend uses these fields to render channel-specific guidance:

    * ``bot_url`` — env-driven install / open link, ``None`` when not configured.
    * ``bot_name`` — display handle so the user can search for the bot manually
      when ``bot_url`` is missing (e.g. ``@wallet-bot`` on Slack).
    * ``instructions`` — short Ukrainian hint shown next to the code.
    """
    if channel == "telegram":
        username = os.getenv("TELEGRAM_BOT_USERNAME") or None
        bot_name = f"@{username}" if username else None
        return {
            "bot_url": _telegram_bot_url(),
            "bot_name": bot_name,
            "instructions": f"Відкрий бот у Telegram і напиши: /link {code}",
        }
    if channel == "slack":
        return {
            "bot_url": os.getenv("SLACK_INSTALL_URL") or None,
            "bot_name": os.getenv("SLACK_BOT_NAME") or None,
            "instructions": f"Напиши боту в Slack DM (або тегни в каналі): /link {code}",
        }
    return {
        "bot_url": os.getenv("DISCORD_INSTALL_URL") or None,
        "bot_name": os.getenv("DISCORD_BOT_NAME") or None,
        "instructions": f"Напиши боту в Discord DM (або в каналі з ним): /link {code}",
    }


@router.post("/link-codes")
async def create_link_code(
    payload: dict | None = Body(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Issue a short-lived code that links an external chat account to this user.

    Body: ``{"channel": "telegram"|"slack"|"discord"}`` (default ``telegram``).
    The returned ``code`` is consumed by the matching channel's ``/link <code>``
    command. The response also includes a deep link (``bot_url``) and a localised
    ``instructions`` string the frontend can render verbatim.
    """
    channel = ((payload or {}).get("channel") or "telegram").lower()
    if channel not in _LINK_SUPPORTED_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")
    if not settings.is_channel_enabled(channel):
        raise HTTPException(status_code=404, detail=f"Channel disabled: {channel}")

    link = generate_link_code(db, user)
    install = _channel_install_payload(channel, link.code)
    return {
        "code": link.code,
        "expires_at": link.expires_at.isoformat(),
        "channel": channel,
        "bot_url": install["bot_url"],
        "bot_name": install["bot_name"],
        "instructions": install["instructions"],
    }


@router.get("/me/transactions")
async def get_recent_transactions(
    limit: int = Query(default=10, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the latest ``limit`` rows from the user's Google Sheets ledger."""
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
    """Return the next ``limit`` upcoming events from the user's primary calendar."""
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

    # Recompute every existing row's Base Amount + Base Currency in-place,
    # using each row's own date for the FX rate. Skipped automatically for v1
    # spreadsheets (no col H/I to write to). No-op when nothing changed.
    recalc: dict | None = None
    if previous != code and user.google_spreadsheet_id:
        recalc = await recalculate_base_amounts(db, user_id=user.id)

    return {
        "base_currency": user.base_currency,
        "previous": previous,
        "recalculation": recalc,
    }


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


@router.post("/me/spreadsheet/reset")
async def reset_spreadsheet(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Provision a fresh Google Spreadsheet for the user.

    The previous spreadsheet stays in the user's Drive — we never auto-delete
    user data. The new sheet uses the latest layout (v2: 9 cols + multi-month
    Dashboard). Useful when:
    - User changed base_currency and wants the entire ledger in the new one.
    - Layout / formulas were updated in code (e.g. new dashboard sections).
    - The current spreadsheet got into a weird state.
    """
    logger.info("Spreadsheet reset requested | user_id=%s", user.id)
    result = await reset_user_spreadsheet(db, user_id=user.id)
    if result.get("status") != "ok":
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Не вдалося створити нову таблицю."),
        )
    return result


@router.put("/me/timezone")
async def update_timezone(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update the user's IANA timezone (e.g. ``Europe/Kyiv``) after validation."""
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
