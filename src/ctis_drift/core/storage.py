"""SQLite persistence and historical CTIS trial snapshot storage via SQLModel.

This module provides:

- Drift evaluation rows (`drift_run`) for scoring history.
- Trial registry and content-addressed snapshots (`trials`, `snapshots`) suitable
  for drift alerts: each snapshot stores full JSON plus a SHA-256 hash of a
  canonical JSON encoding for reliable change detection.

SQLite connections use WAL journaling where applicable for safer concurrent
reads during Streamlit usage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from sqlalchemy import Index, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from ctis_drift.core.drift_detector import DriftReport
from ctis_drift.utils.logging import get_logger

logger = get_logger(__name__)

_JSON_SEPARATORS: Final[tuple[str, str]] = (",", ":")
_DEFAULT_HISTORY_LIMIT: Final[int] = 30
_DIFF_SAMPLE_LIMIT: Final[int] = 48


class DriftRunRecord(SQLModel, table=True):
    """Single persisted drift evaluation row."""

    __tablename__ = "drift_run"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trial_id: str = Field(index=True)
    metric_name: str = Field(index=True)
    drift_score: float
    method: str = Field(default="mean_shift_normalized")
    details_json: str | None = None


class TrialRecord(SQLModel, table=True):
    """Registry row for a CTIS EU CT number (trial identity).

    Denormalizes ``latest_content_hash`` so alerting and polling loops can skip
    full JSON comparisons when content is unchanged.
    """

    __tablename__ = "trials"

    euct_number: str = Field(primary_key=True, max_length=64, description="EU CT number")
    last_checked: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latest_content_hash: str | None = Field(default=None, max_length=64, index=True)

    __table_args__ = (
        Index("ix_trials_latest_hash_checked", "latest_content_hash", "last_checked"),
    )


class TrialSnapshotRecord(SQLModel, table=True):
    """Immutable snapshot of trial payload JSON at a point in time."""

    __tablename__ = "snapshots"

    id: int | None = Field(default=None, primary_key=True)
    euct_number: str = Field(
        foreign_key="trials.euct_number",
        max_length=64,
        index=True,
        description="EU CT number",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC instant when this snapshot was captured (stored as timezone-aware)",
    )
    data_hash: str = Field(max_length=64, index=True, description="SHA-256 hex of canonical JSON")
    raw_json: str = Field(description="Full snapshot JSON as stored")

    __table_args__ = (
        Index("ix_snapshots_euct_timestamp", "euct_number", "timestamp"),
        Index("ix_snapshots_euct_hash", "euct_number", "data_hash"),
    )


def normalize_json_bytes(data: Mapping[str, Any] | dict[str, Any]) -> bytes:
    """Return UTF-8 bytes of JSON with stable key order for hashing.

    Dict keys are sorted recursively. Values use ``default=str`` so unexpected
    objects remain deterministic for a given repr.

    Args:
        data: Trial payload (typically CTIS retrieve/search JSON).

    Returns:
        Canonical JSON encoded as UTF-8 without insignificant whitespace.
    """
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=_JSON_SEPARATORS,
        ensure_ascii=False,
        default=str,
    )
    return canonical.encode("utf-8")


def compute_json_sha256(data: Mapping[str, Any] | dict[str, Any]) -> str:
    """SHA-256 hex digest of :func:`normalize_json_bytes`."""
    return hashlib.sha256(normalize_json_bytes(data)).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotPersistResult:
    """Outcome of :meth:`StorageService.save_snapshot`."""

    euct_number: str
    content_hash: str
    persisted_new_row: bool
    snapshot_id: int | None
    snapshot_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class SnapshotDiffSummary:
    """Human- and machine-friendly summary for alerting pipelines."""

    previous_hash: str | None
    new_hash: str
    previous_timestamp: datetime | None
    keys_added: tuple[str, ...]
    keys_removed: tuple[str, ...]
    keys_modified: tuple[str, ...]
    nested_change_count: int
    notes: str


@dataclass(frozen=True, slots=True)
class ChangeDetectionResult:
    """Result of :meth:`StorageService.has_changed`."""

    changed: bool
    summary: SnapshotDiffSummary


def _sqlite_connect_pragma(dbapi_conn: Any, _: Any) -> None:
    """Enable WAL and a sensible synchronous trade-off for local SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


