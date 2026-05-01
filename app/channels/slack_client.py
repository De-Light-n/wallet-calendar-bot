"""Slack outbound client and inbound signature verification.

Slack Web API: https://api.slack.com/web
Signature verification: https://api.slack.com/authentication/verifying-requests-from-slack
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"
_REQUEST_TIMEOUT_SECONDS = 10.0
# Slack rejects requests older than 5 minutes — anything older is replay-attack territory.
_SIGNATURE_MAX_AGE_SECONDS = 60 * 5


def verify_slack_signature(
    *,
    signing_secret: str,
    request_body: bytes,
    timestamp: str | None,
    signature: str | None,
) -> bool:
    """Verify the Slack request signature using HMAC-SHA256.

    Returns True only when the signature matches AND the timestamp is fresh.
    Empty/missing inputs and clock-skewed timestamps are rejected.
    """
    if not signing_secret or not timestamp or not signature:
        return False

    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False

    if abs(time.time() - ts_int) > _SIGNATURE_MAX_AGE_SECONDS:
        logger.warning(
            "Slack signature rejected: stale timestamp (delta=%ss)",
            int(time.time() - ts_int),
        )
        return False

    base_string = b"v0:" + timestamp.encode("ascii") + b":" + request_body
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        base_string,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


async def post_message(*, channel: str, text: str) -> dict[str, Any]:
    """Send a message via chat.postMessage. Returns the parsed Slack response."""
    token = settings.slack_bot_token
    if not token:
        logger.error("Cannot post to Slack: SLACK_BOT_TOKEN is not configured")
        return {"ok": False, "error": "missing_bot_token"}

    payload = {"channel": channel, "text": text}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{_SLACK_API_BASE}/chat.postMessage",
                json=payload,
                headers=headers,
            )
            data = resp.json()
    except Exception as exc:
        logger.exception(
            "Slack chat.postMessage failed | channel=%s err=%s",
            channel,
            exc,
        )
        return {"ok": False, "error": str(exc)}

    if not data.get("ok"):
        logger.warning(
            "Slack chat.postMessage non-ok | channel=%s response=%s",
            channel,
            data,
        )
    else:
        logger.info(
            "Slack chat.postMessage ok | channel=%s ts=%s text_len=%s",
            channel,
            data.get("ts"),
            len(text),
        )
    return data


async def fetch_user_profile(slack_user_id: str) -> dict[str, str | None]:
    """Best-effort fetch of a user's display info via users.info.

    Returns a dict with optional 'username' and 'display_name' — None values
    when the call fails, so callers can fall back gracefully.
    """
    token = settings.slack_bot_token
    if not token or not slack_user_id:
        return {"username": None, "display_name": None}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{_SLACK_API_BASE}/users.info",
                params={"user": slack_user_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
    except Exception as exc:
        logger.warning(
            "Slack users.info failed | user=%s err=%s",
            slack_user_id,
            exc,
        )
        return {"username": None, "display_name": None}

    if not data.get("ok"):
        logger.debug(
            "Slack users.info non-ok | user=%s response=%s",
            slack_user_id,
            data,
        )
        return {"username": None, "display_name": None}

    user = data.get("user") or {}
    profile = user.get("profile") or {}
    return {
        "username": user.get("name"),
        "display_name": (
            profile.get("display_name") or profile.get("real_name") or user.get("real_name")
        ),
    }
