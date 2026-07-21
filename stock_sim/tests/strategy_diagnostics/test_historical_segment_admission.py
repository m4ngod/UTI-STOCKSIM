from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)


REQUIRED_CHECKS = (
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


def _inspection(
    start: date,
    end: date,
    *,
    failed_check: str | None = None,
    label: str = "A-share development interval",
) -> HistoricalSourceInspection:
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=start,
        end_date=end,
    )
    checks = tuple(
        AdmissionCheck(
            code=code,
            passed=code != failed_check,
            summary=(
                f"{code} passed"
                if code != failed_check
                else f"{code} is incomplete; repair the source data and retry"
            ),
        )
        for code in REQUIRED_CHECKS
    )
    return HistoricalSourceInspection(
        selection=selection,
        label=label,
        provenance=SourceProvenance(
            provider="BaoStock",
            dataset="local-a-share-fixture",
            version="fixture-2026-07-21",
            observed_at=datetime(2026, 7, 21, 23, 0, tzinfo=timezone.utc),
        ),
        artifacts=(
            SourceArtifact(
                name="daily-unadjusted",
                content_hash="1" * 64,
                row_count=60,
            ),
            SourceArtifact(
                name="five-minute-front-adjusted",
                content_hash="2" * 64,
                row_count=5760,
            ),
            SourceArtifact(
                name="industry-as-of",
                content_hash="3" * 64,
                row_count=120,
            ),
        ),
        eligible_instrument_count=120,
        trading_day_count=2,
        bar_count=5760,
        checks=checks,
        recommendation_tags=("development", "stable", "two-day"),
    )


def test_explicit_valid_interval_is_admitted_with_immutable_content_identity() -> None:
    inspection = _inspection(date(2024, 1, 2), date(2024, 1, 3))
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()

    first = application.admit_historical_segment(inspection.selection)
    second = application.admit_historical_segment(inspection.selection)

    assert first.status == "admitted"
    assert first.failure_reasons == ()
    assert first.source_snapshot is not None
    assert first.segment is not None
    assert first.source_snapshot.snapshot_id.startswith("snapshot_")
    assert len(first.source_snapshot.content_hash) == 64
    assert first.segment.segment_id.startswith("segment_")
    assert len(first.segment.content_hash) == 64
    assert first.segment.source_snapshot_id == first.source_snapshot.snapshot_id
    assert second.source_snapshot == first.source_snapshot
    assert second.segment == first.segment
    assert application.list_historical_segments() == (first.segment,)
    with pytest.raises(FrozenInstanceError):
        first.segment.label = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize("failed_check", REQUIRED_CHECKS)
def test_incomplete_quality_dimension_fails_closed_with_actionable_reason(
    failed_check: str,
) -> None:
    inspection = _inspection(
        date(2024, 1, 2),
        date(2024, 1, 3),
        failed_check=failed_check,
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()

    report = application.admit_historical_segment(inspection.selection)

    assert report.status == "rejected"
    assert report.source_snapshot is None
    assert report.segment is None
    assert report.failure_reasons == (
        f"{failed_check}: {failed_check} is incomplete; repair the source data and retry",
    )
    assert application.list_historical_segments() == ()


def test_admission_report_covers_every_required_point_in_time_quality_dimension() -> None:
    inspection = _inspection(date(2024, 1, 2), date(2024, 1, 3))
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()

    report = application.admit_historical_segment(inspection.selection)

    assert tuple(check.code for check in report.checks) == REQUIRED_CHECKS
    payload = report.to_dict()
    assert payload["eligible_instrument_count"] == 120
    assert payload["trading_day_count"] == 2
    assert payload["bar_count"] == 5760
    assert "storage_path" not in repr(payload)


def test_explicit_selection_outside_source_coverage_is_rejected_actionably() -> None:
    source = InMemoryHistoricalSource(
        (_inspection(date(2024, 1, 2), date(2024, 1, 3)),)
    )
    application = create_diagnostics_application(historical_source=source)
    application.start()

    report = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2023, 12, 1),
            end_date=date(2023, 12, 2),
        )
    )

    assert report.status == "rejected"
    assert report.failure_reasons == (
        "source_coverage: No inspected contiguous interval covers "
        "mainland-a-share 2023-12-01 through 2023-12-02.",
    )


def test_catalog_recommendations_are_ranked_bounded_and_non_binding() -> None:
    inspections = tuple(
        _inspection(
            date(2024, 1, day),
            date(2024, 1, day),
            label=f"Stable development interval {day}",
        )
        for day in range(2, 7)
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource(inspections)
    )
    application.start()
    for inspection in inspections:
        application.admit_historical_segment(inspection.selection)

    recommendations = application.recommend_historical_segments(
        intent="stable development",
        limit=99,
    )

    assert len(recommendations) == 3
    assert [item.rank for item in recommendations] == [1, 2, 3]
    assert all(item.reason for item in recommendations)
    assert all(item.segment in application.list_historical_segments() for item in recommendations)
    assert application.latest_segment_admission() is not None


def test_selection_rejects_reverse_date_ranges_before_source_access() -> None:
    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 2),
        )
