"""Trial onboarding & manual JSON ingest tab."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError

from ctis_drift.core.ctis_public_client import CTISAPIClient, CtisPublicApiError
from ctis_drift.core.drift_detector import DriftDetector
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.errors import (
    friendly_api_error as _friendly_api_error,
)
from ctis_drift.ui.utils.errors import (
    streamlit_error_log_hint as _streamlit_error_log_hint,
)
from ctis_drift.ui.utils.session import _bump_data_refresh
from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)



def tab_manage_trials(
    storage: StorageService,
    client: CTISAPIClient,
) -> None:
    ste = streamlit_env.st
    ste.markdown("### Add & manage monitored trials")

    ingest_left, ingest_right = ste.columns((1, 1), gap="large")
    with ingest_left:
        ste.markdown("**Retrieve from CTIS & anchor snapshot**")
        euct_new = ste.text_input(
            "EU CT Number",
            placeholder="e.g. 2024-518143-38-00",
            key="mgmt_euct",
            autocomplete="off",
        )
        col_a, col_b = ste.columns(2)
        with col_a:
            do_eval = ste.toggle(
                "Evaluate drift vs existing baseline first",
                value=True,
                key="manage_toggle_evaluate_drift_vs_baseline_first",
            )
        with col_b:
            skip_duplicate = ste.toggle(
                "Skip inserting identical snapshots",
                value=True,
                key="manage_toggle_skip_duplicate_snapshot_hashes",
            )

        if ste.button(
            "Ingest CTIS retrieve payload",
            type="primary",
            disabled=not (euct_new or "").strip(),
            key="manage_btn_ingest_ctis_retrieve",
        ):
            euct_clean = euct_new.strip().strip("/")
            with ste.spinner("Retrieving authoritative CTIS payload …"):
                try:
                    full = client.get_full_trial(euct_clean)
                    payload_json_any = json.loads(full.model_dump_json())
                    payload_json = (
                        dict(payload_json_any) if isinstance(payload_json_any, dict) else {}
                    )
                    detector = DriftDetector()
                    if do_eval:
                        report = detector.evaluate_with_storage(storage, euct_clean, payload_json)
                        storage.save_snapshot(
                            euct_clean,
                            payload_json,
                            skip_duplicate_hash=skip_duplicate,
                        )
                        storage.save_report(report)
                        ste.success(
                            f"Captured `{full.ct_number}` — band **{report.risk_level.value}**."
                        )
                    else:
                        res = storage.save_snapshot(
                            euct_clean,
                            payload_json,
                            skip_duplicate_hash=skip_duplicate,
                        )
                        note = (
                            "New immutable snapshot persisted."
                            if res.persisted_new_row
                            else "Registry updated — hash matched latest snapshot row."
                        )
                        ste.success(note)
                    _bump_data_refresh()
                    ste.json({"preview": list(payload_json.keys())})

                except CtisPublicApiError as exc:
                    ste.error(_friendly_api_error(exc))
                except ValidationError as exc:
                    logger.warning("CTIS envelope validation failed during ingest: %s", exc)
                    ste.error(
                        "The CTIS response did not match the expected schema. "
                        "Verify the trial identifier or inspect application logs."
                    )
                except Exception:
                    log_unexpected_error(logger, "Ingest pathway failed")
                    ste.error("Unexpected failure during ingestion.")
                    _streamlit_error_log_hint()

        ste.markdown(
            "**Note:** Persisted JSON is hashed with canonical ordering for inspection readiness "
            "and cryptographic drift detection aligned with Annex expectations for traceability.",
        )

    with ingest_right:
        ste.markdown("**Manual JSON onboarding (sandbox / migration)**")
        raw = ste.text_area(
            "Paste trial JSON mapping",
            height=260,
            placeholder='{"exampleKey": true}',
            key="manual_json_area",
        )
        euct_manual = ste.text_input(
            "EU CT identifier for this payload",
            key="manual_euct",
        )

        def _save_manual() -> None:
            try:
                parsed = json.loads(raw or "{}")
            except json.JSONDecodeError:
                log_unexpected_error(logger, "Manual JSON onboarding: invalid JSON")
                ste.error(
                    "The pasted text is not valid JSON — nothing was persisted. "
                    "Fix brackets, commas, or quoting, then try again."
                )
                return
            if not isinstance(parsed, Mapping):
                ste.error("Top-level payload must be a JSON object.")
                return
            key_manual = euct_manual.strip()
            if not key_manual:
                ste.error("Provide the EU CT number this payload belongs to.")
                return
            storage.save_snapshot(key_manual, dict(parsed))
            _bump_data_refresh()
            ste.success(f"Snapshot anchored for `{key_manual}`.")

        if ste.button(
            "Save pasted JSON as snapshot",
            key="manage_btn_manual_json_save_snapshot",
        ):
            _save_manual()

