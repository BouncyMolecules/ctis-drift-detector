"""Logging setup for CLI and Streamlit."""

from __future__ import annotations

import logging
import sys
from typing import Final

_LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_LOG_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S"


def log_unexpected_error(logger: logging.Logger, message: str) -> None:
    """Log a handled failure for operators without emitting tracebacks at INFO/WARNING/ERROR.

    Full stack traces appear only when the effective log level is DEBUG (for example
    ``CTIS_DRIFT_LOG_LEVEL=DEBUG``), matching regulated deployments where stderr/SIEM
    ingestion should not carry verbose internals unless explicitly troubleshooting.
    """

    if logger.isEnabledFor(logging.DEBUG):
        logger.error(message, exc_info=True)
        return
    _exc_type, exc_val, _ = sys.exc_info()
    if exc_val is not None:
        logger.error(
            "%s — %s: %s",
            message,
            type(exc_val).__name__,
            exc_val,
        )
    else:
        logger.error("%s", message)


def setup_logging(level: str) -> None:
    """Configure root logging once (idempotent for repeated Streamlit reruns)."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level.upper())
        return

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_LOG_FORMAT,
        datefmt=_LOG_DATE_FORMAT,
        stream=sys.stderr,
        force=False,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger with a stable naming hierarchy."""
    return logging.getLogger(name)
