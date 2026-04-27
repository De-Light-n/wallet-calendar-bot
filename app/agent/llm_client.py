"""LLM client – OpenAI function-calling agent."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any

import zoneinfo
from openai import APIError, AsyncOpenAI, RateLimitError

from app.agent.tool_registry import ToolDefinition, ToolRegistry
from app.core.config import settings
from app.core.context import AgentRequestContext
from app.agent.system_prompts import SYSTEM_PROMPT

_client: AsyncOpenAI | None = None
logger = logging.getLogger(__name__)

_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
_RETRYABLE_API_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def _render_llm_error(exc: Exception) -> str:
    """Map provider exceptions to user-safe, actionable text."""
    if isinstance(exc, RateLimitError):
        return (
            "Тимчасово перевищено ліміт запитів до LLM-провайдера. "
            "Спробуйте ще раз через 20-60 секунд."
        )
    if isinstance(exc, APIError):
        return (
            "LLM-провайдер зараз недоступний або повернув помилку. "
            "Спробуйте повторити запит пізніше."
        )
    return "Сталася неочікувана помилка під час обробки запиту. Спробуйте ще раз."


def _status_code_from_error(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after is None:
        return None

    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(seconds, 30.0))


def _is_retryable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIError):
        status_code = _status_code_from_error(exc)
        return status_code is None or status_code in _RETRYABLE_API_STATUS_CODES
    return False


async def _create_chat_completion(client: AsyncOpenAI, **kwargs: Any) -> Any:
    attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, attempts + 1):
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:
            if not _is_retryable_llm_error(exc) or attempt >= attempts:
                raise

            wait_seconds = _retry_after_seconds(exc)
            if wait_seconds is None:
                wait_seconds = _RETRY_DELAYS_SECONDS[attempt - 1]

            logger.warning(
                "Transient LLM error (attempt %s/%s, status=%s, type=%s). "
                "Retrying in %.1fs",
                attempt,
                attempts,
                _status_code_from_error(exc),
                exc.__class__.__name__,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    raise RuntimeError("LLM completion retry loop ended unexpectedly")


def _fallback_after_tool_execution(tool_results: list[tuple[str, dict[str, Any]]]) -> str | None:
    successful = [
        (name, payload)
        for name, payload in tool_results
        if payload.get("status") == "ok"
    ]
    if not successful:
        return None

    lines = [
        "Дію виконано, але LLM-провайдер тимчасово обмежив генерацію детальної відповіді.",
    ]

    for tool_name, payload in successful:
        if tool_name == "record_transaction":
            tx_type = payload.get("transaction_type") or "Transaction"
            amount = payload.get("amount")
            currency = payload.get("currency") or ""
            category = payload.get("category")
            detail = f"{tx_type}: {amount} {currency}".strip()
            if category:
                detail = f"{detail} ({category})"
            lines.append(f"- {detail}")
            continue

        if tool_name == "create_calendar_event":
            event_link = payload.get("event_link")
            if event_link:
                lines.append(f"- Подію календаря створено: {event_link}")
            else:
                lines.append("- Подію календаря створено.")
            continue

        lines.append(f"- Виконано дію: {tool_name}")

    lines.append("Спробуйте ще раз через 20-60 секунд для повної текстової відповіді.")
    return "\n".join(lines)


def _get_client() -> AsyncOpenAI:
    """Create OpenAI client lazily to avoid import-time failures in tests."""
    global _client
    if _client is None:
        # Google Gemini тепер має офіційну підтримку OpenAI SDK!
        _client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
    return _client

def _build_registry() -> ToolRegistry:
    """Register default tools for this assistant."""
    # Lazy import so tool modules can safely import DB models.
    from app.tools.calendar_tool import create_calendar_event
    from app.tools.finance_tool import record_transaction

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
            name="record_transaction",
            description=(
                "Records a financial transaction to the user's Google Sheets ledger "
                "(supports both Expense and Income)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "transaction_type": {
                        "type": "string",
                        "enum": ["Expense", "Income"],
                        "description": "Use 'Expense' for money spent or 'Income' for money received.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Transaction amount as a positive number.",
                    },
                    "currency": {
                        "type": "string",
                        "description": "Currency code (e.g. UAH, USD, EUR). Defaults to UAH.",
                        "default": "UAH",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category in English from the allowed taxonomy.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Short human description in Ukrainian.",
                    },
                },
                "required": ["transaction_type", "amount", "category", "description"],
            },
            executor=record_transaction,
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
    # 🌍 Вирішуємо проблему часового поясу
    tz_str = context.timezone if context and context.timezone else "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")

    now_local = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    prompt_timezone = tz.key if hasattr(tz, "key") else tz_str

    system_content = SYSTEM_PROMPT.format(
        current_datetime=now_local,
        timezone=prompt_timezone,
    )
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

    correlation_id = context.correlation_id if context else None
    logger.info(
        "run_agent: user_id=%s correlation_id=%s tz=%s message_len=%s model=%s",
        user_id,
        correlation_id,
        prompt_timezone,
        len(user_message),
        settings.openai_model,
    )

    # First LLM call – may return tool calls
    client = _get_client()
    try:
        response = await _create_chat_completion(
            client,
            model=settings.openai_model,
            messages=messages,
            tools=REGISTRY.get_openai_schemas(),
            tool_choice="auto",
        )
    except Exception as exc:
        logger.exception(
            "run_agent: first LLM call failed (user_id=%s): %s",
            user_id,
            exc,
        )
        return _render_llm_error(exc)

    message = response.choices[0].message
    messages.append(message.model_dump(exclude_none=True))

    # Execute tool calls (if any) and collect results
    tool_calls = message.tool_calls or []
    if tool_calls:
        logger.info(
            "run_agent: model requested %s tool call(s): %s (user_id=%s)",
            len(tool_calls),
            [tc.function.name for tc in tool_calls],
            user_id,
        )
    else:
        logger.info(
            "run_agent: no tool calls — direct answer (user_id=%s, content_len=%s)",
            user_id,
            len(message.content or ""),
        )

    executed_tool_results: list[tuple[str, dict[str, Any]]] = []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as exc:
            logger.error(
                "run_agent: invalid JSON in tool call args | user_id=%s tool=%s "
                "raw_args=%r error=%s",
                user_id,
                func_name,
                tool_call.function.arguments,
                exc,
            )
            tool_result_payload = {"status": "error", "error": f"Invalid JSON args: {exc}"}
            executed_tool_results.append((func_name, tool_result_payload))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result_payload, ensure_ascii=False),
                }
            )
            continue

        logger.info(
            "run_agent: executing tool=%s (user_id=%s, args=%s)",
            func_name,
            user_id,
            args,
        )
        try:
            tool_result = await REGISTRY.execute(
                func_name,
                user_id=user_id,
                db=db_session,
                args=args,
            )
        except Exception as exc:
            logger.exception(
                "run_agent: tool execution raised | user_id=%s tool=%s: %s",
                user_id,
                func_name,
                exc,
            )
            if db_session is not None:
                db_session.rollback()
            tool_result = {"status": "error", "error": str(exc)}

        if isinstance(tool_result, dict):
            tool_result_payload = tool_result
        else:
            tool_result_payload = {"status": "ok", "data": tool_result}

        logger.info(
            "run_agent: tool=%s result_status=%s (user_id=%s)",
            func_name,
            tool_result_payload.get("status"),
            user_id,
        )
        executed_tool_results.append((func_name, tool_result_payload))

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result_payload, ensure_ascii=False),
            }
        )

    # If there were tool calls, make a second LLM call to get the final answer
    if tool_calls:
        try:
            final_response = await _create_chat_completion(
                client,
                model=settings.openai_model,
                messages=messages,
            )
        except Exception as exc:
            logger.exception(
                "run_agent: second LLM call (after tools) failed | user_id=%s: %s",
                user_id,
                exc,
            )
            fallback = _fallback_after_tool_execution(executed_tool_results)
            if fallback and isinstance(exc, (RateLimitError, APIError)):
                logger.warning(
                    "Returning fallback text after tool execution due to final LLM error: %s",
                    exc.__class__.__name__,
                )
                return fallback
            return _render_llm_error(exc)
        final_content = final_response.choices[0].message.content or ""
        logger.info(
            "run_agent: final answer ready (user_id=%s, content_len=%s)",
            user_id,
            len(final_content),
        )
        return final_content

    # No tool calls – return the model's direct response
    return message.content or ""
