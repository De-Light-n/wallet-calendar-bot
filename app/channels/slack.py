"""Slack adapter for event webhook payloads."""
from __future__ import annotations

from typing import Any

from app.channels.base import ChannelAdapter, NormalizedMessage
from app.core.context import AgentRequestContext


class SlackAdapter(ChannelAdapter):
    channel_name = "slack"

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        event = payload.get("event") or {}
        text = event.get("text")
        external_user_id = event.get("user")
        if not text or not external_user_id:
            return None

        context = AgentRequestContext(
            channel=self.channel_name,
            external_user_id=str(external_user_id),
            message_id=str(event.get("client_msg_id") or event.get("ts") or "") or None,
        )
        return NormalizedMessage(context=context, text=text)
