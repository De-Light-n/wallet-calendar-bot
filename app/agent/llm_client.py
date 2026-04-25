"""LLM client – OpenAI function-calling agent."""
from __future__ import annotations

import datetime
import json
import os
from typing import Any

from openai import AsyncOpenAI

from app.agent.system_prompts import SYSTEM_PROMPT

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------------
# Tool schemas (passed to the model as JSON-Schema function definitions)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Creates an event or reminder in the user's Google Calendar."
            ),
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Records a new expense in the user's personal wallet.",
            "parameters": {
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
        },
    },
]


async def run_agent(
    user_message: str,
    telegram_id: int,
    db_session: Any,
) -> str:
    """Run the LLM agent for a given user message.

    Performs one or more tool calls as determined by the model and returns
    the final human-readable response.

    Args:
        user_message: Text message from the user.
        telegram_id:  Telegram user ID (used for tool execution context).
        db_session:   SQLAlchemy database session.

    Returns:
        Final response string to send back to the user.
    """
    # Lazy imports to avoid circular dependencies at module load time
    from app.tools.calendar_tool import create_calendar_event
    from app.tools.finance_tool import add_expense

    now_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    system_content = SYSTEM_PROMPT.format(current_datetime=now_utc)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]

    # First LLM call – may return tool calls
    response = await _client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )

    message = response.choices[0].message
    messages.append(message.model_dump(exclude_none=True))

    # Execute tool calls (if any) and collect results
    tool_calls = message.tool_calls or []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name == "create_calendar_event":
            tool_result = await create_calendar_event(
                telegram_id=telegram_id,
                db=db_session,
                **args,
            )
        elif func_name == "add_expense":
            tool_result = await add_expense(
                telegram_id=telegram_id,
                db=db_session,
                **args,
            )
        else:
            tool_result = {"error": f"Unknown tool: {func_name}"}

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result, ensure_ascii=False),
            }
        )

    # If there were tool calls, make a second LLM call to get the final answer
    if tool_calls:
        final_response = await _client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
        )
        return final_response.choices[0].message.content or ""

    # No tool calls – return the model's direct response
    return message.content or ""
