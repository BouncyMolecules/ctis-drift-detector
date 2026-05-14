"""Stable import surface for the CTIS public HTTP API.

Implementation lives in :mod:`ctis_drift.core.ctis_public_client` (httpx transport, no UI).
Streamlit response memoisation belongs in :mod:`ctis_drift.ui.utils.caching`.
"""

from __future__ import annotations

from ctis_drift.core.ctis_public_client import (
    CTIS_PUBLIC_API_BASE_URL,
    DEFAULT_BACKOFF_CAP_SECONDS,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MAX_TOTAL_RETRIES,
    DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    CTISAPIClient,
    CTISAPIError,
    CtisHttpResponseError,
    CtisMalformedJsonError,
    CtisPublicApiError,
    CtisPublicClient,
    CtisRateLimitError,
    CtisTimeoutError,
    CtisTransportError,
    SearchPagination,
    SearchResponsePagination,
    SearchSort,
    TrialFullRecord,
    TrialSearchCriteria,
    TrialSearchPayload,
    TrialSearchResponse,
    TrialSearchSummary,
    public_client_singleton,
)

__all__ = [
    "CTISAPIError",
    "CTISAPIClient",
    "CTIS_PUBLIC_API_BASE_URL",
    "CtisHttpResponseError",
    "CtisMalformedJsonError",
    "CtisPublicApiError",
    "CtisPublicClient",
    "CtisRateLimitError",
    "CtisTimeoutError",
    "CtisTransportError",
    "DEFAULT_BACKOFF_CAP_SECONDS",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_MAX_TOTAL_RETRIES",
    "DEFAULT_MIN_REQUEST_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "SearchPagination",
    "SearchResponsePagination",
    "SearchSort",
    "TrialFullRecord",
    "TrialSearchCriteria",
    "TrialSearchPayload",
    "TrialSearchResponse",
    "TrialSearchSummary",
    "get_full_trial",
    "public_client_singleton",
    "search_trials",
]


def search_trials(
    *,
    payload: TrialSearchPayload | None = None,
    use_streamlit_cache: bool = True,
) -> TrialSearchResponse:
    """POST ``/search`` via the process-wide :func:`public_client_singleton`.

    The ``use_streamlit_cache`` flag is retained for backwards compatibility; the core layer
    never applies Streamlit caching. Use :func:`ctis_drift.ui.utils.caching.search_trials_cached`
    inside the Streamlit app when TTL memoisation is desired.
    """

    _ = use_streamlit_cache
    body = payload or TrialSearchPayload()
    return public_client_singleton().search_trials(body)


def get_full_trial(
    euct_number: str,
    *,
    use_streamlit_cache: bool = True,
) -> TrialFullRecord:
    """GET ``/retrieve/{euct}`` via :func:`public_client_singleton`.

    ``use_streamlit_cache`` is ignored at this layer; see
    :func:`ctis_drift.ui.utils.caching.get_full_trial_cached` for Streamlit caching.
    """

    _ = use_streamlit_cache
    sanitized = euct_number.strip().strip("/")
    return public_client_singleton().get_full_trial(sanitized)
