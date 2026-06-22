"""Configuration loaded from environment variables (via .env).

Fails fast if GEMINI_API_KEY is missing. MODEL_FALLBACK_CHAIN is the ordered
list of Gemini models the agent rotates through when one is rate-limited.
"""

import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Copy .env.example to .env and add your "
        "Google AI Studio API key, or export GEMINI_API_KEY in your environment."
    )

# Tried in order; the client rotates to the next on a 429 (rate-limited) or 404
# (unavailable). All must support vision + function calling. Each has its own
# quota, so listing several extends total capacity. Override with GEMINI_MODELS.
MODEL_FALLBACK_CHAIN: List[str] = _get_list(
    "GEMINI_MODELS",
    [
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash-lite",
        "gemini-3.1-flash-lite",
    ],
)

TARGET_URL = os.getenv(
    "TARGET_URL", "https://ui.shadcn.com/docs/forms/react-hook-form"
)
HEADLESS = _get_bool("HEADLESS", False)
MAX_STEPS = _get_int("MAX_STEPS", 25)
VIEWPORT_WIDTH = _get_int("VIEWPORT_WIDTH", 1280)
VIEWPORT_HEIGHT = _get_int("VIEWPORT_HEIGHT", 800)
