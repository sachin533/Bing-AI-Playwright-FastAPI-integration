"""Error handling tests for the Bing service and the HTTP layer (mocked)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mocked


class _FakeLocator:
    def __init__(self, text: str = "") -> None:
        self._text = text

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return True

    async def inner_text(self) -> str:
        return self._text

    async def click(self, timeout=None) -> None:
        return None

    async def press_sequentially(self, text, delay=None) -> None:
        return None

    async def press(self, key) -> None:
        return None


class _FakePage:
    def __init__(self, url: str = "https://www.bing.com/copilotsearch?q=x", text: str = "") -> None:
        self.url = url
        self._text = text
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed

    async def title(self) -> str:
        return "bing"

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def evaluate(self, script: str, *args):
        if "innerText" in script:
            return self._text
        if "document.body" in script:
            return self._text
        return True

    def locator(self, selector: str):
        return _FakeLocator(self._text)

    async def goto(self, url, wait_until=None, timeout=None):
        self.url = url


@pytest.mark.asyncio
async def test_login_detected_from_url(monkeypatch):
    """A Microsoft login URL is reported as login required."""
    from app.services.bing_service import BingService

    service = BingService()
    page = _FakePage(url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize")
    assert await service.detect_login_required(page) is True


@pytest.mark.asyncio
async def test_login_detected_from_page_text(monkeypatch):
    """A 'Sign in to your account' page without a composer is login required."""
    from app.services.bing_service import BingService

    service = BingService()
    page = _FakePage(url="https://www.bing.com/copilotsearch", text="Sign in to your account")
    # Force the composer lookup to fail so the text marker is decisive.
    monkeypatch.setattr(service, "_find_input", lambda *a, **k: _async_none())
    assert await service.detect_login_required(page) is True


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_no_login_on_normal_page(monkeypatch):
    """A normal Bing AI page is not flagged as login required."""
    from app.services.bing_service import BingService

    service = BingService()
    page = _FakePage(url="https://www.bing.com/copilotsearch?q=hi", text="some results")
    monkeypatch.setattr(service, "_find_input", lambda *a, **k: _async_locator())
    assert await service.detect_login_required(page) is False


async def _async_locator():
    return _FakeLocator("Ask anything")


@pytest.mark.asyncio
async def test_empty_question_is_rejected():
    """An empty question raises EmptyResponseError."""
    from app.services.bing_service import BingService
    from app.utils.errors import EmptyResponseError

    service = BingService()
    with pytest.raises(EmptyResponseError):
        await service.ask("   ")


@pytest.mark.asyncio
async def test_answer_cleaning_removes_excess_blank_lines():
    """Whitespace normalisation keeps the answer readable."""
    from app.services.bing_service import BingService

    service = BingService()
    raw = "line one\n\n\n\nline two   \n"
    assert service._clean_text(raw) == "line one\n\nline two"


@pytest.mark.asyncio
async def test_answer_cleaning_removes_citation_leftovers():
    """Citation artefacts such as '3 Sources' and bare numbers are removed."""
    from app.services.bing_service import BingService

    service = BingService()
    raw = "The answer.\n3 Sources\n\n2\n\nMore text."
    cleaned = service._clean_text(raw)
    assert "3 Sources" not in cleaned
    assert "\n2\n" not in cleaned
    assert "The answer." in cleaned
    assert "More text." in cleaned


@pytest.mark.asyncio
async def test_answer_cleaning_fixes_space_before_punctuation():
    """A removed citation chip leaves 'word .' behind - it must be repaired."""
    from app.services.bing_service import BingService

    service = BingService()
    assert service._clean_text("Maldivian goods .") == "Maldivian goods."
    assert service._clean_text("a sentence , and more") == "a sentence, and more"


@pytest.mark.asyncio
async def test_answer_cleaning_keeps_content_bullet_lists():
    """Bullet lines must survive the cleaning."""
    from app.services.bing_service import BingService

    service = BingService()
    raw = "Key features:\nObject-Oriented\nPlatform-Independent\nRobust and Secure"
    assert service._clean_text(raw) == raw


def test_turn_index_parsing():
    """Bing's turnindex parameter is parsed out of the answer iframe URL."""
    from app.services.bing_service import _conversation_id, _turn_index

    url = (
        "https://www.bing.com/search?q=hi&cpltsrchif=1"
        "&convid=abc-123&convsig=xyz&iframeid=cplt_frame_2&turnindex=2"
    )
    assert _turn_index(url) == 2
    assert _conversation_id(url) == "abc-123"
    assert _turn_index("https://www.bing.com/search?q=hi") == 0
    assert _conversation_id("https://www.bing.com/search?q=hi") is None


def test_generating_and_citation_selectors_are_configurable():
    """The selector lists are read from the environment."""
    from app.services import bing_service as module

    assert module.ANSWER_SELECTORS
    assert module.GENERATING_SELECTORS
    assert module.CITATION_SELECTORS
    # The content bullet lists must NOT be filtered away.
    assert "ul.gs_cit_stry_pre" not in module.CITATION_SELECTORS
    # The citation chip wrapper must be filtered.
    assert ".gs_sup_cit" in module.CITATION_SELECTORS


def test_error_payload_shape():
    """Typed errors expose a code/message payload for the HTTP layer."""
    from app.utils.errors import BrowserNotRunningError, ResponseTimeoutError

    err = BrowserNotRunningError("browser is down", detail="not started")
    payload = err.to_payload()
    assert payload["code"] == "browser_not_running"
    assert payload["message"] == "browser is down"
    assert payload["detail"] == "not started"
    assert err.status_code == 503
    assert ResponseTimeoutError("x").status_code == 504


def test_login_required_error_status():
    """LoginRequiredError maps to HTTP 401."""
    from app.utils.errors import LoginRequiredError

    assert LoginRequiredError("sign in").status_code == 401


@pytest.mark.asyncio
async def test_browser_status_endpoint_shape(client, mock_bing_service):
    """GET /api/browser/status returns the documented fields."""
    response = client.get("/api/browser/status")
    assert response.status_code == 200
    body = response.json()
    for field in ("running", "page_open", "url", "login_required", "composer_found", "last_error"):
        assert field in body
    blob = str(body).lower()
    for forbidden in ("cookie", "access_token", "password"):
        assert forbidden not in blob


@pytest.mark.asyncio
async def test_browser_start_and_stop_endpoints(client, mock_bing_service):
    """The start/stop endpoints drive the browser manager."""
    start = client.post("/api/browser/start")
    assert start.status_code == 200
    assert start.json()["running"] is True

    stop = client.post("/api/browser/stop")
    assert stop.status_code == 200
    assert stop.json()["running"] is False
