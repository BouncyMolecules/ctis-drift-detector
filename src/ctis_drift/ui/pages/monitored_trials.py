"""Portfolio monitoring tab."""

from __future__ import annotations

import streamlit.column_config as scc

from ctis_drift.cockpit import (
    _extract_risk,
    _parse_run_blob,
    apply_risk_styling,
    build_monitored_dataframe,
    fetch_trial_records,
    fig_change_frequency_histogram,
    fig_risk_trend,
    latest_run_lookup,
    run_ctis_check_and_persist,
)
from ctis_drift.config import Settings
from ctis_drift.core.ctis_public_client import CTISAPIClient, CtisPublicApiError
from ctis_drift.core.drift_detector import DriftDetector, RiskLevel
from ctis_drift.core.storage import StorageService
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.caching import demo_metrics_frame
from ctis_drift.ui.utils.errors import (
    friendly_api_error as _friendly_api_error,
)
from ctis_drift.ui.utils.errors import (
    streamlit_error_log_hint as _streamlit_error_log_hint,
)
from ctis_drift.ui.utils.session import (
    _SS_ACTION_TRIAL,
    _SS_REFRESH_TOKEN,
    _bump_data_refresh,
)
from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)



def tab_monitored_trials(
    storage: StorageService,
    client: CTISAPIClient,
    settings: Settings,
) -> None:
    ste = streamlit_env.st
    _ = ste.session_state.get(_SS_REFRESH_TOKEN, 0)
    runs = storage.recent_runs(limit=2_000)
    trials = fetch_trial_records(storage)
    lookup = latest_run_lookup(runs)

    ste.markdown(
        '<div class="ctis-shell"><h3>Monitored portfolio</h3>'
        "<p class='ctis-muted-page-lede'>"
        "Live registry from your local audit database and last evaluation metadata.</p></div>",
        unsafe_allow_html=True,
    )

    high_crit = 0
    for t in trials:
        lr = lookup.get(t.euct_number)
        if not lr:
            continue
        lvl, _, _ = _extract_risk(_parse_run_blob(lr.details_json))
        if lvl in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}:
            high_crit += 1

    c1, c2, c3, c4 = ste.columns(4)
    c1.metric("Registered trials", len(trials))
    c2.metric("Evaluations on file", len(runs))
    c3.metric("Elevated or critical (latest)", high_crit)
    last_poll = max((t.last_checked for t in trials), default=None)
    c4.metric(
        "Most recent poll (UTC)",
        last_poll.strftime("%Y-%m-%d %H:%M") if last_poll else "—",
    )

    df = build_monitored_dataframe(trials, lookup=lookup)
    if df.empty:
        ste.info(
            "No trials registered yet. Use **Add / manage** to enrol an EU CT number.",
        )
    else:
        selected = ste.selectbox(
            "Focus trial for quick actions",
            options=[""] + list(df["EU CT Number"].unique()),
            index=0,
            key="focus_trial_select",
            help="Keyboard: Tab to this control; select a trial to enable one-click checks below.",
        )
        if selected:
            ste.session_state[_SS_ACTION_TRIAL] = selected

        try:
            styled = apply_risk_styling(df)
            ste.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                height=min(520, 48 + 36 * len(df)),
                key="monitored_df_portfolio_register_styled",
                column_config={
                    "EU CT Number": scc.TextColumn("EU CT number", width="medium"),
                    "Risk band": scc.TextColumn("Risk band", width="small"),
                    "Risk score": scc.NumberColumn(
                        "Risk score", format="%.1f", min_value=0, max_value=100
                    ),
                },
            )
        except Exception:
            log_unexpected_error(logger, "Styled dataframe render failed; plain-table fallback")
            ste.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                key="monitored_df_portfolio_register_plain_fallback",
            )

        ste.markdown("**Quick actions**")
        qa1, qa2, qa3 = ste.columns([1, 1, 1])
        target = ste.session_state.get(_SS_ACTION_TRIAL) or selected
        with qa1:
            if ste.button(
                "Run CTIS drift check",
                type="primary",
                disabled=not target,
                use_container_width=True,
                key="portfolio_btn_run_ctis_drift_check",
                help=("Fetches the live trial JSON, compares to baseline, and logs a drift run."),
            ):
                with ste.spinner("Contacting CTIS and scoring drift …"):
                    try:
                        trial_euct = str(target).strip()
                        report = run_ctis_check_and_persist(
                            storage=storage,
                            euct=trial_euct,
                            api_client=client,
                            persist_snapshot=True,
                            refresh_ui=_bump_data_refresh,
                        )
                        ste.success(
                            f"Completed for `{trial_euct}` — band **{report.risk_level.value}** "
                            f"(score {report.risk_score}/100).",
                        )
                        ste.toast(
                            "Results saved to the audit database.",
                            icon=":material/verified:",
                        )
                    except CtisPublicApiError as exc:
                        ste.error(_friendly_api_error(exc))
                    except Exception:
                        log_unexpected_error(logger, "Drift check failed")
                        ste.error(
                            "An unexpected error occurred while evaluating drift.",
                        )
                        _streamlit_error_log_hint()

        with qa2:
            if ste.button(
                "Smoke-test API (search)",
                use_container_width=True,
                key="portfolio_btn_smoke_test_api_search",
            ):
                with ste.spinner("Running minimal search probe …"):
                    try:
                        resp = client.health(page_size=1)
                        ste.json(dict(resp))
                    except CtisPublicApiError as exc:
                        ste.error(_friendly_api_error(exc))

        with qa3:
            demo = demo_metrics_frame(seed=42)
            if ste.button(
                "Demo numeric drift (sandbox)",
                use_container_width=True,
                key="portfolio_btn_demo_numeric_drift",
                help="Creates a synthetic numeric drift report for UI validation — not CTIS data.",
            ):
                with ste.spinner("Scoring synthetic series …"):
                    try:
                        detector = DriftDetector()
                        rep = detector.score(
                            trial_id=target or "SANDBOX",
                            metric_name="demo_endpoint_rate",
                            reference=demo["reference"],
                            current=demo["current"],
                        )
                        storage.save_report(rep)
                        _bump_data_refresh()
                        ste.success(
                            f"Demo risk {rep.risk_score}/100 ({rep.risk_level.value}) — stored.",
                        )
                    except ValueError:
                        log_unexpected_error(logger, "Demo drift sandbox rejected input")
                        ste.warning(
                            "Demo drift scoring could not run with the current selection "
                            "(domain validation failed). Adjust inputs or check logs."
                        )

    ste.subheader("Portfolio signals")
    col_a, col_b = ste.columns(2, gap="large")
    with col_a:
        ste.plotly_chart(
            fig_change_frequency_histogram(runs),
            use_container_width=True,
            key="monitored_plot_activity_histogram_all_runs",
        )
    with col_b:
        trial_pick_options = sorted({r.trial_id for r in runs}, key=str)
        if not trial_pick_options:
            ste.info("Run at least one evaluation to unlock risk trajectory charts.")
        else:
            default_idx = (
                trial_pick_options.index(str(ste.session_state.get(_SS_ACTION_TRIAL)))
                if ste.session_state.get(_SS_ACTION_TRIAL) in trial_pick_options
                else 0
            )
            picked = ste.selectbox(
                "Trial for risk trajectory",
                options=trial_pick_options,
                index=default_idx,
                key="portfolio_risk_pick",
                help="Choose any trial that already has persisted drift evaluations.",
            )
            chart_runs = [r for r in runs if r.trial_id == picked]
            ste.plotly_chart(
                fig_risk_trend(chart_runs, title=f"Risk trajectory — {picked}"),
                use_container_width=True,
                key="monitored_plot_risk_trajectory_for_selected_trial",
            )

