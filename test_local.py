#!/usr/bin/env python3
"""Local console test: verify LLM understands context and forms tool-call JSON.

Usage:
    FINANCE_STUB_MODE=true python test_local.py

With stub mode the agent calls record_transaction which just prints params —
no DB or Google credentials required.
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()

from app.agent.llm_client import run_agent  # noqa: E402  (dotenv must load first)

# Stub mode bypasses DB lookup, so any non-negative int works here.
_TEST_USER_ID = 0


async def main() -> None:
    print("Local agent REPL (type 'exit' or Ctrl+C to quit)\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_input or user_input.lower() == "exit":
            break
        response = await run_agent(user_input, _TEST_USER_ID, db_session=None)
        print(f"Agent: {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
