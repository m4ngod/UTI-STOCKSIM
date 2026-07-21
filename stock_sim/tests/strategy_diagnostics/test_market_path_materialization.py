from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from strategy_diagnostics import (
    FiveMinuteBar,
    AdmissionCheck,
    FutureDataAccessError,
    HistoricalMarketSegment,
    HistoricalSegmentSelection,
    InMemoryHistoricalMarketDataSource,
    HistoricalSourceInspection,
    InMemoryMarketPathArtifactStore,
    InstrumentState,
    ParquetMarketPathArtifactStore,
    ScenarioDataWorldInput,
    ScenarioMaterializer,
    ScenarioMarketView,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)


_REQUIRED_CHECKS = (
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


def _segment() -> HistoricalMarketSegment:
    return HistoricalMarketSegment(
        segment_id="segment_fixture",
        content_hash="1" * 64,
        source_snapshot_id="snapshot_fixture",
        source_provenance=SourceProvenance(
            provider="Fixture",
            dataset="one-day-a-share",
            version="v1",
            observed_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        ),
        selection=HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        ),
        label="One admitted trading day",
        eligible_instrument_count=1,
        trading_day_count=1,
        bar_count=1,
        recommendation_tags=("baseline",),
    )


def _world() -> ScenarioDataWorldInput:
    return ScenarioDataWorldInput(
        segment_id="segment_fixture",
        segment_content_hash="1" * 64,
        source_snapshot_id="snapshot_fixture",
        bars=(
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 9, 35),
                open=Decimal("10.00"),
                high=Decimal("10.30"),
                low=Decimal("9.90"),
                close=Decimal("10.20"),
                volume=101,
                amount=Decimal("1025.50"),
            ),
        ),
        instrument_states=(
            InstrumentState(
                instrument="sh.600000",
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="banking",
                adjustment_factor=Decimal("1.25"),
                adjustment_provenance="daily-raw/front-ratio-v1",
            ),
        ),
    )


def _two_bar_world() -> ScenarioDataWorldInput:
    first = _world()
    return ScenarioDataWorldInput(
        segment_id=first.segment_id,
        segment_content_hash=first.segment_content_hash,
        source_snapshot_id=first.source_snapshot_id,
        bars=(
            *first.bars,
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 9, 40),
                open=Decimal("10.20"),
                high=Decimal("10.40"),
                low=Decimal("10.10"),
                close=Decimal("10.35"),
                volume=90,
                amount=Decimal("925.00"),
            ),
        ),
        instrument_states=(
            *first.instrument_states,
            InstrumentState(
                instrument="sz.000001",
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="suspended",
                is_st=True,
                industry="regional-bank",
                adjustment_factor=None,
                adjustment_provenance="unavailable-while-suspended",
            ),
            InstrumentState(
                instrument="sh.600000",
                effective_at=datetime(2024, 1, 2, 9, 40),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="diversified-bank",
                adjustment_factor=Decimal("1.25"),
                adjustment_provenance="daily-raw/front-ratio-v1",
            ),
        ),
    )


class _AdmittedFixtureSource:
    def __init__(self) -> None:
        self._selection = _segment().selection

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        if selection != self._selection:
            return None
        return HistoricalSourceInspection(
            selection=selection,
            label="One admitted trading day",
            provenance=_segment().source_provenance,
            artifacts=(SourceArtifact("fixture-bars", "2" * 64, 2),),
            eligible_instrument_count=2,
            trading_day_count=1,
            bar_count=2,
            checks=tuple(
                AdmissionCheck(code, True, f"{code} passed")
                for code in _REQUIRED_CHECKS
            ),
            recommendation_tags=("baseline",),
        )

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        return replace(
            _two_bar_world(),
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
        )


def test_baseline_materialization_is_reconstructed_reaggregatable_and_stable() -> None:
    segment = _segment()
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    first = materializer.materialize_baseline(segment, seed=17)
    second = materializer.materialize_baseline(segment, seed=17)

    assert first.artifact_hash == second.artifact_hash
    assert first.to_preview_dict() == second.to_preview_dict()
    assert first.reconstructed is True
    assert first.source_resolution == "5m"
    assert first.runtime_resolution == "30s"
    assert first.expander_version == "within-bar-expander-v1"
    assert first.numeric_tolerance == "0.000001"
    assert len(first.nodes) == 10
    assert first.nodes[0].simulation_time == datetime(2024, 1, 2, 9, 30, 30)
    assert first.nodes[-1].simulation_time == datetime(2024, 1, 2, 9, 35)
    assert all(node.reconstructed for node in first.nodes)

    assert (
        first.nodes[0].open,
        max(node.high for node in first.nodes),
        min(node.low for node in first.nodes),
        first.nodes[-1].close,
        sum(node.volume for node in first.nodes),
        sum((node.amount for node in first.nodes), Decimal("0")),
    ) == (
        Decimal("10.00"),
        Decimal("10.30"),
        Decimal("9.90"),
        Decimal("10.20"),
        101,
        Decimal("1025.50"),
    )


