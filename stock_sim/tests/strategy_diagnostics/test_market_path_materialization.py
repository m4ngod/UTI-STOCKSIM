from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import errno
import os
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

from strategy_diagnostics import (
    FiveMinuteBar,
    AdmissionCheck,
    EligibleUniverseAccessError,
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
    ScenarioTransformationRequestV1,
    SessionPriceLimitReference,
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


def _approve_baseline_recipe(
    application: object,
    segment_id: str,
    *,
    seed: int,
) -> str:
    payload = {
        "schema_version": "scenario_recipe.v1",
        "name": "Baseline control",
        "historical_segment_id": segment_id,
        "transformations": [],
        "execution_conditions": {},
        "decision_cadence_minutes": 30,
        "materialization_seed": seed,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }
    draft = application.create_manual_recipe_draft(payload, author="test")
    validation = application.validate_recipe_draft(draft.draft_id)
    assert validation.is_valid
    return application.approve_recipe_draft(
        draft.draft_id,
        actor="test-owner",
    ).version_id


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
                decision_adjustment_factor=Decimal("1.25"),
                decision_adjustment_provenance="fixture-as-of-adjustment-v1",
            ),
        ),
        price_limit_references=(
            SessionPriceLimitReference(
                instrument="sh.600000",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10.00"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="fixture.sh-main.ordinary.10pct",
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
                decision_adjustment_factor=None,
                decision_adjustment_provenance="unavailable-while-suspended",
            ),
            InstrumentState(
                instrument="sh.600000",
                effective_at=datetime(2024, 1, 2, 9, 40),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="diversified-bank",
                decision_adjustment_factor=Decimal("1.25"),
                decision_adjustment_provenance="fixture-as-of-adjustment-v1",
            ),
            InstrumentState(
                instrument="sz.000001",
                effective_at=datetime(2024, 1, 2, 9, 40),
                eligible=False,
                trading_status="inactive",
                is_st=False,
                industry="regional-bank",
                decision_adjustment_factor=None,
                decision_adjustment_provenance="not-applicable-outside-listing",
            ),
        ),
        price_limit_references=first.price_limit_references,
    )


def _cross_section_world() -> ScenarioDataWorldInput:
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
                volume=100,
                amount=Decimal("1010"),
            ),
            FiveMinuteBar(
                instrument="sz.000001",
                end_time=datetime(2024, 1, 2, 9, 35),
                open=Decimal("20.00"),
                high=Decimal("20.60"),
                low=Decimal("19.80"),
                close=Decimal("20.40"),
                volume=200,
                amount=Decimal("4040"),
            ),
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 9, 40),
                open=Decimal("10.20"),
                high=Decimal("10.40"),
                low=Decimal("10.10"),
                close=Decimal("10.35"),
                volume=110,
                amount=Decimal("1130"),
            ),
            FiveMinuteBar(
                instrument="sz.000001",
                end_time=datetime(2024, 1, 2, 9, 40),
                open=Decimal("20.40"),
                high=Decimal("20.80"),
                low=Decimal("20.20"),
                close=Decimal("20.60"),
                volume=210,
                amount=Decimal("4300"),
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
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            ),
            InstrumentState(
                instrument="sz.000001",
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=True,
                industry="banking",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            ),
        ),
        price_limit_references=(
            SessionPriceLimitReference(
                instrument="sh.600000",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10.00"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="fixture.sh-main.ordinary.10pct",
            ),
            SessionPriceLimitReference(
                instrument="sz.000001",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("20.00"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board="sz-main",
                is_st=True,
                listing_stage="continuous",
                limit_fraction=Decimal("0.05"),
                rule_code="fixture.sz-main.risk-warning.5pct",
            ),
        ),
    )


def _shock_world() -> ScenarioDataWorldInput:
    reference = _cross_section_world()
    bars: list[FiveMinuteBar] = []
    for index in range(7):
        end_time = datetime(2024, 1, 2, 9, 35) + timedelta(minutes=5 * index)
        for instrument, price, volume in (
            ("sh.600000", Decimal("10"), 100 + index),
            ("sz.000001", Decimal("20"), 200 + index),
        ):
            bars.append(
                FiveMinuteBar(
                    instrument=instrument,
                    end_time=end_time,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    amount=price * volume,
                )
            )
    return replace(reference, bars=tuple(bars))


def _shock_request() -> ScenarioTransformationRequestV1:
    return ScenarioTransformationRequestV1(
        transformation_id="shock-recovery.v1",
        parameters={
            "direction": "bearish",
            "gap_fraction": "0.01",
            "shock_fraction": "0.03",
            "shock_duration_bars": 2,
            "persistence_duration_bars": 1,
            "recovery_duration_bars": 2,
        },
    )


def _market_structure_world() -> ScenarioDataWorldInput:
    instruments = (
        ("sh.600000", "banking", "sh-main"),
        ("sh.600001", "banking", "sh-main"),
        ("sz.000001", "technology", "sz-main"),
        ("sz.000002", "technology", "sz-main"),
    )
    closes_by_time = (
        (datetime(2024, 1, 2, 9, 35), ("10", "10", "10", "10")),
        (datetime(2024, 1, 2, 9, 40), ("10.2", "10.05", "10.15", "10.1")),
        (datetime(2024, 1, 2, 9, 45), ("10.4", "10.1", "10.3", "10.2")),
    )
    previous_closes = {instrument: Decimal("10") for instrument, _, _ in instruments}
    bars: list[FiveMinuteBar] = []
    for end_time, closes in closes_by_time:
        for (instrument, _industry, _board), close_text in zip(
            instruments,
            closes,
            strict=True,
        ):
            opening = previous_closes[instrument]
            close = Decimal(close_text)
            volume = 100
            bars.append(
                FiveMinuteBar(
                    instrument=instrument,
                    end_time=end_time,
                    open=opening,
                    high=max(opening, close),
                    low=min(opening, close),
                    close=close,
                    volume=volume,
                    amount=close * volume,
                )
            )
            previous_closes[instrument] = close
    return ScenarioDataWorldInput(
        segment_id="segment_fixture",
        segment_content_hash="1" * 64,
        source_snapshot_id="snapshot_fixture",
        bars=tuple(bars),
        instrument_states=tuple(
            InstrumentState(
                instrument=instrument,
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry=industry,
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            )
            for instrument, industry, _board in instruments
        ),
        price_limit_references=tuple(
            SessionPriceLimitReference(
                instrument=instrument,
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board=board,
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code=f"fixture.{board}.ordinary.10pct",
            )
            for instrument, _industry, board in instruments
        ),
    )


def _market_structure_request() -> ScenarioTransformationRequestV1:
    return ScenarioTransformationRequestV1(
        transformation_id="market-structure.v1",
        parameters={
            "breadth_target": "0.5",
            "dispersion_fraction": "0.04",
            "sector_concentration": "1",
        },
    )


def _liquidity_world() -> ScenarioDataWorldInput:
    instruments = (
        ("sh.600000", "banking", "sh-main", 100),
        ("sh.600001", "banking", "sh-main", 200),
        ("sz.000001", "technology", "sz-main", 700),
    )
    closes_by_time = (
        (datetime(2024, 1, 2, 9, 35), ("10", "10", "10")),
        (datetime(2024, 1, 2, 9, 40), ("10.3", "10.2", "10.1")),
    )
    previous_closes = {
        instrument: Decimal("10")
        for instrument, _industry, _board, _volume in instruments
    }
    bars: list[FiveMinuteBar] = []
    for end_time, closes in closes_by_time:
        for (instrument, _industry, _board, volume), close_text in zip(
            instruments,
            closes,
            strict=True,
        ):
            opening = previous_closes[instrument]
            close = Decimal(close_text)
            bars.append(
                FiveMinuteBar(
                    instrument=instrument,
                    end_time=end_time,
                    open=opening,
                    high=max(opening, close),
                    low=min(opening, close),
                    close=close,
                    volume=volume,
                    amount=close * volume,
                )
            )
            previous_closes[instrument] = close
    return ScenarioDataWorldInput(
        segment_id="segment_fixture",
        segment_content_hash="1" * 64,
        source_snapshot_id="snapshot_fixture",
        bars=tuple(bars),
        instrument_states=tuple(
            InstrumentState(
                instrument=instrument,
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry=industry,
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            )
            for instrument, industry, _board, _volume in instruments
        ),
        price_limit_references=tuple(
            SessionPriceLimitReference(
                instrument=instrument,
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board=board,
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code=f"fixture.{board}.ordinary.10pct",
            )
            for instrument, _industry, board, _volume in instruments
        ),
    )


