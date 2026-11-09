"""REAL browser integration tests.

These tests drive an actual Chromium instance against the actual Bing AI web
interface. They are skipped unless ``RUN_INTEGRATION_TESTS=1`` is set, so a
normal ``pytest`` run never depends on the network.

Run them with::

    set RUN_INTEGRATION_TESTS=1
    py -m pytest backend/tests/integration -v -s

A passing mocked unit test proves nothing about the real integration - only
these tests do.
"""

from __future__ import annotations

import os
import time

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="Set RUN_INTEGRATION_TESTS=1 to run real-browser integration tests.",
    ),
]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def live_service():
    """Start a real browser + Bing service for the module.

    The fixture is async and shares the session event loop with the tests
    (see pytest.ini) - Playwright objects are bound to the loop that
    created them.
    """
    from app.services.bing_service import BingService
    from app.services.browser_manager import BrowserManager

    manager = BrowserManager()
    yield BingService(manager), manager
    await manager.stop()


@pytest.mark.asyncio
async def test_browser_starts_and_opens_bing(live_service):
    """A real Chromium starts and lands on the Bing AI page."""
    service, manager = live_service
    result = await manager.start()
    assert result["started"] is True
    assert manager.is_running is True
    assert manager.current_url and "bing.com" in manager.current_url


@pytest.mark.asyncio
async def test_bing_page_contains_the_composer(live_service):
    """The real page exposes the question input field."""
    service, manager = live_service
    if not manager.is_running:
        await manager.start()
    page = manager.require_page()
    composer = await service._find_input(page)
    assert composer is not None, "the Bing AI composer input was not found"


@pytest.mark.asyncio
async def test_login_required_detection_does_not_false_positive(live_service):
    """On the normal AI MODE page no sign-in is required."""
    service, manager = live_service
    if not manager.is_running:
        await manager.start()
    page = manager.require_page()
    assert await service.detect_login_required(page) is False


@pytest.mark.asyncio
async def test_real_question_returns_real_answer(live_service):
    """The end-to-end proof: a real question produces a real Bing AI answer."""
    service, manager = live_service
    if not manager.is_running:
        await manager.start()

    question = "What is Java programming?"
    started = time.time()
    result = await service.ask(question)

    assert result.question == question
    assert isinstance(result.answer, str)
    assert len(result.answer) > 50, "the extracted answer looks too short to be real"
    assert "MOCK" not in result.answer.upper(), "a mocked answer must never appear here"

    # The answer should be topical - an error message would not contain these.
    lowered = result.answer.lower()
    assert any(
        word in lowered for word in ("java", "programming", "class", "jvm", "bytecode")
    ), f"answer does not look like a real response about Java: {result.answer[:200]!r}"

    # Headings and lists must survive the extraction.
    assert result.answer.count("\n") >= 3, "the answer lost its structure"

    print("\n=== REAL BING AI ANSWER ===")
    print(result.answer)
    print("=== elapsed:", round(time.time() - started, 1), "s ===")


@pytest.mark.asyncio
async def test_second_question_in_same_conversation(live_service):
    """A follow-up question in the same session also returns an answer."""
    service, manager = live_service
    if not manager.is_running:
        await manager.start()

    result = await service.ask("Give me one sentence about Java.")
    assert len(result.answer) > 10
    assert "MOCK" not in result.answer.upper()


@pytest.mark.asyncio
async def test_conversation_turns_accumulate(live_service):
    """Asking twice creates two conversation turns on the page."""
    service, manager = live_service
    if not manager.is_running:
        await manager.start()
    page = manager.require_page()

    before = await service._count_turns(page)
    await service.ask("Name one popular programming language.")
    after = await service._count_turns(page)
    assert after > before, "the second question did not create a new conversation turn"


@pytest.mark.asyncio
async def test_stop_closes_browser(live_service):
    """Stopping the manager closes the real browser."""
    service, manager = live_service
    await manager.stop()
    assert manager.is_running is False
