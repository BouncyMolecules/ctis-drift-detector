"""Application services shared by tests and the dashboard (framework-agnostic)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Final, cast

import pandas as pd
import plotly.graph_objects as go
from fpdf.enums import XPos, YPos
from fpdf.fpdf import FPDF
from sqlmodel import col, select

from ctis_drift.config import Settings
from ctis_drift.constants import APP_ATTRIBUTION
from ctis_drift.core.ctis_mock_transport import create_mock_ctis_http_client
from ctis_drift.core.ctis_public_client import CTISAPIClient
from ctis_drift.core.drift_detector import DriftDetector, DriftReport, RiskLevel
from ctis_drift.core.storage import DriftRunRecord, StorageService, TrialRecord
from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)


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
        d = _run_dt_utc(r).date()
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


def _drift_run_sort_key(run: DriftRunRecord) -> tuple[int, float, int]:
    """Stable chronological ordering without assuming ``created_at`` is always populated.

    Falls back to monotonic ``id`` (SQLite PK) when timestamps are absent so portfolios
    with partially migrated rows still chart instead of throwing.
    """

    ts = getattr(run, "created_at", None)
    if isinstance(ts, datetime):
        return (0, ts.astimezone(UTC).timestamp(), int(getattr(run, "id", 0) or 0))
    rid = getattr(run, "id", None)
    if isinstance(rid, int):
        return (1, float(rid), rid)
    return (2, 0.0, 0)


def _run_dt_utc(run: DriftRunRecord) -> datetime:
    """Best-effort evaluation instant for plotting (aligns with DriftRun / snapshot wording)."""

    ts = getattr(run, "created_at", None)
    if isinstance(ts, datetime):
        return ts.astimezone(UTC)
    # Extremely defensive: orphaned rows — anchor to UNIX epoch rather than crashing the chart.
    return datetime.fromtimestamp(0, tz=UTC)


def _format_run_timestamp_utc(run: DriftRunRecord) -> str:
    """Display string for tables/expanders; tolerant of partial ORM rows."""

    ts = getattr(run, "created_at", None)
    if isinstance(ts, datetime):
        return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    rid = getattr(run, "id", None)
    return f"(unknown time · row id {rid})" if rid is not None else "(unknown time)"


def _safe_drift_score_01(run: DriftRunRecord) -> float:
    try:
        return round(float(getattr(run, "drift_score", 0.0)), 4)
    except (TypeError, ValueError):
        return 0.0


def fig_risk_trend(runs_for_trial: Sequence[DriftRunRecord], *, title: str) -> go.Figure:
    ascending = sorted(runs_for_trial, key=_drift_run_sort_key)
    if not ascending:
        fig = go.Figure()
        fig.update_layout(template="plotly_white", title=title + " — no data")
        return fig

    # Single evaluation: spline lines are pointless (some renderers degrade);
    # markers + bands stay crisp.
    if len(ascending) == 1:
        fig = go.Figure()
        r0 = ascending[0]
        blob0 = _parse_run_blob(r0.details_json)
        lvl0, pct0, _ = _extract_risk(blob0)
        if pct0 is None:
            try:
                pct0 = round(float(r0.drift_score) * 100.0, 4)
            except (TypeError, ValueError):
                pct0 = 0.0
        pct0 = max(0.0, min(100.0, float(pct0)))
        level_for_color = lvl0 if lvl0 in {e.value for e in RiskLevel} else _level_from_pct(pct0)
        marker_colors_single = [_risk_marker_color(level_for_color)]
        fig.add_trace(
            go.Scatter(
                x=[_run_dt_utc(r0)],
                y=[pct0],
                mode="markers",
                name="Risk score (0–100)",
                marker=dict(
                    color=marker_colors_single,
                    size=14,
                    symbol="square",
                    line=dict(width=0.5),
                ),
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
            title=dict(
                text=title,
                subtitle=dict(
                    text="Single evaluation logged — spline trend unlocks after the next run.",
                ),
            ),
            height=420,
            margin=dict(l=50, r=30, t=70, b=62),
            xaxis=dict(title="Time (UTC)"),
            yaxis=dict(title="Risk score (0–100)"),
            hovermode="x unified",
            font=dict(family="Segoe UI, Inter, Helvetica, Arial, sans-serif", size=12),
            title_font=dict(size=16),
        )
        return fig

    ts: list[datetime] = []
    pct_raw: list[float] = []
    lvls: list[str] = []

    for r in ascending:
        ts.append(_run_dt_utc(r))
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

    # go.Scattergl rejects ``line.shape='spline'`` (WebGL scatter);
    # standard Scatter supports splines.
    fig.add_trace(
        go.Scatter(
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
    refresh_ui: Callable[[], None] | None = None,
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
    if refresh_ui is not None:
        refresh_ui()
    return report


class _ExportPdfDoc(FPDF):
    def header(self) -> None:  # noqa: PLR6301 signature required by fpdf API
        self.set_font("Helvetica", style="B", size=13)
        self.cell(
            0,
            9,
            clean_ascii("CTIS Drift Detector — Regulatory export snapshot"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_font("Helvetica", size=9)
        self.cell(
            0,
            5,
            clean_ascii(f"UTC generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(2)

    def footer(self) -> None:  # noqa: PLR6301 signature required by fpdf API
        self.set_y(-14)
        self.set_font("Helvetica", size=8)
        self.set_text_color(90, 90, 95)
        self.multi_cell(
            0,
            4,
            text=clean_ascii(APP_ATTRIBUTION),
            align="C",
            border=0,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )


def clean_ascii(text: str) -> str:
    """Keep PDF core fonts reliable across environments."""
    return (
        text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2011", "-").replace("–", "-")
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
        log_unexpected_error(logger, "Excel workbook export failed")
        raise


def export_pdf_bytes(
    monitored_headline: str, hist_rows_sample: Iterable[Mapping[str, Any]]
) -> bytes:
    pdf = _ExportPdfDoc()
    pdf.set_auto_page_break(True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.write(h=6, text=clean_ascii(monitored_headline))
    pdf.ln(10)
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.write(h=7, text=clean_ascii("Recent drift evaluations (excerpt):"))
    pdf.ln(7)
    pdf.set_font("Helvetica", size=9)
    for row in hist_rows_sample:
        line = "; ".join(f"{k}: {row[k]}" for k in sorted(row.keys()))
        if len(line) > 112:
            line = line[:109] + "..."
        pdf.multi_cell(
            0,
            5,
            text=clean_ascii(line),
            border="B",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    bio_raw = pdf.output()
    if isinstance(bio_raw, (bytes, bytearray)):
        return bytes(bio_raw)
    if isinstance(bio_raw, str):
        return bio_raw.encode("latin-1")
    return bytes(bio_raw)


def build_ctis_api_client(settings: Settings) -> CTISAPIClient:
    """Wire :class:`CTISAPIClient` from settings (live HTTPS or mock transport).

    When ``CTIS_DRIFT_ENABLE_MOCK_API`` is true, all CTIS-shaped HTTP calls are satisfied by
    :func:`~ctis_drift.core.ctis_mock_transport.create_mock_ctis_http_client` — no outbound
    traffic to ``euclinicaltrials.eu``.
    """

    http_client = (
        create_mock_ctis_http_client(timeout_seconds=settings.api_timeout_seconds)
        if settings.enable_mock_api
        else None
    )
    if settings.enable_mock_api:
        logger.warning(
            "CTIS_DRIFT_ENABLE_MOCK_API=true — mock CTIS transport active (offline demo)."
        )

    return CTISAPIClient(
        settings.api_base_url,
        timeout_seconds=settings.api_timeout_seconds,
        token=settings.api_token,
        http_client=http_client,
    )


def _resolve_audit_history_sort_column(df: pd.DataFrame) -> str | None:
    """Pick a column for newest-first drift-history sorting.

    The export sheet labels evaluation time ``created_utc`` (ISO string from
    :class:`~ctis_drift.core.storage.DriftRunRecord`). Snapshot audit rows mirror
    :class:`~ctis_drift.core.storage.TrialSnapshotRecord` from
    :meth:`~ctis_drift.core.storage.StorageService.get_history` (``timestamp``,
    ``id``, ``euct_number``, …), so we probe those SQLModel names before assuming
    ``created_utc`` exists — avoids ``KeyError`` when callers merge frames or when
    schema aliases differ (e.g. ``UTC time`` from UI-derived exports).

    Ingesting **zero** rows still yields a typed empty frame in sidebar export paths; a bare
    ``pd.DataFrame([])`` has **no** columns and any hard-coded ``sort_values("created_utc")``
    surfaces as ``KeyError`` on hosted dashboard runtimes with cold databases.
    """

    if df.shape[1] == 0:
        return None
    for candidate in (
        "created_utc",
        "timestamp",
        "created_at",
        "last_checked",
        "first_seen_at",
        "UTC time",
        "id",
    ):
        if candidate in df.columns:
            return candidate
    return str(df.columns[0])


# Canonical drift audit headers for Excel/PDF; empty exports keep this schema so sort/export
# paths never reference a column that was never materialised.
_DRIFT_HIST_EXPORT_COLUMNS: Final[tuple[str, ...]] = (
    "created_utc",
    "trial_id",
    "metric_name",
    "drift_score_0_1",
    "method",
    "risk_band",
)


def _audit_row_from_run(r: DriftRunRecord) -> dict[str, Any]:
    """One export row with tolerant timestamp serialisation (mirrors storage field names)."""

    ts = getattr(r, "created_at", None)
    created_utc = ts.isoformat(timespec="seconds") if isinstance(ts, datetime) else ""
    return {
        "created_utc": created_utc,
        "trial_id": getattr(r, "trial_id", "") or "",
        "metric_name": getattr(r, "metric_name", "") or "",
        "drift_score_0_1": getattr(r, "drift_score", None),
        "method": getattr(r, "method", "") or "",
        "risk_band": _extract_risk(_parse_run_blob(getattr(r, "details_json", None)))[0],
    }


def _audit_history_sample_rows_for_pdf(df: pd.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    """PDF-safe rows: string cells only (fpdf core fonts).

    ``DataFrame.to_dict("records")`` is typed as a list of loosely keyed dicts; cast here so
    strict mypy stays aligned with our explicit ``dict[str, Any]`` export contract.
    """

    if df.shape[0] == 0:
        return []
    records = cast(
        list[dict[str, Any]],
        df.head(limit).astype(str).to_dict("records"),
    )
    out: list[dict[str, Any]] = []
    for raw_row in records:
        row_map: dict[str, Any] = {
            str(col_name): "" if val in {"", "nan", "None"} else val
            for col_name, val in raw_row.items()
        }
        out.append(row_map)
    return out

