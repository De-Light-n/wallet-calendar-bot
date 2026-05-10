"""Tool registry for dynamic OpenAI function-call dispatch.

Decouples the agent loop from the concrete tool implementations. Tools are
registered once at import time with a JSON-schema description and an async
executor; the agent then asks the registry for OpenAI-shaped schemas and
dispatches by name when the model returns ``tool_calls``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

ToolExecutor = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolDefinition:
    """A single tool exposed to the LLM.

    Attributes:
        name: Stable identifier the model uses in ``tool_calls``.
        description: Human-readable explanation passed to the model — the
            primary signal it uses to decide when to call the tool.
        parameters: JSON-schema describing the tool arguments.
        executor: Async callable invoked with ``(user_id, db, **args)`` that
            must return a JSON-serialisable dict (typically with a ``status``
            field).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    executor: ToolExecutor


class ToolRegistry:
    """In-memory registry of tools available to the LLM."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Add or replace a tool under its ``name``."""
        self._tools[tool.name] = tool

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI's ``tools=[{type, function}]`` shape."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        name: str,
        *,
        user_id: int,
        db: Session,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Look up ``name`` and run its executor with the given arguments.

        Returns an error envelope when the tool name is unknown rather than
        raising, so the agent loop can feed the message back to the model and
        let it self-correct on the next turn.
        """
        tool = self._tools.get(name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {name}"}
        return await tool.executor(user_id=user_id, db=db, **args)
