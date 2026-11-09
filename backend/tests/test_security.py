"""Security tests (mocked - no network, no browser)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mocked


def test_api_key_disabled_by_default(client, mock_bing_service, monkeypatch):
    """Without API_KEY configured, no key is required."""
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    response = client.get("/api/browser/status")
    assert response.status_code == 200


def test_api_key_required_when_configured(client, mock_bing_service, monkeypatch):
    """With API_KEY configured, a missing key is rejected with 401."""
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-value")
    response = client.get("/api/browser/status")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_api_key_accepted_when_correct(client, mock_bing_service, monkeypatch):
    """A correct key is accepted."""
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-value")
    response = client.get(
        "/api/browser/status", headers={"X-API-Key": "secret-value"}
    )
    assert response.status_code == 200


def test_health_is_not_protected(client, mock_bing_service, monkeypatch):
    """The health endpoint stays reachable for monitoring."""
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-value")
    assert client.get("/health").status_code == 200


def test_status_never_leaks_browser_secrets(client, mock_bing_service):
    """No cookie / token material is present in the status payload."""
    response = client.get("/api/browser/status")
    body = response.json()
    assert set(body).issubset(
        {
            "running",
            "page_open",
            "url",
            "login_required",
            "composer_found",
            "last_error",
            "bing_ai_url",
        }
    )
    blob = str(body).lower()
    for forbidden in ("cookie", "token", "password", "authorization", "storage_state"):
        assert forbidden not in blob


def test_cors_origins_are_configurable():
    """CORS is driven by the configured origins, not a wildcard."""
    from app.config import settings

    assert settings.cors_origins, "CORS_ORIGINS should have a default"
    assert "*" not in settings.cors_origins


def test_gitignore_ignores_sensitive_paths(project_root):
    """The sensitive paths are ignored by git."""
    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("browser_data/", ".venv/", ".env"):
        assert pattern in gitignore, f"{pattern} must be git-ignored"


def test_env_example_exists_and_has_no_secret(project_root):
    """.env.example documents the settings without shipping a secret."""
    example = (project_root / "backend" / ".env.example").read_text(encoding="utf-8")
    assert "BING_AI_URL" in example
    assert "CORS_ORIGINS" in example
    assert "API_KEY=" in example
    # the example must not carry a real-looking key
    for line in example.splitlines():
        if line.strip().startswith("API_KEY="):
            assert line.strip() in {"API_KEY=", "# API_KEY=change-me"}


def test_no_chrome_extension_artifacts(project_root):
    """No Chrome extension exists in this project."""
    forbidden = ("manifest.json",)
    for name in forbidden:
        hits = list(project_root.rglob(name))
        # browser_data is a Chromium profile and may contain unrelated files
        hits = [h for h in hits if "browser_data" not in h.parts]
        assert not hits, f"unexpected extension artifact: {hits}"
