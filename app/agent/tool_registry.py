"""Tool registry for dynamic OpenAI function-call dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

ToolExecutor = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolDefinition:
    """A single tool definition used for schema exposure and execution."""

    name: str
    description: str
    parameters: dict[str, Any]
    executor: ToolExecutor


class ToolRegistry:
    """In-memory registry of tools available to the LLM."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get_openai_schemas(self) -> list[dict[str, Any]]:
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
        tool = self._tools.get(name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {name}"}
        return await tool.executor(user_id=user_id, db=db, **args)
