"""Gemini client with automatic model fallback.

The browser actions are exposed to Gemini as function-calling tools. Free-tier
keys have tight per-model quotas, so the client holds an ordered chain of models
and rotates to the next one when a request is rate-limited (429) or the model is
unavailable (404). Each model has its own quota, so the chain extends how long
the agent can keep running.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors, types

import config
from agent.logger import get_logger

logger = get_logger("llm_client")


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "OBJECT", "properties": properties, "required": required}


def build_tools() -> List[types.Tool]:
    """Build the function declarations for the 7 actions plus task_complete."""
    declarations = [
        types.FunctionDeclaration(
            name="open_browser",
            description=(
                "Launch the Chromium browser at the fixed viewport. The browser "
                "is normally already open, so you rarely need this."
            ),
        ),
        types.FunctionDeclaration(
            name="navigate_to_url",
            description="Navigate the browser to an absolute URL.",
            parameters=_schema(
                {"url": {"type": "STRING", "description": "Absolute URL to open."}},
                ["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="take_screenshot",
            description=(
                "Capture the current page. A fresh screenshot is already shown "
                "to you after every action, so you usually do not need this."
            ),
        ),
        types.FunctionDeclaration(
            name="click_on_screen",
            description=(
                "Click at pixel coordinates in the screenshot (top-left origin). "
                "Click a form field to focus it BEFORE typing into it."
            ),
            parameters=_schema(
                {
                    "x": {"type": "INTEGER", "description": "Horizontal pixel coordinate."},
                    "y": {"type": "INTEGER", "description": "Vertical pixel coordinate."},
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_keys",
            description=(
                "Type text into the currently focused element. Always click the "
                "target field first so the text goes where you intend."
            ),
            parameters=_schema(
                {"text": {"type": "STRING", "description": "The text to type."}},
                ["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="scroll",
            description="Scroll the page up or down by a number of pixels.",
            parameters=_schema(
                {
                    "direction": {
                        "type": "STRING",
                        "enum": ["up", "down"],
                        "description": "Scroll direction.",
                    },
                    "amount": {
                        "type": "INTEGER",
                        "description": "Pixels to scroll (positive).",
                    },
                },
                ["direction"],
            ),
        ),
        types.FunctionDeclaration(
            name="double_click",
            description="Double-click at pixel coordinates (e.g. to select a word).",
            parameters=_schema(
                {
                    "x": {"type": "INTEGER", "description": "Horizontal pixel coordinate."},
                    "y": {"type": "INTEGER", "description": "Vertical pixel coordinate."},
                },
                ["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="task_complete",
            description=(
                "Call this when the task is finished — the required fields have "
                "been filled (and submitted, if asked). Ends the run."
            ),
            parameters=_schema(
                {
                    "summary": {
                        "type": "STRING",
                        "description": "Short summary of what was accomplished.",
                    }
                },
                ["summary"],
            ),
        ),
    ]
    return [types.Tool(function_declarations=declarations)]


def build_system_prompt(width: int, height: int) -> str:
    """System prompt with the exact viewport baked in for accurate coordinates."""
    return f"""\
You are a vision-based web automation agent controlling a REAL Chromium browser.

The browser viewport is fixed at {width}x{height} pixels. Every screenshot you
receive is exactly {width}x{height} pixels, so the pixel coordinates you see map
1:1 to where a click will land. Use the top-left corner as the origin (0, 0).

You act only through the provided tools (functions) — there is no other way to
control the browser. After each action you are shown a fresh screenshot.

How to fill a form field correctly:
  1. Visually locate the field in the screenshot.
  2. click_on_screen at the CENTER of that field to focus it.
  3. send_keys to type the value into the now-focused field.
Never call send_keys without clicking the target field first — otherwise the
text goes nowhere.

Your task involves a "Name" field and a "Description" field. Find each one
visually, click it, then type a sensible sample value. Scroll if a field is not
currently visible. When both fields are filled (and the form submitted if the
task asks for it), call task_complete with a short summary.

Think briefly about what you see, then call exactly one tool per step."""


class RateLimitExhausted(RuntimeError):
    """Raised when every model in the fallback chain is rate-limited."""


class GeminiClient:
    """Gemini wrapper that rotates models on rate limits."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
    ) -> None:
        self.client = genai.Client(api_key=api_key or config.GEMINI_API_KEY)
        self.models = list(models or config.MODEL_FALLBACK_CHAIN)
        if not self.models:
            raise ValueError("Model fallback chain is empty.")
        self._index = 0
        self._unavailable: set[str] = set()

        self._gen_config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(
                config.VIEWPORT_WIDTH, config.VIEWPORT_HEIGHT
            ),
            tools=build_tools(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            temperature=0.0,
        )

    @property
    def current_model(self) -> str:
        return self.models[self._index]

    @staticmethod
    def image_part(image_bytes: bytes) -> types.Part:
        return types.Part.from_bytes(data=image_bytes, mime_type="image/png")

    def _advance(self) -> None:
        self._index = (self._index + 1) % len(self.models)

    @staticmethod
    def _status_code(exc: Exception) -> Optional[int]:
        return getattr(exc, "code", None) or getattr(exc, "status_code", None)

    def _is_rate_limit(self, exc: Exception) -> bool:
        if self._status_code(exc) == 429:
            return True
        text = str(exc).upper()
        return "RESOURCE_EXHAUSTED" in text or "429" in text

    def _is_unavailable(self, exc: Exception) -> bool:
        if self._status_code(exc) == 404:
            return True
        return "NOT_FOUND" in str(exc).upper()

    def next_action(self, contents: List[types.Content]):
        """Get Gemini's next action, rotating models on rate limits/availability.

        Raises RateLimitExhausted if every usable model is rate-limited, or
        RuntimeError if no usable model remains.
        """
        attempts = 0
        total = len(self.models)
        last_exc: Optional[Exception] = None

        while attempts < total:
            model = self.current_model
            if model in self._unavailable:
                self._advance()
                attempts += 1
                continue

            try:
                return self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=self._gen_config,
                )
            except errors.APIError as exc:
                last_exc = exc
                if self._is_rate_limit(exc):
                    logger.warning(
                        "Model '%s' rate-limited — switching to next model.", model
                    )
                    self._advance()
                    attempts += 1
                    continue
                if self._is_unavailable(exc):
                    logger.warning(
                        "Model '%s' unavailable — skipping permanently.", model
                    )
                    self._unavailable.add(model)
                    self._advance()
                    attempts += 1
                    continue
                raise

        usable = [m for m in self.models if m not in self._unavailable]
        if not usable:
            raise RuntimeError(
                f"No usable Gemini models in the chain {self.models!r}. "
                f"Last error: {last_exc}"
            )
        raise RateLimitExhausted(
            f"All models in the fallback chain are rate-limited ({usable!r}). "
            f"Last error: {last_exc}"
        )
