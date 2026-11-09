"""Conversation handling and concurrency tests (mocked - no browser)."""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.mocked


def test_models_endpoint_lists_bing_ai(client, mock_bing_service):
    """GET /v1/models returns the OpenAI-compatible model list."""
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    ids = [m["id"] for m in body["data"]]
    assert "bing-ai" in ids


def test_ask_passes_the_question_to_the_service(client, mock_bing_service):
    """The raw wrapper forwards the latest user message."""
    client.post(
        "/api/ask",
        json={
            "model": "bing-ai",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "second"},
            ],
        },
    )
    assert mock_bing_service.calls == ["second"]


@pytest.mark.asyncio
async def test_service_serialises_concurrent_questions(monkeypatch):
    """Two concurrent questions must not fight over the same composer.

    The browser manager exposes an asyncio lock; the service has to hold it
    for the whole submit/extract cycle so the second request waits.
    """
    from app.services.bing_service import BingService

    active = 0
    max_active = 0

    class _FakeManager:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()

    class _FakeService(BingService):
        def __init__(self) -> None:
            super().__init__(manager=_FakeManager())
            self.questions: list[str] = []

        async def _ask_locked(self, question: str, *, new_conversation: bool):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            self.questions.append(question)
            from app.services.bing_service import BingAnswer

            return BingAnswer(question=question, answer="ok")

    service = _FakeService()
    await asyncio.gather(service.ask("one"), service.ask("two"))

    assert max_active == 1, "the service must serialise access to the page"
    assert sorted(service.questions) == ["one", "two"]


@pytest.mark.asyncio
async def test_new_conversation_flag_is_forwarded(monkeypatch):
    """``new_conversation=True`` reaches the internal implementation."""
    from app.services.bing_service import BingService

    seen: list[bool] = []

    class _FakeManager:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()

    class _FakeService(BingService):
        def __init__(self) -> None:
            super().__init__(manager=_FakeManager())

        async def _ask_locked(self, question: str, *, new_conversation: bool):
            seen.append(new_conversation)
            from app.services.bing_service import BingAnswer

            return BingAnswer(question=question, answer="ok")

    service = _FakeService()
    await service.ask("hello", new_conversation=True)
    assert seen == [True]


@pytest.mark.asyncio
async def test_ask_rejects_blank_question():
    """A blank question never reaches the browser."""
    from app.services.bing_service import BingService
    from app.utils.errors import EmptyResponseError

    service = BingService()
    with pytest.raises(EmptyResponseError):
        await service.ask("   ")


def test_bing_answer_serialises():
    """BingAnswer.to_dict() exposes the fields the API returns."""
    from app.services.bing_service import BingAnswer

    answer = BingAnswer(
        question="q",
        answer="a",
        url="https://www.bing.com/copilotsearch?q=q",
        elapsed_ms=12,
        conversation_id="conv-1",
    )
    data = answer.to_dict()
    assert data["question"] == "q"
    assert data["answer"] == "a"
    assert data["conversation_id"] == "conv-1"
    assert data["elapsed_ms"] == 12
