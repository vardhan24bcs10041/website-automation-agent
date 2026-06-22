"""CLI entry point.

    python main.py
    python main.py "fill the Name and Description fields and submit"
"""

from __future__ import annotations

import sys

from agent.agent_loop import DEFAULT_GOAL, Agent
from agent.browser_tools import BrowserTools, ToolError
from agent.llm_client import GeminiClient
from agent.logger import get_logger

logger = get_logger("main")


def _log_event(event: dict) -> None:
    kind = event.get("event")
    if kind == "decision":
        logger.info(
            "step %s | %s(%s) | %s",
            event.get("step"),
            event.get("tool"),
            event.get("input"),
            event.get("reasoning", "")[:120],
        )
    elif kind == "action":
        status = "ok" if event.get("success") else f"FAIL: {event.get('error')}"
        logger.info("step %s | %s -> %s", event.get("step"), event.get("tool"), status)
    elif kind == "model_switch":
        logger.info("model: %s -> %s", event.get("from"), event.get("to"))
    else:
        logger.info("event: %s", event)


def run(goal: str) -> dict:
    tools = BrowserTools()
    llm = GeminiClient()
    agent = Agent(tools, llm, goal=goal, on_progress=_log_event)
    try:
        return agent.run()
    finally:
        tools.close()


def main() -> None:
    goal = " ".join(sys.argv[1:]).strip() or DEFAULT_GOAL

    try:
        result = run(goal)
    except ToolError as exc:
        logger.error("Agent aborted: %s", exc)
        print(f"\n=== RESULT: FAILED ===\nReason: {exc}")
        sys.exit(1)

    finished = result.get("status") == "finished"
    print("\n=== RESULT: " + ("SUCCESS" if finished else "INCOMPLETE") + " ===")
    print(f"Status : {result.get('status')}")
    print(f"Steps  : {result.get('steps')}")
    print(f"Model  : {result.get('model')}")
    print(f"Summary: {result.get('summary')}")
    sys.exit(0 if finished else 2)


if __name__ == "__main__":
    main()
