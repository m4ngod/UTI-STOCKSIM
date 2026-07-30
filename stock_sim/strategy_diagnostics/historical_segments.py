"""Historical-segment admission and catalog domain for diagnostic scenarios.

The module deliberately receives inspected evidence from a historical-source
port.  It owns admission policy, immutable content identities, cataloguing,
and recommendations without exposing filesystem or query-engine controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Iterable, Protocol


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalSegmentSelection:
    """An explicit market and contiguous inclusive date interval."""

    market: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        normalized_market = self.market.strip().lower()
        if not normalized_market:
            raise ValueError("market must not be empty")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        object.__setattr__(self, "market", normalized_market)

    def to_dict(self) -> dict[str, str]:
        return {
            "market": self.market,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class AdmissionCheck:
    """One user-readable, deterministic source-quality decision."""

    code: str
    passed: bool
    summary: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("admission check code must not be empty")
        if not self.summary.strip():
            raise ValueError("admission check summary must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "passed": self.passed,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Content identity for one logical input, without a storage location."""

    name: str
    content_hash: str
    row_count: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("source artifact name must not be empty")
        if not _SHA256_PATTERN.fullmatch(self.content_hash):
            raise ValueError("source artifact content_hash must be lowercase SHA-256")
        if self.row_count < 0:
            raise ValueError("source artifact row_count must be nonnegative")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "content_hash": self.content_hash,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Searchable source lineage safe to show in the Diagnostics workspace."""

    provider: str
    dataset: str
    version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("provider", "dataset", "version"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"source provenance {field_name} must not be empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("source provenance observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "version": self.version,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class HistoricalSourceInspection:
    """Evidence supplied by a historical-source adapter for one selection."""

    selection: HistoricalSegmentSelection
    label: str
    provenance: SourceProvenance
    artifacts: tuple[SourceArtifact, ...]
    eligible_instrument_count: int
    trading_day_count: int
    bar_count: int
    checks: tuple[AdmissionCheck, ...]
    recommendation_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("historical source inspection label must not be empty")
        if not self.artifacts:
            raise ValueError("historical source inspection requires source artifacts")
        for name in (
            "eligible_instrument_count",
            "trading_day_count",
            "bar_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        codes = tuple(check.code for check in self.checks)
        if len(codes) != len(set(codes)):
            raise ValueError("historical source inspection has duplicate check codes")


class HistoricalSource(Protocol):
    """External boundary that inspects local recorded-market data."""

    def inspect(
        self, selection: HistoricalSegmentSelection
    ) -> HistoricalSourceInspection | None: ...


class InMemoryHistoricalSource:
    """Deterministic source fixture justified for application contract tests."""

    def __init__(self, inspections: Iterable[HistoricalSourceInspection]) -> None:
        self._inspections = tuple(inspections)

    def inspect(
        self, selection: HistoricalSegmentSelection
    ) -> HistoricalSourceInspection | None:
        exact = next(
            (
                inspection
                for inspection in self._inspections
                if inspection.selection == selection
            ),
            None,
        )
        if exact is not None:
            return exact
        return None


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Immutable identity of the logical source inputs used by a segment."""

    snapshot_id: str
    content_hash: str
    provenance: SourceProvenance
    artifacts: tuple[SourceArtifact, ...]

    def __post_init__(self) -> None:
        artifacts = tuple(
            sorted(self.artifacts, key=lambda item: item.name)
        )
        if artifacts != self.artifacts:
            raise ValueError(
                "source snapshot artifacts must use canonical name order"
            )
        payload = {
            "provenance": self.provenance.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in artifacts],
        }
        content_hash = _canonical_hash(payload)
        if self.content_hash != content_hash:
            raise ValueError(
                "source snapshot content hash does not match its content"
            )
        if self.snapshot_id != f"snapshot_{content_hash[:20]}":
            raise ValueError(
                "source snapshot identity does not match its content hash"
            )

    @classmethod
    def from_inspection(
        cls,
        inspection: HistoricalSourceInspection,
    ) -> "SourceSnapshot":
        artifacts = tuple(sorted(inspection.artifacts, key=lambda item: item.name))
        payload = {
            "provenance": inspection.provenance.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in artifacts],
        }
        content_hash = _canonical_hash(payload)
        return cls(
            snapshot_id=f"snapshot_{content_hash[:20]}",
            content_hash=content_hash,
            provenance=inspection.provenance,
            artifacts=artifacts,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "content_hash": self.content_hash,
            "provenance": self.provenance.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class HistoricalMarketSegment:
    """An admitted, immutable catalog entry."""

    segment_id: str
    content_hash: str
    source_snapshot_id: str
    source_provenance: SourceProvenance
    selection: HistoricalSegmentSelection
    label: str
    eligible_instrument_count: int
    trading_day_count: int
    bar_count: int
    recommendation_tags: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "content_hash": self.content_hash,
            "source_snapshot_id": self.source_snapshot_id,
            "provenance": self.source_provenance.to_dict(),
            "market": self.selection.market,
            "start_date": self.selection.start_date.isoformat(),
            "end_date": self.selection.end_date.isoformat(),
            "label": self.label,
            "eligible_instrument_count": self.eligible_instrument_count,
            "trading_day_count": self.trading_day_count,
            "bar_count": self.bar_count,
            "recommendation_tags": list(self.recommendation_tags),
            "admission_status": "admitted",
        }


