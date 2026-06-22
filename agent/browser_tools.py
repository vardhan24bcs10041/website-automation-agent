"""Coordinate-based browser actions backed by Playwright (sync API).

The viewport is pinned and the device scale factor forced to 1 so the screenshots
handed to the model share the exact pixel space the model clicks into — without
that 1:1 mapping, coordinate-based clicking breaks.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime
from typing import Any, Dict

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

import config
from agent.logger import get_logger

logger = get_logger("browser_tools")

SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "screenshots"
)
NAV_TIMEOUT_MS = 30_000


class ToolError(Exception):
    """Raised when a browser tool fails, so the loop catches one error type."""


class BrowserTools:
    """Owns the Playwright lifecycle and the seven browser actions."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    def open_browser(self) -> None:
        """Launch Chromium at the fixed viewport (honors HEADLESS)."""
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=config.HEADLESS
            )
            self._page = self._browser.new_page(
                viewport={
                    "width": config.VIEWPORT_WIDTH,
                    "height": config.VIEWPORT_HEIGHT,
                },
                device_scale_factor=1,
            )
            self._page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            logger.info(
                "Launched Chromium (headless=%s, viewport=%dx%d)",
                config.HEADLESS,
                config.VIEWPORT_WIDTH,
                config.VIEWPORT_HEIGHT,
            )
        except PlaywrightError as exc:
            logger.exception("Failed to open browser")
            raise ToolError(f"Could not open browser: {exc}") from exc

    def close(self) -> None:
        """Tear down page, browser, and driver. Safe to call repeatedly."""
        for name, closer in (
            ("browser", lambda: self._browser and self._browser.close()),
            ("playwright", lambda: self._playwright and self._playwright.stop()),
        ):
            try:
                closer()
            except Exception:
                logger.warning("Error while closing %s", name, exc_info=True)
        self._page = None
        self._browser = None
        self._playwright = None
        logger.info("Browser closed")

    def _require_page(self):
        if self._page is None:
            raise ToolError("Browser is not open. Call open_browser() first.")
        return self._page

    def navigate_to_url(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL and return the final URL and title."""
        page = self._require_page()
        try:
            logger.info("Navigating to %s", url)
            page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
            info = {"url": page.url, "title": page.title()}
            logger.info("Loaded %s (%s)", info["url"], info["title"])
            return info
        except PlaywrightTimeoutError as exc:
            logger.error("Navigation timed out for %s", url)
            raise ToolError(f"Navigation to {url} timed out") from exc
        except PlaywrightError as exc:
            logger.exception("Navigation failed for %s", url)
            raise ToolError(f"Navigation to {url} failed: {exc}") from exc

    def take_screenshot(self) -> Dict[str, Any]:
        """Capture the viewport; return its saved path and base64 PNG."""
        page = self._require_page()
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(SCREENSHOT_DIR, f"screenshot_{stamp}.png")
            image_bytes = page.screenshot(path=path)
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            logger.info("Captured screenshot -> %s", path)
            return {"path": path, "base64": encoded}
        except PlaywrightError as exc:
            logger.exception("Screenshot failed")
            raise ToolError(f"Could not take screenshot: {exc}") from exc

    def click_on_screen(self, x: int, y: int) -> Dict[str, Any]:
        """Click at viewport pixel coordinates (top-left origin)."""
        page = self._require_page()
        try:
            logger.info("Click at (%d, %d)", x, y)
            page.mouse.move(x, y)
            page.mouse.click(x, y)
            return {"x": x, "y": y}
        except PlaywrightError as exc:
            logger.exception("Click failed at (%d, %d)", x, y)
            raise ToolError(f"Could not click at ({x}, {y}): {exc}") from exc

    def send_keys(self, text: str) -> Dict[str, Any]:
        """Type text into the currently focused element."""
        page = self._require_page()
        try:
            logger.info("Typing %d characters", len(text))
            page.keyboard.type(text)
            return {"text": text}
        except PlaywrightError as exc:
            logger.exception("send_keys failed")
            raise ToolError(f"Could not type text: {exc}") from exc

    def scroll(self, direction: str = "down", amount: int = 400) -> Dict[str, Any]:
        """Scroll the page up or down by a pixel amount."""
        page = self._require_page()
        if direction not in ("up", "down"):
            raise ToolError(f"Invalid scroll direction: {direction!r}")
        try:
            delta = amount if direction == "down" else -amount
            logger.info("Scroll %s by %d px", direction, amount)
            page.mouse.wheel(0, delta)
            return {"direction": direction, "amount": amount}
        except PlaywrightError as exc:
            logger.exception("Scroll failed")
            raise ToolError(f"Could not scroll: {exc}") from exc

    def double_click(self, x: int, y: int) -> Dict[str, Any]:
        """Double-click at viewport pixel coordinates."""
        page = self._require_page()
        try:
            logger.info("Double-click at (%d, %d)", x, y)
            page.mouse.move(x, y)
            page.mouse.dblclick(x, y)
            return {"x": x, "y": y}
        except PlaywrightError as exc:
            logger.exception("Double-click failed at (%d, %d)", x, y)
            raise ToolError(f"Could not double-click at ({x}, {y}): {exc}") from exc
