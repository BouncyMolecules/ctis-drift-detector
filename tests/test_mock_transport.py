"""Regression tests for offline CTIS mock transport (portfolio / air-gapped demos)."""

from __future__ import annotations

from ctis_drift.config import Settings
from ctis_drift.core.ctis_api import CTISAPIClient, SearchPagination, TrialSearchPayload
from ctis_drift.core.ctis_mock_transport import create_mock_ctis_http_client
from ctis_drift.main import build_ctis_api_client


def test_mock_ctis_client_search_and_retrieve_validate() -> None:
    """Synthetic JSON must satisfy the same Pydantic models as production traffic."""

    http = create_mock_ctis_http_client(timeout_seconds=10.0)
    try:
        with CTISAPIClient(
            "https://euclinicaltrials.eu/ctis-public-api",
            timeout_seconds=10.0,
            http_client=http,
        ) as client:
            resp = client.search_trials(
                TrialSearchPayload(pagination=SearchPagination(page=1, size=2)),
            )
            assert resp.data
            euct = resp.data[0].ct_number
            rec = client.get_full_trial(euct)
            assert rec.ct_number == euct
    finally:
        http.close()


def test_build_ctis_api_client_respects_mock_setting() -> None:
    """Mock env flag uses the same Pydantic envelopes as production CTIS traffic."""

    settings = Settings(
        enable_mock_api=True,
        api_base_url="https://euclinicaltrials.eu/ctis-public-api",
        api_timeout_seconds=5.0,
    )
    client = build_ctis_api_client(settings)
    try:
        assert client.health(page_size=1).get("status") == "ok"
        rec = client.get_full_trial("2024-518143-38-00")
        assert rec.ct_number == "2024-518143-38-00"
    finally:
        client.close()