@dataclass(frozen=True, slots=True)
class SegmentAdmissionReport:
    """Complete, actionable result of attempting to admit one segment."""

    selection: HistoricalSegmentSelection
    status: str
    checks: tuple[AdmissionCheck, ...]
    failure_reasons: tuple[str, ...]
    eligible_instrument_count: int
    trading_day_count: int
    bar_count: int
    source_snapshot: SourceSnapshot | None = None
    segment: HistoricalMarketSegment | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_dict(),
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "failure_reasons": list(self.failure_reasons),
            "eligible_instrument_count": self.eligible_instrument_count,
            "trading_day_count": self.trading_day_count,
            "bar_count": self.bar_count,
            "source_snapshot": (
                self.source_snapshot.to_dict()
                if self.source_snapshot is not None
                else None
            ),
            "segment": self.segment.to_dict() if self.segment is not None else None,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSegmentRecommendation:
    rank: int
    segment: HistoricalMarketSegment
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "reason": self.reason,
            "segment": self.segment.to_dict(),
        }


class HistoricalSegmentCatalog(Protocol):
    def add(
        self,
        snapshot: SourceSnapshot,
        segment: HistoricalMarketSegment,
        report: SegmentAdmissionReport,
    ) -> HistoricalMarketSegment: ...

    def list_segments(self) -> tuple[HistoricalMarketSegment, ...]: ...

    def get_source_snapshot(self, snapshot_id: str) -> SourceSnapshot: ...


class InMemoryHistoricalSegmentCatalog:
    def __init__(self) -> None:
        self._segments: dict[str, HistoricalMarketSegment] = {}
        self._source_snapshots: dict[str, SourceSnapshot] = {}

    def add(
        self,
        snapshot: SourceSnapshot,
        segment: HistoricalMarketSegment,
        report: SegmentAdmissionReport,
    ) -> HistoricalMarketSegment:
        del report
        existing_snapshot = self._source_snapshots.get(snapshot.snapshot_id)
        if existing_snapshot is not None and existing_snapshot != snapshot:
            raise ValueError("immutable source snapshot identity collision")
        existing = self._segments.get(segment.segment_id)
        if existing is not None and existing != segment:
            raise ValueError("immutable historical segment identity collision")
        self._source_snapshots[snapshot.snapshot_id] = snapshot
        self._segments[segment.segment_id] = segment
        return self._segments[segment.segment_id]

    def list_segments(self) -> tuple[HistoricalMarketSegment, ...]:
        return tuple(
            sorted(
                self._segments.values(),
                key=lambda item: (
                    item.selection.start_date,
                    item.selection.end_date,
                    item.segment_id,
                ),
            )
        )

    def get_source_snapshot(self, snapshot_id: str) -> SourceSnapshot:
        try:
            return self._source_snapshots[snapshot_id]
        except KeyError as error:
            raise KeyError("Unknown source snapshot") from error


_REQUIRED_ADMISSION_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


