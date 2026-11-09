"""Chat API tests.

The happy-path test uses a **mocked** Bing service. The mocked answer is
explicitly labelled and MUST NOT be treated as evidence that the real Bing
integration works - see tests/integration/test_bing_integration.py for the
real-browser coverage.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mocked


def test_chat_completion_returns_openai_shape(client, mock_bing_service):
    """POST /v1/chat/completions returns an OpenAI-compatible envelope."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "bing-ai",
            "messages": [{"role": "user", "content": "What is Java?"}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["object"] == "chat.completion"
    assert body["model"] == "bing-ai"
    assert body["id"].startswith("chatcmpl-bing-")
    assert isinstance(body["created"], int)

    assert len(body["choices"]) == 1
    choice = body["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"
    assert isinstance(choice["message"]["content"], str)
    assert choice["message"]["content"]

    assert "usage" in body
    assert body["usage"]["total_tokens"] > 0


def test_chat_completion_uses_latest_user_message(client, mock_bing_service):
    """The last user message is the one sent to Bing AI."""
    client.post(
        "/v1/chat/completions",
        json={
            "model": "bing-ai",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "an answer"},
                {"role": "user", "content": "second question"},
            ],
        },
    )
    assert mock_bing_service.calls == ["second question"]


def test_chat_requires_user_message(client, mock_bing_service):
    """A request without any user message is rejected with 422."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "bing-ai", "messages": [{"role": "system", "content": "hi"}]},
    )
    assert response.status_code == 422


def test_chat_rejects_empty_message_list(client, mock_bing_service):
    """An empty messages array is rejected with 422."""
    response = client.post(
        "/v1/chat/completions", json={"model": "bing-ai", "messages": []}
    )
    assert response.status_code == 422


def test_chat_rejects_blank_content(client, mock_bing_service):
    """Blank message content is rejected with 422."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "bing-ai", "messages": [{"role": "user", "content": "   "}]},
    )
    assert response.status_code == 422


def test_streaming_is_reported_as_not_implemented(client, mock_bing_service):
    """Streaming is explicitly refused instead of silently degrading."""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "bing-ai",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "streaming_not_supported"


def test_chat_without_browser_returns_503(client, monkeypatch):
    """When the browser is stopped the API returns a clear 503."""
    from app.api import routes as routes_module

    class _Stopped:
        is_running = False

    monkeypatch.setattr(routes_module, "browser_manager", _Stopped())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "bing-ai", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "browser_not_running"


def test_ask_wrapper_returns_answer(client, mock_bing_service):
    """POST /api/ask returns the raw answer payload."""
    response = client.post(
        "/api/ask",
        json={"model": "bing-ai", "messages": [{"role": "user", "content": "What is Java?"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "What is Java?"
    assert body["answer"].startswith("MOCKED")
