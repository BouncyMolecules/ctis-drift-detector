"""Regulatory-facing CTIS drift analysis and orthogonal numeric drift scoring.

This module is the domain layer for detecting and classifying substantive changes in
clinical-trial artefacts exposed via CTIS (status, documents, timelines, regulator
signals, sponsor metadata, etc.). It stays free of persistence and UI concerns while
delegating cryptographic content addressing to :mod:`ctis_drift.core.storage`'s JSON
canonicalization helpers (lazy-imported where needed to avoid import cycles).

**Architecture**

The design follows Clean Architecture boundaries:

- Pure value objects and deterministic algorithms live at module scope (risk mapping,
  path categorisation, deep diff sampling, summaries). These functions are trivially
  unit-testable without a database or Streamlit runtime.
- :class:`DriftDetector` composes orchestration helpers that bridge optional
  infrastructure services (:class:`~ctis_drift.core.storage.StorageService`) behind
  explicit façade methods rather than silently importing globals.
- The risk engine is declarative weights + deterministic rule contributions gathered
  into :class:`DriftReport` for audit reproducibility while remaining extensible via
  callables plugged into each :class:`DriftDetector` instance.

Typical ingestion flow:

#. Acquire previous and candidate JSON payloads from
   :class:`~ctis_drift.core.storage.StorageService` or transports.
#. Call :func:`build_regulatory_report` with prior knowledge of hashes/baselines
   — or :meth:`DriftDetector.evaluate_with_storage` for an end‑to‑end comparison.
#. Persist/export the emitted :class:`DriftReport` (see :func:`report_to_json`).

Separate from CTIS artefacts, numeric series drift (:meth:`DriftDetector.score_numeric_series`)
keeps backwards compatibility with exploratory analytics without diluting regulator-grade
trial snapshot terminology.
"""  # noqa: W505 - module doc length justified for auditors

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Final, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from ctis_drift.core.storage import StorageService

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from ctis_drift.utils.helpers import clamp
from ctis_drift.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_DELTA_VALUES: Final[int] = 512
_MAX_SUMMARY_CHARS: Final[int] = 3_600
_MAX_VALUE_REPR_CHARS: Final[int] = 512
_DIFF_MAX_DEPTH_DEFAULT: Final[int] = 12

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonLeaf: TypeAlias = JsonPrimitive


class RiskLevel(StrEnum):
    """Discrete exposure bands used for alerting and escalation routing."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeCategory(StrEnum):
    """High-level ontology for interpreting field-level deltas."""

    STATUS = "status"
    RFI_AND_QUERIES = "rfi_and_queries"
    DOCUMENT_CORPUS = "document_corpus"
    MILESTONE_AND_TIMELINE = "milestone_and_timeline"
    SAFETY_AND_PHARMACOVIGILANCE = "safety_and_pharmacovigilance"
    REGULATORY_ENGAGEMENT = "regulatory_engagement"
    SPONSOR_AND_SITE = "sponsor_and_site"
    GENERAL_METADATA = "general_metadata"


class RuleContribution(BaseModel):
    """One auditable additive component of aggregate risk."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Annotated[str, Field(min_length=1, description="Stable identifier for auditors.")]
    points: Annotated[int, Field(ge=0)]
    rationale: Annotated[str, Field(min_length=1)]


class RiskBandThresholds(BaseModel):
    """Inclusive upper bounds ascending from LOW."""

    model_config = ConfigDict(frozen=True)

    low_upper_inclusive: int = Field(ge=0, le=100, default=24)
    medium_upper_inclusive: int = Field(ge=0, le=100, default=49)
    high_upper_inclusive: int = Field(ge=0, le=100, default=79)

    @model_validator(mode="after")
    def thresholds_strictly_ordered(self) -> RiskBandThresholds:
        """Guarantee strictly increasing breakpoints ``LOW < MEDIUM < HIGH < CRITICAL``."""

        if not (
            self.low_upper_inclusive < self.medium_upper_inclusive < self.high_upper_inclusive < 100
        ):
            msg = "thresholds must satisfy low < medium < high < 100"
            raise ValueError(msg)
        return self


class CategoryWeightPack(BaseModel):
    """Configurable multipliers keyed by ontology membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: int = Field(ge=0, default=42)
    rfi_and_queries: int = Field(ge=0, default=35)
    document_corpus: int = Field(ge=0, default=24)
    milestone_and_timeline: int = Field(ge=0, default=20)
    safety_and_pharmacovigilance: int = Field(ge=0, default=40)
    regulatory_engagement: int = Field(ge=0, default=26)
    sponsor_and_site: int = Field(ge=0, default=16)
    general_metadata: int = Field(ge=0, default=12)


class StructuralWeightPack(BaseModel):
    """Costs for breadth of JSON structural churn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_added_path: float = Field(ge=0.0, default=2.1)
    per_removed_path: float = Field(ge=0.0, default=2.4)
    per_nested_event: float = Field(ge=0.0, default=1.4)
    structural_cap_points: int = Field(ge=0, default=48)


class FreshBaselinePolicy(BaseModel):
    """Govern first-seen payload behaviour."""

    model_config = ConfigDict(frozen=True)

    acknowledgement_points: int = Field(ge=0, le=100, default=12)
    include_structural_bonus: bool = Field(default=False)