class StorageService:
    """Database engine lifecycle, drift runs, and trial snapshot storage."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._ensure_sqlite_parent_dir(database_url)
        self._engine = self._create_engine(database_url)

    @staticmethod
    def _create_engine(database_url: str) -> Engine:
        connect_args: dict[str, bool] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        engine = create_engine(database_url, connect_args=connect_args, echo=False, future=True)
        if database_url.startswith("sqlite"):
            event.listen(engine, "connect", _sqlite_connect_pragma)
        return engine

    @staticmethod
    def _ensure_sqlite_parent_dir(database_url: str) -> None:
        url = make_url(database_url)
        if url.drivername != "sqlite":
            return
        database_path = url.database
        if not database_path or database_path == ":memory:":
            return
        path = Path(database_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        """Create all registered tables and indexes if they do not exist."""
        SQLModel.metadata.create_all(self._engine)
        logger.info("Database initialized: %s", self._database_url)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self._engine) as session:
            yield session

    def save_report(self, report: DriftReport) -> DriftRunRecord:
        record = DriftRunRecord(
            trial_id=report.trial_id,
            metric_name=report.metric_name,
            drift_score=report.drift_score,
            method=report.method,
            details_json=json.dumps(
            report.model_dump(mode="json"),
            sort_keys=True,
            default=str,
        ),
        )
        with self.session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
        return record

    def recent_runs(self, *, limit: int = 100) -> list[DriftRunRecord]:
        stmt = select(DriftRunRecord).order_by(col(DriftRunRecord.created_at).desc()).limit(limit)
        with self.session() as session:
            rows = session.exec(stmt).all()
        return list(rows)

    # --- Trial snapshots -------------------------------------------------

    def save_snapshot(
        self,
        euct_number: str,
        data: Mapping[str, Any],
        *,
        skip_duplicate_hash: bool = True,
        captured_at: datetime | None = None,
    ) -> SnapshotPersistResult:
        """Persist a trial JSON snapshot and update trial registry metadata.

        Computes SHA-256 over canonical JSON (:func:`compute_json_sha256`).
        When ``skip_duplicate_hash`` is True and the latest stored hash matches,
        no new ``snapshots`` row is inserted (trial ``last_checked`` still updates).

        Args:
            euct_number: EU CT number identifying the trial.
            data: Payload dict (e.g. CTIS retrieve response body).
            skip_duplicate_hash: If True, omit inserting identical consecutive snapshots.
            captured_at: Optional explicit UTC timestamp; defaults to "now".

        Returns:
            Metadata describing whether a new row was written.
        """
        key = euct_number.strip()
        if not key:
            msg = "euct_number must be non-empty"
            raise ValueError(msg)

        content_hash = compute_json_sha256(dict(data))
        raw_json = normalize_json_bytes(dict(data)).decode("utf-8")
        ts = captured_at or datetime.now(UTC)

        with self.session() as session:
            trial = session.get(TrialRecord, key)
            now = datetime.now(UTC)
            if trial is None:
                trial = TrialRecord(
                    euct_number=key,
                    last_checked=now,
                    first_seen_at=now,
                    latest_content_hash=content_hash,
                )
                session.add(trial)
            else:
                trial.last_checked = now
                trial.latest_content_hash = content_hash

            latest_row = self._select_latest_snapshot(session, key)
            duplicate = (
                skip_duplicate_hash
                and latest_row is not None
                and latest_row.data_hash == content_hash
            )
            if duplicate:
                session.commit()
                return SnapshotPersistResult(
                    euct_number=key,
                    content_hash=content_hash,
                    persisted_new_row=False,
                    snapshot_id=None,
                    snapshot_timestamp=None,
                )

            snap = TrialSnapshotRecord(
                euct_number=key,
                timestamp=ts,
                data_hash=content_hash,
                raw_json=raw_json,
            )
            session.add(snap)
            session.commit()
            session.refresh(snap)
            return SnapshotPersistResult(
                euct_number=key,
                content_hash=content_hash,
                persisted_new_row=True,
                snapshot_id=snap.id,
                snapshot_timestamp=snap.timestamp,
            )

    def get_latest_snapshot(self, euct_number: str) -> dict[str, Any] | None:
        """Return the most recent snapshot payload for ``euct_number``, if any.

        Args:
            euct_number: Trial identifier.

        Returns:
            Parsed JSON dict from ``raw_json``, or ``None`` when unknown.
        """
        key = euct_number.strip()
        if not key:
            return None
        with self.session() as session:
            row = self._select_latest_snapshot(session, key)
            if row is None:
                return None
            return cast(dict[str, Any], json.loads(row.raw_json))

    def get_latest_snapshot_record(self, euct_number: str) -> TrialSnapshotRecord | None:
        """Return the latest :class:`TrialSnapshotRecord` row (includes hash and timestamp)."""
        key = euct_number.strip()
        if not key:
            return None
        with self.session() as session:
            return self._select_latest_snapshot(session, key)

    def get_history(
        self,
        euct_number: str,
        *,
        limit: int = _DEFAULT_HISTORY_LIMIT,
    ) -> list[TrialSnapshotRecord]:
        """Return recent snapshots newest-first (bounded by ``limit``).

        Args:
            euct_number: Trial identifier.
            limit: Maximum rows (default 30).

        Returns:
            Snapshot rows ordered by ``timestamp`` descending.
        """
        key = euct_number.strip()
        if not key:
            return []
        lim = max(1, min(limit, 10_000))
        stmt = (
            select(TrialSnapshotRecord)
            .where(col(TrialSnapshotRecord.euct_number) == key)
            .order_by(col(TrialSnapshotRecord.timestamp).desc())
            .limit(lim)
        )
        with self.session() as session:
            rows = session.exec(stmt).all()
        return list(rows)

    def has_changed(self, euct_number: str, new_data: Mapping[str, Any]) -> ChangeDetectionResult:
        """Compare ``new_data`` to the latest snapshot using content hash and structural diff.

        Hash comparison is O(1) relative to payload size once the latest row is loaded.
        Structural diff walks nested dict/list structures up to sampling limits.

        Args:
            euct_number: Trial identifier.
            new_data: Candidate payload.

        Returns:
            Whether content differs from latest snapshot plus a concise diff summary.
        """
        key = euct_number.strip()
        new_hash = compute_json_sha256(dict(new_data))

        if not key:
            summary = SnapshotDiffSummary(
                previous_hash=None,
                new_hash=new_hash,
                previous_timestamp=None,
                keys_added=tuple(),
                keys_removed=tuple(),
                keys_modified=tuple(),
                nested_change_count=0,
                notes="Invalid empty euct_number; treated as changed.",
            )
            return ChangeDetectionResult(changed=True, summary=summary)

        with self.session() as session:
            latest = self._select_latest_snapshot(session, key)

        if latest is None:
            summary = SnapshotDiffSummary(
                previous_hash=None,
                new_hash=new_hash,
                previous_timestamp=None,
                keys_added=tuple(sorted(dict(new_data).keys())),
                keys_removed=tuple(),
                keys_modified=tuple(),
                nested_change_count=0,
                notes="No stored baseline snapshot.",
            )
            return ChangeDetectionResult(changed=True, summary=summary)

        if latest.data_hash == new_hash:
            summary = SnapshotDiffSummary(
                previous_hash=latest.data_hash,
                new_hash=new_hash,
                previous_timestamp=latest.timestamp,
                keys_added=tuple(),
                keys_removed=tuple(),
                keys_modified=tuple(),
                nested_change_count=0,
                notes="Content hash matches latest snapshot.",
            )
            return ChangeDetectionResult(changed=False, summary=summary)

        previous = cast(dict[str, Any], json.loads(latest.raw_json))
        added, removed, modified, nested = _summarize_mapping_diff(previous, dict(new_data))
        summary = SnapshotDiffSummary(
            previous_hash=latest.data_hash,
            new_hash=new_hash,
            previous_timestamp=latest.timestamp,
            keys_added=tuple(added),
            keys_removed=tuple(removed),
            keys_modified=tuple(modified),
            nested_change_count=nested,
            notes="Payload differs from latest snapshot.",
        )
        return ChangeDetectionResult(changed=True, summary=summary)

    @staticmethod
    def _select_latest_snapshot(session: Session, euct_number: str) -> TrialSnapshotRecord | None:
        stmt = (
            select(TrialSnapshotRecord)
            .where(col(TrialSnapshotRecord.euct_number) == euct_number)
            .order_by(col(TrialSnapshotRecord.timestamp).desc())
            .limit(1)
        )
        return session.exec(stmt).first()


def _summarize_mapping_diff(
    old: Any,
    new: Any,
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 12,
) -> tuple[list[str], list[str], list[str], int]:
    """Collect shallow key paths and nested change counts between JSON-like trees."""
    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []
    nested = 0

    if depth > max_depth:
        nested += 1
        return added, removed, modified, nested

    if isinstance(old, Mapping) and isinstance(new, Mapping):
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        for k in sorted(new_keys - old_keys, key=str):
            path = f"{prefix}.{k}" if prefix else str(k)
            if len(added) < _DIFF_SAMPLE_LIMIT:
                added.append(path)
        for k in sorted(old_keys - new_keys, key=str):
            path = f"{prefix}.{k}" if prefix else str(k)
            if len(removed) < _DIFF_SAMPLE_LIMIT:
                removed.append(path)
        for k in sorted(old_keys & new_keys, key=str):
            path = f"{prefix}.{k}" if prefix else str(k)
            ov, nv = old[k], new[k]
            if ov == nv:
                continue
            if isinstance(ov, Mapping) and isinstance(nv, Mapping):
                sub_added, sub_removed, sub_modified, sub_nested = _summarize_mapping_diff(
                    ov,
                    nv,
                    prefix=path,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
                nested += sub_nested
                if sub_added or sub_removed or sub_modified:
                    nested += 1
                    if len(modified) < _DIFF_SAMPLE_LIMIT:
                        modified.append(path)
                elif sub_nested == 0 and ov != nv:
                    if len(modified) < _DIFF_SAMPLE_LIMIT:
                        modified.append(path)
                continue
            if isinstance(ov, list) and isinstance(nv, list):
                if ov != nv:
                    nested += 1
                    if len(modified) < _DIFF_SAMPLE_LIMIT:
                        modified.append(path)
                continue
            nested += 1
            if len(modified) < _DIFF_SAMPLE_LIMIT:
                modified.append(path)
        return added, removed, modified, nested

    if old != new:
        nested += 1
        if prefix and len(modified) < _DIFF_SAMPLE_LIMIT:
            modified.append(prefix)

    return added, removed, modified, nested
