"""Google Calendar tool – creates events on behalf of a user."""
from __future__ import annotations

import datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import OAuthToken, User


def _resolve_user(
    db: Session,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> User | None:
    """Resolve a user by internal ID or legacy telegram ID."""
    if user_id is not None:
        return db.query(User).filter(User.id == user_id).first()
    if telegram_id is not None:
        return db.query(User).filter(User.telegram_id == telegram_id).first()
    return None


def _get_credentials(
    db: Session,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> Credentials | None:
    """Retrieve and return Google OAuth2 credentials for a user."""
    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    if not user or not user.oauth_token:
        return None

    token: OAuthToken = user.oauth_token
    creds = Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.scopes.split() if token.scopes else [],
    )
    return creds


async def create_calendar_event(
    db: Session,
    title: str,
    start_datetime: str,
    end_datetime: str | None = None,
    description: str | None = None,
    location: str | None = None,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Create a Google Calendar event for the given user.

    Args:
        user_id:        Internal user ID.
        db:             Database session.
        title:          Event title/summary.
        start_datetime: ISO 8601 start datetime string.
        end_datetime:   ISO 8601 end datetime string (defaults to start + 1 h).
        description:    Optional event description.
        location:       Optional event location.

    Returns:
        Dict with ``status`` and either ``event_link`` or ``error``.
    """
    creds = _get_credentials(
        db,
        user_id=user_id,
        telegram_id=telegram_id,
    )
    if not creds:
        return {
            "status": "error",
            "error": (
                "Google Calendar is not connected. "
                "Please authorize via the web interface first."
            ),
        }

    # Parse start datetime and derive end datetime when not provided
    try:
        start_dt = datetime.datetime.fromisoformat(start_datetime)
    except ValueError:
        return {"status": "error", "error": f"Invalid start_datetime: {start_datetime}"}

    if end_datetime:
        try:
            end_dt = datetime.datetime.fromisoformat(end_datetime)
        except ValueError:
            end_dt = start_dt + datetime.timedelta(hours=1)
    else:
        end_dt = start_dt + datetime.timedelta(hours=1)

    time_zone = "UTC"
    event_body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": time_zone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": time_zone},
    }
    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location

    try:
        service = build("calendar", "v3", credentials=creds)
        created_event = (
            service.events()
            .insert(calendarId="primary", body=event_body)
            .execute()
        )
        return {
            "status": "ok",
            "event_link": created_event.get("htmlLink", ""),
            "event_id": created_event.get("id", ""),
        }
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "error": str(exc)}
