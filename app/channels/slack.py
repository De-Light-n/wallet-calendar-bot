"""Slack adapter for inbound event normalization."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.channels.base import ChannelAdapter, NormalizedMessage
from app.core.context import AgentRequestContext

# Strips a leading `<@U12345678>` mention so the agent doesn't see itself addressed.
_MENTION_PATTERN = re.compile(r"^<@([A-Z0-9]+)>\s*", re.IGNORECASE)


@dataclass(slots=True)
class SlackInbound(NormalizedMessage):
    """Slack-specific extension that carries the channel id needed to reply."""

    slack_channel_id: str = ""


class SlackAdapter(ChannelAdapter):
    channel_name = "slack"

    def normalize(self, payload: dict[str, Any]) -> SlackInbound | None:
        """Convert a Slack Events API payload into a NormalizedMessage.

        Returns None when:
        - The payload isn't an `event_callback` (e.g. URL verification handled elsewhere).
        - The event isn't a user message (system events, channel joins, etc.).
        - The author is a bot (including this bot itself) — prevents loops.
        """
        if payload.get("type") != "event_callback":
            return None

        event = payload.get("event") or {}
        event_type = event.get("type")

        # We respond to two event types:
        #   message         — DMs (subtype=None) and channel messages we can read
        #   app_mention     — when someone tags @bot in a channel
        if event_type not in {"message", "app_mention"}:
            return None

        # Skip edits, deletions, channel-join system messages, etc.
        # A regular user DM has no `subtype`.
        if event.get("subtype"):
            return None

        # Skip messages authored by bots (including ourselves) so we don't loop.
        if event.get("bot_id") or event.get("bot_profile"):
            return None

        text = (event.get("text") or "").strip()
        external_user_id = event.get("user")
        slack_channel_id = event.get("channel")

        if not text or not external_user_id or not slack_channel_id:
            return None

        # Strip a leading "<@BOTID>" if present so the LLM sees clean user text.
        text = _MENTION_PATTERN.sub("", text).strip()
        if not text:
            return None

        context = AgentRequestContext(
            channel=self.channel_name,
            external_user_id=str(external_user_id),
            message_id=str(
                event.get("client_msg_id") or event.get("event_ts") or event.get("ts") or ""
            )
            or None,
        )
        return SlackInbound(
            context=context,
            text=text,
            slack_channel_id=str(slack_channel_id),
        )
