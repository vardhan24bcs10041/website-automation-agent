"""The perceive -> decide -> act loop.

Each step: capture a screenshot, ask Gemini for the next action, run the matching
browser tool, then feed a fresh screenshot back. Runs until the model calls
task_complete or MAX_STEPS is reached. Tool failures and model rate-limit
switches are surfaced as events so the run never crashes silently.
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional

from google.genai import types

import config
from agent.browser_tools import BrowserTools, ToolError
from agent.llm_client import GeminiClient
from agent.logger import get_logger

logger = get_logger("agent_loop")

ProgressCallback = Callable[[Dict[str, Any]], None]

DEFAULT_GOAL = (
    "Find the Name field and the Description field on the page. Click the Name "
    "field and type a sample name, then click the Description field and type a "
    "sample description. When both are filled, call task_complete."
)

_TERMINAL_TOOL = "task_complete"


class Agent:
    """Drives the vision/decision/action cycle against a browser."""

    def __init__(
        self,
        tools: BrowserTools,
        llm: GeminiClient,
        goal: str = DEFAULT_GOAL,
        max_steps: Optional[int] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        self.tools = tools
        self.llm = llm
        self.goal = goal
        self.max_steps = max_steps or config.MAX_STEPS
        self.on_progress = on_progress
        self.contents: List[types.Content] = []
        self._last_model: Optional[str] = None

    def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_progress is not None:
            try:
                self.on_progress(event)
            except Exception:
                logger.exception("progress callback failed")
        else:
            logger.info("event: %s", event)

    def _note_model(self, step: int) -> str:
        """Emit a model_switch event when the active model changes."""
        model = self.llm.current_model
        if model != self._last_model:
            self._emit(
                {"event": "model_switch", "step": step,
                 "from": self._last_model, "to": model}
            )
            self._last_model = model
        return model

    def _execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "open_browser":
            self.tools.open_browser()
            return {"tool": "open_browser", "status": "ok"}
        if name == "navigate_to_url":
            return self.tools.navigate_to_url(args["url"])
        if name == "take_screenshot":
            shot = self.tools.take_screenshot()
            return {"tool": "take_screenshot", "path": shot["path"]}
        if name == "click_on_screen":
            return self.tools.click_on_screen(int(args["x"]), int(args["y"]))
        if name == "send_keys":
            return self.tools.send_keys(args["text"])
        if name == "scroll":
            return self.tools.scroll(
                args.get("direction", "down"), int(args.get("amount", 400))
            )
        if name == "double_click":
            return self.tools.double_click(int(args["x"]), int(args["y"]))
        raise ToolError(f"Unknown tool: {name}")

    @staticmethod
    def _candidate_parts(response) -> List[Any]:
        try:
            return response.candidates[0].content.parts or []
        except (AttributeError, IndexError, TypeError):
            return []

    def _extract_text(self, response) -> str:
        parts = self._candidate_parts(response)
        return " ".join(p.text for p in parts if getattr(p, "text", None)).strip()

    def _extract_calls(self, response) -> List[Any]:
        parts = self._candidate_parts(response)
        return [p.function_call for p in parts if getattr(p, "function_call", None)]

    def _fresh_screenshot_part(self) -> types.Part:
        shot = self.tools.take_screenshot()
        return self.llm.image_part(base64.b64decode(shot["base64"]))

    def run(self) -> Dict[str, Any]:
        """Run until task_complete or the step cap; return a summary dict."""
        logger.info("Goal: %s", self.goal)
        self._last_model = self.llm.current_model
        self._emit({"event": "start", "goal": self.goal, "model": self._last_model})

        self.tools.open_browser()
        nav = self.tools.navigate_to_url(config.TARGET_URL)
        first_shot = self.tools.take_screenshot()
        self.contents.append(
            types.Content(
                role="user",
                parts=[
                    self.llm.image_part(base64.b64decode(first_shot["base64"])),
                    types.Part.from_text(
                        text=f"The browser is on {nav['url']}.\n\nTask: {self.goal}"
                    ),
                ],
            )
        )

        for step in range(1, self.max_steps + 1):
            logger.info("Step %d/%d (model=%s)", step, self.max_steps, self.llm.current_model)
            response = self.llm.next_action(self.contents)
            model = self._note_model(step)

            parts = self._candidate_parts(response)
            if not parts:
                logger.warning("Empty response (no candidate); nudging.")
                self._emit({"event": "no_action", "step": step, "reasoning": ""})
                self.contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Please call one tool to proceed.")],
                    )
                )
                continue

            self.contents.append(response.candidates[0].content)
            reasoning = self._extract_text(response)
            calls = self._extract_calls(response)

            if not calls:
                logger.warning("No function call this step; nudging.")
                self._emit({"event": "no_action", "step": step, "reasoning": reasoning})
                self.contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Please continue by calling exactly one tool.")],
                    )
                )
                continue

            response_parts: List[types.Part] = []
            executed_any = False
            for fc in calls:
                name = fc.name
                args = dict(fc.args or {})
                self._emit({
                    "event": "decision", "step": step, "model": model,
                    "tool": name, "input": args, "reasoning": reasoning,
                })

                if name == _TERMINAL_TOOL:
                    summary = args.get("summary", "Task complete.")
                    logger.info("Finished: %s", summary)
                    self._emit({"event": "finish", "step": step, "summary": summary})
                    return {"status": "finished", "steps": step,
                            "summary": summary, "model": model}

                try:
                    result = self._execute(name, args)
                    executed_any = True
                    response_parts.append(
                        types.Part.from_function_response(
                            name=name, response={"result": result}
                        )
                    )
                    self._emit({"event": "action", "step": step, "tool": name,
                                "success": True, "result": result})
                except ToolError as exc:
                    logger.warning("Tool %s failed: %s", name, exc)
                    response_parts.append(
                        types.Part.from_function_response(
                            name=name, response={"error": str(exc)}
                        )
                    )
                    self._emit({"event": "action", "step": step, "tool": name,
                                "success": False, "error": str(exc)})

            if executed_any:
                response_parts.append(self._fresh_screenshot_part())
            self.contents.append(types.Content(role="user", parts=response_parts))

        logger.info("Reached max steps (%d) without finishing.", self.max_steps)
        self._emit({"event": "max_steps", "steps": self.max_steps})
        return {
            "status": "max_steps",
            "steps": self.max_steps,
            "summary": f"Stopped after {self.max_steps} steps without completing.",
            "model": self.llm.current_model,
        }
