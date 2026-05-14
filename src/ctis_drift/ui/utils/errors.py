"""User-facing wording for surfaced errors."""

from __future__ import annotations

from ctis_drift.core.ctis_public_client import CtisPublicApiError, CtisTransportError
from ctis_drift.ui import streamlit_env
from ctis_drift.utils.logging import get_logger

logger = get_logger(__name__)


def streamlit_error_log_hint() -> None:
    """Consistent guidance after failures (technical detail stays in logs)."""

    streamlit_env.st.caption(
        "If this keeps happening, note the time and check application logs "
        "(set `CTIS_DRIFT_LOG_LEVEL=DEBUG` for verbose diagnostics). "
        "Stack traces are intentionally omitted from this UI."
    )


def friendly_api_error(exc: CtisPublicApiError) -> str:
    """Return safe UI copy for API failures — never echo raw exception text to the browser."""

    context_url = getattr(exc, "url", "") or ""
    logger.debug(
        "CTIS API failure (full detail for logs only): %s | url=%s",
        exc,
        context_url,
        exc_info=True,
    )
    if isinstance(exc, CtisTransportError):
        return (
            "Could not reach the CTIS public API. This is usually a network, firewall, VPN, "
            "or DNS issue rather than an incorrect trial identifier."
        )
    return (
        "The CTIS public API could not complete this request. Verify the trial identifier, "
        "try again later, or check application logs."
    )
