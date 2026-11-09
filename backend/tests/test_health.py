"""Backend health tests (mocked - no browser, no network)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mocked


def test_health_returns_ok(client):
    """GET /health reports the backend as healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"]
    assert body["version"]
    assert isinstance(body["browser_running"], bool)
    assert body["uptime_seconds"] >= 0


def test_health_lists_bing_url(client):
    """The health payload exposes which Bing URL is configured."""
    body = client.get("/health").json()
    assert "bing_ai_url" in body["details"]
    assert body["details"]["bing_ai_url"].startswith("http")


def test_readiness_endpoint(client):
    """GET /health/ready exists and reports a status string."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ready", "not-ready"}


def test_root_points_at_docs(client):
    """The root endpoint advertises the Swagger docs."""
    body = client.get("/").json()
    assert body["docs"] == "/docs"
    assert body["chat"] == "/v1/chat/completions"


def test_openapi_schema_is_served(client):
    """Swagger / OpenAPI schema is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/v1/chat/completions" in schema["paths"]
    assert "/api/browser/status" in schema["paths"]
    assert "/health" in schema["paths"]
