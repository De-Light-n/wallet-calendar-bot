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

_DEFAULT_TIMEZONE = "UTC"
_DATE_ONLY_LENGTH = 10  # "YYYY-MM-DD"


def _is_date_only(value: str) -> bool:
    """Return True when value looks like YYYY-MM-DD with no time component."""
    return "T" not in value and len(value) == _DATE_ONLY_LENGTH


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
    end_datetime: str,
    description: str | None = None,
    location: str | None = None,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Create a Google Calendar event for the given user.

    Args:
        title:          Event title/summary.
        start_datetime: ISO 8601 start. Either ``YYYY-MM-DD`` (all-day) or
                        ``YYYY-MM-DDTHH:MM:SS`` (timed).
        end_datetime:   ISO 8601 end. Same format as start_datetime. Required.
                        For all-day events this is the exclusive end day
                        (Google's convention).
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

    user = _resolve_user(db, user_id=user_id, telegram_id=telegram_id)
    user_tz = (user.timezone if user and user.timezone else _DEFAULT_TIMEZONE)

    is_all_day = _is_date_only(start_datetime)

    if is_all_day:
        try:
            start_date = datetime.date.fromisoformat(start_datetime)
        except ValueError:
            logger.warning(
                "create_calendar_event: invalid all-day start=%r (user_id=%s)",
                start_datetime,
                user_id,
            )
            return {
                "status": "error",
                "error": f"Invalid all-day start_datetime: {start_datetime}",
            }

        if not _is_date_only(end_datetime):
            logger.warning(
                "create_calendar_event: all-day event got non-date end=%r (user_id=%s)",
                end_datetime,
                user_id,
            )
            return {
                "status": "error",
                "error": (
                    "For all-day events, end_datetime must also be YYYY-MM-DD "
                    "(exclusive end day)."
                ),
            }
        try:
            end_date = datetime.date.fromisoformat(end_datetime)
        except ValueError:
            return {
                "status": "error",
                "error": f"Invalid all-day end_datetime: {end_datetime}",
            }

        if end_date <= start_date:
            end_date = start_date + datetime.timedelta(days=1)

        event_body: dict[str, Any] = {
            "summary": title,
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
        log_start, log_end = start_date.isoformat(), end_date.isoformat()
    else:
        try:
            start_dt = datetime.datetime.fromisoformat(start_datetime)
        except ValueError:
            logger.warning(
                "create_calendar_event: invalid start_datetime=%r (user_id=%s)",
                start_datetime,
                user_id,
            )
            return {
                "status": "error",
                "error": f"Invalid start_datetime: {start_datetime}",
            }

        try:
            end_dt = datetime.datetime.fromisoformat(end_datetime)
        except ValueError:
            logger.warning(
                "create_calendar_event: invalid end_datetime=%r (user_id=%s)",
                end_datetime,
                user_id,
            )
            return {
                "status": "error",
                "error": f"Invalid end_datetime: {end_datetime}",
            }

        if end_dt <= start_dt:
            logger.warning(
                "create_calendar_event: end_datetime <= start_datetime (start=%s end=%s) "
                "— forcing end = start + 1h (user_id=%s)",
                start_dt.isoformat(),
                end_dt.isoformat(),
                user_id,
            )
            end_dt = start_dt + datetime.timedelta(hours=1)

        event_body = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": user_tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": user_tz},
        }
        log_start, log_end = start_dt.isoformat(), end_dt.isoformat()

    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location
    # Honour the user's default reminders configured in Google Calendar.
    event_body["reminders"] = {"useDefault": True}

    logger.info(
        "Inserting Calendar event for user_id=%s: summary=%r start=%s end=%s "
        "tz=%s all_day=%s",
        user_id,
        title,
        log_start,
        log_end,
        user_tz if not is_all_day else "(date-only)",
        is_all_day,
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
            "all_day": is_all_day,
        }
    except Exception as exc:
        logger.exception(
            "Calendar insert failed for user_id=%s title=%r: %s",
            user_id,
            title,
            exc,
        )
        return {"status": "error", "error": str(exc)}


def _to_rfc3339(value: str) -> str:
    """Coerce a YYYY-MM-DD or naive ISO datetime to RFC3339 by appending UTC offset."""
    if _is_date_only(value):
        return f"{value}T00:00:00Z"
    if value.endswith("Z") or "+" in value or value.count("-") > 2:
        return value
    return f"{value}Z"


async def list_upcoming_events(
    db: Session,
    user_id: int,
    limit: int = 10,
    time_min: str | None = None,
    time_max: str | None = None,
    query: str | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """List upcoming events for a user.

    Args:
        limit:    Max events to return (1..50).
        time_min: ISO 8601 lower bound (inclusive). Defaults to "now".
        time_max: ISO 8601 upper bound. Defaults to no upper bound.
        query:    Free-text search across title/description (Calendar `q` param).
    """
    logger.info(
        "list_upcoming_events called | user_id=%s limit=%s time_min=%s time_max=%s "
        "query=%r",
        user_id,
        limit,
        time_min,
        time_max,
        query,
    )
    creds = _get_credentials(db, user_id=user_id, telegram_id=telegram_id)
    if not creds:
        return {
            "status": "error",
            "error": (
                "Google Calendar is not connected. "
                "Please authorize via the web interface first."
            ),
            "events": [],
        }

    capped_limit = max(1, min(limit, 50))
    request_args: dict[str, Any] = {
        "calendarId": "primary",
        "maxResults": capped_limit,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    request_args["timeMin"] = (
        _to_rfc3339(time_min)
        if time_min
        else datetime.datetime.now(datetime.UTC).isoformat()
    )
    if time_max:
        request_args["timeMax"] = _to_rfc3339(time_max)
    if query:
        request_args["q"] = query

    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        result = execute_with_retry(
            service.events().list(**request_args),
            label="calendar.events.list",
        )
    except Exception as exc:
        logger.exception(
            "list_upcoming_events failed for user_id=%s: %s",
            user_id,
            exc,
        )
        return {"status": "error", "error": str(exc), "events": []}

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
                "all_day": "date" in start and "dateTime" not in start,
                "location": ev.get("location"),
                "description": ev.get("description"),
                "html_link": ev.get("htmlLink"),
            }
        )
    logger.info(
        "list_upcoming_events returned %s event(s) for user_id=%s",
        len(events),
        user_id,
    )
    return {"status": "ok", "events": events, "count": len(events)}
