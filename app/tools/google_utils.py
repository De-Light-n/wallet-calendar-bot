"""Shared helpers for talking to Google APIs (Sheets, Drive, Calendar)."""
from __future__ import annotations

import logging
import time
from typing import Any

from google.auth.exceptions import TransportError as AuthTransportError
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

logger = logging.getLogger(__name__)

_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
_RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def _is_transient(exc: BaseException) -> bool:
    """Decide whether a Google API exception is worth retrying."""
    if isinstance(exc, (AuthTransportError, ServerNotFoundError)):
        return True
    if isinstance(exc, HttpError):
        status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            return status is not None and int(status) in _RETRYABLE_HTTP_STATUS
        except (TypeError, ValueError):
            return False
    return False


def is_spreadsheet_missing(exc: BaseException) -> bool:
    """True if the error indicates the target spreadsheet/file is gone (404)."""
    if not isinstance(exc, HttpError):
        return False
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        return status is not None and int(status) == 404
    except (TypeError, ValueError):
        return False


def execute_with_retry(request: Any, *, label: str = "google-api") -> Any:
    """Execute a googleapiclient request, retrying on transient failures.

    Retries on DNS lookup failures (httplib2.ServerNotFoundError),
    google-auth TransportError (covers token-refresh DNS hiccups),
    and HttpError with status 408/429/5xx. Other errors propagate immediately.
    """
    attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except Exception as exc:
            if attempt >= attempts or not _is_transient(exc):
                raise
            wait_seconds = _RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                "Transient Google API error (label=%s attempt=%s/%s type=%s): %s. "
                "Retrying in %.1fs",
                label,
                attempt,
                attempts,
                exc.__class__.__name__,
                exc,
                wait_seconds,
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"execute_with_retry({label}) retry loop ended unexpectedly")
