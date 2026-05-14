"""Sidebar shell and audit-bundle exports."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from ctis_drift.cockpit import (
    _audit_history_sample_rows_for_pdf,
    _audit_row_from_run,
    _resolve_audit_history_sort_column,
    build_monitored_dataframe,
    export_pdf_bytes,
    export_workbook_bytes,
    fetch_trial_records,
    latest_run_lookup,
)
from ctis_drift.config import Settings
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env
from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)

# Mirrors cockpit.export column contract for cold-start frames.
_DRIFT_COLUMNS: tuple[str, ...] = (
    "created_utc",
    "trial_id",
    "metric_name",
    "drift_score_0_1",
    "method",
    "risk_band",
)


def render_global_exports(storage: StorageService) -> None:
    ste = streamlit_env.st
    trials = fetch_trial_records(storage)
    runs = storage.recent_runs(limit=2_000)
    lookup = latest_run_lookup(runs)
    df_mon = build_monitored_dataframe(trials, lookup=lookup)

    if not trials:
        ste.caption(
            "First-run workspace: enrol at least one trial to populate the monitoring register "
            "sheet; drift history fills after the first evaluations."
        )

    hist = pd.DataFrame([_audit_row_from_run(r) for r in runs])
    if hist.empty:
        hist = pd.DataFrame(columns=list(_DRIFT_COLUMNS))

    if hist.empty or not runs:
        ste.info(
            "No archived drift evaluations yet. Workbook and PDF exports still "
            "include the monitoring register and an empty drift history sheet."
        )

    sort_col = _resolve_audit_history_sort_column(hist)
    hist_for_export = hist
    if sort_col is not None and sort_col in hist.columns and not hist.empty:
        try:
            hist_for_export = hist.sort_values(by=sort_col, ascending=False, na_position="last")
        except Exception:
            log_unexpected_error(logger, "Drift history sort failed; exporting unsorted rows")
            hist_for_export = hist
    sample_rows = _audit_history_sample_rows_for_pdf(hist_for_export, limit=30)

    ex1, ex2 = ste.columns(2)
    with ex1:
        try:
            xbytes = export_workbook_bytes(df_mon, hist_for_export)
            ste.download_button(
                "Export workbook (Excel, TMF-friendly)",
                data=xbytes,
                file_name=f"ctis_drift_audit_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.xlsx",
                mime=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                use_container_width=True,
                key="sidebar_dl_export_audit_workbook_xlsx",
            )
        except Exception:
            log_unexpected_error(logger, "Excel export blocked")
            ste.error(
                f"Excel export unavailable as of "
                f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC. "
                "Confirm `openpyxl` is installed and that the workbook is not corrupted. "
                "Set `CTIS_DRIFT_LOG_LEVEL=DEBUG` for a full traceback in server logs.",
            )

    with ex2:
        try:
            headline = (
                f"{len(df_mon)} trials registered; {len(hist_for_export)} evaluation rows archived."
            )
            pbytes = export_pdf_bytes(headline, sample_rows)
            ste.download_button(
                "Export PDF summary",
                data=pbytes,
                file_name=f"ctis_drift_summary_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="sidebar_dl_export_summary_pdf",
            )
        except Exception:
            log_unexpected_error(logger, "PDF export blocked")
            ste.error(
                f"PDF export unavailable as of "
                f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC "
                "(summary uses PDF core fonts; see logs for exporter diagnostics). "
                "Use the Excel audit bundle if the fault persists — it preserves UTF-8. "
                "Set `CTIS_DRIFT_LOG_LEVEL=DEBUG` for a full traceback in server logs.",
            )


def sidebar_shell(settings: Settings, storage: StorageService) -> None:
    """Branding, exports, controls that stay visible alongside every primary tab."""
    ste = streamlit_env.st
    with ste.sidebar:
        ste.markdown("#### CTIS Drift Sentinel")
        ste.caption("Substantive change detection for EU CTIS public artefacts")

        with ste.expander(
            "Audit bundle exports (Excel & PDF)",
            expanded=False,
            key="sidebar_expander_audit_bundle_exports",
        ):
            ste.caption(
                "Workbook mirrors TMF traceability worksheets; PDF is a concise appendix—"
                "refresh before regulatory submissions."
            )
            try:
                render_global_exports(storage)
            except Exception:
                log_unexpected_error(logger, "Sidebar audit exports failed")
                ste.warning(
                    "Exports could not be prepared (empty database, missing dependency, or "
                    "transient error). Refresh the page after the first data load, or check logs."
                )

        ste.divider()
        ste.markdown("**Environment snapshot**")
        ste.caption("Read-only telemetry from environment / `.env`")
        ste.text_input(
            "Log level",
            value=settings.log_level,
            disabled=True,
            key="sidebar_env_snapshot_log_level",
        )
        ste.text_input(
            "API base",
            value=settings.api_base_url,
            disabled=True,
            key="sidebar_env_snapshot_api_base_url",
        )
        ste.toggle(
            "Offline mock CTIS (`CTIS_DRIFT_ENABLE_MOCK_API`) — status only",
            value=settings.enable_mock_api,
            disabled=True,
            key="sidebar_env_snapshot_mock_api_toggle",
        )
        ste.caption(
            "When `CTIS_DRIFT_ENABLE_MOCK_API=true`, `bootstrap_runtime` wires "
            "`create_mock_ctis_http_client` into `CTISAPIClient` (see `ctis_mock_transport.py`). "
            "Restart the app after changing `.env`."
            if settings.enable_mock_api
            else "Live traffic uses your configured API base URL; set the env var above to enable "
            "the built-in mock transport for offline demos."
        )

        ste.divider()
        ste.markdown("**Appearance**")
        ste.caption(
            "Adjust light or dark preference from the Streamlit *Settings → Theme* menu. "
            "Enterprise defaults reside in `.streamlit/config.toml`."
        )
