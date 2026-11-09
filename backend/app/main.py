"""FastAPI application entry point for the Bing AI Playwright backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from .api.health import router as health_router
from .api.routes import router as bing_router
from .config import settings
from .services.browser_manager import browser_manager
from .utils.errors import BingAIError
from .utils.logging_config import setup_logging

logger = setup_logging(level=settings.log_level, log_file=settings.log_file)

# Optional shared secret. When API_KEY is empty the check is disabled
# (local development); when it is set, callers must send the header.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    provided: str | None = Security(_api_key_header),
) -> None:
    """Validate the optional API key.

    Disabled when ``API_KEY`` is not configured. The key itself is never
    logged.
    """
    expected = settings.api_key
    if not expected:
        return
    if not provided or provided != expected:
        logger.warning("rejected a request with a missing or invalid API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_api_key",
                "message": "A valid X-API-Key header is required.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start / stop the browser together with the FastAPI process.

    The browser is intentionally *not* auto-started: the operator decides
    when to open the visible browser (which is also when a manual Microsoft
    sign-in can be completed).  A browser that is already running when the
    server starts is re-used.
    """
    logger.info("%s v%s starting", settings.app_name, settings.app_version)
    if browser_manager.is_running:
        logger.info("an existing browser session was detected and will be reused")
    yield
    logger.info("shutting down - closing the browser")
    await browser_manager.stop()
    logger.info("shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "OpenAI-compatible chat API backed by the real Bing AI (Copilot Search) "
        "web interface, automated with Playwright. No Chrome extension is used."
    ),
    lifespan=lifespan,
)

# --- CORS: restricted to the configured frontend origins --------------------
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
else:  # pragma: no cover - configuration dependent
    logger.warning("CORS_ORIGINS is empty - browser origins will be rejected")

app.include_router(health_router)
app.include_router(bing_router, dependencies=[Depends(require_api_key)])


@app.exception_handler(BingAIError)
async def bing_ai_error_handler(request: Request, exc: BingAIError) -> JSONResponse:
    """Map typed integration errors onto clean HTTP responses."""
    logger.warning("%s -> %s: %s", request.url.path, exc.code, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_payload()})


@app.get("/", include_in_schema=False)
async def root() -> dict:
    """Tiny landing payload pointing at the docs."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "browser_status": "/api/browser/status",
        "chat": "/v1/chat/completions",
    }
