"""Webhook and API routes for multi-channel ingress."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.agent.orchestrator import process_user_message
from app.channels.discord import DiscordAdapter
from app.channels.slack import SlackAdapter
from app.channels.webchat import WebChatAdapter
from app.core.config import settings
from app.database.session import get_db

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("/slack/webhook")
async def slack_webhook(
    payload: dict,
    db: Session = Depends(get_db),
    x_slack_signature: str | None = Header(default=None),
) -> dict:
    if not settings.is_channel_enabled("slack"):
        raise HTTPException(status_code=404, detail="Slack channel is disabled")

    expected = settings.slack_signing_secret
    if expected and x_slack_signature != expected:
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    normalized = SlackAdapter().normalize(payload)
    if not normalized:
        return {"status": "ignored"}

    response = await process_user_message(
        db=db,
        context=normalized.context,
        user_message=normalized.text,
    )
    return {"status": "ok", "response": response}


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