def test_scenario_market_view_refuses_every_kind_of_future_data() -> None:
    segment = _segment()
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    path = materializer.materialize_baseline(segment, seed=17)
    view = ScenarioMarketView(
        path,
        initial_cursor=datetime(2024, 1, 2, 9, 35),
    )

    snapshot = view.snapshot().to_dict()

    assert snapshot["simulation_time"] == "2024-01-02T09:35:00"
    assert snapshot["eligible_universe"] == ["sh.600000", "sz.000001"]
    assert snapshot["trading_status"] == {
        "sh.600000": {"status": "trading", "is_st": False},
        "sz.000001": {"status": "suspended", "is_st": True},
    }
    assert snapshot["industries"] == {
        "sh.600000": "banking",
        "sz.000001": "regional-bank",
    }
    assert snapshot["adjustments"]["sh.600000"] == {
        "factor": "1.25",
        "provenance": "daily-raw/front-ratio-v1",
    }
    assert set(snapshot["features"]["sh.600000"]) == {
        "return_30s",
        "session_return",
    }
    assert "sz.000001" not in snapshot["features"]
    assert len(view.history("sh.600000")) == 10

    with pytest.raises(FutureDataAccessError, match="Simulation Time cursor"):
        view.node_at("sh.600000", datetime(2024, 1, 2, 9, 40))

    view.advance_to(datetime(2024, 1, 2, 9, 40))

    assert len(view.history("sh.600000")) == 20
    assert view.snapshot().to_dict()["industries"]["sh.600000"] == (
        "diversified-bank"
    )


def test_headless_application_materializes_and_previews_an_admitted_segment() -> None:
    source = _AdmittedFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None

    materialized = application.materialize_baseline_reference_path(
        admission.segment.segment_id,
        seed=17,
    )
    preview = application.preview_reference_market_path(
        materialized.artifact_hash,
        at_time=datetime(2024, 1, 2, 9, 35),
    )

    assert materialized.segment_id == admission.segment.segment_id
    assert preview["simulation_time"] == "2024-01-02T09:35:00"
    assert preview["eligible_universe"] == ["sh.600000", "sz.000001"]
    assert preview["artifact_hash"] == materialized.artifact_hash
    assert preview["reconstructed"] is True


def test_content_addressed_path_survives_artifact_store_restart(tmp_path: Path) -> None:
    root = tmp_path / "market-paths"
    first_store = ParquetMarketPathArtifactStore(root)
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=first_store,
    )
    materialized = materializer.materialize_baseline(_segment(), seed=17)

    restored = ParquetMarketPathArtifactStore(root).get(materialized.artifact_hash)

    assert restored == materialized
    assert restored.to_preview_dict() == materialized.to_preview_dict()


def test_materializer_rejects_source_bars_outside_a_share_sessions() -> None:
    invalid_world = replace(
        _world(),
        bars=(replace(_world().bars[0], end_time=datetime(2024, 1, 2, 12, 0)),),
    )
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((invalid_world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="A-share session"):
        materializer.materialize_baseline(_segment(), seed=17)


def test_artifact_identity_ignores_equivalent_decimal_text_scales() -> None:
    original = _world()
    equivalent = replace(
        original,
        bars=(
            replace(
                original.bars[0],
                open=Decimal("10.000"),
                high=Decimal("10.3000"),
                low=Decimal("9.900"),
                close=Decimal("10.2000"),
                amount=Decimal("1025.5000"),
            ),
        ),
        instrument_states=(
            replace(
                original.instrument_states[0],
                adjustment_factor=Decimal("1.250000"),
            ),
        ),
    )
    first = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((original,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize_baseline(_segment(), seed=17)
    second = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((equivalent,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize_baseline(_segment(), seed=17)

    assert first.artifact_hash == second.artifact_hash
    assert first.to_preview_dict() == second.to_preview_dict()
