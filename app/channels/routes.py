"""Webhook and API routes for multi-channel ingress."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent.orchestrator import process_user_message
from app.auth.link_codes import LinkCodeError, consume_link_code
from app.channels.discord import DiscordAdapter
from app.channels.slack import SlackAdapter, SlackInbound
from app.channels.slack_client import (
    fetch_user_profile,
    post_message as slack_post_message,
    verify_slack_signature,
)
from app.channels.webchat import WebChatAdapter
from app.core.config import settings
from app.database.session import SessionLocal, get_db

router = APIRouter(prefix="/api/channels", tags=["channels"])
logger = logging.getLogger(__name__)


# ─── Slack ────────────────────────────────────────────────────────────────────

_SLACK_LINK_PREFIX = "/link"


@router.post("/slack/webhook")
async def slack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_signature: str | None = Header(default=None),
    x_slack_request_timestamp: str | None = Header(default=None),
) -> dict:
    """Slack Events API endpoint.

    Slack expects HTTP 200 within 3 seconds (otherwise it retries — and the
    retry would create duplicate replies). We verify the signature, handle the
    initial url_verification handshake synchronously, and offload any actual
    LLM work to a background task that posts the response back via Web API.
    """
    if not settings.is_channel_enabled("slack"):
        raise HTTPException(status_code=404, detail="Slack channel is disabled")

    raw_body = await request.body()

    # Always verify the signature when we have a secret configured. Without one
    # we fall through (useful only for local-only sandboxes).
    if settings.slack_signing_secret:
        if not verify_slack_signature(
            signing_secret=settings.slack_signing_secret,
            request_body=raw_body,
            timestamp=x_slack_request_timestamp,
            signature=x_slack_signature,
        ):
            logger.warning(
                "Slack webhook rejected: invalid signature (ts=%s sig_present=%s)",
                x_slack_request_timestamp,
                bool(x_slack_signature),
            )
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Step 1: URL verification handshake (Events API setup screen).
    if payload.get("type") == "url_verification":
        logger.info("Slack URL verification handshake received")
        return {"challenge": payload.get("challenge", "")}

    # Step 2: Slack retries on slow / failed responses. The header
    # X-Slack-Retry-Num indicates a retry — drop it to avoid duplicate replies.
    retry_num = request.headers.get("x-slack-retry-num")
    if retry_num:
        logger.info(
            "Ignoring Slack retry attempt=%s reason=%s",
            retry_num,
            request.headers.get("x-slack-retry-reason"),
        )
        return {"status": "ignored_retry"}

    normalized = SlackAdapter().normalize(payload)
    if not normalized:
        return {"status": "ignored"}

    background_tasks.add_task(
        _handle_slack_message,
        text=normalized.text,
        external_user_id=normalized.context.external_user_id,
        slack_channel_id=normalized.slack_channel_id,
    )
    return {"status": "ok"}


async def _handle_slack_message(
    *,
    text: str,
    external_user_id: str,
    slack_channel_id: str,
) -> None:
    """Background work for one inbound Slack message.

    Opens its own DB session because BackgroundTasks runs after the request
    cycle ends and the request-scoped session would already be closed.
    """
    logger.info(
        "Slack message | user=%s channel=%s text_len=%s",
        external_user_id,
        slack_channel_id,
        len(text),
    )

    if text.lower().startswith(_SLACK_LINK_PREFIX):
        await _handle_slack_link(
            text=text,
            external_user_id=external_user_id,
            slack_channel_id=slack_channel_id,
        )
        return

    with SessionLocal() as db:
        from app.core.context import AgentRequestContext

        context = AgentRequestContext(
            channel="slack",
            external_user_id=external_user_id,
        )
        try:
            response = await process_user_message(
                db=db,
                context=context,
                user_message=text,
            )
        except Exception as exc:
            logger.exception(
                "Slack process_user_message failed | user=%s: %s",
                external_user_id,
                exc,
            )
            response = "Сталася неочікувана помилка під час обробки. Спробуй ще раз."

    await slack_post_message(channel=slack_channel_id, text=response)


async def _handle_slack_link(
    *,
    text: str,
    external_user_id: str,
    slack_channel_id: str,
) -> None:
    """Handle '/link <code>' as a special command (no LLM hop)."""
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        await slack_post_message(
            channel=slack_channel_id,
            text=(
                "Вкажи код після команди. Наприклад: `/link ABC123XY`. "
                "Згенеруй код на сайті після входу через Google."
            ),
        )
        return

    profile = await fetch_user_profile(external_user_id)
    with SessionLocal() as db:
        try:
            user = consume_link_code(
                db,
                code=code,
                channel="slack",
                external_user_id=external_user_id,
                username=profile.get("username"),
                display_name=profile.get("display_name"),
            )
        except LinkCodeError as exc:
            logger.warning(
                "Slack /link failed | user=%s reason=%s",
                external_user_id,
                exc,
            )
            await slack_post_message(channel=slack_channel_id, text=f"❌ {exc}")
            return

    label = user.email or user.full_name or "твого профілю"
    logger.info(
        "Slack /link success | slack_user=%s linked_to user_id=%s",
        external_user_id,
        user.id,
    )
    await slack_post_message(
        channel=slack_channel_id,
        text=(
            f"✅ Slack підключено до акаунта *{label}*.\n"
            "Тепер пиши мені в DM або тегни в каналі — я запишу витрату чи створю подію."
        ),
    )


# ─── Discord ──────────────────────────────────────────────────────────────────


@router.post("/discord/webhook")
async def discord_webhook(
    payload: dict,
    db: Session = Depends(get_db),
    x_discord_token: str | None = Header(default=None),
) -> dict:
    if not settings.is_channel_enabled("discord"):
        raise HTTPException(status_code=404, detail="Discord channel is disabled")

    expected = settings.discord_webhook_secret
    if expected and x_discord_token != expected:
        raise HTTPException(status_code=401, detail="Invalid Discord webhook token")

    normalized = DiscordAdapter().normalize(payload)
    if not normalized:
        return {"status": "ignored"}

    response = await process_user_message(
        db=db,
        context=normalized.context,
        user_message=normalized.text,
    )
    return {"status": "ok", "response": response}


# ─── Web chat ─────────────────────────────────────────────────────────────────


@router.post("/webchat/message")
async def webchat_message(payload: dict, db: Session = Depends(get_db)) -> dict:
    if not settings.is_channel_enabled("web"):
        raise HTTPException(status_code=404, detail="Web chat channel is disabled")

    api_key = settings.webchat_api_key
    if api_key and payload.get("api_key") != api_key:
        raise HTTPException(status_code=401, detail="Invalid web chat API key")

    normalized = WebChatAdapter().normalize(payload)
    if not normalized:
        raise HTTPException(status_code=422, detail="Invalid web chat payload")

    response = await process_user_message(
        db=db,
        context=normalized.context,
        user_message=normalized.text,
    )
    return {
        "status": "ok",
        "channel": normalized.context.channel,
        "correlation_id": normalized.context.correlation_id,
        "response": response,
    }
