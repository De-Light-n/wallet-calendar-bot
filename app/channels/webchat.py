"""Web chat adapter for React frontend payloads."""
from __future__ import annotations

from typing import Any

from app.channels.base import ChannelAdapter, NormalizedMessage
from app.core.context import AgentRequestContext


class WebChatAdapter(ChannelAdapter):
    channel_name = "web"

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        text = payload.get("text")
        external_user_id = payload.get("external_user_id")
        if not text or not external_user_id:
            return None

        context = AgentRequestContext(
            channel=self.channel_name,
            external_user_id=str(external_user_id),
            message_id=str(payload.get("message_id") or "") or None,
        )
        return NormalizedMessage(context=context, text=text)