class RegulatoryDriftConfig(BaseModel):
    """Central configuration for ontology matching and scoring."""

    category_keywords: Mapping[ChangeCategory, tuple[str, ...]] = Field(
        default_factory=lambda: {
            ChangeCategory.STATUS: (
                "ctstatus",
                "publicstatus",
                "decision",
                "status",
                "ctpublicstatuscode",
                "mscstatus",
            ),
            ChangeCategory.RFI_AND_QUERIES: (
                "rfi",
                "requestforinformation",
                "informationrequest",
                "query",
                "queries",
                "clarification",
            ),
            ChangeCategory.DOCUMENT_CORPUS: (
                "document",
                "authorizedapplication",
                "protocol",
                "csr",
                "annex",
                "submission",
                "smpc",
                "label",
                "coverletter",
                "attachment",
                "investigator",
            ),
            ChangeCategory.MILESTONE_AND_TIMELINE: (
                "milestone",
                "timeline",
                "deadline",
                "startdate",
                "enddate",
                "estimated",
                "recruitment",
                "enrollment",
                "overall",
                "firstpatient",
                "lastvisit",
                "trialphase",
            ),
            ChangeCategory.SAFETY_AND_PHARMACOVIGILANCE: (
                "safety",
                "unexpected",
                "seriousbreach",
                "urgentsafetymeasure",
                "adverse",
                "pv",
                "pharmacovigilance",
                "signal",
                "dsur",
                "deviation",
                "breach",
            ),
            ChangeCategory.REGULATORY_ENGAGEMENT: (
                "rms",
                "ethics",
                "competentauthority",
                "memberstate",
                "reference",
                "inspection",
                "regulator",
                "committee",
                "assessmentreport",
                "evaluation",
                "msc",
                "eea",
                "ca",
                "ethic",
                "irb",
                "ec",
                "eec",
                "rec",
                "ethicscommittee",
                "compassionateuse",
                "riskmanagement",
                "rmp",
            ),
            ChangeCategory.SPONSOR_AND_SITE: (
                "sponsor",
                "organisation",
                "organization",
                "site",
                "cro",
                "contact",
                "country",
                "location",
                "thirdparty",
            ),
            ChangeCategory.GENERAL_METADATA: (
                "title",
                "trial",
                "condition",
                "population",
                "product",
                "imp",
                "auxiliary",
                "comparator",
                "identifier",
                "number",
                "medicalcondition",
                "therapy",
            ),
        }
    )

    categorical_weights: CategoryWeightPack = Field(default_factory=CategoryWeightPack)
    structural_weights: StructuralWeightPack = Field(default_factory=StructuralWeightPack)
    risk_band_thresholds: RiskBandThresholds = Field(default_factory=RiskBandThresholds)
    freshness_policy: FreshBaselinePolicy = Field(default_factory=FreshBaselinePolicy)

    categorical_repeat_penalty_denominator: int = Field(
        ge=1,
        default=3,
        description="Divide repeated category occurrences by this factor after the first.",
    )

    duplicate_hash_needs_attention: float = Field(
        default=18.0,
        ge=0.0,
        description=(
            "Reserved operational uplift when payloads differ materially despite matching digests "
            "(extremely unlikely with SHA‑256)."
        ),
    )

    diff_max_depth: int = Field(default=_DIFF_MAX_DEPTH_DEFAULT, ge=2, le=32)

    allow_hash_mismatch: bool = Field(
        default=False,
        description="Permit callers to supply fingerprints that mismatch lazy recomputation.",
    )


class SeriesDriftConfig(BaseModel):
    """Configuration for exploratory numeric-series drift."""

    epsilon: float = Field(default=1e-9, gt=0.0)


class StructuralDiffSummary(BaseModel):
    """Top-level envelope mirroring hashed snapshot comparisons."""

    model_config = ConfigDict(frozen=True)

    previous_content_hash: str | None
    current_content_hash: str
    previous_snapshot_at: datetime | None = None
    keys_added_sample: tuple[str, ...] = ()
    keys_removed_sample: tuple[str, ...] = ()
    keys_modified_sample: tuple[str, ...] = ()
    nested_change_count: int = Field(ge=0, default=0)
    ingest_notes: str = Field(default="")


class ChangedField(BaseModel):
    """Field-level artefact surfaced to alerting channels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    category: ChangeCategory
    previous_value_repr: str | None = Field(default=None, description="None when introduced.")
    current_value_repr: str | None = Field(default=None, description="None when removed.")


class DetailedDiff(BaseModel):
    """Unified machine + human artefacts describing change shape."""

    model_config = ConfigDict(frozen=True)

    structural: StructuralDiffSummary
    changed_fields: tuple[ChangedField, ...]
    numeric_series: Mapping[str, float] | None = None


class DriftReport(BaseModel):
    """Authoritative persisted drift artefact bridging SQL + Streamlit widgets."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    trial_id: str = Field(min_length=1)
    metric_name: str = Field(default="trial_snapshot")
    analysis_kind: str = Field(
        default="regulatory_snapshot",
        description="Semantic discriminator for mixed analytics.",
    )

    changed: bool
    risk_score: Annotated[int, Field(ge=0, le=100)]
    risk_level: RiskLevel
    human_readable_summary: Annotated[str, Field(min_length=1, max_length=16_384)]
    detailed_diff: DetailedDiff
    changed_fields: tuple[ChangedField, ...]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    contributions: tuple[RuleContribution, ...] = ()

    method: str = Field(
        default="regulatory_snapshot_v1",
        min_length=1,
        description="Propagated to persisted drift_run rows.",
    )

    ingest_context: Mapping[str, Any] | None = Field(
        default=None,
        description=(
            "Optional caller metadata (runner id, correlation id...). Not validated strictly."
        ),
    )

    @computed_field(return_type=float)  # type: ignore[prop-decorator]
    @property
    def drift_score(self) -> float:
        """Normalised analogue for backwards-compatible analytics charts."""

        return self.risk_score / 100.0

    @property
    def details(self) -> dict[str, Any]:
        """Legacy accessor mirroring unstructured ``details_json`` payloads."""

        return {"report": self.model_dump(mode="json")}

    @field_validator("trial_id", "metric_name", "human_readable_summary", mode="before")
    @classmethod
    def strip_space(cls, v: Any) -> Any:
        if isinstance(v, str):
            trimmed = v.strip()
            if not trimmed:
                raise ValueError("text fields must remain non-empty after stripping")
            return trimmed
        return v


