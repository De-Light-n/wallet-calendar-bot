"""Base channel adapter contracts and message envelope."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.context import AgentRequestContext


@dataclass(slots=True)
class NormalizedMessage:
    """Channel-normalized incoming message."""

    context: AgentRequestContext
    text: str


class ChannelAdapter:
    """Common adapter interface for inbound payload normalization.

    Concrete subclasses set ``channel_name`` and implement :meth:`normalize`
    to convert provider-specific payloads (Telegram update, Slack event,
    Discord message, etc.) into a :class:`NormalizedMessage`.
    """

    channel_name: str

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        """Translate a raw provider payload into a normalised message.

        Returns ``None`` when the payload should be ignored (system events,
        bot messages, edits, retries, ...). Concrete adapters MUST keep this
        contract so the caller can branch on a single ``is None`` check.
        """
        raise NotImplementedError
