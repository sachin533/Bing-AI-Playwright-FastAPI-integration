"""Health / readiness endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter

from ..config import settings
from ..schemas.browser import HealthResponse
from ..services.browser_manager import browser_manager

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/health", response_model=HealthResponse, summary="Backend health status")
async def health() -> HealthResponse:
    """Return the backend health status.

    The backend is considered healthy when the FastAPI process is serving
    requests; the browser is reported separately because it is started and
    stopped explicitly by the operator.
    """
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        browser_running=browser_manager.is_running,
        uptime_seconds=round(time.time() - _STARTED_AT, 3),
        details={
            "bing_ai_url": settings.bing_ai_url,
            "headless": settings.headless,
        },
    )


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness status")
async def readiness() -> HealthResponse:
    """Readiness: healthy when the browser is up and the Bing page is loaded."""
    running = browser_manager.is_running
    page_open = browser_manager.is_page_open
    return HealthResponse(
        status="ready" if (running and page_open) else "not-ready",
        app=settings.app_name,
        version=settings.app_version,
        browser_running=running,
        uptime_seconds=round(time.time() - _STARTED_AT, 3),
        details={"page_open": page_open},
    )
