"""Logging setup for CLI and Streamlit."""

from __future__ import annotations

import logging
import sys
from typing import Final

_LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_LOG_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S"


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