def _liquidity_request() -> ScenarioTransformationRequestV1:
    return ScenarioTransformationRequestV1(
        transformation_id="liquidity-stress.v1",
        parameters={
            "volume_multiplier": "0.5",
            "cross_sectional_concentration": "1",
        },
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
        "provenance": "fixture-as-of-adjustment-v1",
    }
    assert set(snapshot["features"]["sh.600000"]) == {
        "capacity_proxy_30s",
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_liquidity",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
        "session_turnover_value",
        "session_volume",
    }
    assert snapshot["market_context"] == {
        "return": "0.02",
        "breadth": "1",
        "instrument_count": 1,
    }
    assert snapshot["candidates"] == ["sh.600000"]
    assert snapshot["rankings"] == [
        {"instrument": "sh.600000", "rank": 1, "score": "0"}
    ]
    assert "sz.000001" not in snapshot["features"]
    assert len(view.history("sh.600000")) == 10

    with pytest.raises(FutureDataAccessError, match="Simulation Time cursor"):
        view.node_at("sh.600000", datetime(2024, 1, 2, 9, 40))

    view.advance_to(datetime(2024, 1, 2, 9, 40))

    assert len(view.history("sh.600000")) == 20
    later_snapshot = view.snapshot().to_dict()
    assert later_snapshot["eligible_universe"] == ["sh.600000"]
    assert later_snapshot["industries"]["sh.600000"] == (
        "diversified-bank"
    )


def test_scenario_market_view_refuses_direct_reads_before_ipo() -> None:
    world = replace(
        _world(),
        instrument_states=(
            replace(
                _world().instrument_states[0],
                eligible=False,
                trading_status="inactive",
                decision_adjustment_factor=None,
                decision_adjustment_provenance="not-applicable-outside-listing",
            ),
            replace(
                _world().instrument_states[0],
                effective_at=datetime(2024, 1, 2, 9, 35),
            ),
        ),
    )
    path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize_baseline(_segment(), seed=17)
    view = ScenarioMarketView(
        path,
        initial_cursor=datetime(2024, 1, 2, 9, 34),
    )

    with pytest.raises(EligibleUniverseAccessError, match="Eligible Universe"):
        view.history("sh.600000")
    with pytest.raises(EligibleUniverseAccessError, match="Eligible Universe"):
        view.node_at("sh.600000", datetime(2024, 1, 2, 9, 31))

    view.advance_to(datetime(2024, 1, 2, 9, 35))
    assert len(view.history("sh.600000")) == 10


def test_scenario_market_view_refuses_direct_reads_after_delisting() -> None:
    active_state = _world().instrument_states[0]
    world = replace(
        _two_bar_world(),
        instrument_states=(
            active_state,
            replace(
                active_state,
                effective_at=datetime(2024, 1, 2, 9, 40),
                eligible=False,
                trading_status="inactive",
                decision_adjustment_factor=None,
                decision_adjustment_provenance="not-applicable-outside-listing",
            ),
        ),
    )
    path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize_baseline(_segment(), seed=17)
    view = ScenarioMarketView(
        path,
        initial_cursor=datetime(2024, 1, 2, 9, 35),
    )
    assert len(view.history("sh.600000")) == 10

    view.advance_to(datetime(2024, 1, 2, 9, 40))

    with pytest.raises(EligibleUniverseAccessError, match="Eligible Universe"):
        view.history("sh.600000")
    with pytest.raises(EligibleUniverseAccessError, match="Eligible Universe"):
        view.node_at("sh.600000", datetime(2024, 1, 2, 9, 35))


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

    recipe_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
        seed=17,
    )
    materialized = application.materialize_baseline_reference_path(
        recipe_version_id
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

    reopened_store = ParquetMarketPathArtifactStore(root)
    restored = reopened_store.get(materialized.artifact_hash)

    assert restored == materialized
    assert restored.to_preview_dict() == materialized.to_preview_dict()
    assert reopened_store.list_paths() == (materialized,)
    artifact_directory = root / materialized.artifact_hash
    cache_path = (
        artifact_directory / ".verified-materialized-path.jsonl.gz"
    )
    authoritative_size = sum(
        (artifact_directory / name).stat().st_size
        for name in (
            "manifest.json",
            "nodes.parquet",
            "instrument_states.parquet",
        )
    )
    assert cache_path.read_bytes()[:2] == b"\x1f\x8b"
    assert cache_path.stat().st_size < authoritative_size


def test_parquet_store_retries_transient_directory_publish_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_replace = Path.replace
    publish_attempts = 0

    def replace_with_one_transient_conflict(
        source: Path,
        target: Path,
    ) -> Path:
        nonlocal publish_attempts
        if source.name.startswith(".staging-"):
            publish_attempts += 1
            if publish_attempts == 1:
                raise PermissionError(
                    errno.EACCES,
                    "transient directory publish conflict",
                )
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace_with_one_transient_conflict)

    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(tmp_path / "market-paths"),
    ).materialize_baseline(_segment(), seed=17)

    assert publish_attempts == 2
    assert (
        ParquetMarketPathArtifactStore(tmp_path / "market-paths").get(
            materialized.artifact_hash
        )
        == materialized
    )


def test_parquet_store_bounds_publish_retries_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_diagnostics.market_paths as market_paths_module

    root = tmp_path / "market-paths"
    publish_attempts = 0
    conflict = PermissionError(
        errno.EACCES,
        "persistent directory publish conflict",
    )

    def replace_with_persistent_conflict(
        source: Path,
        target: Path,
    ) -> Path:
        nonlocal publish_attempts
        del target
        if source.name.startswith(".staging-"):
            publish_attempts += 1
            raise conflict
        raise AssertionError("unexpected replace outside staging publication")

    monkeypatch.setattr(Path, "replace", replace_with_persistent_conflict)
    monkeypatch.setattr(market_paths_module, "sleep", lambda _: None)

    with pytest.raises(PermissionError) as captured:
        ScenarioMaterializer(
            source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
            artifact_store=ParquetMarketPathArtifactStore(root),
        ).materialize_baseline(_segment(), seed=17)

    assert captured.value is conflict
    assert publish_attempts == 5
    assert tuple(root.glob(".staging-*")) == ()


def test_parquet_store_propagates_non_retryable_publish_error_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_diagnostics.market_paths as market_paths_module

    root = tmp_path / "market-paths"
    publish_attempts = 0
    denied = PermissionError(
        errno.EPERM,
        "non-retryable directory publish error",
    )

    def replace_with_non_retryable_error(
        source: Path,
        target: Path,
    ) -> Path:
        nonlocal publish_attempts
        del target
        if source.name.startswith(".staging-"):
            publish_attempts += 1
            raise denied
        raise AssertionError("unexpected replace outside staging publication")

    def fail_if_sleeping(delay: float) -> None:
        raise AssertionError(f"non-retryable error slept for {delay}")

    monkeypatch.setattr(Path, "replace", replace_with_non_retryable_error)
    monkeypatch.setattr(market_paths_module, "sleep", fail_if_sleeping)

    with pytest.raises(PermissionError) as captured:
        ScenarioMaterializer(
            source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
            artifact_store=ParquetMarketPathArtifactStore(root),
        ).materialize_baseline(_segment(), seed=17)

    assert captured.value is denied
    assert publish_attempts == 1
    assert tuple(root.glob(".staging-*")) == ()


def test_reopened_parquet_store_reuses_verified_immutable_path_within_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb

    root = tmp_path / "market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize_baseline(_segment(), seed=17)
    original_connect = duckdb.connect
    connect_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    reopened_store = ParquetMarketPathArtifactStore(root)

    assert reopened_store.list_paths() == (materialized,)
    assert reopened_store.get(materialized.artifact_hash) == materialized
    assert connect_count == 0
    manifest_path = root / materialized.artifact_hash / "manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    rereopened_store = ParquetMarketPathArtifactStore(root)
    assert rereopened_store.get(materialized.artifact_hash) == materialized
    assert connect_count == 1


def test_store_generation_hashes_once_before_reusing_local_verified_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize_baseline(_segment(), seed=17)
    original_fingerprint = (
        ParquetMarketPathArtifactStore._artifact_fingerprint
    )
    fingerprint_count = 0

    def counting_fingerprint(directory: Path):
        nonlocal fingerprint_count
        fingerprint_count += 1
        return original_fingerprint(directory)

    monkeypatch.setattr(
        ParquetMarketPathArtifactStore,
        "_artifact_fingerprint",
        staticmethod(counting_fingerprint),
    )
    reopened_store = ParquetMarketPathArtifactStore(root)

    for _ in range(50):
        assert reopened_store.get(materialized.artifact_hash) == materialized
    assert reopened_store.list_paths() == (materialized,)

    assert fingerprint_count == 1


