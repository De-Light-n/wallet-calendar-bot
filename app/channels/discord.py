"""Discord adapter for message create webhook payloads."""
from __future__ import annotations

from typing import Any

from app.channels.base import ChannelAdapter, NormalizedMessage
from app.core.context import AgentRequestContext


class DiscordAdapter(ChannelAdapter):
    channel_name = "discord"

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        text = payload.get("content")
        author = payload.get("author") or {}
        external_user_id = author.get("id")
        if not text or not external_user_id:
            return None

        context = AgentRequestContext(
            channel=self.channel_name,
            external_user_id=str(external_user_id),
            message_id=str(payload.get("id") or "") or None,
        )
        return NormalizedMessage(context=context, text=text)
