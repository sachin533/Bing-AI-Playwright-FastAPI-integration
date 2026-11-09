"""Reusable, persistent Playwright browser manager.

Responsibilities
----------------
* Launch / stop Chromium with a persistent user-data profile that lives
  inside the project (``browser_data/``) so the session survives restarts.
* Keep exactly one browser + one chat page alive and reuse it for every
  question (no per-request browser launch).
* Detect disconnects, navigation errors and startup failures and surface
  them as typed exceptions.
* Serialise access to the single page with an asyncio lock so that two
  concurrent API calls can never fight over the same composer.
* Never expose cookies, tokens or profile contents.

The manager deliberately does **not** attempt to bypass login, CAPTCHA or any
other access control. If Microsoft asks for a sign-in, the user completes it
manually in the visible browser window and the persistent profile keeps it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from ..config import settings
from ..utils.errors import (
    BrowserDisconnectedError,
    BrowserNotRunningError,
    BrowserStartupError,
    NavigationError,
)
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """Owns the Playwright lifecycle and the persistent browser context."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()
        self._started = False
        self._last_error: str | None = None
        self._start_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        """True when a usable browser context and page exist."""
        if not self._started or self._context is None or self._page is None:
            return False
        try:
            if self._page.is_closed():
                return False
        except Exception:
            return False
        return True

    @property
    def is_page_open(self) -> bool:
        """True when the Bing page is loaded on the managed page."""
        if not self.is_running:
            return False
        page = self._page
        assert page is not None
        try:
            return "bing.com" in (page.url or "") or "copilot" in (page.url or "").lower()
        except Exception:
            return False

    @property
    def current_url(self) -> str | None:
        if not self.is_running:
            return None
        try:
            return self._page.url  # type: ignore[union-attr]
        except Exception:
            return None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def lock(self) -> asyncio.Lock:
        """Lock serialising operations against the single shared page."""
        return self._lock

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> dict[str, Any]:
        """Launch Chromium (if needed) and open the Bing AI page.

        Safe to call repeatedly: an already-running browser is reused.
        """
        async with self._start_lock:
            if self.is_running:
                logger.info("browser already running - reusing existing session")
                return {
                    "started": True,
                    "reused": True,
                    "url": self.current_url,
                }

            await self._teardown(quiet=True)
            self._last_error = None

            user_data_dir = settings.browser_user_data_dir
            user_data_dir.mkdir(parents=True, exist_ok=True)

            try:
                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=settings.headless,
                    viewport={
                        "width": settings.browser_viewport_width,
                        "height": settings.browser_viewport_height,
                    },
                    locale=settings.browser_locale,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                self._context.set_default_timeout(settings.action_timeout_ms)
                self._context.set_default_navigation_timeout(settings.navigation_timeout_ms)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                await self._teardown(quiet=True)
                logger.error("browser startup failed: %s", type(exc).__name__)
                raise BrowserStartupError(
                    "Failed to start the Playwright Chromium browser.",
                    detail=str(exc),
                ) from exc

            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._started = True
            logger.info("browser started (persistent profile at %s)", user_data_dir.name)

            try:
                await self.open_bing()
            except Exception as exc:
                # Navigation problems are reported but the browser stays up so
                # the user can inspect / recover manually.
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Bing page did not open automatically: %s", exc)

            return {"started": True, "reused": False, "url": self.current_url}

    async def stop(self) -> dict[str, Any]:
        """Close the browser gracefully."""
        await self._teardown(quiet=False)
        return {"stopped": True, "running": self.is_running}

    async def _teardown(self, *, quiet: bool) -> None:
        """Internal cleanup that never raises."""
        context, playwright = self._context, self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        self._started = False

        if context is not None:
            try:
                await context.close()
                if not quiet:
                    logger.info("browser closed")
            except Exception as exc:
                logger.warning("error while closing browser context: %s", type(exc).__name__)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:
                logger.warning("error while stopping playwright: %s", type(exc).__name__)

    # ------------------------------------------------------------------
    # Page helpers
    # ------------------------------------------------------------------
    def require_page(self) -> Page:
        """Return the managed page or raise a typed error."""
        if not self.is_running:
            raise BrowserNotRunningError(
                "Browser is not running. POST /api/browser/start first."
            )
        page = self._page
        assert page is not None
        if page.is_closed():
            raise BrowserDisconnectedError(
                "The browser page was closed unexpectedly. Restart the browser."
            )
        return page

    async def open_bing(self) -> str:
        """Navigate the managed page to the Bing AI (Copilot Search) URL."""
        page = self.require_page()
        url = settings.bing_ai_url
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.navigation_timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise NavigationError(
                "Timed out while loading the Bing AI page.",
                detail=str(exc),
            ) from exc
        except PlaywrightError as exc:
            raise NavigationError(
                "Could not load the Bing AI page.",
                detail=str(exc),
            ) from exc

        await page.wait_for_timeout(2500)
        logger.info("Bing AI page loaded: %s", page.url)
        return page.url

    async def ensure_page_alive(self) -> Page:
        """Verify the page is still usable; raise if it died."""
        page = self.require_page()
        try:
            await page.title()
        except Exception as exc:
            raise BrowserDisconnectedError(
                "The browser session was lost (page is no longer responsive).",
                detail=str(exc),
            ) from exc
        return page

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """Non-sensitive status snapshot for the API."""
        return {
            "running": self.is_running,
            "page_open": self.is_page_open,
            "url": self.current_url,
            "last_error": self._last_error,
        }


# Module-level singleton used by the FastAPI app.
browser_manager = BrowserManager()
