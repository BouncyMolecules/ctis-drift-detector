"""Runtime wiring (database + CTIS client)."""

from __future__ import annotations

from ctis_drift.cockpit import build_ctis_api_client
from ctis_drift.config import Settings
from ctis_drift.core.ctis_public_client import CTISAPIClient
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.caching import storage_service
from ctis_drift.ui.utils.errors import streamlit_error_log_hint
from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)


def bootstrap_runtime(settings: Settings) -> tuple[StorageService, CTISAPIClient]:
    """Open database + outbound API client."""

    ste = streamlit_env.st
    try:
        storage_local = storage_service(settings.database_url)
    except OSError:
        log_unexpected_error(logger, "Database bootstrap failed")
        ste.error(
            "The surveillance database could not be initialised. "
            "Confirm `CTIS_DRIFT_DATABASE_URL` points at a writable path."
        )
        streamlit_error_log_hint()
        ste.stop()

    client_local = build_ctis_api_client(settings)
    return storage_local, client_local
