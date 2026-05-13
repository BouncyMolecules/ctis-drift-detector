"""Unit tests for regulatory drift scoring primitives (no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from ctis_drift.core.drift_detector import (
    ChangeCategory,
    DriftDetector,
    RegulatoryDriftConfig,
    RiskLevel,
    build_regulatory_report,
    categorize_path_component,
    risk_level_from_score,
    snapshot_content_hash,
)


def test_risk_level_from_score_bands() -> None:
    """Threshold mapping should stay monotone across business bands."""

    assert risk_level_from_score(0) is RiskLevel.LOW
    assert risk_level_from_score(24) is RiskLevel.LOW
    assert risk_level_from_score(25) is RiskLevel.MEDIUM
    assert risk_level_from_score(49) is RiskLevel.MEDIUM
    assert risk_level_from_score(50) is RiskLevel.HIGH
    assert risk_level_from_score(79) is RiskLevel.HIGH
    assert risk_level_from_score(80) is RiskLevel.CRITICAL
    assert risk_level_from_score(100) is RiskLevel.CRITICAL


def test_categorize_path_component_status() -> None:
    """CTIS-style status keys must route to the STATUS ontology."""

    cfg = RegulatoryDriftConfig()
    assert categorize_path_component("ctStatus", cfg) is ChangeCategory.STATUS


def test_categorize_ambiguous_fallback() -> None:
    """Tied keyword hits degrade to GENERAL_METADATA to avoid silent misrouting."""

    cfg = RegulatoryDriftConfig(
        category_keywords={
            ChangeCategory.STATUS: ("foo",),
            ChangeCategory.SPONSOR_AND_SITE: ("foo",),
        },
    )
    assert categorize_path_component("foo.foo", cfg) is ChangeCategory.GENERAL_METADATA


def test_snapshot_content_hash_stable() -> None:
    """Hashing aligns with persisted snapshot canonicalisation semantics."""

    a = snapshot_content_hash({"b": 1, "a": 2})
    b = snapshot_content_hash({"a": 2, "b": 1})
    assert a == b


def test_build_regulatory_report_unchanged_short_circuit() -> None:
    """Explicit ``changed_explicit=False`` must bypass expensive reconciliation."""

    payload = {"authorizedApplication": {"status": "X"}}
    digest = snapshot_content_hash(payload)
    baseline_ts = datetime(2024, 1, 1, tzinfo=UTC)
    report = build_regulatory_report(
        trial_id="2024-000001-42-99",
        baseline_payload=payload,
        candidate_payload=payload,
        previous_content_hash=digest,
        current_content_hash=digest,
        ingest_notes="Synthetic regression fixture.",
        baseline_timestamp=baseline_ts,
        changed_explicit=False,
    )
    assert report.changed is False
    assert report.risk_score == 0
    assert report.risk_level is RiskLevel.LOW
    assert report.changed_fields == ()


def test_build_regulatory_report_status_delta_elevates() -> None:
    """Status ontology hits should materially increase deterministic mass."""

    old = {"ctStatus": "Authorised"}
    new = {"ctStatus": "Suspended"}
    h_old = snapshot_content_hash(old)
    h_new = snapshot_content_hash(new)
    ts = datetime(2024, 6, 1, tzinfo=UTC)
    report = build_regulatory_report(
        trial_id="2024-000002-42-98",
        baseline_payload=old,
        candidate_payload=new,
        previous_content_hash=h_old,
        current_content_hash=h_new,
        ingest_notes="Status transition rehearsal.",
        baseline_timestamp=ts,
    )
    assert report.changed is True
    assert report.risk_score > 35
    assert any(
        contrib.rule_id.endswith(ChangeCategory.STATUS.value)
        for contrib in report.contributions
        if contrib.rule_id.startswith("category_mass::")
    )


def test_numeric_series_back_compat() -> None:
    """Streamlit-era ``score`` API still surfaces unified DriftReport objects."""

    det = DriftDetector()
    ref = pd.Series([100.0, 100.5, 99.9])
    cur = pd.Series([115.0, 114.0, 115.5])
    rep = det.score(trial_id="DEMO", metric_name="kpi_latency", reference=ref, current=cur)
    assert rep.analysis_kind == "numeric_series"
    assert 0 <= rep.risk_score <= 100


def test_negative_risk_raises() -> None:
    """Guard rails must reject irrational inputs early."""

    with pytest.raises(ValueError):
        risk_level_from_score(-1)
