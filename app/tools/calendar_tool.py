"""Google Calendar tool – creates events on behalf of a user."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import OAuthToken, User
from app.tools.google_utils import execute_with_retry

logger = logging.getLogger(__name__)


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
    if not user:
        logger.warning(
            "Calendar credentials unavailable: user not found "
            "(user_id=%s, telegram_id=%s)",
            user_id,
            telegram_id,
        )
        return None
    if not user.oauth_token:
        logger.warning(
            "Calendar credentials unavailable: user id=%s has no OAuth token "
            "(Google account not connected)",
            user.id,
        )
        return None

    token: OAuthToken = user.oauth_token
    logger.info(
        "Built Google Calendar credentials for user id=%s (scopes=%s, has_refresh_token=%s)",
        user.id,
        token.scopes,
        bool(token.refresh_token),
    )
    return Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.scopes.split() if token.scopes else [],
    )


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
    logger.info(
        "create_calendar_event called | user_id=%s telegram_id=%s title=%r "
        "start=%s end=%s has_description=%s has_location=%s",
        user_id,
        telegram_id,
        title,
        start_datetime,
        end_datetime,
        bool(description),
        bool(location),
    )

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
        logger.warning(
            "create_calendar_event: invalid start_datetime=%r (user_id=%s)",
            start_datetime,
            user_id,
        )
        return {"status": "error", "error": f"Invalid start_datetime: {start_datetime}"}

    if end_datetime:
        try:
            end_dt = datetime.datetime.fromisoformat(end_datetime)
        except ValueError:
            logger.warning(
                "create_calendar_event: invalid end_datetime=%r — defaulting to start+1h "
                "(user_id=%s)",
                end_datetime,
                user_id,
            )
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

    logger.info(
        "Inserting Calendar event for user_id=%s: summary=%r start=%s end=%s tz=%s",
        user_id,
        title,
        start_dt.isoformat(),
        end_dt.isoformat(),
        time_zone,
    )

    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        created_event = execute_with_retry(
            service.events().insert(calendarId="primary", body=event_body),
            label="calendar.events.insert",
        )
        event_id = created_event.get("id", "")
        event_link = created_event.get("htmlLink", "")
        logger.info(
            "Calendar event created OK | user_id=%s event_id=%s link=%s",
            user_id,
            event_id,
            event_link,
        )
        return {
            "status": "ok",
            "event_link": event_link,
            "event_id": event_id,
        }
    except Exception as exc:
        logger.exception(
            "Calendar insert failed for user_id=%s title=%r: %s",
            user_id,
            title,
            exc,
        )
        return {"status": "error", "error": str(exc)}


async def list_upcoming_events(
    db: Session,
    *,
    user_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` upcoming events for the user. Empty list if Google not connected."""
    creds = _get_credentials(db, user_id=user_id)
    if not creds:
        return []

    now_utc = datetime.datetime.now(datetime.UTC).isoformat()
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        result = execute_with_retry(
            service.events().list(
                calendarId="primary",
                timeMin=now_utc,
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            ),
            label="calendar.events.list",
        )
    except Exception as exc:
        logger.exception(
            "list_upcoming_events failed for user_id=%s: %s",
            user_id,
            exc,
        )
        return []

    events: list[dict[str, Any]] = []
    for ev in result.get("items", []):
        start = ev.get("start", {})
        end = ev.get("end", {})
        events.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": ev.get("location"),
                "description": ev.get("description"),
                "html_link": ev.get("htmlLink"),
            }
        )
    return events
