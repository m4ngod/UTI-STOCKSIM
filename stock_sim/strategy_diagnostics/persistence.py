"""Versioned persistence baseline owned by the diagnostic product path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Final

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from .historical_segments import (
    HistoricalMarketSegment,
    HistoricalSegmentSelection,
    SegmentAdmissionReport,
    SourceProvenance,
    SourceSnapshot,
)


DIAGNOSTIC_SCHEMA_REVISION: Final = "0002_historical_segment_catalog"
_MIGRATION_TABLE: Final = "diagnostic_schema_migrations"
_MIGRATION_REVISIONS: Final = (
    "0001_diagnostics_baseline",
    DIAGNOSTIC_SCHEMA_REVISION,
)


@dataclass(frozen=True, slots=True)
class DiagnosticMigrationReport:
    current_revision: str
    applied_revisions: tuple[str, ...]


def initialize_diagnostic_persistence(engine: Engine) -> DiagnosticMigrationReport:
    """Apply diagnostic-only migrations without touching legacy metadata."""

    applied_revisions: list[str] = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL"
            ")"
        )
        existing_revisions = set(
            connection.execute(
                text(f"SELECT revision FROM {_MIGRATION_TABLE}")
            ).scalars()
        )
        for revision in _MIGRATION_REVISIONS:
            if revision in existing_revisions:
                continue
            if revision == DIAGNOSTIC_SCHEMA_REVISION:
                _create_historical_segment_catalog(connection)
            connection.execute(
                text(
                    f"INSERT INTO {_MIGRATION_TABLE} "
                    "(revision, applied_at_utc) VALUES (:revision, :applied_at_utc)"
                ),
                {
                    "revision": revision,
                    "applied_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            applied_revisions.append(revision)

    return DiagnosticMigrationReport(
        current_revision=DIAGNOSTIC_SCHEMA_REVISION,
        applied_revisions=tuple(applied_revisions),
    )


def _create_historical_segment_catalog(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_source_snapshots ("
        "snapshot_id VARCHAR(64) PRIMARY KEY NOT NULL, "
        "content_hash VARCHAR(64) UNIQUE NOT NULL, "
        "provenance_json TEXT NOT NULL, "
        "artifacts_json TEXT NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_historical_segments ("
        "segment_id VARCHAR(64) PRIMARY KEY NOT NULL, "
        "content_hash VARCHAR(64) UNIQUE NOT NULL, "
        "source_snapshot_id VARCHAR(64) NOT NULL, "
        "market VARCHAR(64) NOT NULL, "
        "start_date VARCHAR(10) NOT NULL, "
        "end_date VARCHAR(10) NOT NULL, "
        "label VARCHAR(256) NOT NULL, "
        "eligible_instrument_count INTEGER NOT NULL, "
        "trading_day_count INTEGER NOT NULL, "
        "bar_count INTEGER NOT NULL, "
        "recommendation_tags_json TEXT NOT NULL, "
        "admission_report_json TEXT NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL, "
        "FOREIGN KEY(source_snapshot_id) "
        "REFERENCES diagnostic_source_snapshots(snapshot_id)"
        ")"
    )


def _json_dumps(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SqlHistoricalSegmentCatalog:
    """Transactional catalog adapter backed by diagnostic-owned tables."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(
        self,
        snapshot: SourceSnapshot,
        segment: HistoricalMarketSegment,
        report: SegmentAdmissionReport,
    ) -> HistoricalMarketSegment:
        provenance_json = _json_dumps(snapshot.provenance.to_dict())
        artifacts_json = _json_dumps(
            [artifact.to_dict() for artifact in snapshot.artifacts]
        )
        tags_json = _json_dumps(list(segment.recommendation_tags))
        report_json = _json_dumps(report.to_dict())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._engine.begin() as connection:
            existing_snapshot = connection.execute(
                text(
                    "SELECT content_hash, provenance_json, artifacts_json "
                    "FROM diagnostic_source_snapshots "
                    "WHERE snapshot_id = :snapshot_id"
                ),
                {"snapshot_id": snapshot.snapshot_id},
            ).one_or_none()
            if existing_snapshot is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_source_snapshots ("
                        "snapshot_id, content_hash, provenance_json, artifacts_json, "
                        "created_at_utc) VALUES ("
                        ":snapshot_id, :content_hash, :provenance_json, "
                        ":artifacts_json, :created_at_utc)"
                    ),
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "content_hash": snapshot.content_hash,
                        "provenance_json": provenance_json,
                        "artifacts_json": artifacts_json,
                        "created_at_utc": created_at,
                    },
                )
            elif tuple(existing_snapshot) != (
                snapshot.content_hash,
                provenance_json,
                artifacts_json,
            ):
                raise ValueError("immutable source snapshot identity collision")

            existing_segment = connection.execute(
                text(
                    "SELECT content_hash, source_snapshot_id, market, start_date, "
                    "end_date, label, eligible_instrument_count, trading_day_count, "
                    "bar_count, recommendation_tags_json, admission_report_json "
                    "FROM diagnostic_historical_segments "
                    "WHERE segment_id = :segment_id"
                ),
                {"segment_id": segment.segment_id},
            ).one_or_none()
            if existing_segment is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_historical_segments ("
                        "segment_id, content_hash, source_snapshot_id, market, "
                        "start_date, end_date, label, eligible_instrument_count, "
                        "trading_day_count, bar_count, recommendation_tags_json, "
                        "admission_report_json, created_at_utc) VALUES ("
                        ":segment_id, :content_hash, :source_snapshot_id, :market, "
                        ":start_date, :end_date, :label, "
                        ":eligible_instrument_count, :trading_day_count, :bar_count, "
                        ":recommendation_tags_json, :admission_report_json, "
                        ":created_at_utc)"
                    ),
                    {
                        "segment_id": segment.segment_id,
                        "content_hash": segment.content_hash,
                        "source_snapshot_id": segment.source_snapshot_id,
                        "market": segment.selection.market,
                        "start_date": segment.selection.start_date.isoformat(),
                        "end_date": segment.selection.end_date.isoformat(),
                        "label": segment.label,
                        "eligible_instrument_count": segment.eligible_instrument_count,
                        "trading_day_count": segment.trading_day_count,
                        "bar_count": segment.bar_count,
                        "recommendation_tags_json": tags_json,
                        "admission_report_json": report_json,
                        "created_at_utc": created_at,
                    },
                )
            elif tuple(existing_segment) != (
                segment.content_hash,
                segment.source_snapshot_id,
                segment.selection.market,
                segment.selection.start_date.isoformat(),
                segment.selection.end_date.isoformat(),
                segment.label,
                segment.eligible_instrument_count,
                segment.trading_day_count,
                segment.bar_count,
                tags_json,
                report_json,
            ):
                raise ValueError("immutable historical segment identity collision")
        return segment

    def list_segments(self) -> tuple[HistoricalMarketSegment, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT s.segment_id, s.content_hash, s.source_snapshot_id, "
                    "s.market, "
                    "start_date, end_date, label, eligible_instrument_count, "
                    "trading_day_count, bar_count, recommendation_tags_json, "
                    "p.provenance_json "
                    "FROM diagnostic_historical_segments AS s "
                    "JOIN diagnostic_source_snapshots AS p "
                    "ON p.snapshot_id = s.source_snapshot_id "
                    "ORDER BY start_date, end_date, segment_id"
                )
            ).all()
        return tuple(
            HistoricalMarketSegment(
                segment_id=str(row.segment_id),
                content_hash=str(row.content_hash),
                source_snapshot_id=str(row.source_snapshot_id),
                source_provenance=_source_provenance_from_json(
                    str(row.provenance_json)
                ),
                selection=HistoricalSegmentSelection(
                    market=str(row.market),
                    start_date=datetime.strptime(
                        str(row.start_date), "%Y-%m-%d"
                    ).date(),
                    end_date=datetime.strptime(str(row.end_date), "%Y-%m-%d").date(),
                ),
                label=str(row.label),
                eligible_instrument_count=int(row.eligible_instrument_count),
                trading_day_count=int(row.trading_day_count),
                bar_count=int(row.bar_count),
                recommendation_tags=tuple(
                    str(tag) for tag in json.loads(row.recommendation_tags_json)
                ),
            )
            for row in rows
        )


def _source_provenance_from_json(payload: str) -> SourceProvenance:
    values = json.loads(payload)
    observed_at = datetime.fromisoformat(str(values["observed_at"]))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return SourceProvenance(
        provider=str(values["provider"]),
        dataset=str(values["dataset"]),
        version=str(values["version"]),
        observed_at=observed_at,
    )


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticMigrationReport",
    "SqlHistoricalSegmentCatalog",
    "initialize_diagnostic_persistence",
]