class _LeafDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    previous: Any
    current: Any


@runtime_checkable
class ContributionRuleHook(Protocol):
    """Plug-in boundary for customised regulatory policies."""

    def __call__(
        self,
        *,
        changed_fields: Sequence[ChangedField],
        structural: StructuralDiffSummary,
        trial_id: str,
        config: RegulatoryDriftConfig,
    ) -> Iterable[RuleContribution]: ...


class DriftDetectorConfig(BaseModel):
    """Aggregate constructor configuration."""

    regulatory: RegulatoryDriftConfig = Field(default_factory=RegulatoryDriftConfig)
    numeric: SeriesDriftConfig = Field(default_factory=SeriesDriftConfig)


def risk_level_from_score(score: int, thresholds: RiskBandThresholds | None = None) -> RiskLevel:
    """Map monotone ``score`` to :class:`RiskLevel` buckets.

    Args:
        score: Integer risk mass in ``[0, 100]``.
        thresholds: Optional override; defaults to production baseline.

    Returns:
        Mapped enumeration member.

    Raises:
        ValueError: If ``score`` is outside numeric bounds after sanitisation attempts.
    """

    bounds = thresholds or RiskBandThresholds()
    if score < 0 or score > 100:
        msg = "score must be within 0..100 inclusive"
        raise ValueError(msg)
    if score <= bounds.low_upper_inclusive:
        return RiskLevel.LOW
    if score <= bounds.medium_upper_inclusive:
        return RiskLevel.MEDIUM
    if score <= bounds.high_upper_inclusive:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def snapshot_content_hash(payload: Mapping[str, Any]) -> str:
    """Compute SHA‑256 fingerprint using persistence canonical encoding.

    The helper performs a deferred import so :mod:`~ctis_drift.core.storage`
    stays free while this module initializes.

    Args:
        payload: Mapping suitable for canonical JSON hashing.

    Returns:
        Hex digest identical to rows stored via :class:`~ctis_drift.core.storage.StorageService`.
    """

    from ctis_drift.core.storage import compute_json_sha256  # noqa: PLC0415 avoid cycle

    return compute_json_sha256(dict(payload))


def categorize_path_component(path: str, config: RegulatoryDriftConfig) -> ChangeCategory:
    """Assign ``path`` to the highest-signal ontology label.

    Args:
        path: Dot-separated JSON pointer fragment as produced by drift walking.
        config: Keyword dictionary describing regulatory categories.

    Returns:
        Resolved :class:`ChangeCategory`; defaults to GENERAL_METADATA when ambiguous.
    """

    normalised = path.lower().replace("`", "").replace(" ", "")
    scoring: list[tuple[ChangeCategory, int]] = []

    tokens = re.findall(r"[A-Za-z0-9]{3,}", normalised)

    haystack_parts = "".join(tokens)
    for category, needles in config.category_keywords.items():
        hits = sum(1 for needle in needles if needle in haystack_parts or needle in normalised)
        if hits > 0:
            scoring.append((category, hits))

    if not scoring:
        return ChangeCategory.GENERAL_METADATA

    scoring.sort(key=lambda kv: kv[1], reverse=True)
    dominant = scoring[0]
    runner = scoring[1] if len(scoring) > 1 else (ChangeCategory.GENERAL_METADATA, 0)
    if dominant[1] == runner[1] and dominant[0] != runner[0]:
        logger.debug(
            "Ambiguous path categorisation fallback for %s (ties between %s and %s)",
            path,
            dominant[0].value,
            runner[0].value,
        )
        return ChangeCategory.GENERAL_METADATA
    logger.debug("Path %s resolved to category %s", path, dominant[0].value)
    return dominant[0]