def test_verified_cache_rejects_same_metadata_manifest_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize_baseline(_segment(), seed=17)
    reopened_store = ParquetMarketPathArtifactStore(root)
    assert reopened_store.get(materialized.artifact_hash) == materialized
    manifest_path = root / materialized.artifact_hash / "manifest.json"
    original = manifest_path.read_bytes()
    modified = original.replace(b'"seed":17', b'"seed":18', 1)
    assert modified != original
    assert len(modified) == len(original)
    original_stat = manifest_path.stat()

    manifest_path.write_bytes(modified)
    os.utime(
        manifest_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    restored_stat = manifest_path.stat()
    assert restored_stat.st_size == original_stat.st_size
    assert restored_stat.st_mtime_ns == original_stat.st_mtime_ns

    assert reopened_store.get(materialized.artifact_hash) == materialized
    with pytest.raises(
        ValueError,
        match="persisted Materialized Market Path changed after verification",
    ):
        reopened_store.get_verified(materialized.artifact_hash)


def test_verified_cache_rejects_same_metadata_parquet_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb
    import strategy_diagnostics.market_paths as market_paths_module

    root = tmp_path / "market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize_baseline(_segment(), seed=17)
    reopened_store = ParquetMarketPathArtifactStore(root)
    assert reopened_store.get(materialized.artifact_hash) == materialized
    nodes_path = root / materialized.artifact_hash / "nodes.parquet"
    original = nodes_path.read_bytes()
    assert original.endswith(b"PAR1")
    modified = original[:-1] + b"2"
    assert len(modified) == len(original)
    original_stat = nodes_path.stat()

    nodes_path.write_bytes(modified)
    os.utime(
        nodes_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    restored_stat = nodes_path.stat()
    assert restored_stat.st_size == original_stat.st_size
    assert restored_stat.st_mtime_ns == original_stat.st_mtime_ns

    assert reopened_store.get(materialized.artifact_hash) == materialized
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None

    def fail_native_reread(*args, **kwargs):
        raise AssertionError(
            "tamper verification must not reread native Parquet"
        )

    monkeypatch.setattr(
        duckdb,
        "connect",
        fail_native_reread,
    )
    with pytest.raises(
        ValueError,
        match="persisted Materialized Market Path changed after verification",
    ):
        ParquetMarketPathArtifactStore(root).get_verified(
            materialized.artifact_hash
        )


def test_process_verified_cache_enforces_estimated_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb
    import strategy_diagnostics.market_paths as market_paths_module

    first_root = tmp_path / "first-market-paths"
    second_root = tmp_path / "second-market-paths"
    first_path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(first_root),
    ).materialize_baseline(_segment(), seed=17)
    second_path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(second_root),
    ).materialize_baseline(_segment(), seed=18)
    one_path_budget = max(
        market_paths_module._estimated_market_path_retained_bytes(first_path),
        market_paths_module._estimated_market_path_retained_bytes(second_path),
    )
    monkeypatch.setattr(
        market_paths_module,
        "_PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTE_BUDGET",
        one_path_budget,
    )
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None
    original_connect = duckdb.connect
    connect_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", counting_connect)

    first_store = ParquetMarketPathArtifactStore(first_root)
    second_store = ParquetMarketPathArtifactStore(second_root)
    assert first_store.get(first_path.artifact_hash) == first_path
    assert second_store.get(second_path.artifact_hash) == second_path
    assert connect_count == 0
    assert (
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES
        <= one_path_budget
    )
    assert second_store.get(second_path.artifact_hash) == second_path
    assert connect_count == 0
    assert first_store.get(first_path.artifact_hash) == first_path
    assert connect_count == 0


def test_evicted_oversized_paths_use_safe_reread_across_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb
    import strategy_diagnostics.market_paths as market_paths_module

    first_written_root = tmp_path / "first-written-market-paths"
    second_written_root = tmp_path / "second-written-market-paths"
    first_path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(first_written_root),
    ).materialize_baseline(_segment(), seed=17)
    second_path = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(second_written_root),
    ).materialize_baseline(_segment(), seed=18)
    first_root = tmp_path / "first-cold-market-paths"
    second_root = tmp_path / "second-cold-market-paths"
    first_written_root.rename(first_root)
    second_written_root.rename(second_root)
    retained_bytes = max(
        market_paths_module._estimated_market_path_retained_bytes(first_path),
        market_paths_module._estimated_market_path_retained_bytes(second_path),
    )
    monkeypatch.setattr(
        market_paths_module,
        "_PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTE_BUDGET",
        retained_bytes - 1,
    )
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None
    original_connect = duckdb.connect
    connect_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    first_generation = ParquetMarketPathArtifactStore(first_root)
    second_generation = ParquetMarketPathArtifactStore(second_root)

    assert first_generation.get(first_path.artifact_hash) == first_path
    assert second_generation.get(second_path.artifact_hash) == second_path
    assert ParquetMarketPathArtifactStore(first_root).get(
        first_path.artifact_hash
    ) == first_path
    assert ParquetMarketPathArtifactStore(second_root).get(
        second_path.artifact_hash
    ) == second_path

    assert connect_count == 0


def test_legacy_parquet_path_publishes_safe_reread_after_one_native_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb
    import strategy_diagnostics.market_paths as market_paths_module

    written_root = tmp_path / "written-market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(written_root),
    ).materialize_baseline(_segment(), seed=17)
    root = tmp_path / "legacy-market-paths"
    written_root.rename(root)
    artifact_directory = root / materialized.artifact_hash
    for name in (".verified-materialized-path.jsonl.gz",):
        (artifact_directory / name).unlink()
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None
    original_connect = duckdb.connect
    original_replace = Path.replace
    connect_count = 0
    cache_replace_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return original_connect(*args, **kwargs)

    def counting_cache_replace(source: Path, target: Path) -> Path:
        nonlocal cache_replace_count
        if source.name.startswith(".verified-read-cache-"):
            cache_replace_count += 1
        return original_replace(source, target)

    monkeypatch.setattr(duckdb, "connect", counting_connect)
    monkeypatch.setattr(Path, "replace", counting_cache_replace)

    assert (
        ParquetMarketPathArtifactStore(root).get(materialized.artifact_hash)
        == materialized
    )
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None
    assert (
        ParquetMarketPathArtifactStore(root).get(materialized.artifact_hash)
        == materialized
    )

    assert connect_count == 1
    assert cache_replace_count == 1


def test_legacy_cache_publish_failure_does_not_block_authoritative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_diagnostics.market_paths as market_paths_module

    written_root = tmp_path / "written-market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(written_root),
    ).materialize_baseline(_segment(), seed=17)
    root = tmp_path / "legacy-market-paths"
    written_root.rename(root)
    artifact_directory = root / materialized.artifact_hash
    cache_path = (
        artifact_directory / ".verified-materialized-path.jsonl.gz"
    )
    cache_path.unlink()
    with market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_LOCK:
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS.clear()
        market_paths_module._PROCESS_VERIFIED_MARKET_PATHS_ESTIMATED_BYTES = 0
        market_paths_module._PROCESS_VERIFIED_OVERSIZED_MARKET_PATH = None
    original_replace = Path.replace

    def fail_cache_replace(source: Path, target: Path) -> Path:
        if source.name.startswith(".verified-read-cache-"):
            raise PermissionError(
                errno.EACCES,
                "derived cache publication is unavailable",
            )
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_cache_replace)

    assert (
        ParquetMarketPathArtifactStore(root).get(materialized.artifact_hash)
        == materialized
    )
    assert not cache_path.exists()
    assert tuple(artifact_directory.glob(".verified-read-cache-*.tmp")) == ()


