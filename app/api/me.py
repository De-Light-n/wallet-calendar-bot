"""Authenticated dashboard API: link codes, transactions, calendar, settings."""
from __future__ import annotations

import zoneinfo

import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.auth.link_codes import generate_link_code
from app.core.config import settings
from app.database.models import User
from app.database.session import get_db
from app.tools.calendar_tool import list_upcoming_events
from app.tools.finance_tool import list_recent_transactions, summarize_transactions

router = APIRouter(prefix="/api", tags=["api"])

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

    user.timezone = tz
    db.commit()
    return {"timezone": user.timezone}
