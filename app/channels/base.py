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
    """Common adapter interface for inbound payload normalization."""

    channel_name: str

    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage | None:
        raise NotImplementedError
