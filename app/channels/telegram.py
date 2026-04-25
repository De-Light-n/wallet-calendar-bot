"""Telegram adapter helpers."""
from __future__ import annotations

from typing import Any

from app.channels.base import ChannelAdapter, NormalizedMessage
from app.core.context import AgentRequestContext


class TelegramAdapter(ChannelAdapter):
    channel_name = "telegram"

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        message = payload.get("message") or {}
        from_user = message.get("from") or {}
        text = message.get("text")
        if not text:
            return None

        external_user_id = str(from_user.get("id", ""))
        if not external_user_id:
            return None

        context = AgentRequestContext(
            channel=self.channel_name,
            external_user_id=external_user_id,
            message_id=str(message.get("message_id", "")) or None,
        )
        return NormalizedMessage(context=context, text=text)
