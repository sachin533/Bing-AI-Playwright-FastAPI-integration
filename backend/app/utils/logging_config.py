"""Logging configuration.

Never logs cookies, tokens, storage state or browser profile contents.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False

# Patterns that must never reach the log files.
_REDACT_PATTERNS = (
    "cookie",
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "session_id",
    "wry cookie",
    "storage_state",
    "password",
)


class _RedactingFilter(logging.Filter):
    """Best-effort scrubber for well-known secret-bearing keywords."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        lowered = message.lower()
        if any(pattern in lowered for pattern in _REDACT_PATTERNS):
            record.msg = "[redacted: sensitive browser data]"
            record.args = ()
        return True


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """Configure root logging once and return the application logger."""
    global _CONFIGURED

    root = logging.getLogger()
    if not _CONFIGURED:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        stream_handler.addFilter(_RedactingFilter())
        root.addHandler(stream_handler)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(fmt)
            file_handler.addFilter(_RedactingFilter())
            root.addHandler(file_handler)

        _CONFIGURED = True

    logger = logging.getLogger("bing_ai")
    logger.addFilter(_RedactingFilter())
    return logger


def get_logger(name: str = "bing_ai") -> logging.Logger:
    return logging.getLogger(name)
