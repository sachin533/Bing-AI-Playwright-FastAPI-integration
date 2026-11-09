"""Browser manager unit tests (mocked Playwright - no real browser)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mocked


class _FakePage:
    def __init__(self, url: str = "https://www.bing.com/copilotsearch?q=x") -> None:
        self.url = url
        self._closed = False
        self.goto_calls: list[tuple[str, str | None, int | None]] = []

    def is_closed(self) -> bool:
        return self._closed

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url

    async def title(self) -> str:
        if self._closed:
            raise RuntimeError("page closed")
        return "bing"

    async def wait_for_timeout(self, ms: int) -> None:
        return None


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]
        self.closed = False
        self.default_timeout: int | None = None
        self.default_navigation_timeout: int | None = None

    def set_default_timeout(self, ms: int) -> None:
        self.default_timeout = ms

    def set_default_navigation_timeout(self, ms: int) -> None:
        self.default_navigation_timeout = ms

    async def new_page(self) -> _FakePage:
        return _FakePage()

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, page: _FakePage, *, fail: bool = False) -> None:
        self._page = page
        self._fail = fail
        self.context: _FakeContext | None = None

    async def launch_persistent_context(self, **kwargs):
        if self._fail:
            raise RuntimeError("chromium exploded")
        self.context = _FakeContext(self._page)
        return self.context


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _patch_playwright(monkeypatch, chromium: _FakeChromium) -> None:
    from app.services import browser_manager as bm

    class _Starter:
        def __init__(self) -> None:
            self.pw = _FakePlaywright(chromium)

        async def start(self):
            return self.pw

    monkeypatch.setattr(bm, "async_playwright", lambda: _Starter())


@pytest.mark.asyncio
async def test_start_launches_browser_and_opens_bing(monkeypatch):
    """start() launches Chromium and navigates to the Bing AI URL."""
    from app.services.browser_manager import BrowserManager

    page = _FakePage()
    chromium = _FakeChromium(page)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    result = await manager.start()

    assert result["started"] is True
    assert manager.is_running is True
    assert page.goto_calls, "the Bing AI URL should have been opened"
    assert "bing.com" in page.goto_calls[0][0] or "copilot" in page.goto_calls[0][0]


@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch):
    """Calling start() twice reuses the running browser."""
    from app.services.browser_manager import BrowserManager

    page = _FakePage()
    chromium = _FakeChromium(page)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    await manager.start()
    launches_before = len(page.goto_calls)
    result = await manager.start()

    assert result["reused"] is True
    assert manager.is_running is True
    assert len(page.goto_calls) == launches_before


@pytest.mark.asyncio
async def test_stop_closes_context_and_playwright(monkeypatch):
    """stop() closes the context and stops Playwright."""
    from app.services.browser_manager import BrowserManager

    page = _FakePage()
    chromium = _FakeChromium(page)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    await manager.start()
    await manager.stop()

    assert manager.is_running is False
    assert chromium.context is not None and chromium.context.closed is True


@pytest.mark.asyncio
async def test_start_failure_raises_typed_error(monkeypatch):
    """A Chromium launch failure raises BrowserStartupError."""
    from app.services.browser_manager import BrowserManager
    from app.utils.errors import BrowserStartupError

    chromium = _FakeChromium(_FakePage(), fail=True)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    with pytest.raises(BrowserStartupError):
        await manager.start()
    assert manager.is_running is False
    assert manager.last_error


@pytest.mark.asyncio
async def test_require_page_raises_when_not_running():
    """require_page() raises BrowserNotRunningError when stopped."""
    from app.services.browser_manager import BrowserManager
    from app.utils.errors import BrowserNotRunningError

    manager = BrowserManager()
    with pytest.raises(BrowserNotRunningError):
        manager.require_page()


@pytest.mark.asyncio
async def test_closed_page_is_detected(monkeypatch):
    """A closed page flips is_running to False."""
    from app.services.browser_manager import BrowserManager

    page = _FakePage()
    chromium = _FakeChromium(page)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    await manager.start()
    assert manager.is_running is True
    page._closed = True
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_status_contains_no_secrets(monkeypatch):
    """The status payload never contains cookies or tokens."""
    from app.services.browser_manager import BrowserManager

    page = _FakePage()
    chromium = _FakeChromium(page)
    _patch_playwright(monkeypatch, chromium)

    manager = BrowserManager()
    await manager.start()
    status = manager.status()
    assert set(status) == {"running", "page_open", "url", "last_error"}
    blob = str(status).lower()
    for forbidden in ("cookie", "token", "password", "authorization"):
        assert forbidden not in blob


@pytest.mark.asyncio
async def test_lock_serialises_access(monkeypatch):
    """The manager exposes an asyncio lock to serialise page usage."""
    import asyncio

    from app.services.browser_manager import BrowserManager

    manager = BrowserManager()
    assert isinstance(manager.lock, asyncio.Lock)