def test_parquet_store_serializes_parallel_first_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb

    written_root = tmp_path / "written-market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(written_root),
    ).materialize_baseline(_segment(), seed=17)
    root = tmp_path / "cold-market-paths"
    written_root.rename(root)
    artifact_directory = root / materialized.artifact_hash
    for name in (".verified-materialized-path.jsonl.gz",):
        (artifact_directory / name).unlink()
    original_connect = duckdb.connect
    callers_ready = Barrier(3)
    first_connect_entered = Event()
    second_connect_entered = Event()
    release_connect = Event()
    counter_guard = Lock()
    connect_count = 0
    active_connects = 0
    maximum_active = 0

    def blocking_connect(*args, **kwargs):
        nonlocal connect_count, active_connects, maximum_active
        with counter_guard:
            connect_count += 1
            active_connects += 1
            maximum_active = max(maximum_active, active_connects)
            if connect_count == 1:
                first_connect_entered.set()
            else:
                second_connect_entered.set()
        try:
            if not release_connect.wait(timeout=5):
                raise TimeoutError("test did not release DuckDB connect")
            return original_connect(*args, **kwargs)
        finally:
            with counter_guard:
                active_connects -= 1

    monkeypatch.setattr(duckdb, "connect", blocking_connect)
    reopened_store = ParquetMarketPathArtifactStore(root)

    def load_path():
        callers_ready.wait()
        return reopened_store.get(materialized.artifact_hash)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(load_path)
        second = executor.submit(load_path)
        callers_ready.wait()
        assert first_connect_entered.wait(timeout=5)
        try:
            assert not second_connect_entered.wait(timeout=0.5)
        finally:
            release_connect.set()
        restored = (first.result(timeout=5), second.result(timeout=5))

    assert restored == (materialized, materialized)
    assert connect_count == 1
    assert maximum_active == 1


def test_parquet_store_does_not_publish_cache_after_mid_read_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import duckdb

    written_root = tmp_path / "written-market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(written_root),
    ).materialize_baseline(_segment(), seed=17)
    root = tmp_path / "cold-market-paths"
    written_root.rename(root)
    artifact_directory = root / materialized.artifact_hash
    for name in (".verified-materialized-path.jsonl.gz",):
        (artifact_directory / name).unlink()
    original_connect = duckdb.connect
    first_connect_entered = Event()
    release_connect = Event()
    connect_count = 0

    def blocking_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            first_connect_entered.set()
            if not release_connect.wait(timeout=5):
                raise TimeoutError("test did not release DuckDB connect")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", blocking_connect)
    reopened_store = ParquetMarketPathArtifactStore(root)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            reopened_store.get,
            materialized.artifact_hash,
        )
        assert first_connect_entered.wait(timeout=5)
        manifest_path = root / materialized.artifact_hash / "manifest.json"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        release_connect.set()
        first_result = first.result(timeout=5)

    second_result = reopened_store.get(materialized.artifact_hash)

    assert first_result == materialized
    assert second_result == materialized
    assert connect_count == 2


def test_parquet_store_idempotently_accepts_equivalent_feature_map_order(
    tmp_path: Path,
) -> None:
    root = tmp_path / "market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_two_bar_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize_baseline(_segment(), seed=17)
    reordered = replace(
        materialized,
        nodes=tuple(
            replace(node, features=tuple(reversed(node.features)))
            for node in materialized.nodes
        ),
    )

    restored = ParquetMarketPathArtifactStore(root).put(reordered)

    assert restored.artifact_hash == materialized.artifact_hash
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
                decision_adjustment_factor=Decimal("1.250000"),
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


def test_trend_regime_transform_is_deterministic_and_preserves_path_invariants() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_cross_section_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    request = ScenarioTransformationRequestV1(
        transformation_id="trend-regime.v1",
        parameters={"direction": "bullish", "strength": "0.75"},
    )

    baseline = materializer.materialize_baseline(_segment(), seed=17)
    first = materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )
    second = materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )

    assert first == second
    assert first.artifact_hash == second.artifact_hash
    assert first.artifact_hash != baseline.artifact_hash
    assert first.transformation_catalog_version == (
        "scenario-transformation-catalog.v1"
    )
    assert first.market_rule_profile_version == "a-share-cash-equity.v1"
    assert [item.to_dict() for item in first.applied_transformations] == [
        {
            "transformation_id": "trend-regime.v1",
            "family": "trend-regime",
            "catalog_version": "scenario-transformation-catalog.v1",
            "implementation_version": "trend-regime.v1",
            "parameters": {"direction": "bullish", "strength": "0.75"},
        }
    ]

    assert [
        (node.instrument, node.simulation_time, node.volume)
        for node in first.nodes
    ] == [
        (node.instrument, node.simulation_time, node.volume)
        for node in baseline.nodes
    ]
    assert any(
        transformed.close != original.close
        for transformed, original in zip(first.nodes, baseline.nodes, strict=True)
    )
    for simulation_time in sorted({node.simulation_time for node in first.nodes}):
        transformed_at_time = {
            node.instrument: node
            for node in first.nodes
            if node.simulation_time == simulation_time
        }
        baseline_at_time = {
            node.instrument: node
            for node in baseline.nodes
            if node.simulation_time == simulation_time
        }
        factors = {
            transformed_at_time[instrument].close
            / baseline_at_time[instrument].close
            for instrument in transformed_at_time
        }
        assert len(factors) == 1
        for node in transformed_at_time.values():
            assert node.low <= min(node.open, node.close)
            assert node.high >= max(node.open, node.close)

    previous_closes = {"sh.600000": Decimal("10"), "sz.000001": Decimal("20")}
    for node in first.nodes:
        price_limit = (
            Decimal("0.05")
            if node.instrument == "sz.000001"
            else Decimal("0.10")
        )
        previous_close = previous_closes[node.instrument]
        assert node.low >= previous_close * (Decimal("1") - price_limit)
        assert node.high <= previous_close * (Decimal("1") + price_limit)


