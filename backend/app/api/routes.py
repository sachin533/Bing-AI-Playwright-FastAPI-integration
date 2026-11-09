"""Browser control + OpenAI-compatible chat endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..schemas.browser import BrowserActionResponse, BrowserStatusResponse
from ..schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from ..services.bing_service import bing_service
from ..services.browser_manager import browser_manager
from ..utils.errors import BingAIError, LoginRequiredError
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["bing-ai"])


# ---------------------------------------------------------------------------
# Browser control
# ---------------------------------------------------------------------------
@router.get(
    "/api/browser/status",
    response_model=BrowserStatusResponse,
    summary="Browser and Bing page status",
)
async def browser_status() -> BrowserStatusResponse:
    """Report whether the browser runs, whether the Bing page is open and
    whether a Microsoft sign-in appears to be required.

    No cookies, tokens or profile data are ever returned.
    """
    data = await bing_service.status()
    return BrowserStatusResponse(**data)


@router.post(
    "/api/browser/start",
    response_model=BrowserActionResponse,
    summary="Start the Playwright browser and open Bing AI",
)
async def browser_start() -> BrowserActionResponse:
    """Launch Chromium with the persistent project profile and open Bing AI.

    The window is visible (unless ``HEADLESS=true``) so that a manual
    Microsoft sign-in can be completed by the operator.
    """
    try:
        result = await browser_manager.start()
    except BingAIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc

    status_data = await bing_service.status()
    login_required = status_data.get("login_required")

    message = "Browser started and Bing AI opened."
    if login_required:
        message = (
            "Browser started, but Microsoft sign-in is required. "
            "Complete the sign-in manually in the open browser window, then retry."
        )

    return BrowserActionResponse(
        started=True,
        running=browser_manager.is_running,
        reused=result.get("reused", False),
        url=status_data.get("url"),
        login_required=login_required,
        composer_found=status_data.get("composer_found"),
        message=message,
    )


@router.post(
    "/api/browser/stop",
    response_model=BrowserActionResponse,
    summary="Stop the Playwright browser",
)
async def browser_stop() -> BrowserActionResponse:
    """Close the browser gracefully."""
    try:
        await browser_manager.stop()
    except BingAIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc
    return BrowserActionResponse(
        stopped=True,
        running=browser_manager.is_running,
        message="Browser stopped.",
    )


@router.post(
    "/api/browser/reload",
    response_model=BrowserActionResponse,
    summary="Reload the Bing AI page",
)
async def browser_reload() -> BrowserActionResponse:
    """Re-navigate the managed page to the Bing AI URL."""
    if not browser_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "browser_not_running",
                "message": "Browser is not running. POST /api/browser/start first.",
            },
        )
    try:
        url = await browser_manager.open_bing()
    except BingAIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc
    return BrowserActionResponse(
        running=browser_manager.is_running,
        url=url,
        message="Bing AI page reloaded.",
    )


@router.get(
    "/v1/models",
    summary="List the available models (OpenAI-compatible)",
)
async def list_models() -> dict:
    """Return the single model this backend exposes."""
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": "bing-ai",
                "object": "model",
                "created": now,
                "owned_by": "bing-ai-playwright",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Chat completions (OpenAI-compatible)
# ---------------------------------------------------------------------------
@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    summary="Ask Bing AI (OpenAI-compatible chat completion)",
)
async def chat_completions(payload: ChatCompletionRequest) -> ChatCompletionResponse:
    """Send the latest user message to Bing AI and return the real answer.

    The answer always comes from the live Bing AI page - nothing is
    simulated or hardcoded.
    """
    if payload.stream:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "streaming_not_supported",
                "message": "Streaming responses are not implemented yet. Use \"stream\": false.",
            },
        )

    if not browser_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "browser_not_running",
                "message": "Browser is not running. POST /api/browser/start first.",
            },
        )

    user_messages = [m for m in payload.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_user_message",
                "message": "At least one message with role 'user' is required.",
            },
        )
    question = user_messages[-1].content

    try:
        result = await asyncio.wait_for(
            bing_service.ask(question),
            timeout=settings.api_request_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "request_timeout",
                "message": (
                    f"The request exceeded {settings.api_request_timeout_s}s waiting for Bing AI."
                ),
            },
        ) from exc
    except LoginRequiredError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc
    except BingAIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected error while asking Bing AI")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "internal_error",
                "message": "Unexpected error while talking to Bing AI.",
                "detail": type(exc).__name__,
            },
        ) from exc

    prompt_chars = sum(len(m.content) for m in payload.messages)
    completion_chars = len(result.answer)

    return ChatCompletionResponse(
        model=payload.model or "bing-ai",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=result.answer),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=max(1, prompt_chars // 4),
            completion_tokens=max(1, completion_chars // 4),
            total_tokens=max(2, (prompt_chars + completion_chars) // 4),
        ),
    )


@router.post(
    "/api/ask",
    summary="Ask a question directly (convenience wrapper)",
)
async def ask(payload: ChatCompletionRequest) -> dict:
    """Convenience wrapper around /v1/chat/completions returning raw data."""
    if not browser_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "browser_not_running",
                "message": "Browser is not running. POST /api/browser/start first.",
            },
        )
    user_messages = [m for m in payload.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_user_message",
                "message": "At least one message with role 'user' is required.",
            },
        )
    try:
        result = await asyncio.wait_for(
            bing_service.ask(user_messages[-1].content),
            timeout=settings.api_request_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "request_timeout",
                "message": "Timed out waiting for Bing AI.",
            },
        ) from exc
    except BingAIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc
    return result.to_dict()
