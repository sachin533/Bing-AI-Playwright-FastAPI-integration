"""Pydantic schemas for the browser control endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BrowserStatusResponse(BaseModel):
    running: bool = Field(..., description="True when the Playwright browser process is alive.")
    page_open: bool = Field(..., description="True when the Bing AI page is loaded.")
    url: str | None = Field(default=None, description="Current page URL (no secrets).")
    login_required: bool | None = Field(
        default=None, description="True/False when detectable, null when unknown."
    )
    composer_found: bool | None = Field(
        default=None, description="True when the question input box is present."
    )
    last_error: str | None = Field(default=None, description="Last error message, if any.")
    bing_ai_url: str | None = None


class BrowserActionResponse(BaseModel):
    started: bool | None = None
    stopped: bool | None = None
    running: bool
    reused: bool | None = None
    url: str | None = None
    login_required: bool | None = None
    composer_found: bool | None = None
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    browser_running: bool
    uptime_seconds: float
    details: dict[str, Any] = Field(default_factory=dict)
