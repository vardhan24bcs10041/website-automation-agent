"""FastAPI backend: serves the dashboard and streams a live agent run over /ws.

The agent is reused as-is; this module only forwards its progress events (with
the latest screenshot) onto a WebSocket. Run with: uvicorn server.app:app
"""

from __future__ import annotations

import asyncio
import base64
import glob
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.agent_loop import DEFAULT_GOAL, Agent
from agent.browser_tools import BrowserTools
from agent.llm_client import GeminiClient
from agent.logger import get_logger

logger = get_logger("server")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")

app = FastAPI(title="website-automation-agent")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR), name="screenshots")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


def _latest_screenshot_b64() -> Optional[str]:
    """Newest screenshot as base64 — the agent writes one after each action."""
    files = glob.glob(os.path.join(SCREENSHOT_DIR, "*.png"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    try:
        with open(newest, "rb") as fh:
            return base64.b64encode(fh.read()).decode("utf-8")
    except OSError:
        return None


def _run_agent_blocking(goal: str, emit) -> Dict[str, Any]:
    """Run one agent session synchronously (intended for a worker thread)."""
    tools = BrowserTools()
    llm = GeminiClient()
    agent = Agent(tools, llm, goal=goal, on_progress=emit)
    try:
        return agent.run()
    finally:
        tools.close()


@app.websocket("/ws")
async def agent_socket(ws: WebSocket) -> None:
    """On {"action": "start"}, run the agent and stream events + screenshots."""
    await ws.accept()
    loop = asyncio.get_running_loop()

    def emit(event: Dict[str, Any]) -> None:
        # Called from the worker thread; hand the send back to the event loop.
        payload = dict(event)
        shot = _latest_screenshot_b64()
        if shot is not None:
            payload["screenshot"] = shot
        asyncio.run_coroutine_threadsafe(ws.send_json(payload), loop)

    running = False
    try:
        while True:
            message = await ws.receive_json()
            action = (message or {}).get("action")

            if action != "start":
                await ws.send_json(
                    {"event": "error", "detail": f"Unknown action: {action!r}"}
                )
                continue
            if running:
                await ws.send_json(
                    {"event": "error", "detail": "A run is already in progress."}
                )
                continue

            goal = (message.get("goal") or "").strip() or DEFAULT_GOAL
            logger.info("Starting agent run via WebSocket: %s", goal)
            running = True
            try:
                result = await asyncio.to_thread(_run_agent_blocking, goal, emit)
                await ws.send_json({"event": "done", "result": result})
            finally:
                running = False
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as exc:
        logger.exception("WebSocket run failed")
        try:
            await ws.send_json({"event": "error", "detail": str(exc)})
        except Exception:
            pass