class _AdmittedCrossSectionFixtureSource(_AdmittedFixtureSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        return replace(inspection, bar_count=4) if inspection is not None else None

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        return replace(
            _cross_section_world(),
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
        )


class _AdmittedShockFixtureSource(_AdmittedCrossSectionFixtureSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        return replace(inspection, bar_count=14) if inspection is not None else None

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        return replace(
            _shock_world(),
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
        )


class _AdmittedMarketStructureFixtureSource(_AdmittedCrossSectionFixtureSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        return replace(inspection, bar_count=12) if inspection is not None else None

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        return replace(
            _market_structure_world(),
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
        )


def test_volatility_scaling_is_deterministic_and_preserves_path_invariants() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_cross_section_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    request = ScenarioTransformationRequestV1(
        transformation_id="volatility-scaling.v1",
        parameters={"multiplier": "1.5"},
    )

    baseline = materializer.materialize_baseline(_segment(), seed=17)
    first = materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )
    second = materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )

    assert first == second
    assert first.artifact_hash == second.artifact_hash
    assert first.artifact_hash != baseline.artifact_hash
    assert [item.to_dict() for item in first.applied_transformations] == [
        {
            "transformation_id": "volatility-scaling.v1",
            "family": "volatility",
            "catalog_version": "scenario-transformation-catalog.v1",
            "implementation_version": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        }
    ]

    first_shanghai_bar = tuple(
        node
        for node in first.nodes
        if node.instrument == "sh.600000"
        and node.simulation_time <= datetime(2024, 1, 2, 9, 35)
    )
    assert first_shanghai_bar[0].open == Decimal("10")
    assert max(node.high for node in first_shanghai_bar) == Decimal("10.45")
    assert min(node.low for node in first_shanghai_bar) == Decimal("9.85")
    assert first_shanghai_bar[-1].close == Decimal("10.30")
    assert sum(node.volume for node in first_shanghai_bar) == 100
    assert max(
        node.high for node in first.nodes if node.instrument == "sz.000001"
    ) == Decimal("21")

    previous_closes = {"sh.600000": Decimal("10"), "sz.000001": Decimal("20")}
    for node in first.nodes:
        assert node.low <= min(node.open, node.close)
        assert node.high >= max(node.open, node.close)
        assert node.volume >= 0
        price_limit = (
            Decimal("0.05")
            if node.instrument == "sz.000001"
            else Decimal("0.10")
        )
        previous_close = previous_closes[node.instrument]
        assert node.low >= previous_close * (Decimal("1") - price_limit)
        assert node.high <= previous_close * (Decimal("1") + price_limit)
        second = (
            node.simulation_time.hour * 3600
            + node.simulation_time.minute * 60
            + node.simulation_time.second
        )
        assert 9 * 3600 + 30 * 60 < second <= 11 * 3600 + 30 * 60

    def mean_absolute_return(path: object) -> Decimal:
        nodes = getattr(path, "nodes")
        values = [abs(dict(node.features)["return_30s"]) for node in nodes]
        return sum(values, Decimal("0")) / Decimal(len(values))

    assert mean_absolute_return(first) > mean_absolute_return(baseline)


def test_shock_recovery_is_deterministic_and_persists_phase_identity() -> None:
    first = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_shock_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_shock_request(),),
        seed=17,
    )
    second = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_shock_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_shock_request(),),
        seed=17,
    )

    assert first == second
    assert first.artifact_hash == second.artifact_hash
    assert [item.to_dict() for item in first.applied_transformations] == [
        {
            "transformation_id": "shock-recovery.v1",
            "family": "shock-recovery",
            "catalog_version": "scenario-transformation-catalog.v1",
            "implementation_version": "shock-recovery.v1",
            "parameters": {
                "direction": "bearish",
                "gap_fraction": "0.01",
                "persistence_duration_bars": "1",
                "recovery_duration_bars": "2",
                "shock_duration_bars": "2",
                "shock_fraction": "0.03",
            },
            "phase_markers": [
                {
                    "phase": "gap",
                    "start_source_bar_end_time": "2024-01-02T09:35:00",
                    "end_source_bar_end_time": "2024-01-02T09:35:00",
                    "source_time_count": 1,
                },
                {
                    "phase": "shock",
                    "start_source_bar_end_time": "2024-01-02T09:40:00",
                    "end_source_bar_end_time": "2024-01-02T09:45:00",
                    "source_time_count": 2,
                },
                {
                    "phase": "persistence",
                    "start_source_bar_end_time": "2024-01-02T09:50:00",
                    "end_source_bar_end_time": "2024-01-02T09:50:00",
                    "source_time_count": 1,
                },
                {
                    "phase": "recovery",
                    "start_source_bar_end_time": "2024-01-02T09:55:00",
                    "end_source_bar_end_time": "2024-01-02T10:00:00",
                    "source_time_count": 2,
                },
            ],
            "statistics": {
                "affected_source_bar_count": "10",
                "effective_peak_displacement_fraction": "0.04",
                "requested_peak_displacement_fraction": "0.04",
                "source_bar_count": "14",
                "source_time_count": "7",
            },
        }
    ]

    closes_by_time = {
        end_time: next(
            node.close
            for node in first.nodes
            if node.instrument == "sh.600000"
            and node.simulation_time == end_time
        )
        for end_time in (
            datetime(2024, 1, 2, 9, 35) + timedelta(minutes=5 * index)
            for index in range(7)
        )
    }
    assert tuple(closes_by_time.values()) == (
        Decimal("9.9"),
        Decimal("9.75"),
        Decimal("9.6"),
        Decimal("9.6"),
        Decimal("9.8"),
        Decimal("10"),
        Decimal("10"),
    )
    for node in first.nodes:
        assert node.low <= min(node.open, node.close)
        assert node.high >= max(node.open, node.close)
        assert node.volume >= 0
        previous_close = (
            Decimal("20")
            if node.instrument == "sz.000001"
            else Decimal("10")
        )
        price_limit = (
            Decimal("0.05")
            if node.instrument == "sz.000001"
            else Decimal("0.10")
        )
        assert node.low >= previous_close * (Decimal("1") - price_limit)
        assert node.high <= previous_close * (Decimal("1") + price_limit)
        second_of_day = (
            node.simulation_time.hour * 3600
            + node.simulation_time.minute * 60
            + node.simulation_time.second
        )
        assert 9 * 3600 + 30 * 60 < second_of_day <= 11 * 3600 + 30 * 60


def test_shock_recovery_uses_the_tightest_cross_sectional_price_limit() -> None:
    request = ScenarioTransformationRequestV1(
        transformation_id="shock-recovery.v1",
        parameters={
            **_shock_request().parameters,
            "direction": "bullish",
            "gap_fraction": "0.04",
            "shock_fraction": "0.03",
        },
    )
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_shock_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )

    for simulation_time in sorted(
        {node.simulation_time for node in materialized.nodes}
    ):
        nodes = tuple(
            node
            for node in materialized.nodes
            if node.simulation_time == simulation_time
        )
        factors = {
            node.close
            / (Decimal("20") if node.instrument == "sz.000001" else Decimal("10"))
            for node in nodes
        }
        assert len(factors) == 1
    assert max(
        node.high
        for node in materialized.nodes
        if node.instrument == "sz.000001"
    ) == Decimal("21")
    assert max(
        node.high
        for node in materialized.nodes
        if node.instrument == "sh.600000"
    ) == Decimal("10.5")
    assert dict(materialized.applied_transformations[0].statistics) == {
        "affected_source_bar_count": "10",
        "effective_peak_displacement_fraction": "0.05",
        "requested_peak_displacement_fraction": "0.07",
        "source_bar_count": "14",
        "source_time_count": "7",
    }


def test_shock_recovery_rejects_incompatible_phase_duration() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_cross_section_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="requires at least 6 distinct source bar times"):
        materializer.materialize(
            _segment(),
            transformations=(_shock_request(),),
            seed=17,
        )


def test_shock_recovery_phase_identity_survives_artifact_store_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "shock-market-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_shock_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize(
        _segment(),
        transformations=(_shock_request(),),
        seed=17,
    )

    restored = ParquetMarketPathArtifactStore(root).get(
        materialized.artifact_hash
    )

    assert restored == materialized
    assert restored.applied_transformations[0].to_dict() == materialized.applied_transformations[
        0
    ].to_dict()


def test_market_structure_is_deterministic_and_recomputes_the_full_world() -> None:
    request = _market_structure_request()
    first_materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_market_structure_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    baseline = first_materializer.materialize_baseline(_segment(), seed=17)
    first = first_materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )
    second = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_market_structure_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )
    distributed = first_materializer.materialize(
        _segment(),
        transformations=(
            ScenarioTransformationRequestV1(
                transformation_id="market-structure.v1",
                parameters={
                    **request.parameters,
                    "sector_concentration": "0",
                },
            ),
        ),
        seed=17,
    )

    assert first.artifact_hash == second.artifact_hash
    assert first.to_preview_dict() == second.to_preview_dict()
    assert distributed.artifact_hash != first.artifact_hash
    assert dict(distributed.applied_transformations[0].statistics)[
        "effective_final_sector_winner_concentration"
    ] == "0.5"
    assert first.applied_transformations[0].to_dict() == {
        "transformation_id": "market-structure.v1",
        "family": "market-structure",
        "catalog_version": "scenario-transformation-catalog.v1",
        "implementation_version": "market-structure.v1",
        "parameters": {
            "breadth_target": "0.5",
            "dispersion_fraction": "0.04",
            "sector_concentration": "1",
        },
        "statistics": {
            "affected_source_bar_count": "7",
            "effective_final_breadth": "0.5",
            "effective_final_return_spread_fraction": "0.04",
            "effective_final_sector_winner_concentration": "1",
            "source_bar_count": "12",
            "source_time_count": "3",
        },
    }
    assert all(node.low <= node.open <= node.high for node in first.nodes)
    assert all(node.low <= node.close <= node.high for node in first.nodes)
    assert all(
        Decimal("9") <= node.low <= node.high <= Decimal("11")
        for node in first.nodes
    )
    assert all(node.volume >= 0 for node in first.nodes)
    final_closes = {
        instrument: next(
            node.close
            for node in reversed(first.nodes)
            if node.instrument == instrument
        )
        for instrument in (
            "sh.600000",
            "sh.600001",
            "sz.000001",
            "sz.000002",
        )
    }
    assert final_closes == {
        "sh.600000": Decimal("10.2"),
        "sh.600001": Decimal("10.2"),
        "sz.000001": Decimal("9.8"),
        "sz.000002": Decimal("9.8"),
    }

    baseline_snapshot = ScenarioMarketView(
        baseline,
        initial_cursor=datetime(2024, 1, 2, 9, 45),
    ).snapshot().to_dict()
    transformed_snapshot = ScenarioMarketView(
        first,
        initial_cursor=datetime(2024, 1, 2, 9, 45),
    ).snapshot().to_dict()
    assert baseline_snapshot["market_context"] == {
        "return": "0.025",
        "breadth": "1",
        "instrument_count": 4,
    }
    assert transformed_snapshot["market_context"] == {
        "return": "0",
        "breadth": "0.5",
        "instrument_count": 4,
    }
    assert transformed_snapshot["sector_context"] == {
        "banking": {
            "return": "0.02",
            "breadth": "1",
            "instrument_count": 2,
        },
        "technology": {
            "return": "-0.02",
            "breadth": "0",
            "instrument_count": 2,
        },
    }
    assert baseline_snapshot["features"] != transformed_snapshot["features"]
    assert baseline_snapshot["rankings"] != transformed_snapshot["rankings"]
    assert transformed_snapshot["candidates"] == [
        "sh.600000",
        "sh.600001",
        "sz.000001",
        "sz.000002",
    ]


