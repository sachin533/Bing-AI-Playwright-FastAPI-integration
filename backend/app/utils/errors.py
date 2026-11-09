"""Application-wide exceptions mapped to HTTP responses."""

from __future__ import annotations


class BingAIError(Exception):
    """Base class for all errors raised by the Bing AI integration."""

    status_code = 500
    code = "bing_ai_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_payload(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class BrowserNotRunningError(BingAIError):
    status_code = 503
    code = "browser_not_running"


class BrowserStartupError(BingAIError):
    status_code = 500
    code = "browser_startup_failed"


class BrowserDisconnectedError(BingAIError):
    status_code = 503
    code = "browser_disconnected"


class NavigationError(BingAIError):
    status_code = 502
    code = "navigation_failed"


class SiteUnavailableError(BingAIError):
    status_code = 502
    code = "site_unavailable"


class LoginRequiredError(BingAIError):
    status_code = 401
    code = "login_required"


class SessionExpiredError(BingAIError):
    status_code = 401
    code = "session_expired"


class InputNotFoundError(BingAIError):
    status_code = 502
    code = "input_not_found"


class SubmitNotFoundError(BingAIError):
    status_code = 502
    code = "submit_not_found"


class ResponseTimeoutError(BingAIError):
    status_code = 504
    code = "response_timeout"


class EmptyResponseError(BingAIError):
    status_code = 502
    code = "empty_response"


class UnexpectedLayoutError(BingAIError):
    status_code = 502
    code = "unexpected_layout"


class ConcurrentRequestError(BingAIError):
    status_code = 429
    code = "concurrent_request"
