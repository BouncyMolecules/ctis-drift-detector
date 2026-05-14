"""Forensic drift history tab."""

from __future__ import annotations

import json

import pandas as pd

from ctis_drift.cockpit import (
    _drift_run_sort_key,
    _extract_risk,
    _format_run_timestamp_utc,
    _parse_run_blob,
    _run_dt_utc,
    _safe_drift_score_01,
    fig_change_frequency_histogram,
)
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.session import _SS_REFRESH_TOKEN


def tab_drift_history(storage: StorageService) -> None:
    ste = streamlit_env.st
    _ = ste.session_state.get(_SS_REFRESH_TOKEN, 0)
    runs = storage.recent_runs(limit=500)
    ste.markdown("### Drift history & forensic detail")
    ste.caption(
        "Expand any row to inspect structured differentials and regulatory narrative.",
    )

    if not runs:
        ste.info(
            "No drift rows stored. Run checks from **Monitored trials** or **Add / manage**.",
        )
        return

    filter_trial = ste.selectbox(
        "Filter by trial",
        options=["(all)"] + sorted({r.trial_id for r in runs}, key=str),
        key="history_trial_filter",
    )

    filtered = (
        list(runs) if filter_trial == "(all)" else [r for r in runs if r.trial_id == filter_trial]
    )
    # Newest-first table + charts; ordering key tolerates missing ``created_at``.
    filtered_sorted = sorted(filtered, key=_drift_run_sort_key, reverse=True)

    hist_df = pd.DataFrame(
        {
            "UTC time": [_format_run_timestamp_utc(r) for r in filtered_sorted],
            "Trial": [r.trial_id for r in filtered_sorted],
            "Metric": [r.metric_name for r in filtered_sorted],
            "Method": [r.method for r in filtered_sorted],
            "Score (0–1)": [_safe_drift_score_01(r) for r in filtered_sorted],
        },
    )

    ste.dataframe(
        hist_df,
        use_container_width=True,
        hide_index=True,
        height=min(320, 60 + len(hist_df) * 44),
        key="history_df_drift_runs_filtered_overview",
    )

    ste.subheader("Timeline")
    ste.plotly_chart(
        fig_change_frequency_histogram(filtered_sorted),
        use_container_width=True,
        key="history_plot_activity_histogram_filtered_runs",
    )

    ste.subheader("Per-run evidence")
    for ev_idx, r in enumerate(filtered_sorted[:40]):
        blob = _parse_run_blob(r.details_json)
        lvl, pct, _ = _extract_risk(blob)
        rid = getattr(r, "id", None)
        rid_suffix = str(rid) if rid is not None else "noid"
        header = f"{r.trial_id} · {_format_run_timestamp_utc(r)} UTC · {lvl}"
        ev_key = f"history_evidence_expander_row_{ev_idx}_{r.trial_id}_{rid_suffix}"
        with ste.expander(header, expanded=False, key=ev_key):
            if pct is not None:
                ste.progress(int(min(100, max(0, pct))) / 100.0)
            narrative = blob.get("human_readable_summary") or ""
            if isinstance(narrative, str) and narrative:
                ste.markdown(f"_{narrative}_")

            cfs = blob.get("changed_fields")
            structural = blob.get("detailed_diff") or {}
            structural_s = structural.get("structural") if isinstance(structural, dict) else None

            c1, c2 = ste.columns(2)
            with c1:
                ste.markdown("**Changed fields (sample)**")
                if isinstance(cfs, list) and cfs:
                    ste.json(cfs[:50])
                else:
                    ste.caption(
                        "No field-level artefacts (numeric-only or unchanged run).",
                    )
            with c2:
                ste.markdown("**Structural summary**")
                if isinstance(structural_s, dict):
                    ste.json(structural_s)
                else:
                    ste.caption("No structural envelope on this payload.")

            ste.download_button(
                label="Download full JSON artefact",
                data=json.dumps(blob, indent=2, sort_keys=True, default=str),
                file_name=(
                    f"drift_report_{r.trial_id}_{rid_suffix}_"
                    f"{_run_dt_utc(r).strftime('%Y%m%dT%H%M%SZ')}.json"
                ),
                mime="application/json",
                key=f"history_dl_full_json_artefact_row_{ev_idx}_{r.trial_id}_{rid_suffix}",
            )

