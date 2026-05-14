"""Backward-compatible package entry and re-exports.

The Streamlit experience is composed under :mod:`ctis_drift.ui`; domain services that tests
import from this module live in :mod:`ctis_drift.cockpit`.
"""

from __future__ import annotations

from typing import Any

from ctis_drift.cockpit import (
    _resolve_audit_history_sort_column,
    apply_risk_styling,
    build_ctis_api_client,
    build_monitored_dataframe,
    export_pdf_bytes,
    export_workbook_bytes,
    fetch_trial_records,
    fig_change_frequency_histogram,
    fig_risk_trend,
    latest_run_lookup,
    run_ctis_check_and_persist,
)
from ctis_drift.constants import APP_ATTRIBUTION
from ctis_drift.ui.app import render_app
from ctis_drift.ui.sidebar import render_global_exports
from ctis_drift.ui.utils.errors import friendly_api_error as _friendly_api_error
from ctis_drift.ui.utils.session import (
    _SS_REFRESH_TOKEN,
    _bump_data_refresh,
    _init_session_defaults,
)
from ctis_drift.ui.utils.theme import inject_app_theme_styles

__all__ = [
    "APP_ATTRIBUTION",
    "inject_app_theme_styles",
    "main",
    "render_global_exports",
    "_SS_REFRESH_TOKEN",
    "_bump_data_refresh",
    "_friendly_api_error",
    "_init_session_defaults",
    "_resolve_audit_history_sort_column",
    "apply_risk_styling",
    "build_ctis_api_client",
    "build_monitored_dataframe",
    "export_pdf_bytes",
    "export_workbook_bytes",
    "fetch_trial_records",
    "fig_change_frequency_histogram",
    "fig_risk_trend",
    "latest_run_lookup",
    "run_ctis_check_and_persist",
]


def __getattr__(name: str) -> Any:
    """Resolve ``st`` lazily so tests can patch :data:`ctis_drift.ui.streamlit_env.st`."""
    if name == "st":
        from ctis_drift.ui import streamlit_env

        return streamlit_env.st
    msg = f"module '{__name__}' has no attribute {name!r}"
    raise AttributeError(msg)


def main() -> None:
    render_app()