def test_market_structure_never_uses_future_source_bars() -> None:
    original = _market_structure_world()
    changed_future_bars = tuple(
        replace(
            bar,
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("9.9"),
            close=Decimal("9.9"),
            amount=Decimal("990"),
        )
        if bar.end_time == datetime(2024, 1, 2, 9, 45)
        else bar
        for bar in original.bars
    )
    changed_future = replace(original, bars=changed_future_bars)

    first = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((original,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_market_structure_request(),),
        seed=17,
    )
    second = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((changed_future,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_market_structure_request(),),
        seed=17,
    )

    cutoff = datetime(2024, 1, 2, 9, 40)
    assert tuple(
        node for node in first.nodes if node.simulation_time <= cutoff
    ) == tuple(
        node for node in second.nodes if node.simulation_time <= cutoff
    )


def test_market_structure_requires_multiple_point_in_time_industries() -> None:
    world = _market_structure_world()
    single_industry_world = replace(
        world,
        instrument_states=tuple(
            replace(state, industry="banking") for state in world.instrument_states
        ),
    )
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((single_industry_world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="multiple point-in-time industries"):
        materializer.materialize(
            _segment(),
            transformations=(_market_structure_request(),),
            seed=17,
        )


def test_market_structure_identity_survives_artifact_store_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "market-structure-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_market_structure_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize(
        _segment(),
        transformations=(_market_structure_request(),),
        seed=17,
    )

    restored = ParquetMarketPathArtifactStore(root).get(
        materialized.artifact_hash
    )

    assert restored == materialized
    assert restored.applied_transformations[0].to_dict() == (
        materialized.applied_transformations[0].to_dict()
    )


def test_liquidity_stress_is_deterministic_and_conserves_scaled_volume() -> None:
    first_materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_liquidity_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    baseline = first_materializer.materialize_baseline(_segment(), seed=17)
    first = first_materializer.materialize(
        _segment(),
        transformations=(_liquidity_request(),),
        seed=17,
    )
    second = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_liquidity_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_liquidity_request(),),
        seed=17,
    )

    assert first.artifact_hash == second.artifact_hash
    assert first.to_preview_dict() == second.to_preview_dict()
    assert first.artifact_hash != baseline.artifact_hash
    assert first.applied_transformations[0].to_dict() == {
        "transformation_id": "liquidity-stress.v1",
        "family": "liquidity",
        "catalog_version": "scenario-transformation-catalog.v1",
        "implementation_version": "liquidity-stress.v1",
        "parameters": {
            "cross_sectional_concentration": "1",
            "volume_multiplier": "0.5",
        },
        "statistics": {
            "affected_source_bar_count": "6",
            "effective_top_volume_share": "0.5",
            "effective_volume_multiplier": "0.5",
            "scaled_volume_conservation_error": "0",
            "source_bar_count": "6",
            "source_time_count": "2",
            "source_volume_total": "2000",
            "transformed_volume_total": "1000",
        },
    }
    assert all(node.volume >= 0 and node.amount >= 0 for node in first.nodes)
    assert tuple(
        (node.open, node.high, node.low, node.close) for node in first.nodes
    ) == tuple(
        (node.open, node.high, node.low, node.close) for node in baseline.nodes
    )
    assert {
        instrument: sum(
            node.volume for node in first.nodes if node.instrument == instrument
        )
        for instrument in ("sh.600000", "sh.600001", "sz.000001")
    } == {
        "sh.600000": 166,
        "sh.600001": 334,
        "sz.000001": 500,
    }
    for end_time in (datetime(2024, 1, 2, 9, 35), datetime(2024, 1, 2, 9, 40)):
        start_time = end_time - timedelta(minutes=5)
        assert sum(
            node.volume
            for node in first.nodes
            if start_time < node.simulation_time <= end_time
        ) == 500

    baseline_snapshot = ScenarioMarketView(
        baseline,
        initial_cursor=datetime(2024, 1, 2, 9, 40),
    ).snapshot().to_dict()
    transformed_snapshot = ScenarioMarketView(
        first,
        initial_cursor=datetime(2024, 1, 2, 9, 40),
    ).snapshot().to_dict()
    assert baseline_snapshot["features"] != transformed_snapshot["features"]
    assert [item["instrument"] for item in baseline_snapshot["rankings"]] == [
        "sh.600000",
        "sz.000001",
        "sh.600001",
    ]
    assert [item["instrument"] for item in transformed_snapshot["rankings"]] == [
        "sh.600000",
        "sh.600001",
        "sz.000001",
    ]
    final_features = transformed_snapshot["features"]["sh.600001"]
    assert {
        "capacity_proxy_30s",
        "relative_liquidity",
        "session_turnover_value",
        "session_volume",
    }.issubset(final_features)


def test_liquidity_stress_preserves_zero_volume_nonrecipients() -> None:
    world = _liquidity_world()
    zero_volume_bars = tuple(
        FiveMinuteBar(
            instrument="sh.600002",
            end_time=end_time,
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=0,
            amount=Decimal("0"),
        )
        for end_time in (
            datetime(2024, 1, 2, 9, 35),
            datetime(2024, 1, 2, 9, 40),
        )
    )
    extended = replace(
        world,
        bars=tuple(sorted(
            (*world.bars, *zero_volume_bars),
            key=lambda bar: (bar.end_time, bar.instrument),
        )),
        instrument_states=(
            *world.instrument_states,
            InstrumentState(
                instrument="sh.600002",
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="utilities",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            ),
        ),
        price_limit_references=(
            *world.price_limit_references,
            SessionPriceLimitReference(
                instrument="sh.600002",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="fixture.sh-main.ordinary.10pct",
            ),
        ),
    )
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((extended,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(_liquidity_request(),),
        seed=17,
    )

    zero_nodes = tuple(
        node for node in materialized.nodes if node.instrument == "sh.600002"
    )
    assert zero_nodes
    assert all(node.volume == 0 and node.amount == 0 for node in zero_nodes)
    assert dict(materialized.applied_transformations[0].statistics)[
        "scaled_volume_conservation_error"
    ] == "0"


def test_liquidity_stress_identity_survives_artifact_store_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "liquidity-paths"
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_liquidity_world(),)),
        artifact_store=ParquetMarketPathArtifactStore(root),
    ).materialize(
        _segment(),
        transformations=(_liquidity_request(),),
        seed=17,
    )

    restored = ParquetMarketPathArtifactStore(root).get(
        materialized.artifact_hash
    )

    assert restored == materialized
    assert restored.applied_transformations[0].to_dict() == (
        materialized.applied_transformations[0].to_dict()
    )


def test_volatility_scaling_fails_closed_without_previous_close_reference() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource(
            (replace(_world(), price_limit_references=()),)
        ),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="previous-close reference"):
        materializer.materialize(
            _segment(),
            transformations=(
                ScenarioTransformationRequestV1(
                    transformation_id="volatility-scaling.v1",
                    parameters={"multiplier": "1.5"},
                ),
            ),
            seed=17,
        )


def test_volatility_scaling_fails_closed_on_point_in_time_rule_mismatch() -> None:
    reference = replace(
        _world().price_limit_references[0],
        is_st=True,
        limit_fraction=Decimal("0.05"),
        rule_code="fixture.sh-main.risk-warning.5pct",
    )
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource(
            (replace(_world(), price_limit_references=(reference,)),)
        ),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="disagree"):
        materializer.materialize(
            _segment(),
            transformations=(
                ScenarioTransformationRequestV1(
                    transformation_id="volatility-scaling.v1",
                    parameters={"multiplier": "1.5"},
                ),
            ),
            seed=17,
        )


def test_volatility_scaling_does_not_hide_source_price_limit_violations() -> None:
    invalid_source = FiveMinuteBar(
        instrument="sh.600000",
        end_time=datetime(2024, 1, 2, 15, 0),
        open=Decimal("10.80"),
        high=Decimal("11.01"),
        low=Decimal("10.70"),
        close=Decimal("10.98"),
        volume=100,
        amount=Decimal("1090"),
    )
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource(
            (replace(_world(), bars=(invalid_source,)),)
        ),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="source data already exceeds"):
        materializer.materialize(
            _segment(),
            transformations=(
                ScenarioTransformationRequestV1(
                    transformation_id="volatility-scaling.v1",
                    parameters={"multiplier": "0.5"},
                ),
            ),
            seed=17,
        )


