"""Application configuration.

All settings are read from environment variables (optionally via a .env file)
so that no secret ever needs to live in source control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/app/config.py -> backend/app -> backend -> <project root>
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BACKEND_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    """Runtime settings for the Bing AI Playwright backend.

    Not frozen so that tests can override individual values.
    """

    # --- App ---------------------------------------------------------------
    app_name: str = "Bing AI Playwright Backend"
    app_version: str = "1.0.0"
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))

    # --- Security ----------------------------------------------------------
    # Comma separated list of allowed browser origins. Empty = same-origin only.
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("CORS_ORIGINS", ["http://localhost:3000", "http://localhost:5173"])
    )
    # Optional shared secret required in the X-API-Key header. Empty = disabled.
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))

    # --- Bing / Playwright -------------------------------------------------
    bing_ai_url: str = field(
        default_factory=lambda: os.getenv(
            "BING_AI_URL", "https://www.bing.com/copilotsearch?q=what+is+java&FORM=CSSCOP"
        )
    )
    browser_user_data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("BROWSER_USER_DATA_DIR", str(PROJECT_ROOT / "browser_data"))
        ).resolve()
    )
    headless: bool = field(default_factory=lambda: _env_bool("HEADLESS", False))
    browser_viewport_width: int = field(default_factory=lambda: _env_int("BROWSER_VIEWPORT_WIDTH", 1440))
    browser_viewport_height: int = field(default_factory=lambda: _env_int("BROWSER_VIEWPORT_HEIGHT", 900))
    browser_locale: str = field(default_factory=lambda: os.getenv("BROWSER_LOCALE", "en-US"))

    # --- Timeouts (milliseconds / seconds) ---------------------------------
    navigation_timeout_ms: int = field(default_factory=lambda: _env_int("NAVIGATION_TIMEOUT_MS", 60_000))
    action_timeout_ms: int = field(default_factory=lambda: _env_int("ACTION_TIMEOUT_MS", 30_000))
    answer_timeout_ms: int = field(default_factory=lambda: _env_int("ANSWER_TIMEOUT_MS", 120_000))
    # How long to wait for the streamed answer text to stop changing.
    stream_settle_ms: int = field(default_factory=lambda: _env_int("STREAM_SETTLE_MS", 3_000))
    api_request_timeout_s: int = field(default_factory=lambda: _env_int("API_REQUEST_TIMEOUT_S", 180))

    # --- Logging -----------------------------------------------------------
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_file: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["LOG_FILE"]).resolve() if os.getenv("LOG_FILE") else None
        )
    )

    @property
    def browser_timeout_ms(self) -> int:
        """Timeout used for Playwright operations."""
        return self.action_timeout_ms


settings = Settings()