class HistoricalSegmentAdmissionService:
    """Deep module for fail-closed admission and catalog recommendations."""

    def __init__(
        self,
        source: HistoricalSource | None,
        catalog: HistoricalSegmentCatalog | None = None,
    ) -> None:
        self._source = source
        self._catalog = catalog or InMemoryHistoricalSegmentCatalog()
        self._latest_report: SegmentAdmissionReport | None = None

    def replace_catalog(self, catalog: HistoricalSegmentCatalog) -> None:
        self._catalog = catalog

    def admit(
        self, selection: HistoricalSegmentSelection
    ) -> SegmentAdmissionReport:
        inspection = self._source.inspect(selection) if self._source is not None else None
        if inspection is None:
            reason = (
                "No inspected contiguous interval covers "
                f"{selection.market} {selection.start_date.isoformat()} through "
                f"{selection.end_date.isoformat()}."
            )
            report = SegmentAdmissionReport(
                selection=selection,
                status="rejected",
                checks=(AdmissionCheck("source_coverage", False, reason),),
                failure_reasons=(f"source_coverage: {reason}",),
                eligible_instrument_count=0,
                trading_day_count=0,
                bar_count=0,
            )
            self._latest_report = report
            return report

        checks_by_code = {check.code: check for check in inspection.checks}
        completed_checks = list(inspection.checks)
        for code in _REQUIRED_ADMISSION_CHECKS:
            if code not in checks_by_code:
                completed_checks.append(
                    AdmissionCheck(
                        code=code,
                        passed=False,
                        summary=(
                            "The historical source did not provide this required "
                            "quality result; repair the adapter and retry"
                        ),
                    )
                )
        checks = tuple(completed_checks)
        failures = tuple(
            f"{check.code}: {check.summary}" for check in checks if not check.passed
        )
        if failures:
            report = SegmentAdmissionReport(
                selection=selection,
                status="rejected",
                checks=checks,
                failure_reasons=failures,
                eligible_instrument_count=inspection.eligible_instrument_count,
                trading_day_count=inspection.trading_day_count,
                bar_count=inspection.bar_count,
            )
            self._latest_report = report
            return report

        snapshot = SourceSnapshot.from_inspection(inspection)
        segment_payload = {
            "source_snapshot_hash": snapshot.content_hash,
            "selection": selection.to_dict(),
            "label": inspection.label,
            "eligible_instrument_count": inspection.eligible_instrument_count,
            "trading_day_count": inspection.trading_day_count,
            "bar_count": inspection.bar_count,
            "checks": [check.to_dict() for check in checks],
            "recommendation_tags": list(inspection.recommendation_tags),
        }
        segment_hash = _canonical_hash(segment_payload)
        segment = HistoricalMarketSegment(
            segment_id=f"segment_{segment_hash[:20]}",
            content_hash=segment_hash,
            source_snapshot_id=snapshot.snapshot_id,
            source_provenance=inspection.provenance,
            selection=selection,
            label=inspection.label,
            eligible_instrument_count=inspection.eligible_instrument_count,
            trading_day_count=inspection.trading_day_count,
            bar_count=inspection.bar_count,
            recommendation_tags=inspection.recommendation_tags,
        )
        report = SegmentAdmissionReport(
            selection=selection,
            status="admitted",
            checks=checks,
            failure_reasons=(),
            eligible_instrument_count=inspection.eligible_instrument_count,
            trading_day_count=inspection.trading_day_count,
            bar_count=inspection.bar_count,
            source_snapshot=snapshot,
            segment=segment,
        )
        admitted = self._catalog.add(snapshot, segment, report)
        if admitted != segment:
            raise ValueError("catalog returned a different immutable historical segment")
        self._latest_report = report
        return report

    def list_segments(self) -> tuple[HistoricalMarketSegment, ...]:
        return self._catalog.list_segments()

    def get_source_snapshot(self, snapshot_id: str) -> SourceSnapshot:
        return self._catalog.get_source_snapshot(snapshot_id)

    def latest_report(self) -> SegmentAdmissionReport | None:
        return self._latest_report

    def recommend(
        self,
        intent: str = "",
        limit: int = 3,
    ) -> tuple[HistoricalSegmentRecommendation, ...]:
        bounded_limit = max(0, min(limit, 3))
        if bounded_limit == 0:
            return ()
        intent_tokens = {
            token for token in re.findall(r"[\w-]+", intent.lower()) if token
        }

        def score(segment: HistoricalMarketSegment) -> tuple[int, date, str]:
            searchable = " ".join(
                (segment.label, *segment.recommendation_tags)
            ).lower()
            matches = sum(token in searchable for token in intent_tokens)
            return (matches, segment.selection.start_date, segment.segment_id)

        ranked = sorted(self.list_segments(), key=score, reverse=True)[:bounded_limit]
        recommendations = []
        for rank, segment in enumerate(ranked, start=1):
            matches = score(segment)[0]
            reason = (
                f"Matches {matches} intent term(s) and has passed all admission checks."
                if intent_tokens
                else "Passed all admission checks and is available in the catalog."
            )
            recommendations.append(
                HistoricalSegmentRecommendation(
                    rank=rank,
                    segment=segment,
                    reason=reason,
                )
            )
        return tuple(recommendations)


__all__ = [
    "AdmissionCheck",
    "HistoricalMarketSegment",
    "HistoricalSegmentAdmissionService",
    "HistoricalSegmentCatalog",
    "HistoricalSegmentRecommendation",
    "HistoricalSegmentSelection",
    "HistoricalSource",
    "HistoricalSourceInspection",
    "InMemoryHistoricalSegmentCatalog",
    "InMemoryHistoricalSource",
    "SegmentAdmissionReport",
    "SourceArtifact",
    "SourceProvenance",
    "SourceSnapshot",
]