@pytest.mark.parametrize(
    ("direction", "source_bar", "bound", "extreme"),
    (
        (
            "bullish",
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 15, 0),
                open=Decimal("10.80"),
                high=Decimal("10.99"),
                low=Decimal("10.70"),
                close=Decimal("10.98"),
                volume=100,
                amount=Decimal("1090"),
            ),
            Decimal("11.00"),
            "high",
        ),
        (
            "bearish",
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 15, 0),
                open=Decimal("9.20"),
                high=Decimal("9.30"),
                low=Decimal("9.01"),
                close=Decimal("9.02"),
                volume=100,
                amount=Decimal("910"),
            ),
            Decimal("9.00"),
            "low",
        ),
    ),
)
def test_trend_regime_uses_previous_close_for_gap_day_price_limits(
    direction: str,
    source_bar: FiveMinuteBar,
    bound: Decimal,
    extreme: str,
) -> None:
    world = replace(
        _world(),
        bars=(source_bar,),
        price_limit_references=(
            SessionPriceLimitReference(
                instrument="sh.600000",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10.00"),
                effective_at=datetime(2024, 1, 2, 9, 30),
                provenance="fixture-preclose-v1",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="fixture.sh-main.ordinary.10pct",
            ),
        ),
    )
    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(
            ScenarioTransformationRequestV1(
                transformation_id="trend-regime.v1",
                parameters={"direction": direction, "strength": "1"},
            ),
        ),
        seed=17,
    )

    values = tuple(getattr(node, extreme) for node in materialized.nodes)
    if direction == "bullish":
        assert max(values) <= bound
    else:
        assert min(values) >= bound


def test_trend_regime_fails_closed_without_previous_close_reference() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource(
            (replace(_world(), price_limit_references=()),)
        ),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="previous-close reference"):
        materializer.materialize(
            _segment(),
            transformations=(
                ScenarioTransformationRequestV1(
                    transformation_id="trend-regime.v1",
                    parameters={"direction": "bullish", "strength": "1"},
                ),
            ),
            seed=17,
        )


def test_trend_regime_does_not_invent_limits_for_initial_unbounded_session() -> None:
    source_bar = FiveMinuteBar(
        instrument="sh.600000",
        end_time=datetime(2024, 1, 2, 15, 0),
        open=Decimal("10.80"),
        high=Decimal("10.99"),
        low=Decimal("10.70"),
        close=Decimal("10.98"),
        volume=100,
        amount=Decimal("1090"),
    )
    reference = replace(
        _world().price_limit_references[0],
        listing_stage="initial-unbounded",
        limit_fraction=None,
        rule_code="fixture.sh-main.ipo-initial-unbounded.v1",
    )
    world = replace(
        _world(),
        bars=(source_bar,),
        price_limit_references=(reference,),
    )

    materialized = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    ).materialize(
        _segment(),
        transformations=(
            ScenarioTransformationRequestV1(
                transformation_id="trend-regime.v1",
                parameters={"direction": "bullish", "strength": "1"},
            ),
        ),
        seed=17,
    )

    assert max(node.high for node in materialized.nodes) > Decimal("11.00")


def test_trend_regime_fails_closed_when_rule_and_st_state_disagree() -> None:
    reference = replace(
        _world().price_limit_references[0],
        is_st=True,
        limit_fraction=Decimal("0.05"),
        rule_code="fixture.sh-main.risk-warning.5pct",
    )
    world = replace(_world(), price_limit_references=(reference,))
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((world,)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )

    with pytest.raises(ValueError, match="disagree"):
        materializer.materialize(
            _segment(),
            transformations=(
                ScenarioTransformationRequestV1(
                    transformation_id="trend-regime.v1",
                    parameters={"direction": "bullish", "strength": "1"},
                ),
            ),
            seed=17,
        )


def test_transformed_world_recomputes_every_derived_scenario_data_family() -> None:
    materializer = ScenarioMaterializer(
        source=InMemoryHistoricalMarketDataSource((_cross_section_world(),)),
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    request = ScenarioTransformationRequestV1(
        transformation_id="trend-regime.v1",
        parameters={"direction": "bullish", "strength": "0.75"},
    )
    baseline = materializer.materialize_baseline(_segment(), seed=17)
    transformed = materializer.materialize(
        _segment(),
        transformations=(request,),
        seed=17,
    )

    def snapshot(path: object) -> dict[str, object]:
        return ScenarioMarketView(
            path,
            initial_cursor=datetime(2024, 1, 2, 9, 40),
        ).snapshot().to_dict()

    baseline_snapshot = snapshot(baseline)
    transformed_snapshot = snapshot(transformed)

    def expected_session_returns(path: object) -> dict[str, Decimal]:
        nodes = getattr(path, "nodes")
        return {
            instrument: (
                next(
                    node.close
                    for node in reversed(nodes)
                    if node.instrument == instrument
                )
                / next(node.open for node in nodes if node.instrument == instrument)
                - Decimal("1")
            )
            for instrument in ("sh.600000", "sz.000001")
        }

    returns = expected_session_returns(transformed)
    expected_market_return = sum(returns.values(), Decimal("0")) / Decimal("2")
    expected_market_text = format(expected_market_return.normalize(), "f")
    transformed_nodes = getattr(transformed, "nodes")
    session_volumes = {
        instrument: Decimal(
            sum(
                node.volume
                for node in transformed_nodes
                if node.instrument == instrument
            )
        )
        for instrument in ("sh.600000", "sz.000001")
    }
    market_session_volume = sum(
        session_volumes.values(),
        Decimal("0"),
    ) / Decimal("2")
    expected_scores = {
        instrument: (
            value
            - expected_market_return
            + Decimal("0.01")
            * (session_volumes[instrument] / market_session_volume - Decimal("1"))
        )
        for instrument, value in returns.items()
    }
    expected_ranking = tuple(
        sorted(
            expected_scores,
            key=lambda instrument: (-expected_scores[instrument], instrument),
        )
    )

    assert transformed_snapshot["market_context"] == {
        "return": expected_market_text,
        "breadth": "1",
        "instrument_count": 2,
    }
    assert transformed_snapshot["sector_context"] == {
        "banking": {
            "return": expected_market_text,
            "breadth": "1",
            "instrument_count": 2,
        }
    }
    assert transformed_snapshot["candidates"] == list(expected_ranking)
    assert transformed_snapshot["rankings"] == [
        {
            "instrument": instrument,
            "rank": rank,
            "score": format(expected_scores[instrument].normalize(), "f"),
        }
        for rank, instrument in enumerate(expected_ranking, start=1)
    ]
    assert set(transformed_snapshot["features"]["sh.600000"]) == {
        "capacity_proxy_30s",
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_liquidity",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
        "session_turnover_value",
        "session_volume",
    }
    assert transformed_snapshot["market_context"] != baseline_snapshot[
        "market_context"
    ]
    assert transformed_snapshot["rankings"] != baseline_snapshot["rankings"]


def test_headless_application_previews_baseline_versus_transformed_results() -> None:
    source = _AdmittedFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None
    baseline_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
        seed=17,
    )
    transformed_payload = {
        "schema_version": "scenario_recipe.v1",
        "name": "Bullish trend",
        "historical_segment_id": admission.segment.segment_id,
        "transformations": [
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {"direction": "bullish", "strength": "0.75"},
            }
        ],
        "execution_conditions": {},
        "decision_cadence_minutes": 30,
        "materialization_seed": 17,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }
    transformed_draft = application.create_manual_recipe_draft(
        transformed_payload,
        author="test",
    )
    assert application.validate_recipe_draft(transformed_draft.draft_id).is_valid
    transformed_version_id = application.approve_recipe_draft(
        transformed_draft.draft_id,
        actor="test-owner",
    ).version_id

    with pytest.raises(ValueError, match="baseline"):
        application.materialize_baseline_reference_path(transformed_version_id)
    baseline = application.materialize_reference_path(baseline_version_id)
    transformed = application.materialize_reference_path(transformed_version_id)
    comparison = application.compare_reference_market_paths(
        baseline.artifact_hash,
        transformed.artifact_hash,
        at_time=datetime(2024, 1, 2, 9, 40),
    )

    assert comparison["status"] == "ready"
    assert comparison["simulation_time"] == "2024-01-02T09:40:00"
    assert comparison["baseline"]["artifact_hash"] == baseline.artifact_hash
    assert comparison["transformed"]["artifact_hash"] == transformed.artifact_hash
    assert comparison["baseline"]["market_context"] != comparison["transformed"][
        "market_context"
    ]
    assert comparison["baseline"]["candidates"] == comparison["transformed"][
        "candidates"
    ]
    assert Decimal(str(comparison["market_return_delta"])) > 0


