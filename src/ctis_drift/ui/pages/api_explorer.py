"""Direct CTIS endpoint explorer tab."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
from pydantic import ValidationError

from ctis_drift.core.ctis_public_client import CTISAPIClient, CtisPublicApiError, TrialSearchPayload
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.errors import friendly_api_error as _friendly_api_error
from ctis_drift.utils.logging import get_logger

logger = get_logger(__name__)



def tab_api_explorer(client: CTISAPIClient) -> None:
    ste = streamlit_env.st
    ste.markdown("### API explorer")
    ste.caption(
        "Power users — exercise CTIS endpoints with pacing, retries, and typed envelopes.",
    )

    t_search, t_retrieve, t_health = ste.tabs(
        ["POST /search", "GET /retrieve/{euct}", "Health"],
        key="explorer_tabs_endpoint_surfaces",
    )

    with t_health:
        if ste.button("Run health(search=1)", key="explorer_btn_health_probe"):
            with ste.spinner("Probing …"):
                try:
                    ste.success("OK — parsed envelope returned below.")
                    ste.json(dict(client.health(page_size=1)))
                except CtisPublicApiError as exc:
                    ste.error(_friendly_api_error(exc))

    with t_search:
        defaults = (
            '{"pagination":{"page":1,"size":5},'
            '"sort":{"property":"decisionDate","direction":"DESC"}}'
        )
        body = ste.text_area(
            "Search payload JSON (`searchCriteria` optional)",
            defaults,
            height=180,
            key="explorer_search_payload_json",
        )
        if ste.button("Execute search", key="explorer_btn_search_execute"):
            body_text = (body or "").strip()
            if not body_text:
                ste.info(
                    "Use the default JSON or paste a search payload, then execute again.",
                )
            else:
                try:
                    model = TrialSearchPayload.model_validate_json(body_text)
                    with ste.spinner(
                        "Waiting on CTIS (may take up to configured timeout) …",
                    ):
                        resp = client.search_trials(model)
                        ste.download_button(
                            "Download serialised envelope",
                            data=resp.model_dump_json(by_alias=True),
                            file_name=f"search_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json",
                            mime="application/json",
                            key="explorer_dl_search_envelope_serialised",
                        )
                        n_rows = len(resp.data)
                        ste.success(f"Fetched {n_rows} rows (pagination aware).")
                        ste.dataframe(
                            pd.DataFrame([h.model_dump(by_alias=True) for h in resp.data]),
                            use_container_width=True,
                            hide_index=True,
                            height=min(560, 200 + len(resp.data) * 42),
                            key="explorer_df_search_response_rows",
                        )
                except (json.JSONDecodeError, ValidationError) as exc:
                    logger.warning("API explorer search payload invalid: %s", exc)
                    ste.error(
                        "Payload is not valid JSON or does not match the CTIS search schema "
                        "(check pagination and camelCase aliases)."
                    )

    with t_retrieve:
        euct_probe = ste.text_input(
            "EU CT Number",
            key="explorer_input_retrieve_euct",
            placeholder="e.g. 2024-518143-38-00",
        )
        if ste.button("Execute retrieve", key="explorer_btn_retrieve_execute"):
            if not euct_probe.strip():
                ste.warning("Enter a trial identifier.")
            else:
                try:
                    with ste.spinner("Retrieving canonical record …"):
                        rec = client.get_full_trial(euct_probe)
                        payload = json.dumps(rec.model_dump(mode="json", by_alias=True), indent=2)
                        ste.code(payload[:24000])
                        if len(payload) > 24000:
                            ste.caption(
                                "Snippet truncated — use Download for full artefact.",
                            )
                        ste.download_button(
                            label="Download full retrieve JSON",
                            data=payload,
                            file_name=f"retrieve_{euct_probe.strip()}.json",
                            mime="application/json",
                            key="explorer_dl_retrieve_full_json",
                        )
                except CtisPublicApiError as exc:
                    ste.error(_friendly_api_error(exc))