def _coerce_primitive(value: Any) -> tuple[bool, JsonLeaf]:
    """Return ``(is_primitive, interpreted)`` for leaf representations."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return True, value
    if isinstance(value, (bytes, bytearray)):
        decoded = bytes(value).decode("utf-8", errors="replace")
        return True, decoded
    return False, None


def repr_json_value(value: Any, *, limit: int = _MAX_VALUE_REPR_CHARS) -> str | None:
    """Render truncated JSON-ish text stable for auditors."""

    is_primitive, prim = _coerce_primitive(value)
    if is_primitive:
        blob = json.dumps(prim, ensure_ascii=False, sort_keys=True, default=str)
    else:
        blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    blob = blob if len(blob) <= limit else f"{blob[: limit - 1]}…"

    logger.debug(
        "Serialised artefact snippet len=%s is_truncated=%s",
        len(blob),
        blob.endswith("…"),
    )
    return blob


def summarise_structural_keys(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    *,
    max_samples: int = 48,
) -> tuple[list[str], list[str], list[str], int]:
    """Compute shallow-ish diff mirroring SQLite helper semantics.

    This intentionally stays aligned with :func:`~ctis_drift.core.storage._summarize_mapping_diff`
    to keep hash-gated summaries and granular scoring coherent.

    Args:
        old: Baseline dictionary.
        new: Candidate dictionary.
        max_samples: Soft cap guarding UI explosion.

    Returns:
        Quadruple listing added paths, removed paths, modified parent paths, nested events.
    """

    from ctis_drift.core.storage import _summarize_mapping_diff  # noqa: PLC0415

    added_raw, removed_raw, modified_raw, nested = _summarize_mapping_diff(
        dict(old),
        dict(new),
    )
    return (
        added_raw[:max_samples],
        removed_raw[:max_samples],
        modified_raw[:max_samples],
        nested,
    )


def collect_leaf_deltas(
    old: Mapping[str, Any] | dict[str, Any],
    new: Mapping[str, Any] | dict[str, Any],
    *,
    cfg: RegulatoryDriftConfig,
) -> tuple[_LeafDelta, ...]:
    """Enumerate representative leaf deltas for scoring.

    Args:
        old: Baseline nested JSON.
        new: Candidate nested JSON.
        cfg: Depth guardrail host.

    Returns:
        Frozen sequence bounded by operational limits.
    """

    buffer: list[_LeafDelta] = []

    def inner(
        left: Any,
        right: Any,
        *,
        prefix: str,
        depth: int,
    ) -> None:
        if len(buffer) >= _MAX_DELTA_VALUES:
            logger.warning("Leaf drift sampling truncated at path prefix %s", prefix or "$")
            return
        max_depth_local = cfg.diff_max_depth
        if depth > max_depth_local:
            buffer.append(_LeafDelta(path=prefix or "$", previous=left, current=right))
            return

        if left == right:
            return

        if isinstance(left, Mapping) and isinstance(right, Mapping):
            left_keys = set(left.keys())
            right_keys = set(right.keys())

            for key in sorted(right_keys - left_keys, key=str):
                candidate_path = f"{prefix}.{key}" if prefix else str(key)
                inner(None, right[key], prefix=candidate_path, depth=depth + 1)
                if len(buffer) >= _MAX_DELTA_VALUES:
                    return

            for key in sorted(left_keys - right_keys, key=str):
                candidate_path = f"{prefix}.{key}" if prefix else str(key)
                inner(left[key], None, prefix=candidate_path, depth=depth + 1)
                if len(buffer) >= _MAX_DELTA_VALUES:
                    return

            for key in sorted(left_keys & right_keys, key=str):
                candidate_path = f"{prefix}.{key}" if prefix else str(key)
                inner(left[key], right[key], prefix=candidate_path, depth=depth + 1)
                if len(buffer) >= _MAX_DELTA_VALUES:
                    return

            return

        if isinstance(left, list) and isinstance(right, list):
            if left != right:
                buffer.append(_LeafDelta(path=prefix or "$", previous=left, current=right))
            return

        buffer.append(_LeafDelta(path=prefix or "$", previous=left, current=right))

    inner(dict(old), dict(new), prefix="", depth=0)
    return tuple(buffer)


def build_changed_fields(
    deltas: Sequence[_LeafDelta],
    *,
    cfg: RegulatoryDriftConfig,
) -> tuple[ChangedField, ...]:
    """Convert raw comparisons into categorised artefacts."""

    fields = []
    for delta in deltas:
        category = categorize_path_component(delta.path, cfg)
        fields.append(
            ChangedField(
                path=delta.path,
                category=category,
                previous_value_repr=None
                if delta.previous is None
                else repr_json_value(delta.previous),
                current_value_repr=None
                if delta.current is None
                else repr_json_value(delta.current),
            ),
        )

    dedup_seen: dict[str, ChangedField] = {}
    for field in sorted(fields, key=lambda f: (f.category.value, f.path)):
        dedup_seen[f"{field.path}|{field.category.value}"] = field
    logger.debug(
        "Produced %s unique categorised deltas from %s raw leaves",
        len(dedup_seen),
        len(deltas),
    )
    return tuple(dedup_seen.values())


def _apply_structural_scoring(
    structural: StructuralDiffSummary,
    weights: StructuralWeightPack,
) -> tuple[int, RuleContribution]:
    """Translate structural summaries into bounded mass."""

    added = len(structural.keys_added_sample)
    removed_len = len(structural.keys_removed_sample)
    nested = max(0, structural.nested_change_count)
    if added == 0 and removed_len == 0 and nested == 0:
        return 0, RuleContribution(
            rule_id="structural_stable",
            points=0,
            rationale="No sampled structural deltas vs baseline.",
        )

    added_cost = weights.per_added_path * added
    removed_cost = weights.per_removed_path * removed_len
    nested_cost = weights.per_nested_event * nested
    capped = clamp(
        added_cost + removed_cost + nested_cost,
        0.0,
        float(weights.structural_cap_points),
    )
    points = int(round(capped))

    contrib = RuleContribution(
        rule_id="structural_breadth",
        points=points,
        rationale=(
            f"Agglomerates sampled JSON churn "
            f"(+{added} / −{removed_len} top-level-ish paths, {nested} nested events)."
        ),
    )
    return points, contrib


def _aggregate_categorical_mass(
    fields: Sequence[ChangedField],
    *,
    weights: CategoryWeightPack,
    penalty_denominator: int,
) -> tuple[int, list[RuleContribution]]:
    """Weighted scoring with diminishing returns on repeated ontology hits."""

    if not fields:
        return 0, []

    tally = Counter(fc.category for fc in fields)
    total_points = 0
    contrib: list[RuleContribution] = []

    lookup: dict[ChangeCategory, int] = {
        ChangeCategory.STATUS: weights.status,
        ChangeCategory.RFI_AND_QUERIES: weights.rfi_and_queries,
        ChangeCategory.DOCUMENT_CORPUS: weights.document_corpus,
        ChangeCategory.MILESTONE_AND_TIMELINE: weights.milestone_and_timeline,
        ChangeCategory.SAFETY_AND_PHARMACOVIGILANCE: weights.safety_and_pharmacovigilance,
        ChangeCategory.REGULATORY_ENGAGEMENT: weights.regulatory_engagement,
        ChangeCategory.SPONSOR_AND_SITE: weights.sponsor_and_site,
        ChangeCategory.GENERAL_METADATA: weights.general_metadata,
    }

    for category, occurrences in tally.items():
        baseline = lookup.get(category, weights.general_metadata)
        mass: float = float(baseline)
        if occurrences > 1:
            extra = occurrences - 1
            diminishing = baseline * (extra / penalty_denominator)
            mass = float(baseline) + diminishing
            mass = clamp(mass, 0.0, float(baseline) * 1.75)

        pts = int(round(mass))
        total_points += pts
        contrib.append(
            RuleContribution(
                rule_id=f"category_mass::{category.value}",
                points=pts,
                rationale=f"{occurrences} observed field(s) tagged {category.value}.",
            ),
        )

    return total_points, contrib


def _safety_escalations(fields: Sequence[ChangedField]) -> list[RuleContribution]:
    """Guarantees floor adjustments when pharmacovigilance surfaces."""

    flagged = tuple(f for f in fields if f.category is ChangeCategory.SAFETY_AND_PHARMACOVIGILANCE)
    if not flagged:
        return []

    rationale = "; ".join(sorted({f.path.split(".")[-1] for f in flagged}))[:384]
    return [
        RuleContribution(
            rule_id="escalation::safety_signals",
            points=25,
            rationale=f"Elevated owing to pharmacovigilance-tagged paths ({rationale}).",
        ),
    ]


def _status_escalations(fields: Sequence[ChangedField]) -> list[RuleContribution]:
    """Detect explicit status ontology hits."""

    if any(f.category is ChangeCategory.STATUS for f in fields):
        return [
            RuleContribution(
                rule_id="escalation::trial_status_transition",
                points=22,
                rationale="Statuses drive submission posture; independent uplift applied.",
            ),
        ]
    return []


def score_regulatory_signals(
    structural: StructuralDiffSummary,
    fields: Sequence[ChangedField],
    *,
    cfg: RegulatoryDriftConfig,
    extras: Callable[..., Iterable[RuleContribution]] | None = None,
    trial_id: str = "",
) -> tuple[int, tuple[RuleContribution, ...]]:
    """Deterministic aggregator returning ``(score_0_100, contributions)``."""

    score = 0
    contrib: list[RuleContribution] = []

    structural_points, structural_note = _apply_structural_scoring(
        structural, cfg.structural_weights
    )
    score += structural_points
    contrib.append(structural_note)

    cat_mass, cats = _aggregate_categorical_mass(
        fields,
        weights=cfg.categorical_weights,
        penalty_denominator=cfg.categorical_repeat_penalty_denominator,
    )
    score += cat_mass
    contrib.extend(cats)

    for bump in (*_safety_escalations(fields), *_status_escalations(fields)):
        score += bump.points
        contrib.append(bump)

    if extras is not None:
        extra_iter = extras(
            changed_fields=list(fields),
            structural=structural,
            trial_id=trial_id,
            config=cfg,
        )
        converted = tuple(extra_iter)
        for item in converted:
            score += item.points
            contrib.append(item)

        logger.debug(
            "Custom hooks contributed %s additional rule rows for trial=%s",
            len(converted),
            trial_id,
        )

    if score >= 94:
        logger.warning(
            "CRITICAL-tier scoring observed for trial=%s (mass=%s) — escalate per SOP.",
            trial_id or "UNKNOWN",
            score,
        )

    clamped_score = int(round(clamp(score, 0.0, 100.0)))
    return clamped_score, tuple(contrib)


def build_human_readable_summary(
    *,
    trial_id: str,
    changed: bool,
    risk_level: RiskLevel,
    structural: StructuralDiffSummary,
    fields: Sequence[ChangedField],
    notes: Iterable[str],
) -> str:
    """Generate regulatory narrative respecting length safeguards."""

    if not changed:
        body = (
            f"Trial `{trial_id}` shows no cryptographic drift versus the persisted anchor "
            f"(hash `{structural.current_content_hash}`). Continue scheduled monitoring cadence."
        )
        stitched = body
        if len(stitched) > _MAX_SUMMARY_CHARS:
            return stitched[: _MAX_SUMMARY_CHARS - 1] + "…"
        return stitched

    preamble = (
        f"Detected substantive drift for `{trial_id}` yielding band `{risk_level.value}`. "
        f"Structural churn summary: `{structural.ingest_notes or 'Validated payload divergence'}`. "
    )

    high_signal = tuple(
        f"{f.category.value}:{f.path}" for f in sorted(fields, key=lambda x: x.path)[:8]
    )
    mid_section = ""
    if high_signal:
        mid_section = "Priority fields: " + "; ".join(high_signal) + ". "

    tail = "".join(note + " " for note in sorted(set(notes)) if note)

    appendix = ""
    hashes = ""
    if (
        structural.previous_content_hash
        and structural.previous_content_hash != structural.current_content_hash
    ):
        hashes = (
            f"Fingerprints transitioned from `{structural.previous_content_hash}` "
            f"→ `{structural.current_content_hash}`. "
        )

    appendix = hashes + structural.ingest_notes
    stitched = (preamble + mid_section + tail + appendix).strip()
    if len(stitched) > _MAX_SUMMARY_CHARS:
        logger.debug("Trimming human_readable_summary excess from %s characters", len(stitched))
        return stitched[: _MAX_SUMMARY_CHARS - 1] + "…"
    logger.info("Constructed summary for trial=%s len=%s", trial_id, len(stitched))
    return stitched


def build_regulatory_report(
    *,
    trial_id: str,
    baseline_payload: Mapping[str, Any] | None,
    candidate_payload: Mapping[str, Any],
    previous_content_hash: str | None,
    current_content_hash: str,
    ingest_notes: str,
    baseline_timestamp: datetime | None,
    detector_cfg: RegulatoryDriftConfig | None = None,
    extras: ContributionRuleHook | None = None,
    timestamp: datetime | None = None,
    ingest_context: Mapping[str, Any] | None = None,
    changed_explicit: bool | None = None,
) -> DriftReport:
    """Pure builder constructing :class:`DriftReport`.

    Args:
        trial_id: EU CT identifier.
        baseline_payload: Historical JSON (may be ``None`` for onboarding).
        candidate_payload: Newly polled JSON requiring evaluation.
        previous_content_hash: Optional baseline digest (checked lazily when provided).
        current_content_hash: Required digest aligning with persisted rows.
        ingest_notes: Operational hint (typically storage ``SnapshotDiffSummary.notes``).
        baseline_timestamp: Last observed snapshot UTC instant.
        detector_cfg: Overrides for ontology/risk knobs.
        extras: Optional supplementary rule functor.
        timestamp: Freeze instant for deterministic tests.
        ingest_context: Telemetry dict not interpreted here.
        changed_explicit: Bypass structural equality when hashing already adjudicated change.

    Returns:
        Hydrated immutable-in-practice pydantic artefact suitable for SQLite persistence.

    Raises:
        ValueError: When hashes contradict recomputation outside duplicate-hash safeguards.
    """

    cfg = detector_cfg or RegulatoryDriftConfig()
    ts_val = timestamp or datetime.now(UTC)

    recomputed_candidate = snapshot_content_hash(candidate_payload)
    if recomputed_candidate != current_content_hash and not cfg.allow_hash_mismatch:
        msg_candidate = (
            "current_content_hash does not match canonical SHA-256 of candidate_payload; "
            "enable RegulatoryDriftConfig.allow_hash_mismatch only for audited exceptions."
        )
        logger.warning("%s (trial=%s)", msg_candidate, trial_id)
        raise ValueError(msg_candidate)

    if baseline_payload is not None and previous_content_hash is not None:
        recomputed_baseline = snapshot_content_hash(dict(baseline_payload))
        if recomputed_baseline != previous_content_hash:
            logger.warning(
                "Baseline fingerprint mismatch recomputation for trial %s "
                "(expected historical digest alignment). Continuing with supplied hash.",
                trial_id,
            )

    if changed_explicit is False:
        structural = StructuralDiffSummary(
            previous_content_hash=previous_content_hash,
            current_content_hash=current_content_hash,
            previous_snapshot_at=baseline_timestamp,
            keys_added_sample=(),
            keys_removed_sample=(),
            keys_modified_sample=(),
            nested_change_count=0,
            ingest_notes=ingest_notes,
        )
        unchanged_diff = DetailedDiff(
            structural=structural,
            changed_fields=tuple(),
            numeric_series=None,
        )
        return DriftReport(
            trial_id=trial_id.strip(),
            changed=False,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            human_readable_summary=build_human_readable_summary(
                trial_id=trial_id.strip(),
                changed=False,
                risk_level=RiskLevel.LOW,
                structural=structural,
                fields=tuple(),
                notes=(
                    ingest_notes,
                    "Cryptographic fingerprints matched the stored anchor.",
                ),
            ),
            detailed_diff=unchanged_diff,
            changed_fields=tuple(),
            timestamp=ts_val,
            contributions=tuple(),
            ingest_context=dict(ingest_context or {}),
        )

    deltas = collect_leaf_deltas(
        baseline_payload if baseline_payload is not None else {},
        candidate_payload,
        cfg=cfg,
    )
    fields = build_changed_fields(deltas, cfg=cfg)

    added, removed, modified, nested = summarise_structural_keys(
        baseline_payload if baseline_payload is not None else {},
        dict(candidate_payload),
    )

    structural = StructuralDiffSummary(
        previous_content_hash=previous_content_hash,
        current_content_hash=current_content_hash,
        previous_snapshot_at=baseline_timestamp,
        keys_added_sample=tuple(added),
        keys_removed_sample=tuple(removed),
        keys_modified_sample=tuple(modified),
        nested_change_count=nested,
        ingest_notes=ingest_notes,
    )

    if changed_explicit is None:
        content_changed = bool(deltas) or bool(added or removed or modified or nested)
    else:
        content_changed = bool(changed_explicit)

    if not content_changed:
        unchanged_diff = DetailedDiff(
            structural=structural,
            changed_fields=tuple(),
            numeric_series=None,
        )
        return DriftReport(
            trial_id=trial_id.strip(),
            changed=False,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            human_readable_summary=build_human_readable_summary(
                trial_id=trial_id.strip(),
                changed=False,
                risk_level=RiskLevel.LOW,
                structural=structural,
                fields=tuple(),
                notes=(ingest_notes, "No sampled field-level deltas after structural walk."),
            ),
            detailed_diff=unchanged_diff,
            changed_fields=tuple(),
            timestamp=ts_val,
            contributions=tuple(),
            ingest_context=dict(ingest_context or {}),
        )

    new_baseline = baseline_payload is None

    aggregated_score, contrib = score_regulatory_signals(
        structural,
        fields,
        cfg=cfg,
        extras=callback_to_rule(extras),
        trial_id=trial_id,
    )

    if new_baseline and cfg.freshness_policy.include_structural_bonus:
        aggregated_score = min(
            100,
            aggregated_score + cfg.freshness_policy.acknowledgement_points,
        )
    elif new_baseline:
        aggregated_score = max(aggregated_score, cfg.freshness_policy.acknowledgement_points)

    level = risk_level_from_score(aggregated_score, cfg.risk_band_thresholds)

    detail = DetailedDiff(
        structural=structural,
        changed_fields=tuple(fields),
        numeric_series=None,
    )

    narrative_notes: list[str] = []
    if structural.ingest_notes:
        narrative_notes.extend(
            note.strip() for note in structural.ingest_notes.split(". ") if note.strip()
        )
    if new_baseline:
        narrative_notes.append("First persisted snapshot seeded the drift engine.")

    return DriftReport(
        trial_id=trial_id.strip(),
        metric_name="trial_snapshot",
        changed=True,
        risk_score=aggregated_score,
        risk_level=level,
        human_readable_summary=build_human_readable_summary(
            trial_id=trial_id.strip(),
            changed=True,
            risk_level=level,
            structural=structural,
            fields=fields,
            notes=narrative_notes,
        ),
        detailed_diff=detail,
        changed_fields=tuple(fields),
        timestamp=ts_val,
        contributions=contrib,
        ingest_context=dict(ingest_context or {}),
        method="regulatory_snapshot_v1",
    )


def callback_to_rule(
    hook: ContributionRuleHook | None,
) -> Callable[..., Iterable[RuleContribution]] | None:
    """Adapter wiring optional hooks into aggregator signature."""

    if hook is None:
        return None

    def wrapped(
        *,
        changed_fields: Sequence[ChangedField],
        structural: StructuralDiffSummary,
        trial_id: str,
        config: RegulatoryDriftConfig,
    ) -> Iterable[RuleContribution]:
        return hook(
            changed_fields=changed_fields,
            structural=structural,
            trial_id=trial_id,
            config=config,
        )

    return wrapped


class DriftDetector:
    """Facade exposing pure builders plus Thin integration with :class:`StorageService`.

    Instances are deliberately cheap; configuration is immutable Pydantic data passed
    at construction along with optional ``ContributionRuleHook`` delegates for bespoke
    evidence-weighting regimes.
    """

    def __init__(
        self,
        config: DriftDetectorConfig | None = None,
        *,
        extra_rules: ContributionRuleHook | None = None,
    ) -> None:
        detector_cfg_model = config or DriftDetectorConfig()
        self._reg_cfg = detector_cfg_model.regulatory
        self._series_cfg = detector_cfg_model.numeric
        self._extra_rules = extra_rules

        logger.debug(
            "Initialised drift detector thresholds low=%s med=%s high=%s extra_hook=%s",
            self._reg_cfg.risk_band_thresholds.low_upper_inclusive,
            self._reg_cfg.risk_band_thresholds.medium_upper_inclusive,
            self._reg_cfg.risk_band_thresholds.high_upper_inclusive,
            bool(extra_rules),
        )

    def evaluate_with_storage(
        self,
        storage: StorageService | Any,
        euct_number: str,
        candidate_payload: Mapping[str, Any],
    ) -> DriftReport:
        """Compare candidate JSON to persisted snapshots using hashing + SQLite diff helpers.

        The method trusts :meth:`StorageService.has_changed` for change arbitration but
        recomputes the candidate digest locally to guard against transport tampering prior
        to persistence.

        Args:
            storage: Live service instance exposing ``has_changed`` / ``get_latest_snapshot``.
            euct_number: EU CT identifier.
            candidate_payload: Fresh JSON dict from CTIS transports.

        Returns:
            Hydrated regulatory :class:`DriftReport`.

        Raises:
            TypeError: When ``storage`` lacks the operational contract expected.
            ValueError: When digest alignment fails unexpectedly.
        """

        from ctis_drift.core.storage import (
            StorageService as StorageServiceConcrete,  # noqa: PLC0415
        )

        if not isinstance(storage, StorageServiceConcrete):
            msg = "storage argument must be a StorageService implementation"
            raise TypeError(msg)

        key = euct_number.strip()
        if not key:
            msg = "euct_number must be non-blank after trimming"
            raise ValueError(msg)

        result = storage.has_changed(key, candidate_payload)
        baseline = storage.get_latest_snapshot(key)
        snapshot_meta = storage.get_latest_snapshot_record(key)
        baseline_instant = snapshot_meta.timestamp if snapshot_meta is not None else None

        digest_now = snapshot_content_hash(candidate_payload)
        digest_storage = getattr(result.summary, "new_hash", "")
        if digest_storage and digest_now != digest_storage:
            logger.warning(
                (
                    "StorageService summary hash mismatched local recomputation for %s "
                    "(local=%s storage=%s)."
                ),
                key,
                digest_now,
                digest_storage,
            )

        report = build_regulatory_report(
            trial_id=key,
            baseline_payload=baseline,
            candidate_payload=dict(candidate_payload),
            previous_content_hash=result.summary.previous_hash,
            current_content_hash=digest_now,
            ingest_notes=result.summary.notes,
            baseline_timestamp=baseline_instant,
            detector_cfg=self._reg_cfg,
            extras=self._extra_rules,
            changed_explicit=result.changed,
            ingest_context={
                "storage_has_changed_flag": result.changed,
                "summary_previous_hash": result.summary.previous_hash,
                "summary_new_hash": getattr(result.summary, "new_hash", None),
                "evaluation_engine": "StorageService.has_changed",
            },
        )

        logger.info(
            "Storage-backed drift ct=%s changed=%s score=%s level=%s",
            key,
            report.changed,
            report.risk_score,
            report.risk_level.value,
        )
        return report

    def score_numeric_series(
        self,
        *,
        trial_id: str,
        metric_name: str,
        reference: pd.Series,
        current: pd.Series,
    ) -> DriftReport:
        """Compute exploratory mean-shift drift for numeric exploratory analytics.

        This path intentionally bypasses cryptographic anchoring documented for CTIS payloads
        and should never substitute for regulated snapshot monitoring.

        Args:
            trial_id: Caller-provided analytic key (may be sandbox id).
            metric_name: Series label surfaced in dashboards and SQLite persistence.
            reference: Baseline pandas series.
            current: Comparative pandas series aligned by caller responsibility.

        Returns:
            Structured :class:`DriftReport` using ``analysis_kind=numeric_series``.

        Raises:
            ValueError: If either series lacks any numeric datapoints post coercion.
        """

        ref_series = pd.to_numeric(reference, errors="coerce").dropna()
        cur_series = pd.to_numeric(current, errors="coerce").dropna()
        if ref_series.empty or cur_series.empty:
            msg = "reference and current must contain at least one numeric value"
            raise ValueError(msg)

        ref_mean = float(ref_series.mean())
        cur_mean = float(cur_series.mean())
        denom = max(abs(ref_mean), self._series_cfg.epsilon)
        raw_shift = abs(cur_mean - ref_mean) / denom
        normalised_shift = clamp(float(1.0 - math.exp(-raw_shift)), 0.0, 1.0)
        drift_score_pct = int(round(normalised_shift * 100))

        structured = StructuralDiffSummary(
            previous_content_hash=None,
            current_content_hash="numeric-only",
            previous_snapshot_at=None,
            ingest_notes=(
                "NumericSeries drift uses statistical mean divergence (no cryptographic hashing)."
            ),
        )

        detail = DetailedDiff(
            structural=structured,
            changed_fields=tuple(),
            numeric_series={
                "n_reference": float(ref_series.shape[0]),
                "n_current": float(cur_series.shape[0]),
                "reference_mean": ref_mean,
                "current_mean": cur_mean,
                "raw_shift_ratio": raw_shift,
                "normalised_shift_unit_interval": normalised_shift,
            },
        )

        contribution = RuleContribution(
            rule_id="numeric_mean_shift_softmax",
            points=drift_score_pct,
            rationale="Diminishing returns mapping preserves interpretability.",
        )

        level = risk_level_from_score(drift_score_pct)
        narrative = (
            f"Measured numeric drift `{metric_name}` for `{trial_id}` with "
            f"mean-shift {raw_shift:.4f} ⇒ normalised `{normalised_shift:.4f}`."
        )

        report = DriftReport(
            trial_id=trial_id.strip(),
            metric_name=metric_name.strip(),
            analysis_kind="numeric_series",
            changed=normalised_shift > 1e-4,
            risk_score=drift_score_pct,
            risk_level=level,
            human_readable_summary=narrative,
            detailed_diff=detail,
            changed_fields=tuple(),
            timestamp=datetime.now(UTC),
            contributions=(contribution,),
            method="mean_shift_normalized",
        )

        logger.info(
            "Numeric drift computed trial=%s metric=%s risk=%s lvl=%s",
            report.trial_id,
            report.metric_name,
            report.risk_score,
            report.risk_level.value,
        )
        return report

    def score(
        self,
        *,
        trial_id: str,
        metric_name: str,
        reference: pd.Series,
        current: pd.Series,
    ) -> DriftReport:
        """Backwards-compatible alias for :meth:`score_numeric_series`."""

        return self.score_numeric_series(
            trial_id=trial_id,
            metric_name=metric_name,
            reference=reference,
            current=current,
        )

    @staticmethod
    def report_to_json(report: DriftReport) -> str:
        """Backward-compatible façade over :func:`report_to_json`."""

        return report_to_json(report)


def report_to_json(report: DriftReport) -> str:
    """JSON serialisation respecting stable ordering."""

    return json.dumps(report.model_dump(mode="json"), sort_keys=True, default=str)


__all__ = [
    "ChangeCategory",
    "ChangedField",
    "ContributionRuleHook",
    "DetailedDiff",
    "DriftDetector",
    "DriftDetectorConfig",
    "DriftReport",
    "RegulatoryDriftConfig",
    "RiskBandThresholds",
    "RiskLevel",
    "RuleContribution",
    "SeriesDriftConfig",
    "StructuralDiffSummary",
    "build_changed_fields",
    "build_human_readable_summary",
    "build_regulatory_report",
    "callback_to_rule",
    "collect_leaf_deltas",
    "categorize_path_component",
    "report_to_json",
    "risk_level_from_score",
    "score_regulatory_signals",
    "snapshot_content_hash",
    "summarise_structural_keys",
]
