"""Streamlit ``st.cache_*`` decorators — keeps memoisation out of core layers."""

from __future__ import annotations

import random

import pandas as pd

from ctis_drift.core.ctis_public_client import (
    DEFAULT_CACHE_TTL_SECONDS,
    TrialFullRecord,
    TrialSearchPayload,
    TrialSearchResponse,
    public_client_singleton,
)
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env


@streamlit_env.st.cache_resource(show_spinner=False)
def storage_service(database_url: str) -> StorageService:
    storage = StorageService(database_url)
    storage.init_db()
    return storage


@streamlit_env.st.cache_data(
    ttl=300, show_spinner="Loading analytic reference series …"
)
def demo_metrics_frame(*, seed: int) -> pd.DataFrame:
    rnd = random.Random(seed)
    idx = list(range(50))
    reference = [100.0 + rnd.random() * 2.0 for _ in idx]
    current = [102.0 + rnd.random() * 2.5 + (i % 5) * 0.05 for i in idx]
    return pd.DataFrame({"idx": idx, "reference": reference, "current": current})


@streamlit_env.st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def search_trials_cached(payload_json: str) -> TrialSearchResponse:
    """TTL cache for anonymous CTIS `/search` calls (JSON-stable cache key).

    Uses the shared :func:`~ctis_drift.core.ctis_public_client.public_client_singleton`; it does
    not inherit app :class:`~ctis_drift.config.Settings` overrides (offline mock, base URL tweaks).
    Prefer calling :meth:`CTISAPIClient.search_trials` directly for mocked or bespoke clients.
    """

    client = public_client_singleton()
    payload = TrialSearchPayload.model_validate_json(payload_json)
    return client.search_trials(payload)


@streamlit_env.st.cache_data(ttl=DEFAULT_CACHE_TTL_SECONDS, show_spinner=False)
def get_full_trial_cached(euct_number: str) -> TrialFullRecord:
    """TTL cache keyed by sanitised EU CT identifier (anonymous singleton client)."""

    return public_client_singleton().get_full_trial(euct_number)
