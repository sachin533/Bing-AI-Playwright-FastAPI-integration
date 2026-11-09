"""Shared pytest fixtures.

Two clearly separated test groups:

* **Unit tests** (default) - fully mocked. They never touch the network and
  never open a browser. A mocked Bing answer is *never* counted as proof
  that the real Bing integration works.
* **Integration tests** - marked with ``@pytest.mark.integration``. They
  drive a real Chromium browser against the real Bing AI page.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make ``backend/app`` importable without installing the package.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: real browser / real network integration test (slow)"
    )
    config.addinivalue_line("markers", "mocked: unit test using mocks (no network)")

    # The Windows console defaults to cp1252 and cannot encode the emoji /
    # typographic characters that Bing AI answers contain.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture()
def client():
    """FastAPI TestClient for the application (no live browser needed)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def mock_browser_manager(monkeypatch):
    """Patch the browser manager so no real browser is launched."""
    from app.services import browser_manager as bm_module

    class _FakeManager:
        def __init__(self) -> None:
            # Pretend the browser is already up so chat endpoints are reachable.
            # Tests that need a stopped browser replace this explicitly.
            self._running = True
            self._page_open = True
            self._url = "https://www.bing.com/copilotsearch?q=test&FORM=CSSCOP"

        @property
        def is_running(self) -> bool:
            return self._running

        @property
        def is_page_open(self) -> bool:
            return self._page_open

        @property
        def current_url(self):
            return self._url

        @property
        def last_error(self):
            return None

        @property
        def lock(self):
            import asyncio

            return asyncio.Lock()

        async def start(self):
            self._running = True
            self._page_open = True
            return {"started": True, "reused": False, "url": self.current_url}

        async def stop(self):
            self._running = False
            self._page_open = False
            return {"stopped": True, "running": False}

        async def open_bing(self):
            self._page_open = True
            return self.current_url

        async def ensure_page_alive(self):
            if not self._running:
                from app.utils.errors import BrowserNotRunningError

                raise BrowserNotRunningError("Browser is not running.")
            return object()

        def require_page(self):
            if not self._running:
                from app.utils.errors import BrowserNotRunningError

                raise BrowserNotRunningError("Browser is not running.")
            return object()

        def status(self):
            return {
                "running": self._running,
                "page_open": self._page_open,
                "url": self._url,
                "last_error": None,
            }

    fake = _FakeManager()
    monkeypatch.setattr(bm_module, "browser_manager", fake)
    return fake


@pytest.fixture()
def mock_bing_service(monkeypatch, mock_browser_manager):
    """Patch bing_service with a deterministic fake answer.

    The returned payload is clearly labelled ``MOCKED`` so that a passing
    mocked test can never be mistaken for a successful real integration.
    """
    from app.services import bing_service as bs_module

    class _FakeService:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.answer = "MOCKED answer - this is NOT a real Bing AI response."

        async def ask(self, question: str, *, new_conversation: bool = False):
            self.calls.append(question)
            from app.services.bing_service import BingAnswer

            return BingAnswer(
                question=question,
                answer=self.answer,
                url="https://www.bing.com/copilotsearch?q=test&FORM=CSSCOP",
                elapsed_ms=1,
            )

        async def status(self):
            return {
                **mock_browser_manager.status(),
                "login_required": False,
                "composer_found": True,
                "bing_ai_url": "https://www.bing.com/copilotsearch?q=test&FORM=CSSCOP",
            }

        async def open(self):
            return {"url": self.current_url if hasattr(self, "current_url") else None}

    fake = _FakeService()
    monkeypatch.setattr(bs_module, "bing_service", fake)
    # routes.py imported the singleton directly - patch it there too.
    from app.api import routes as routes_module

    monkeypatch.setattr(routes_module, "bing_service", fake)
    monkeypatch.setattr(routes_module, "browser_manager", mock_browser_manager)
    return fake
