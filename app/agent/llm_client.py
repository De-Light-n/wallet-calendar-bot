"""LLM client – OpenAI function-calling agent."""
from __future__ import annotations

import datetime
import json
from typing import Any

from openai import AsyncOpenAI

from app.agent.tool_registry import ToolDefinition, ToolRegistry
from app.core.config import settings
from app.core.context import AgentRequestContext
from app.agent.system_prompts import SYSTEM_PROMPT

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Create OpenAI client lazily to avoid import-time failures in tests."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client

def _build_registry() -> ToolRegistry:
    """Register default tools for this assistant."""
    # Lazy import so tool modules can safely import DB models.
    from app.tools.calendar_tool import create_calendar_event
    from app.tools.finance_tool import add_expense

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="create_calendar_event",
            description="Creates an event or reminder in the user's Google Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title / summary of the event.",
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Start date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": (
                            "End date and time in ISO 8601 format. "
                            "If not specified by the user, defaults to 1 hour after start."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description or notes for the event.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional location of the event.",
                    },
                },
                "required": ["title", "start_datetime"],
            },
            executor=create_calendar_event,
        )
    )
    registry.register(
        ToolDefinition(
            name="add_expense",
            description="Records a new expense in the user's personal wallet.",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Monetary amount of the expense.",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Currency code (e.g. UAH, USD, EUR). Defaults to UAH.",
                        "default": "UAH",
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Expense category: food, transport, entertainment, "
                            "health, utilities, shopping, other."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Short description of what the expense was for.",
                    },
                },
                "required": ["amount"],
            },
            executor=add_expense,
        )
    )
    return registry


REGISTRY = _build_registry()


async def run_agent(
    user_message: str,
    user_id: int,
    db_session: Any,
    context: AgentRequestContext | None = None,
) -> str:
    """Run the LLM agent for a given user message.

    Performs one or more tool calls as determined by the model and returns
    the final human-readable response.

    Args:
        user_message: Text message from the user.
        user_id:      Internal user ID (used for tool execution context).
        db_session:   SQLAlchemy database session.
        context:      Optional normalized request context.

    Returns:
        Final response string to send back to the user.
    """
    now_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    system_content = SYSTEM_PROMPT.format(current_datetime=now_utc)
    if context:
        system_content = (
            f"{system_content}\n"
            f"Channel: {context.channel}; timezone: {context.timezone}; "
            f"correlation_id: {context.correlation_id}."
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]

    # First LLM call – may return tool calls
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        tools=REGISTRY.get_openai_schemas(),
        tool_choice="auto",
    )

    message = response.choices[0].message
    messages.append(message.model_dump(exclude_none=True))

    # Execute tool calls (if any) and collect results
    tool_calls = message.tool_calls or []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        try:
            tool_result = await REGISTRY.execute(
                func_name,
                user_id=user_id,
                db=db_session,
                args=args,
            )
        except Exception as exc:  # pragma: no cover
            db_session.rollback()
            tool_result = {"status": "error", "error": str(exc)}

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result, ensure_ascii=False),
            }
        )

    # If there were tool calls, make a second LLM call to get the final answer
    if tool_calls:
        final_response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
        )
        return final_response.choices[0].message.content or ""

    # No tool calls – return the model's direct response
    return message.content or ""
