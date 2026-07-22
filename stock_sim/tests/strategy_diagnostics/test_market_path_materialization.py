from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

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
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
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
    expected_scores = {
        instrument: value - expected_market_return
        for instrument, value in returns.items()
    }

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
    assert transformed_snapshot["candidates"] == ["sh.600000", "sz.000001"]
    assert transformed_snapshot["rankings"] == [
        {
            "instrument": "sh.600000",
            "rank": 1,
            "score": format(expected_scores["sh.600000"].normalize(), "f"),
        },
        {
            "instrument": "sz.000001",
            "rank": 2,
            "score": format(expected_scores["sz.000001"].normalize(), "f"),
        },
    ]
    assert set(transformed_snapshot["features"]["sh.600000"]) == {
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
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
    assert transformed_preview["rankings"] == [
        {"instrument": "sh.600000", "rank": 1, "score": "0.00375"},
        {"instrument": "sz.000001", "rank": 2, "score": "-0.00375"},
    ]
    assert set(transformed_preview["features"]["sh.600000"]) == {
        "candidate_rank",
        "candidate_score",
        "market_breadth",
        "market_return",
        "relative_strength",
        "return_30s",
        "sector_breadth",
        "sector_return",
        "session_return",
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