def test_headless_application_previews_volatility_and_recomputed_statistics() -> None:
    source = _AdmittedCrossSectionFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None
    baseline_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
        seed=17,
    )
    volatility_payload = {
        "schema_version": "scenario_recipe.v1",
        "name": "Amplified volatility",
        "historical_segment_id": admission.segment.segment_id,
        "transformations": [
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.5"},
            }
        ],
        "execution_conditions": {},
        "decision_cadence_minutes": 30,
        "materialization_seed": 17,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }
    volatility_draft = application.create_manual_recipe_draft(
        volatility_payload,
        author="test",
    )
    assert application.validate_recipe_draft(volatility_draft.draft_id).is_valid
    volatility_version_id = application.approve_recipe_draft(
        volatility_draft.draft_id,
        actor="test-owner",
    ).version_id
    baseline = application.materialize_reference_path(baseline_version_id)
    transformed = application.materialize_reference_path(volatility_version_id)

    comparison = application.compare_reference_market_paths(
        baseline.artifact_hash,
        transformed.artifact_hash,
        at_time=datetime(2024, 1, 2, 9, 40),
    )

    transformed_preview = comparison["transformed"]
    assert transformed_preview["applied_transformations"] == [
        {
            "transformation_id": "volatility-scaling.v1",
            "family": "volatility",
            "catalog_version": "scenario-transformation-catalog.v1",
            "implementation_version": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        }
    ]
    assert transformed_preview["market_context"] == {
        "return": "0.04875",
        "breadth": "1",
        "instrument_count": 2,
    }
    assert transformed_preview["sector_context"] == {
        "banking": {
            "return": "0.04875",
            "breadth": "1",
            "instrument_count": 2,
        }
    }
    assert transformed_preview["candidates"] == ["sh.600000", "sz.000001"]
    expected_sh_score = Decimal("0.00375") + Decimal("0.01") * (
        Decimal("210") / Decimal("310") - Decimal("1")
    )
    expected_sz_score = Decimal("-0.00375") + Decimal("0.01") * (
        Decimal("410") / Decimal("310") - Decimal("1")
    )
    assert [item["instrument"] for item in transformed_preview["rankings"]] == [
        "sh.600000",
        "sz.000001",
    ]
    assert Decimal(str(transformed_preview["rankings"][0]["score"])) == (
        expected_sh_score
    )
    assert Decimal(str(transformed_preview["rankings"][1]["score"])) == (
        expected_sz_score
    )
    assert set(transformed_preview["features"]["sh.600000"]) == {
        "capacity_proxy_30s",
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_liquidity",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
        "session_turnover_value",
        "session_volume",
    }
    baseline_statistics = comparison["baseline"]["path_statistics"]
    transformed_statistics = transformed_preview["path_statistics"]
    assert transformed_statistics["node_count"] == 40
    assert Decimal(
        str(transformed_statistics["mean_absolute_return_30s"])
    ) > Decimal(str(baseline_statistics["mean_absolute_return_30s"]))
    assert Decimal(
        str(transformed_statistics["mean_range_fraction_30s"])
    ) > Decimal(str(baseline_statistics["mean_range_fraction_30s"]))


def test_headless_application_previews_shock_phases_and_recomputed_statistics() -> None:
    source = _AdmittedShockFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None
    baseline_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
        seed=17,
    )
    shock_payload = {
        "schema_version": "scenario_recipe.v1",
        "name": "Bearish shock and recovery",
        "historical_segment_id": admission.segment.segment_id,
        "transformations": [
            {
                "transformation_id": "shock-recovery.v1",
                "parameters": _shock_request().parameters,
            }
        ],
        "execution_conditions": {},
        "decision_cadence_minutes": 30,
        "materialization_seed": 17,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }
    shock_draft = application.create_manual_recipe_draft(
        shock_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(shock_draft.draft_id).is_valid
    shock_version_id = application.approve_recipe_draft(
        shock_draft.draft_id,
        actor="owner",
    ).version_id
    baseline = application.materialize_reference_path(baseline_version_id)
    transformed = application.materialize_reference_path(shock_version_id)

    comparison = application.compare_reference_market_paths(
        baseline.artifact_hash,
        transformed.artifact_hash,
        at_time=datetime(2024, 1, 2, 10, 5),
    )

    baseline_preview = comparison["baseline"]
    transformed_preview = comparison["transformed"]
    assert transformed_preview["reconstructed"] is True
    assert transformed_preview["source_resolution"] == "5m"
    assert transformed_preview["runtime_resolution"] == "30s"
    assert transformed_preview["reconstruction_notice"] == (
        "Reconstructed 30-second path from admitted 5-minute bars; "
        "not recorded microstructure."
    )
    applied = transformed_preview["applied_transformations"][0]
    assert [marker["phase"] for marker in applied["phase_markers"]] == [
        "gap",
        "shock",
        "persistence",
        "recovery",
    ]
    assert applied["statistics"] == {
        "affected_source_bar_count": "10",
        "effective_peak_displacement_fraction": "0.04",
        "requested_peak_displacement_fraction": "0.04",
        "source_bar_count": "14",
        "source_time_count": "7",
    }
    assert Decimal(str(comparison["market_return_delta"])) != 0
    assert baseline_preview["market_context"] != transformed_preview["market_context"]
    assert baseline_preview["sector_context"] != transformed_preview["sector_context"]
    assert baseline_preview["features"] != transformed_preview["features"]
    assert baseline_preview["rankings"] == transformed_preview["rankings"]
    assert Decimal(
        str(transformed_preview["path_statistics"]["mean_absolute_return_30s"])
    ) > Decimal(
        str(baseline_preview["path_statistics"]["mean_absolute_return_30s"])
    )


def test_headless_application_previews_requested_and_effective_market_structure() -> None:
    source = _AdmittedMarketStructureFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None
    baseline_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
        seed=17,
    )
    structure_payload = {
        "schema_version": "scenario_recipe.v1",
        "name": "Concentrated two-sector structure",
        "historical_segment_id": admission.segment.segment_id,
        "transformations": [
            {
                "transformation_id": "market-structure.v1",
                "parameters": _market_structure_request().parameters,
            }
        ],
        "execution_conditions": {},
        "decision_cadence_minutes": 30,
        "materialization_seed": 17,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }
    structure_draft = application.create_manual_recipe_draft(
        structure_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(structure_draft.draft_id).is_valid
    structure_version_id = application.approve_recipe_draft(
        structure_draft.draft_id,
        actor="owner",
    ).version_id
    baseline = application.materialize_reference_path(baseline_version_id)
    transformed = application.materialize_reference_path(structure_version_id)

    comparison = application.compare_reference_market_paths(
        baseline.artifact_hash,
        transformed.artifact_hash,
        at_time=datetime(2024, 1, 2, 9, 45),
    )

    baseline_preview = comparison["baseline"]
    transformed_preview = comparison["transformed"]
    applied = transformed_preview["applied_transformations"][0]
    assert applied["parameters"] == {
        "breadth_target": "0.5",
        "dispersion_fraction": "0.04",
        "sector_concentration": "1",
    }
    assert applied["statistics"] == {
        "affected_source_bar_count": "7",
        "effective_final_breadth": "0.5",
        "effective_final_return_spread_fraction": "0.04",
        "effective_final_sector_winner_concentration": "1",
        "source_bar_count": "12",
        "source_time_count": "3",
    }
    assert baseline_preview["market_context"] != transformed_preview[
        "market_context"
    ]
    assert baseline_preview["sector_context"] != transformed_preview[
        "sector_context"
    ]
    assert baseline_preview["features"] != transformed_preview["features"]
    assert baseline_preview["rankings"] != transformed_preview["rankings"]
    assert transformed_preview["market_context"]["breadth"] == "0.5"
    assert transformed_preview["sector_context"] == {
        "banking": {
            "return": "0.02",
            "breadth": "1",
            "instrument_count": 2,
        },
        "technology": {
            "return": "-0.02",
            "breadth": "0",
            "instrument_count": 2,
        },
    }
