"""Streamlit entry point — CTIS Drift Detector clinical operations dashboard."""

from __future__ import annotations

import json
import random
import traceback
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Final, cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.column_config as scc
from fpdf import FPDF
from pydantic import ValidationError
from sqlmodel import col, select

from ctis_drift.config import Settings, get_settings
from ctis_drift.core.ctis_api import (
    CTISAPIClient,
    CtisPublicApiError,
    CtisTransportError,
    TrialSearchPayload,
    get_full_trial,
)
from ctis_drift.core.drift_detector import DriftDetector, DriftReport, RiskLevel
from ctis_drift.core.storage import DriftRunRecord, StorageService, TrialRecord
from ctis_drift.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

_SS_ACTION_TRIAL: Final[str] = "_ctis_action_trial_euct"
_SS_REFRESH_TOKEN: Final[str] = "_ctis_data_refresh"


def _init_session_defaults() -> None:
    defaults: dict[str, Any] = {
        _SS_ACTION_TRIAL: "",
        _SS_REFRESH_TOKEN: 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _bump_data_refresh() -> None:
    st.session_state[_SS_REFRESH_TOKEN] = int(st.session_state.get(_SS_REFRESH_TOKEN, 0)) + 1


def inject_app_theme_styles() -> None:
    """Unobtrusive pharma-style framing; respects Streamlit theme tokens."""
    st.markdown(
        """
        <style>
        /* Focus visibility for keyboard users */
        button:focus-visible, div[data-baseweb] button:focus-visible {
            outline: 2px solid #0f4f6b;
            outline-offset: 2px;
        }
        .ctis-shell {
            padding: 0.85rem 0 0;
        }
        .ctis-shell h3 {
            font-weight: 650;
            letter-spacing: -0.02em;
            margin-bottom: 0;
        }
        .ctis-kpi {
            border-radius: 10px;
            padding: 0.75rem 0.95rem;
            border: 1px solid rgba(15,79,107,0.22);
            background: linear-gradient(180deg,
                rgba(15,79,107,0.07) 0%,
                rgba(15,79,107,0.02) 100%);
            min-height: 5.75rem;
        }
        div[data-testid="stSidebarNav"] ~ div {
            scrollbar-gutter: stable;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


APP_ATTRIBUTION: Final[str] = (
    "Built as a professional portfolio project by Ela Halilovic – Regulatory Operations "
    "Specialist & Digital Transformation"
)


@st.cache_resource(show_spinner=False)
def storage_service(database_url: str) -> StorageService:
    storage = StorageService(database_url)
    storage.init_db()
    return storage


@st.cache_data(ttl=300, show_spinner="Loading analytic reference series …")
def demo_metrics_frame(*, seed: int) -> pd.DataFrame:
    rnd = random.Random(seed)
    idx = list(range(50))
    reference = [100.0 + rnd.random() * 2.0 for _ in idx]
    current = [102.0 + rnd.random() * 2.5 + (i % 5) * 0.05 for i in idx]
    return pd.DataFrame({"idx": idx, "reference": reference, "current": current})


def _friendly_api_error(exc: CtisPublicApiError) -> str:
    hint = getattr(exc, "url", "") or type(exc).__name__
    if isinstance(exc, CtisTransportError):
        return (
            "Could not reach the CTIS public API (network connectivity or firewall). "
            f"Technical detail: {exc} [{hint}]"
        )
    return f"API request failed: {exc}. Location: [{hint}]"


def _risk_level_css_class(level: str) -> str:
    lut = {
        RiskLevel.LOW.value: "#1b7f4a",
        RiskLevel.MEDIUM.value: "#a86b00",
        RiskLevel.HIGH.value: "#b94a03",
        RiskLevel.CRITICAL.value: "#9f1f2c",
        "UNKNOWN": "#5c6f7a",
    }
    return lut.get(level.upper(), lut["UNKNOWN"])


def _parse_run_blob(details_json: str | None) -> dict[str, Any]:
    if not details_json:
        return {}
    try:
        blob = json.loads(details_json)
        return blob if isinstance(blob, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Malformed details_json skipped for drift run row")
        return {}


def _extract_risk(blob: Mapping[str, Any]) -> tuple[str, float | None, str | None]:
    level = str(blob.get("risk_level") or "").upper().strip()
    metric = blob.get("metric_name")
    metric_s = metric if metric is None or isinstance(metric, str) else str(metric)

    drift_f: float | None = None
    if "risk_score" in blob and blob["risk_score"] is not None:
        try:
            rs = float(blob["risk_score"])
            drift_f = rs * 100.0 if 0.0 <= rs <= 1.0 else rs
            drift_f = max(0.0, min(100.0, drift_f))
        except (TypeError, ValueError):
            drift_f = None
    if drift_f is None and "drift_score" in blob:
        try:
            drift_f = float(blob["drift_score"]) * 100.0
            drift_f = max(0.0, min(100.0, drift_f))
        except (TypeError, ValueError):
            drift_f = None

    resolved = (
        level
        if level in {e.value for e in RiskLevel}
        else (_level_from_pct(drift_f) if drift_f is not None else "UNKNOWN")
    )
    return resolved, drift_f, metric_s


def _level_from_pct(pct: float | None) -> str:
    if pct is None:
        return "UNKNOWN"
    if pct <= 24:
        return RiskLevel.LOW.value
    if pct <= 49:
        return RiskLevel.MEDIUM.value
    if pct <= 79:
        return RiskLevel.HIGH.value
    return RiskLevel.CRITICAL.value


def fetch_trial_records(storage: StorageService) -> list[TrialRecord]:
    with storage.session() as session:
        stmt = select(TrialRecord).order_by(col(TrialRecord.last_checked).desc())
        return list(session.exec(stmt).all())


def latest_run_lookup(runs: Sequence[DriftRunRecord]) -> dict[str, DriftRunRecord]:
    best: dict[str, DriftRunRecord] = {}
    for row in runs:
        if row.trial_id not in best:
            best[row.trial_id] = row
    return best


def build_monitored_dataframe(
    trials: Iterable[TrialRecord],
    *,
    lookup: Mapping[str, DriftRunRecord],
) -> pd.DataFrame:
    rows_out: list[dict[str, Any]] = []
    for t in trials:
        lr = lookup.get(t.euct_number)
        blob = _parse_run_blob(lr.details_json if lr else None) if lr else {}
        level, pct, metric = _extract_risk(blob) if lr else ("UNKNOWN", None, None)
        rows_out.append(
            {
                "EU CT Number": t.euct_number,
                "Last polled (UTC)": t.last_checked.strftime("%Y-%m-%d %H:%M"),
                "Content fingerprint": (t.latest_content_hash or "")[:12] + "…",
                "Last drift check (UTC)": lr.created_at.strftime("%Y-%m-%d %H:%M") if lr else "—",
                "Metric": (lr.metric_name if lr else "") or metric or "—",
                "Risk score": round(pct, 1) if pct is not None else None,
                "Risk band": level,
            },
        )
    return pd.DataFrame(rows_out)


def apply_risk_styling(df_display: pd.DataFrame) -> Any:
    if df_display.empty:
        return df_display

    def style_band(row: pd.Series) -> list[str]:
        band_raw = row.get("Risk band", "UNKNOWN")
        band_str = band_raw if isinstance(band_raw, str) else str(band_raw or "UNKNOWN")
        color = "#f9fafb" if band_str == "UNKNOWN" else _risk_level_hex_bg(band_str)
        css = f"background-color: {color}; color: #0f1720"
        return [css] * len(row)

    formatted = df_display.copy()
    try:
        return formatted.style.apply(style_band, axis=1).format(
            {"Risk score": "{:.1f}"},
            na_rep="—",
        )
    except ValueError:
        return formatted.style.apply(style_band, axis=1)


def _risk_level_hex_bg(level: str) -> str:
    return {
        RiskLevel.LOW.value: "#d8f7e8",
        RiskLevel.MEDIUM.value: "#ffeec2",
        RiskLevel.HIGH.value: "#ffe0bf",
        RiskLevel.CRITICAL.value: "#ffdde1",
        "UNKNOWN": "#eef2f6",
    }.get(level.upper(), "#eef2f6")


def fig_change_frequency_histogram(runs: Sequence[DriftRunRecord]) -> go.Figure:
    days: list[str] = []
    for r in runs:
        d = r.created_at.astimezone(UTC).date()
        days.append(str(d))
    tally = Counter(days)
    if not tally:
        fig = go.Figure()
        fig.update_layout(template="plotly_white", title="Activity (no drift runs yet)")
        return fig

    xs = sorted(tally.keys())
    ys = [tally[d] for d in xs]

    colors = px_like_seq(len(xs))
    fig = go.Figure(go.Bar(x=xs, y=ys, marker_color=colors))
    fig.update_layout(
        template="plotly_white",
        title="Recorded drift evaluations by day",
        xaxis_title="Day (UTC date)",
        yaxis_title="Count",
        bargap=0.2,
        height=340,
        margin=dict(l=50, r=20, t=54, b=62),
        font=dict(family="Segoe UI, Inter, Helvetica, Arial, sans-serif", size=12),
        title_font=dict(size=16),
        xaxis=dict(tickangle=35),
        showlegend=False,
    )
    return fig


def px_like_seq(n: int) -> list[str]:
    base = "#0f4f6b"
    if n <= 1:
        return [base]
    interp = plotly_palette(n)
    return interp


def plotly_palette(n: int) -> list[str]:
    """Linear blend from primary to teal for categorical bars."""

    palette: list[str] = []
    for i in range(n):
        frac = i / max(1, n - 1)
        r = int(15 + (28 - 15) * frac)
        gr = int(79 + (130 - 79) * frac)
        b = int(107 + (146 - 107) * frac)
        palette.append(f"rgb({r},{gr},{b})")
    return palette


def fig_risk_trend(runs_for_trial: Sequence[DriftRunRecord], *, title: str) -> go.Figure:
    ascending = sorted(runs_for_trial, key=lambda r: r.created_at)
    if not ascending:
        fig = go.Figure()
        fig.update_layout(template="plotly_white", title=title + " — no data")
        return fig

    ts: list[datetime] = []
    pct_raw: list[float] = []
    lvls: list[str] = []

    for r in ascending:
        ts.append(r.created_at.astimezone(UTC))
        blob = _parse_run_blob(r.details_json)
        lvl, pct, _ = _extract_risk(blob)
        if pct is None:
            try:
                pct = round(float(r.drift_score) * 100.0, 4)
            except (TypeError, ValueError):
                pct = 0.0
        pct_raw.append(max(0.0, min(100.0, pct)))
        if lvl not in {e.value for e in RiskLevel}:
            lvl = _level_from_pct(pct_raw[-1])
        lvls.append(lvl)

    fig = go.Figure()

    marker_colors = [_risk_marker_color(lvl_band) for lvl_band in lvls]
    fig.add_trace(
        go.Scattergl(
            x=ts,
            y=pct_raw,
            mode="lines+markers",
            name="Risk score (0–100)",
            marker=dict(color=marker_colors, size=11, symbol="square", line=dict(width=0.5)),
            line=dict(color="#0f4f6b", width=3, shape="spline"),
            hovertemplate="%{x|%Y-%m-%d %H:%M} UTC<br>Score %{y:.1f}<extra></extra>",
        ),
    )
    fig.update_yaxes(range=[0.0, 100.0])
    thresholds = [(24.5, "LOW"), (49.5, "MEDIUM"), (79.5, "HIGH")]
    for y_band, lbl in thresholds:
        fig.add_hline(
            y=y_band,
            line_dash="dot",
            line_color="rgba(23,36,46,0.28)",
            annotation_text=lbl + " cutoff",
            annotation_position="bottom right",
        )

    fig.update_layout(
        template="plotly_white",
        title=title,
        height=400,
        margin=dict(l=50, r=30, t=54, b=62),
        xaxis=dict(title="Time (UTC)"),
        yaxis=dict(title="Risk score (0–100)"),
        hovermode="x unified",
        font=dict(family="Segoe UI, Inter, Helvetica, Arial, sans-serif", size=12),
        title_font=dict(size=16),
    )
    return fig


def _risk_marker_color(level: str) -> str:
    return _risk_level_css_class(level)


def run_ctis_check_and_persist(
    *,
    storage: StorageService,
    euct: str,
    api_client: CTISAPIClient,
    persist_snapshot: bool,
) -> DriftReport:
    """Fetch live CTIS JSON, evaluate drift vs baseline, optionally persist snapshot."""
    record = api_client.get_full_trial(euct.strip())
    raw_any = json.loads(record.model_dump_json())
    raw = dict(raw_any) if isinstance(raw_any, dict) else {}
    if not raw:
        msg = "CTIS retrieve payload was not usable JSON object after validation"
        raise ValueError(msg)

    detector = DriftDetector()
    report = detector.evaluate_with_storage(storage, euct, raw)
    if persist_snapshot:
        storage.save_snapshot(euct, raw, skip_duplicate_hash=True)
    storage.save_report(report)
    _bump_data_refresh()
    return report


class _ExportPdfDoc(FPDF):
    def header(self) -> None:  # noqa: PLR6301 signature required by fpdf API
        self.set_font("Helvetica", style="B", size=13)
        self.cell(
            0,
            9,
            clean_ascii("CTIS Drift Detector — Regulatory export snapshot"),
            ln=1,  # type: ignore[arg-type]
        )
        self.set_font("Helvetica", size=9)
        self.cell(
            0,
            5,
            clean_ascii(f"UTC generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}"),
            ln=1,  # type: ignore[arg-type]
        )
        self.ln(2)

    def footer(self) -> None:  # noqa: PLR6301 signature required by fpdf API
        self.set_y(-14)
        self.set_font("Helvetica", size=8)
        self.set_text_color(90, 90, 95)
        self.multi_cell(
            0,
            4,
            clean_ascii(APP_ATTRIBUTION),
            align="C",
            border=0,
        )


def clean_ascii(text: str) -> str:
    """Keep PDF core fonts reliable across environments."""
    return (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2011", "-")
        .replace("–", "-")
    )


def export_workbook_bytes(
    monitored: pd.DataFrame,
    hist: pd.DataFrame,
) -> bytes:
    bio = BytesIO()
    sheet_a = monitored.copy()
    sheet_b = hist.copy()
    try:
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            sheet_a.to_excel(writer, index=False, sheet_name="Monitoring_register")
            sheet_b.to_excel(writer, index=False, sheet_name="Drift_runs_audit")
            meta = pd.DataFrame(
                {
                    "Field": ["Generated UTC", APP_ATTRIBUTION],
                    "Value": [
                        datetime.now(UTC).isoformat(timespec="seconds"),
                        APP_ATTRIBUTION.replace("\n", " "),
                    ],
                },
            )
            meta.to_excel(writer, index=False, sheet_name="Document_control")
        return bio.getvalue()
    except Exception:
        logger.exception("Excel workbook export failed")
        raise


def export_pdf_bytes(
    monitored_headline: str, hist_rows_sample: Iterable[Mapping[str, Any]]
) -> bytes:
    pdf = _ExportPdfDoc()
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.write(6, clean_ascii(monitored_headline))
    pdf.ln(10)
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.write(7, clean_ascii("Recent drift evaluations (excerpt):"))
    pdf.ln(7)
    pdf.set_font("Helvetica", size=9)
    for row in hist_rows_sample:
        line = "; ".join(f"{k}: {row[k]}" for k in sorted(row.keys()))
        if len(line) > 112:
            line = line[:109] + "..."
        pdf.multi_cell(0, 5, clean_ascii(line), border="B")

    bio_any = pdf.output(dest="S")  # type: ignore[call-overload]
    if isinstance(bio_any, bytes):
        return bio_any
    return bio_any.encode("latin-1") if isinstance(bio_any, str) else bytes(bio_any)


def render_footer() -> None:
    st.divider()
    st.caption(APP_ATTRIBUTION)


def sidebar_shell(settings: Settings, storage: StorageService) -> None:
    """Branding, exports, controls that stay visible alongside every primary tab."""
    with st.sidebar:
        st.markdown("#### CTIS Drift Sentinel")
        st.caption("Substantive change detection for EU CTIS public artefacts")

        with st.expander("Audit bundle exports (Excel & PDF)", expanded=False):
            st.caption(
                "Workbook mirrors TMF traceability worksheets; PDF is a concise appendix—"
                "refresh before regulatory submissions."
            )
            render_global_exports(storage)

        st.divider()
        st.markdown("**Environment snapshot**")
        st.caption("Read-only telemetry from environment / `.env`")
        st.text_input(
            "Log level",
            value=settings.log_level,
            disabled=True,
        )
        st.text_input("API base", value=settings.api_base_url, disabled=True)
        st.toggle(
            "Mock API flag (`CTIS_DRIFT_ENABLE_MOCK_API`)",
            value=settings.enable_mock_api,
            disabled=True,
        )

        st.divider()
        st.markdown("**Appearance**")
        st.caption(
            "Adjust light or dark preference from the Streamlit *Settings → Theme* menu. "
            "Enterprise defaults reside in `.streamlit/config.toml`."
        )


def bootstrap_runtime(settings: Settings) -> tuple[StorageService, CTISAPIClient]:
    """Open database + outbound API client."""
    try:
        storage_local = storage_service(settings.database_url)
    except OSError:
        logger.exception("Database bootstrap failed")
        st.error(
            "The surveillance database could not be initialised. "
            "Confirm `CTIS_DRIFT_DATABASE_URL` points at a writable path."
        )
        st.code(traceback.format_exc())
        st.stop()

    client_local = CTISAPIClient(
        settings.api_base_url,
        timeout_seconds=settings.api_timeout_seconds,
        token=settings.api_token,
    )
    return storage_local, client_local


def tab_monitored_trials(storage: StorageService, client: CTISAPIClient) -> None:
    _ = st.session_state.get(_SS_REFRESH_TOKEN, 0)
    runs = storage.recent_runs(limit=2_000)
    trials = fetch_trial_records(storage)
    lookup = latest_run_lookup(runs)

    st.markdown(
        '<div class="ctis-shell"><h3>Monitored portfolio</h3>'
        "<p style='margin-top:0.35rem;color:#4a5b66;'>"
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

    c1, c2, c3, c4 = st.columns(4)
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
        st.info("No trials registered yet. Use **Add / manage** to enrol an EU CT number.")
    else:
        selected = st.selectbox(
            "Focus trial for quick actions",
            options=[""] + list(df["EU CT Number"].unique()),
            index=0,
            key="focus_trial_select",
            help="Keyboard: Tab to this control; select a trial to enable one-click checks below.",
        )
        if selected:
            st.session_state[_SS_ACTION_TRIAL] = selected

        try:
            styled = apply_risk_styling(df)
            st.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                height=min(520, 48 + 36 * len(df)),
                column_config={
                    "EU CT Number": scc.TextColumn("EU CT number", width="medium"),
                    "Risk band": scc.TextColumn("Risk band", width="small"),
                    "Risk score": scc.NumberColumn(
                        "Risk score", format="%.1f", min_value=0, max_value=100
                    ),
                },
            )
        except Exception:
            logger.exception("Styled dataframe render failed; falling back to plain table")
            st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("**Quick actions**")
        qa1, qa2, qa3 = st.columns([1, 1, 1])
        target = st.session_state.get(_SS_ACTION_TRIAL) or selected
        with qa1:
            if st.button(
                "Run CTIS drift check",
                type="primary",
                disabled=not target,
                use_container_width=True,
                help=(
                    "Fetches the live trial JSON, compares to baseline, and logs a drift run."
                ),
            ):
                with st.spinner("Contacting CTIS and scoring drift …"):
                    try:
                        trial_euct = str(target).strip()
                        report = run_ctis_check_and_persist(
                            storage=storage,
                            euct=trial_euct,
                            api_client=client,
                            persist_snapshot=True,
                        )
                        st.success(
                            f"Completed for `{trial_euct}` — band **{report.risk_level.value}** "
                            f"(score {report.risk_score}/100).",
                        )
                        st.toast("Results saved to the audit database.", icon=":material/verified:")
                    except CtisPublicApiError as exc:
                        st.error(_friendly_api_error(exc))
                    except Exception:
                        logger.exception("Drift check failed")
                        st.error("An unexpected error occurred while evaluating drift.")
                        st.code(traceback.format_exc())

        with qa2:
            if st.button(
                "Smoke-test API (search)",
                use_container_width=True,
            ):
                with st.spinner("Running minimal search probe …"):
                    try:
                        resp = client.health(page_size=1)
                        st.json(dict(resp))
                    except CtisPublicApiError as exc:
                        st.error(_friendly_api_error(exc))

        with qa3:
            demo = demo_metrics_frame(seed=42)
            if st.button(
                "Demo numeric drift (sandbox)",
                use_container_width=True,
                help="Creates a synthetic numeric drift report for UI validation — not CTIS data.",
            ):
                with st.spinner("Scoring synthetic series …"):
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
                        st.success(
                            f"Demo risk {rep.risk_score}/100 ({rep.risk_level.value}) — stored.",
                        )
                    except ValueError as exc:
                        st.warning(str(exc))

    st.subheader("Portfolio signals")
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.plotly_chart(fig_change_frequency_histogram(runs), use_container_width=True)
    with col_b:
        trial_pick_options = sorted({r.trial_id for r in runs}, key=str)
        if not trial_pick_options:
            st.info("Run at least one evaluation to unlock risk trajectory charts.")
        else:
            default_idx = (
                trial_pick_options.index(str(st.session_state.get(_SS_ACTION_TRIAL)))
                if st.session_state.get(_SS_ACTION_TRIAL) in trial_pick_options
                else 0
            )
            picked = st.selectbox(
                "Trial for risk trajectory",
                options=trial_pick_options,
                index=default_idx,
                key="portfolio_risk_pick",
                help="Choose any trial that already has persisted drift evaluations.",
            )
            chart_runs = [r for r in runs if r.trial_id == picked]
            st.plotly_chart(
                fig_risk_trend(chart_runs, title=f"Risk trajectory — {picked}"),
                use_container_width=True,
            )


def tab_drift_history(storage: StorageService) -> None:
    _ = st.session_state.get(_SS_REFRESH_TOKEN, 0)
    runs = storage.recent_runs(limit=500)
    st.markdown("### Drift history & forensic detail")
    st.caption("Expand any row to inspect structured differentials and regulatory narrative.")

    if not runs:
        st.info("No drift rows stored. Run checks from **Monitored trials** or **Add / manage**.")
        return

    filter_trial = st.selectbox(
        "Filter by trial",
        options=["(all)"] + sorted({r.trial_id for r in runs}, key=str),
        key="history_trial_filter",
    )

    filtered = (
        list(runs) if filter_trial == "(all)" else [r for r in runs if r.trial_id == filter_trial]
    )

    hist_df = pd.DataFrame(
        {
            "UTC time": [
                r.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S") for r in filtered
            ],
            "Trial": [r.trial_id for r in filtered],
            "Metric": [r.metric_name for r in filtered],
            "Method": [r.method for r in filtered],
            "Score (0–1)": [round(float(r.drift_score), 4) for r in filtered],
        },
    )

    st.dataframe(
        hist_df, use_container_width=True, hide_index=True, height=min(320, 60 + len(hist_df) * 44)
    )

    st.subheader("Timeline")
    st.plotly_chart(fig_change_frequency_histogram(filtered), use_container_width=True)

    st.subheader("Per-run evidence")
    for r in filtered[:40]:
        blob = _parse_run_blob(r.details_json)
        lvl, pct, _ = _extract_risk(blob)
        header = (
            f"{r.trial_id} · {r.created_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC · {lvl}"
        )
        with st.expander(header, expanded=False):
            if pct is not None:
                st.progress(int(min(100, max(0, pct))) / 100.0)
            narrative = blob.get("human_readable_summary") or ""
            if isinstance(narrative, str) and narrative:
                st.markdown(f"_{narrative}_")

            cfs = blob.get("changed_fields")
            structural = blob.get("detailed_diff") or {}
            structural_s = structural.get("structural") if isinstance(structural, dict) else None

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Changed fields (sample)**")
                if isinstance(cfs, list) and cfs:
                    st.json(cfs[:50])
                else:
                    st.caption("No field-level artefacts (numeric-only or unchanged run).")
            with c2:
                st.markdown("**Structural summary**")
                if isinstance(structural_s, dict):
                    st.json(structural_s)
                else:
                    st.caption("No structural envelope on this payload.")

            st.download_button(
                label="Download full JSON artefact",
                data=json.dumps(blob, indent=2, sort_keys=True, default=str),
                file_name=(
                    f"drift_report_{r.trial_id}_{r.id}_"
                    f"{r.created_at.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
                ),
                mime="application/json",
                key=f"dl_hist_{r.id}",
            )


def tab_manage_trials(storage: StorageService) -> None:
    st.markdown("### Add & manage monitored trials")

    ingest_left, ingest_right = st.columns((1, 1), gap="large")
    with ingest_left:
        st.markdown("**Retrieve from CTIS & anchor snapshot**")
        euct_new = st.text_input(
            "EU CT Number",
            placeholder="e.g. 2024-518143-38-00",
            key="mgmt_euct",
            autocomplete="off",
        )
        col_a, col_b = st.columns(2)
        with col_a:
            do_eval = st.toggle("Evaluate drift vs existing baseline first", value=True)
        with col_b:
            skip_duplicate = st.toggle("Skip inserting identical snapshots", value=True)

        if st.button(
            "Ingest CTIS retrieve payload",
            type="primary",
            disabled=not (euct_new or "").strip(),
        ):
            euct_clean = euct_new.strip().strip("/")
            with st.spinner("Retrieving authoritative CTIS payload …"):
                try:
                    full = get_full_trial(euct_clean, use_streamlit_cache=False)
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
                        st.success(
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
                        st.success(note)
                    _bump_data_refresh()
                    st.json({"preview": list(payload_json.keys())})

                except CtisPublicApiError as exc:
                    st.error(_friendly_api_error(exc))
                except ValidationError as exc:
                    st.error("Validated CTIS envelope failed pydantic parsing.")
                    st.json({"validation_errors": exc.errors()})
                except Exception:
                    logger.exception("Ingest pathway failed")
                    st.error("Unexpected failure during ingestion.")
                    st.code(traceback.format_exc())

        st.markdown(
            "**Note:** Persisted JSON is hashed with canonical ordering for inspection readiness "
            "and cryptographic drift detection aligned with Annex expectations for traceability.",
        )

    with ingest_right:
        st.markdown("**Manual JSON onboarding (sandbox / migration)**")
        raw = st.text_area(
            "Paste trial JSON mapping",
            height=260,
            placeholder='{"exampleKey": true}',
            key="manual_json_area",
        )
        euct_manual = st.text_input("EU CT identifier for this payload", key="manual_euct")

        def _save_manual() -> None:
            try:
                parsed = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                st.error(f"Malformed JSON ({exc}); nothing was persisted.")
                return
            if not isinstance(parsed, Mapping):
                st.error("Top-level payload must be a JSON object.")
                return
            key_manual = euct_manual.strip()
            if not key_manual:
                st.error("Provide the EU CT number this payload belongs to.")
                return
            storage.save_snapshot(key_manual, dict(parsed))
            _bump_data_refresh()
            st.success(f"Snapshot anchored for `{key_manual}`.")

        if st.button("Save pasted JSON as snapshot"):
            _save_manual()


def tab_api_explorer(client: CTISAPIClient) -> None:
    st.markdown("### API explorer")
    st.caption("Power users — exercise CTIS endpoints with pacing, retries, and typed envelopes.")

    t_search, t_retrieve, t_health = st.tabs(["POST /search", "GET /retrieve/{euct}", "Health"])

    with t_health:
        if st.button("Run health(search=1)", key="health_btn"):
            with st.spinner("Probing …"):
                try:
                    st.success("OK — parsed envelope returned below.")
                    st.json(dict(client.health(page_size=1)))
                except CtisPublicApiError as exc:
                    st.error(_friendly_api_error(exc))

    with t_search:
        defaults = (
            '{"pagination":{"page":1,"size":5},'
            '"sort":{"property":"decisionDate","direction":"DESC"}}'
        )
        body = st.text_area("Search payload JSON (`searchCriteria` optional)", defaults, height=180)
        if st.button("Execute search"):
            try:
                model = TrialSearchPayload.model_validate_json(body)
                with st.spinner("Waiting on CTIS (may take up to configured timeout) …"):
                    resp = client.search_trials(model)
                    st.download_button(
                        "Download serialised envelope",
                        data=resp.model_dump_json(by_alias=True),
                        file_name=f"search_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                    )
                    st.success(f"Fetched {len(resp.data)} rows (pagination aware).")
                    st.dataframe(
                        pd.DataFrame([h.model_dump(by_alias=True) for h in resp.data]),
                        use_container_width=True,
                        hide_index=True,
                        height=min(560, 200 + len(resp.data) * 42),
                    )
            except (json.JSONDecodeError, ValidationError) as exc:
                st.error("Payload invalid.")
                st.code(str(exc))

    with t_retrieve:
        euct_probe = st.text_input("EU CT Number", key="retrieve_euct")
        if st.button("Execute retrieve"):
            if not euct_probe.strip():
                st.warning("Enter a trial identifier.")
            else:
                try:
                    with st.spinner("Retrieving canonical record …"):
                        rec = client.get_full_trial(euct_probe)
                        payload = json.dumps(rec.model_dump(mode="json", by_alias=True), indent=2)
                        st.code(payload[:24000])
                        if len(payload) > 24000:
                            st.caption("Snippet truncated — use Download for full artefact.")
                        st.download_button(
                            label="Download full retrieve JSON",
                            data=payload,
                            file_name=f"retrieve_{euct_probe.strip()}.json",
                            mime="application/json",
                            key="dl_retrieve_probe",
                        )
                except CtisPublicApiError as exc:
                    st.error(_friendly_api_error(exc))


def _resolve_audit_history_sort_column(df: pd.DataFrame) -> str | None:
    """Pick a column for newest-first drift-history sorting.

    The export sheet labels evaluation time ``created_utc`` (ISO string from
    :class:`~ctis_drift.core.storage.DriftRunRecord`). Other layers or future
    refactors may align frame columns with SQLModel field names—for example
    ``timestamp`` on snapshot rows—or the list comprehension may yield **zero
    rows**, in which case pandas builds an empty DataFrame with **no columns**
    and ``sort_values(by="created_utc")`` raises ``KeyError`` on Streamlit Cloud.

    Resolution prefers chronological-looking columns, then ``id``, then falls back to
    the first remaining column so exports stay operational across schema drift.
    """
    if df.shape[1] == 0:
        return None
    for candidate in ("created_utc", "timestamp", "created_at", "UTC time", "id"):
        if candidate in df.columns:
            return candidate
    return str(df.columns[0])


def render_global_exports(storage: StorageService) -> None:
    trials = fetch_trial_records(storage)
    runs = storage.recent_runs(limit=2_000)
    lookup = latest_run_lookup(runs)
    df_mon = build_monitored_dataframe(trials, lookup=lookup)

    hist = pd.DataFrame(
        [
            {
                "created_utc": r.created_at.isoformat(timespec="seconds"),
                "trial_id": r.trial_id,
                "metric_name": r.metric_name,
                "drift_score_0_1": r.drift_score,
                "method": r.method,
                "risk_band": _extract_risk(_parse_run_blob(r.details_json))[0],
            }
            for r in runs
        ]
    )

    # Empty run lists produce a column-less frame; sorting must skip until data exists.
    if hist.shape[1] == 0:
        st.info(
            "No archived drift evaluations yet. Workbook and PDF exports still "
            "include the monitoring register and an empty drift history sheet."
        )
        sample_rows: list[dict[str, Any]] = []
    else:
        sort_col = _resolve_audit_history_sort_column(hist)
        hist_ordered = (
            hist.sort_values(by=sort_col, ascending=False, na_position="last")
            if sort_col is not None
            else hist
        )
        sample_rows = list(hist_ordered.head(30).astype(str).to_dict("records"))

    ex1, ex2 = st.columns(2)
    with ex1:
        try:
            xbytes = export_workbook_bytes(df_mon, hist)
            st.download_button(
                "Export workbook (Excel, TMF-friendly)",
                data=xbytes,
                file_name=f"ctis_drift_audit_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.xlsx",
                mime=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                use_container_width=True,
            )
        except Exception:
            logger.exception("Excel export blocked")
            st.error("Excel export unavailable (see logs). Confirm `openpyxl` installation.")

    with ex2:
        try:
            pbytes = export_pdf_bytes(
                f"{len(df_mon)} trials registered; {len(hist)} evaluation rows archived.",
                cast(Iterable[Mapping[str, Any]], sample_rows),
            )
            st.download_button(
                "Export PDF summary",
                data=pbytes,
                file_name=f"ctis_drift_summary_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception:
            logger.exception("PDF export blocked")
            st.error("PDF export failed — consult server logs regarding fpdf runtime.")


def render_app() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    st.set_page_config(
        layout="wide",
        page_title="CTIS Drift Detector | Vigilance Command Center",
        page_icon=":material/analytics:",
        initial_sidebar_state="expanded",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": (
                "## CTIS Drift Detector\nSubstantive change surveillance for CTIS-derived clinical "
                "trial disclosures."
            ),
        },
    )

    inject_app_theme_styles()
    _init_session_defaults()

    storage, client = bootstrap_runtime(settings)
    sidebar_shell(settings, storage)

    st.markdown(
        '<main class="ctis-shell" role="main">'
        "<h2>Clinical vigilance cockpit</h2>"
        "<p style='margin-top:0.35rem;color:#4a5b66;margin-bottom:1.35rem'>"
        "Operate a sponsor-grade monitoring desk for CTIS artefacts: cryptographic baselines, "
        "risk-graded deltas, audit exports, and direct API ergonomics.</p>"
        "</main>",
        unsafe_allow_html=True,
    )

    monitored_tab, history_tab, manage_tab, explorer_tab = st.tabs(
        [
            "1 · Monitored trials",
            "2 · Drift history & details",
            "3 · Add / manage trials",
            "4 · API explorer",
        ],
    )

    with monitored_tab:
        tab_monitored_trials(storage, client)
    with history_tab:
        tab_drift_history(storage)
    with manage_tab:
        tab_manage_trials(storage)
    with explorer_tab:
        tab_api_explorer(client)

    render_footer()


def main() -> None:
    render_app()


if __name__ == "__main__":
    main()
