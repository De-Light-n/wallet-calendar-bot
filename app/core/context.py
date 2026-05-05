"""Shared request context types for channel-agnostic orchestration."""
from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class AgentRequestContext:
    """Normalized inbound context across all channels."""

    channel: str
    external_user_id: str
    message_id: str | None = None
    locale: str | None = None
    timezone: str = "UTC"
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.correlation_id:
            self.correlation_id = str(uuid.uuid4())
