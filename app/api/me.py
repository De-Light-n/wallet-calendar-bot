"""Authenticated dashboard API: link codes, transactions, calendar, settings."""
from __future__ import annotations

import zoneinfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.auth.link_codes import generate_link_code
from app.core.config import settings
from app.database.models import User
from app.database.session import get_db
from app.tools.calendar_tool import list_upcoming_events
from app.tools.finance_tool import list_recent_transactions

router = APIRouter(prefix="/api", tags=["api"])


def _bot_username() -> str | None:
    """Best-effort extraction of the bot's @username for deep links.

    The Telegram bot username is not stored in settings; we rely on the
    operator to set ``TELEGRAM_BOT_USERNAME`` in the environment if they want a
    clickable deep link. Otherwise the frontend falls back to plain instructions.
    """
    import os
    return os.getenv("TELEGRAM_BOT_USERNAME") or None


@router.post("/link-codes")
async def create_link_code(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    link = generate_link_code(db, user)
    bot_username = _bot_username()
    return {
        "code": link.code,
        "expires_at": link.expires_at.isoformat(),
        "bot_url": f"https://t.me/{bot_username}" if bot_username else None,
        "instructions": f"Відкрий бот у Telegram і напиши: /link {link.code}",
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


@router.get("/me/calendar/upcoming")
async def get_upcoming_events(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = await list_upcoming_events(db, user_id=user.id, limit=limit)
    return {"items": items}


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
