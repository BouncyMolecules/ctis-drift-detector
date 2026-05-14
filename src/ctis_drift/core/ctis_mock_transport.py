"""Offline/mock CTIS-shaped HTTP replies for demos and CI (no outbound EU portal traffic).

Wired via :class:`~ctis_drift.core.ctis_api.CTISAPIClient` when
``Settings.enable_mock_api`` is true: an :class:`httpx.MockTransport` supplies JSON
that validates against the same Pydantic envelopes as the live public API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ctis_drift.utils.logging import get_logger

logger = get_logger(__name__)


def _parse_json_object(content: bytes) -> dict[str, Any]:
    if not content:
        return {}
    try:
        parsed = json.loads(content.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mock_search_envelope(request: httpx.Request) -> dict[str, Any]:
    """Return a minimal ``POST /search`` body compatible with :class:`TrialSearchResponse`."""

    payload = _parse_json_object(request.content or b"")
    pagination_raw = payload.get("pagination")
    pagination: dict[str, Any] = pagination_raw if isinstance(pagination_raw, dict) else {}
    page_raw = pagination.get("page", 1)
    size_raw = pagination.get("size", 5)
    try:
        page = max(1, int(page_raw))
    except (TypeError, ValueError):
        page = 1
    try:
        size = max(1, min(500, int(size_raw)))
    except (TypeError, ValueError):
        size = 5

    row = {
        "ctNumber": "2024-518143-38-00",
        "ctStatus": 12,
        "ctTitle": "Mock CTIS trial — offline demo payload (not EU production data)",
        "shortTitle": "Mock demo",
        "decisionDate": "2025-01-15",
        "sponsor": "Example Sponsor SA (mock)",
        "trialPhase": "Phase II (illustrative)",
    }
    # Mirror page size up to three duplicate summaries so pagination UI visibly responds.
    data = [dict(row)] * min(size, 3)

    total_records = len(data)
    return {
        "showWarning": False,
        "pagination": {
            "totalRecords": total_records,
            "currentPage": page,
            "totalPages": max(1, (total_records + size - 1) // size),
            "nextPage": False,
            "prevPage": page > 1,
        },
        "data": data,
    }


def _mock_retrieve_envelope(*, url: httpx.URL) -> dict[str, Any]:
    """Return a minimal ``GET /retrieve/{euct}`` body compatible with :class:`TrialFullRecord`."""

    path = url.path.rstrip("/")
    if "/retrieve/" not in path:
        euct = "UNKNOWN-EUCT"
    else:
        euct = path.rsplit("/retrieve/", maxsplit=1)[-1].split("/", maxsplit=1)[0]

    return {
        "ctNumber": euct or "UNKNOWN-EUCT",
        "ctStatus": "MOCK_AUTHORISED — synthetic record for demos only",
        "decisionDate": "2025-01-15",
        "publishDate": "2025-01-16",
        "startDateEU": "2024-06-01",
        "ctPublicStatusCode": 1,
        "authorizedApplication": {
            "applicationId": "MOCK-AA-001",
            "memberStatesConcerned": ["DE", "FR", "NL"],
        },
    }


def _dispatch_mock_request(request: httpx.Request) -> httpx.Response:
    method = request.method.upper()
    path = request.url.path

    if method == "POST" and path.rstrip("/").endswith("/search"):
        return httpx.Response(200, json=_mock_search_envelope(request))

    if method == "GET" and "/retrieve/" in path:
        return httpx.Response(200, json=_mock_retrieve_envelope(url=request.url))

    logger.warning(
        "Mock CTIS handler: no canned response for %s %s (expected /search POST or /retrieve GET).",
        method,
        request.url,
    )
    return httpx.Response(
        404,
        json={"detail": "Mock CTIS transport: endpoint not implemented"},
    )


def create_mock_ctis_http_client(*, timeout_seconds: float) -> httpx.Client:
    """Build a dedicated httpx client that routes all traffic through synthetic CTIS echoes."""

    return httpx.Client(
        transport=httpx.MockTransport(_dispatch_mock_request),
        timeout=httpx.Timeout(timeout_seconds),
        headers={
            "accept": "application/json",
            "user-agent": "ctis-drift-detector/mock-transport (+https://github.com/)",
        },
    )
