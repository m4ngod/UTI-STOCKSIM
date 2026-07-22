from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.panels.diagnostics.panel import DiagnosticsPanel
from app.ui.adapters.diagnostics_adapter import DiagnosticsPanelAdapter
from strategy_diagnostics import (
    A_SHARE_EXECUTION_REASON_CODES,
    AdmissionCheck,
    FiveMinuteBar,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryMarketPathArtifactStore,
    InMemoryHistoricalSource,
    InstrumentState,
    ScenarioDataWorldInput,
    SessionPriceLimitReference,
    SourceArtifact,
    SourceProvenance,
    UnapprovedScenarioRecipeError,
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


class _WorkspaceSource:
    def __init__(self) -> None:
        selection = HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
        self._source = InMemoryHistoricalSource(
            (
                HistoricalSourceInspection(
                    selection=selection,
                    label="Visible diagnostic interval",
                    provenance=SourceProvenance(
                        provider="BaoStock",
                        dataset="workspace-fixture",
                        version="v1",
                        observed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    ),
                    artifacts=(SourceArtifact("bars", "f" * 64, 48),),
                    eligible_instrument_count=1,
                    trading_day_count=1,
                    bar_count=48,
                    checks=tuple(
                        AdmissionCheck(code, True, f"{code} passed")
                        for code in REQUIRED_CHECKS
                    ),
                ),
            )
        )

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        return self._source.inspect(selection)

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
            bars=(
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 35),
                    open=Decimal("10"),
                    high=Decimal("10.2"),
                    low=Decimal("9.9"),
                    close=Decimal("10.1"),
                    volume=100,
                    amount=Decimal("1005"),
                ),
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 40),
                    open=Decimal("10.1"),
                    high=Decimal("10.4"),
                    low=Decimal("10.0"),
                    close=Decimal("10.3"),
                    volume=120,
                    amount=Decimal("1225"),
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
            ),
            price_limit_references=(
                SessionPriceLimitReference(
                    instrument="sh.600000",
                    session_date=date(2024, 1, 2),
                    previous_close=Decimal("10"),
                    effective_at=datetime(2024, 1, 2, 9, 30),
                    provenance="fixture-preclose-v1",
                    profile_version="a-share-cash-equity.v1",
                    board="sh-main",
                    is_st=False,
                    listing_stage="continuous",
                    limit_fraction=Decimal("0.10"),
                    rule_code="sh-main.ordinary.10pct.effective-2024-01-02",
                ),
            ),
        )


class _ExecutionWorkspaceSource(_WorkspaceSource):
    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
            bars=tuple(
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=end_time,
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("10"),
                    close=Decimal("10"),
                    volume=100_000,
                    amount=Decimal("1000000"),
                )
                for end_time in (
                    datetime(2024, 1, 2, 10, 0),
                    datetime(2024, 1, 2, 10, 5),
                )
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
            ),
            price_limit_references=(
                SessionPriceLimitReference(
                    instrument="sh.600000",
                    session_date=date(2024, 1, 2),
                    previous_close=Decimal("10"),
                    effective_at=datetime(2024, 1, 2, 9, 30),
                    provenance="fixture-preclose-v1",
                    profile_version="a-share-cash-equity.v1",
                    board="sh-main",
                    is_st=False,
                    listing_stage="continuous",
                    limit_fraction=Decimal("0.10"),
                    rule_code="sh-main.ordinary.10pct.effective-2024-01-02",
                ),
            ),
        )


class _ShockWorkspaceSource(_WorkspaceSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        if inspection is None:
            return None
        return replace(
            inspection,
            artifacts=(SourceArtifact("shock-bars", "e" * 64, 7),),
            bar_count=7,
        )

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
        bars = tuple(
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 9, 35)
                + timedelta(minutes=5 * index),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=100 + index,
                amount=Decimal("10") * (100 + index),
            )
            for index in range(7)
        )
        base = super().load_scenario_data_world(segment)
        return replace(base, bars=bars)


class _MarketStructureWorkspaceSource(_WorkspaceSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        if inspection is None:
            return None
        return replace(
            inspection,
            artifacts=(SourceArtifact("market-structure-bars", "d" * 64, 12),),
            eligible_instrument_count=4,
            bar_count=12,
        )

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
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
        previous_closes = {
            instrument: Decimal("10") for instrument, _industry, _board in instruments
        }
        bars: list[FiveMinuteBar] = []
        for end_time, closes in closes_by_time:
            for (instrument, _industry, _board), close_text in zip(
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
                        volume=100,
                        amount=close * 100,
                    )
                )
                previous_closes[instrument] = close
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
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


class _LiquidityWorkspaceSource(_WorkspaceSource):
    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        inspection = super().inspect(selection)
        if inspection is None:
            return None
        return replace(
            inspection,
            artifacts=(SourceArtifact("liquidity-bars", "c" * 64, 6),),
            eligible_instrument_count=3,
            bar_count=6,
        )

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
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
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
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


def _admittable_application() -> object:
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )
    source = _WorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _execution_admittable_application() -> object:
    source = _ExecutionWorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _shock_admittable_application() -> object:
    source = _ShockWorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _market_structure_admittable_application() -> object:
    source = _MarketStructureWorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _liquidity_admittable_application() -> object:
    source = _LiquidityWorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


def _ensure_qapp() -> object | None:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance() or QApplication([])


def test_diagnostics_panel_uses_the_headless_application_interface() -> None:
    application = create_diagnostics_application()
    panel = DiagnosticsPanel(application)

    view = panel.get_view()

    assert {
        key: view[key] for key in application.status().to_dict()
    } == application.status().to_dict()
    assert view["workspace"] == "Diagnostics"
    assert view["status"] == "ready"
    assert view["historical_segment_catalog"] == {
        "status": "not_checked",
        "segment_count": 0,
        "segments": [],
        "latest_admission": None,
        "recommendations": [],
    }


def test_diagnostics_adapter_renders_the_logic_panel_view() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(create_diagnostics_application())
    adapter = DiagnosticsPanelAdapter().bind(panel)

    widget = adapter.widget()

    assert widget is not None
    assert adapter.current_view() == panel.get_view()


def test_diagnostics_workspace_admits_and_displays_segment_provenance() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]

    admission = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    view = panel.get_view()
    catalog = view["historical_segment_catalog"]

    assert admission["status"] == "admitted"
    assert catalog["status"] == "admitted"
    assert catalog["segment_count"] == 1
    assert catalog["segments"][0]["provenance"] == {
        "provider": "BaoStock",
        "dataset": "workspace-fixture",
        "version": "v1",
        "observed_at": "2026-07-21T00:00:00+00:00",
    }
    visible_payload = repr(catalog).lower()
    assert "storage_path" not in visible_payload
    assert "duckdb" not in visible_payload
    assert "parquet" not in visible_payload


def test_diagnostics_workspace_returns_a_bounded_recommendation_shortlist() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )

    recommendations = panel.recommend_historical_segments(
        intent="visible interval",
        limit=10,
    )

    assert len(recommendations) == 1
    assert recommendations[0]["rank"] == 1
    assert panel.get_view()["historical_segment_catalog"]["recommendations"] == (
        recommendations
    )


def test_diagnostics_workspace_completes_the_manual_recipe_lifecycle() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]

    draft = panel.create_baseline_recipe(
        name="Thirty minute baseline",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    assert draft["status"] == "untrusted"
    assert panel.get_view()["scenario_recipe_workbench"]["status"] == "draft"

    validation = panel.validate_current_recipe()
    assert validation["is_valid"] is True
    assert validation["issues"] == []

    approved = panel.approve_current_recipe(actor="owner")
    assert approved["approval_actor"] == "owner"
    assert approved["approved_at"] == "2026-07-22T08:00:00+00:00"

    materialized = panel.materialize_current_recipe()
    assert materialized["segment_id"] == segment_id
    workbench = panel.get_view()["scenario_recipe_workbench"]
    assert workbench["status"] == "materialized"
    assert workbench["approved_version"]["version_id"] == approved["version_id"]
    assert workbench["materialization"]["artifact_hash"]


def test_diagnostics_workspace_previews_baseline_versus_trend_regime() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Baseline control",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    baseline = panel.materialize_current_recipe()

    panel.create_trend_regime_recipe(
        name="Bullish trend",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        direction="bullish",
        strength="0.75",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    transformed = panel.materialize_current_recipe()
    view = panel.get_view()
    preview = view["scenario_comparison_preview"]

    assert view["transformation_catalog"]["catalog_version"] == (
        "scenario-transformation-catalog.v1"
    )
    assert baseline["applied_transformations"] == []
    assert transformed["applied_transformations"][0]["transformation_id"] == (
        "trend-regime.v1"
    )
    assert preview["status"] == "ready"
    assert preview["baseline"]["market_context"] != preview["transformed"][
        "market_context"
    ]
    assert Decimal(str(preview["market_return_delta"])) > 0
    assert preview["transformed"]["candidates"] == ["sh.600000"]
    assert preview["transformed"]["rankings"] == [
        {"instrument": "sh.600000", "rank": 1, "score": "0"}
    ]


def test_diagnostics_workspace_shows_volatility_request_and_path_statistics() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Baseline control",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()

    panel.create_volatility_recipe(
        name="Amplified volatility",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        multiplier="1.5",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    transformed = panel.materialize_current_recipe()
    preview = panel.get_view()["scenario_comparison_preview"]

    assert transformed["applied_transformations"] == [
        {
            "transformation_id": "volatility-scaling.v1",
            "family": "volatility",
            "catalog_version": "scenario-transformation-catalog.v1",
            "implementation_version": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        }
    ]
    assert preview["transformed"]["applied_transformations"] == transformed[
        "applied_transformations"
    ]
    baseline_statistics = preview["baseline"]["path_statistics"]
    transformed_statistics = preview["transformed"]["path_statistics"]
    assert Decimal(
        str(transformed_statistics["mean_absolute_return_30s"])
    ) > Decimal(str(baseline_statistics["mean_absolute_return_30s"]))
    assert Decimal(
        str(transformed_statistics["mean_range_fraction_30s"])
    ) > Decimal(str(baseline_statistics["mean_range_fraction_30s"]))


def test_diagnostics_workspace_shows_shock_recovery_phases_and_statistics() -> None:
    panel = DiagnosticsPanel(_shock_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Baseline control",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()

    panel.create_shock_recovery_recipe(
        name="Bearish shock and recovery",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        direction="bearish",
        gap_fraction="0.01",
        shock_fraction="0.03",
        shock_duration_bars=2,
        persistence_duration_bars=1,
        recovery_duration_bars=2,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    transformed = panel.materialize_current_recipe()
    preview = panel.get_view()["scenario_comparison_preview"]

    applied = transformed["applied_transformations"][0]
    assert applied["transformation_id"] == "shock-recovery.v1"
    assert [marker["phase"] for marker in applied["phase_markers"]] == [
        "gap",
        "shock",
        "persistence",
        "recovery",
    ]
    assert applied["statistics"]["effective_peak_displacement_fraction"] == "0.04"
    assert transformed["reconstruction_notice"].endswith(
        "not recorded microstructure."
    )
    assert preview["transformed"]["reconstruction_notice"].endswith(
        "not recorded microstructure."
    )
    assert Decimal(
        str(preview["transformed"]["path_statistics"]["mean_absolute_return_30s"])
    ) > Decimal(
        str(preview["baseline"]["path_statistics"]["mean_absolute_return_30s"])
    )


def test_diagnostics_workspace_shows_requested_and_effective_market_structure() -> None:
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _market_structure_admittable_application()
    )
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Baseline control",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()

    panel.create_market_structure_recipe(
        name="Concentrated two-sector structure",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        breadth_target="0.5",
        dispersion_fraction="0.04",
        sector_concentration="1",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    transformed = panel.materialize_current_recipe()
    preview = panel.get_view()["scenario_comparison_preview"]

    applied = transformed["applied_transformations"][0]
    assert applied["transformation_id"] == "market-structure.v1"
    assert applied["parameters"] == {
        "breadth_target": "0.5",
        "dispersion_fraction": "0.04",
        "sector_concentration": "1",
    }
    assert applied["statistics"]["effective_final_breadth"] == "0.5"
    assert (
        applied["statistics"]["effective_final_return_spread_fraction"]
        == "0.04"
    )
    assert (
        applied["statistics"]["effective_final_sector_winner_concentration"]
        == "1"
    )
    assert preview["baseline"]["market_context"] != preview["transformed"][
        "market_context"
    ]
    assert preview["baseline"]["sector_context"] != preview["transformed"][
        "sector_context"
    ]
    assert preview["baseline"]["rankings"] != preview["transformed"][
        "rankings"
    ]


def test_diagnostics_panel_controls_and_inspects_an_anchored_baseline_run() -> None:
    application = _admittable_application()
    panel = DiagnosticsPanel(application)
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = str(admitted["segment"]["segment_id"])
    panel.create_baseline_recipe(
        name="Anchored baseline",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()

    started = panel.start_baseline_run(
        initial_cash="100000",
        order_shares=100,
        replica_id="workspace-baseline-1",
    )
    paused = panel.pause_baseline_run()
    resumed = panel.resume_baseline_run()
    completed = panel.complete_baseline_run(nodes_per_batch=3)
    view = panel.get_view()["baseline_strategy_run"]

    assert started["status"] == "running"
    assert paused["status"] == "paused"
    assert resumed["status"] == "running"
    assert completed["status"] == "completed"
    assert completed["materialization_hash"] == materialized["artifact_hash"]
    assert completed["processed_node_count"] == completed["total_node_count"]
    assert completed["equity_curve"]
    assert completed["portfolio"] == {"cash": "100000", "positions": []}
    assert completed["run_artifact_hash"]
    assert view == completed


def test_diagnostics_panel_cancels_a_baseline_run_at_a_node_boundary() -> None:
    application = _admittable_application()
    panel = DiagnosticsPanel(application)
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_baseline_recipe(
        name="Cancellable baseline",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=60,
        seed=18,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    started = panel.start_baseline_run(
        initial_cash="100000",
        order_shares=100,
        replica_id="workspace-cancel-1",
    )
    advanced = panel.advance_baseline_run(node_count=1)

    cancelled = panel.cancel_baseline_run()

    assert cancelled["run_id"] == started["run_id"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["processed_node_count"] == advanced["processed_node_count"] == 1


def test_diagnostics_workspace_shows_requested_and_effective_liquidity() -> None:
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _liquidity_admittable_application()
    )
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Baseline control",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    baseline = panel.materialize_current_recipe()

    panel.create_liquidity_recipe(
        name="Concentrated liquidity stress",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        volume_multiplier="0.5",
        cross_sectional_concentration="1",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    transformed = panel.materialize_current_recipe()
    preview = panel.get_view()["scenario_comparison_preview"]

    applied = transformed["applied_transformations"][0]
    assert applied["transformation_id"] == "liquidity-stress.v1"
    assert applied["parameters"] == {
        "cross_sectional_concentration": "1",
        "volume_multiplier": "0.5",
    }
    assert applied["statistics"]["effective_volume_multiplier"] == "0.5"
    assert applied["statistics"]["effective_top_volume_share"] == "0.5"
    assert applied["statistics"]["scaled_volume_conservation_error"] == "0"
    for node_key in ("first_node", "last_node"):
        assert {
            price_key: baseline[node_key][price_key]
            for price_key in ("open", "high", "low", "close")
        } == {
            price_key: transformed[node_key][price_key]
            for price_key in ("open", "high", "low", "close")
        }
    assert preview["baseline"]["features"] != preview["transformed"][
        "features"
    ]
    assert preview["baseline"]["rankings"] != preview["transformed"][
        "rankings"
    ]


def test_diagnostics_workspace_shows_actionable_recipe_validation_feedback() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    panel.create_baseline_recipe(
        name="Unsupported cadence",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=15,
        seed=17,
    )

    validation = panel.validate_current_recipe()

    assert validation["is_valid"] is False
    assert validation["issues"][0]["rule"] == "bounds.invalid"
    assert validation["issues"][0]["correction"]
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        panel.approve_current_recipe(actor="owner")


def test_diagnostics_adapter_drives_recipe_review_approval_and_materialization() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()

    adapter._recipe_name_input.setText("UI baseline")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    workbench = adapter.current_view()["scenario_recipe_workbench"]
    assert workbench["status"] == "materialized"
    assert workbench["validation"]["is_valid"] is True
    assert workbench["approved_version"]["approval_actor"] == "owner"


def test_diagnostics_adapter_controls_and_renders_a_baseline_strategy_run() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("UI anchored baseline")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()
    adapter._run_initial_cash_input.setText("100000")
    adapter._run_order_shares_input.setText("100")
    adapter._run_replica_input.setText("ui-baseline-1")

    adapter._start_run_button.click()
    assert adapter.current_view()["baseline_strategy_run"]["status"] == "running"
    adapter._pause_run_button.click()
    assert adapter.current_view()["baseline_strategy_run"]["status"] == "paused"
    adapter._resume_run_button.click()
    adapter._complete_run_button.click()

    run = adapter.current_view()["baseline_strategy_run"]
    assert run["status"] == "completed"
    assert run["equity_curve"]
    assert "completed" in adapter._run_status_label.text()
    assert "Private Portfolio Ledger" in adapter._run_equity_label.text()
    assert "remain immutable" in adapter._run_equity_label.text()
    curve_text = adapter._run_equity_curve_view.toPlainText()
    assert str(run["equity_curve"][0]["simulation_time"]) in curve_text
    assert str(run["equity_curve"][-1]["simulation_time"]) in curve_text
    assert len(curve_text.splitlines()) == len(run["equity_curve"]) + 1
    order_text = adapter._run_order_details_view.toPlainText()
    assert "Requested | Accepted | Unfilled | Status | Reason code" in order_text
    assert (
        "Commission | Transfer fee | Stamp duty | Total fee | Execution erosion"
        in order_text
    )
    assert "No A-share order decisions recorded yet" in order_text


def test_diagnostics_adapter_compares_execution_overrides_and_erosion() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _execution_admittable_application()
    )
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("Private execution stress")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._commission_input.setText("3")
    adapter._slippage_input.setText("0")
    adapter._fill_fraction_input.setText("1")
    adapter._latency_input.setText("0")
    adapter._partial_fills_input.setText("true")
    adapter._execution_override_commission_input.setText("")
    adapter._execution_override_slippage_input.setText("100")
    adapter._execution_override_fill_fraction_input.setText("0.01")
    adapter._execution_override_latency_input.setText("2")
    adapter._execution_override_partial_input.setText("")
    adapter._execution_rejection_mode_input.setText("")
    adapter._create_execution_stress_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()
    adapter._run_initial_cash_input.setText("100000")
    adapter._run_order_shares_input.setText("200")
    adapter._run_replica_input.setText("ui-execution-stress-1")

    adapter._start_run_button.click()
    adapter._complete_run_button.click()

    run = adapter.current_view()["baseline_strategy_run"]
    applied = adapter.current_view()["scenario_recipe_workbench"][
        "materialization"
    ]["applied_transformations"][0]
    assert run["status"] == "completed"
    assert applied["transformation_id"] == "execution-stress.v1"
    assert applied["statistics"]["reference_market_path_changed"] == "false"
    assert applied["parameters"] == {
        "latency_nodes": "2",
        "max_fill_fraction": "0.01",
        "slippage_bps": "100",
    }
    assert run["orders"][0]["reason_code"] == "execution.partial_fill"
    assert run["orders"][0]["status"] == "partially_filled"
    assert run["orders"][0]["accepted_shares"] == 100
    assert run["orders"][0]["unfilled_shares"] == 100
    assert run["fills"][0]["reference_price"] == "10"
    assert run["fills"][0]["price"] == "10.10"
    assert run["fills"][0]["execution_erosion"] == "15.01"
    condition_text = adapter._run_execution_conditions_view.toPlainText()
    assert "commission_bps | 3 | 3 | request retained" in condition_text
    assert "slippage_bps | 0 | 100 | scenario execution-stress.v1 override" in condition_text
    assert "latency_nodes | 0 | 2 | scenario execution-stress.v1 override" in condition_text
    assert "allow_partial_fills | true | true | request retained" in condition_text
    assert "rejection_mode | none | none | request retained" in condition_text
    assert "Total private execution erosion | 15.01" in condition_text
    order_text = adapter._run_order_details_view.toPlainText()
    assert "execution.partial_fill" in order_text
    assert "10 | 10.10 | 100" in order_text


def test_approved_execution_recipe_cannot_run_another_materialization() -> None:
    application = _execution_admittable_application()
    panel = DiagnosticsPanel(application)  # type: ignore[arg-type]
    panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = panel.get_view()["historical_segment_catalog"]["segments"][0][
        "segment_id"
    ]
    common = {
        "segment_id": segment_id,
        "author": "researcher",
        "cadence_minutes": 30,
        "seed": 17,
        "override_commission_bps": "8",
        "override_max_fill_fraction": "1",
        "override_latency_nodes": 0,
        "override_allow_partial_fills": True,
        "rejection_mode": "none",
    }
    panel.create_execution_stress_recipe(
        name="First stress",
        override_slippage_bps="25",
        **common,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    first_materialization = panel.materialize_current_recipe()
    panel.create_execution_stress_recipe(
        name="Revised stress",
        override_slippage_bps="100",
        **common,
    )
    panel.validate_current_recipe()
    approved = panel.approve_current_recipe(actor="owner")

    with pytest.raises(ValueError, match="do not match the approved recipe"):
        getattr(application, "start_baseline_strategy_run")(
            str(approved["version_id"]),
            str(first_materialization["artifact_hash"]),
            initial_cash=Decimal("100000"),
            order_shares=100,
            replica_id="mismatched-materialization",
        )


def test_diagnostics_adapter_order_audit_renders_every_a_share_reason_code() -> None:
    _ensure_qapp()
    adapter = DiagnosticsPanelAdapter()
    adapter.widget()
    orders = [
        {
            "order_id": f"fixture-{index}",
            "instrument": "sh.600000",
                "requested_shares": 100,
                "accepted_shares": 100 if reason_code == "accepted" else 0,
                "unfilled_shares": 0 if reason_code == "accepted" else 100,
                "status": "filled" if reason_code == "accepted" else "rejected",
                "reason_code": reason_code,
                "reference_price": "10.00",
                "execution_price": "10.00",
                "slippage_bps": "0",
            "price_limits": {"lower": "9.00", "upper": "11.00"},
            "account_effect": {
                "cash_change": "-1005.01" if reason_code == "accepted" else "0",
                "position_change": 100 if reason_code == "accepted" else 0,
                "sellable_shares_change": 0,
            },
        }
        for index, reason_code in enumerate(A_SHARE_EXECUTION_REASON_CODES)
    ]
    adapter._apply_view(
        {
            "baseline_strategy_run": {
                "orders": orders,
                "fills": [
                    {
                        "order_id": "fixture-0",
                        "fees": {
                            "commission": "5.00",
                            "transfer_fee": "0.01",
                            "stamp_duty": "0.00",
                            "total": "5.01",
                        },
                        "cash_change": "-1005.01",
                        "execution_erosion": "5.01",
                    }
                ],
                "portfolio": {"cash": "98994.99"},
                "equity_curve": [],
            }
        }
    )

    order_text = adapter._run_order_details_view.toPlainText()
    for reason_code in A_SHARE_EXECUTION_REASON_CODES:
        assert reason_code in order_text
    assert (
        "5.00 | 0.01 | 0.00 | 5.01 | 5.01 | -1005.01 | 100 | 0"
        in order_text
    )


def test_diagnostics_adapter_renders_baseline_versus_transformed_preview() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("Baseline control")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._seed_input.setText("17")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._recipe_name_input.setText("Bullish trend")
    adapter._trend_direction_input.setText("bullish")
    adapter._trend_strength_input.setText("0.75")
    adapter._create_trend_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    preview = adapter.current_view()["scenario_comparison_preview"]
    preview_text = adapter._scenario_preview_label.text()
    assert preview["status"] == "ready"
    assert "Baseline vs transformed" in preview_text
    assert str(preview["baseline"]["market_context"]["return"]) in preview_text
    assert str(preview["transformed"]["market_context"]["return"]) in preview_text
    assert str(preview["market_return_delta"]) in preview_text
    assert "1. sh.600000" in preview_text
    assert "trend-regime.v1" in adapter._transformation_catalog_label.text()


def test_diagnostics_adapter_authors_volatility_and_renders_path_statistics() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._seed_input.setText("17")
    adapter._recipe_name_input.setText("Baseline control")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._recipe_name_input.setText("Amplified volatility")
    adapter._volatility_multiplier_input.setText("1.5")
    adapter._create_volatility_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    preview = adapter.current_view()["scenario_comparison_preview"]
    transformed = preview["transformed"]
    preview_text = adapter._scenario_preview_label.text()
    assert transformed["applied_transformations"][0]["transformation_id"] == (
        "volatility-scaling.v1"
    )
    assert transformed["applied_transformations"][0]["parameters"] == {
        "multiplier": "1.5"
    }
    assert "volatility-scaling.v1" in preview_text
    assert "multiplier 1.5" in preview_text
    assert "mean |30s return|" in preview_text
    assert str(
        preview["baseline"]["path_statistics"]["mean_absolute_return_30s"]
    ) in preview_text
    assert str(
        transformed["path_statistics"]["mean_absolute_return_30s"]
    ) in preview_text
    assert "volatility-scaling.v1" in adapter._transformation_catalog_label.text()


def test_diagnostics_adapter_previews_shock_phases_without_microstructure_claim() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_shock_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._seed_input.setText("17")
    adapter._recipe_name_input.setText("Baseline control")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._recipe_name_input.setText("Bearish shock and recovery")
    adapter._shock_direction_input.setText("bearish")
    adapter._gap_fraction_input.setText("0.01")
    adapter._shock_fraction_input.setText("0.03")
    adapter._shock_duration_input.setText("2")
    adapter._persistence_duration_input.setText("1")
    adapter._recovery_duration_input.setText("2")
    adapter._create_shock_recovery_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    preview = adapter.current_view()["scenario_comparison_preview"]
    preview_text = adapter._scenario_preview_label.text()
    applied = preview["transformed"]["applied_transformations"][0]
    assert applied["transformation_id"] == "shock-recovery.v1"
    assert "shock-recovery.v1" in preview_text
    assert "gap" in preview_text
    assert "shock" in preview_text
    assert "persistence" in preview_text
    assert "recovery" in preview_text
    assert "effective peak 0.04" in preview_text
    assert "not recorded microstructure" in preview_text
    assert "shock-recovery.v1" in adapter._transformation_catalog_label.text()


def test_diagnostics_adapter_previews_requested_and_effective_market_structure() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _market_structure_admittable_application()
    )
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._seed_input.setText("17")
    adapter._recipe_name_input.setText("Baseline control")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._recipe_name_input.setText("Concentrated two-sector structure")
    adapter._breadth_target_input.setText("0.5")
    adapter._dispersion_fraction_input.setText("0.04")
    adapter._sector_concentration_input.setText("1")
    adapter._create_market_structure_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    preview = adapter.current_view()["scenario_comparison_preview"]
    preview_text = adapter._scenario_preview_label.text()
    applied = preview["transformed"]["applied_transformations"][0]
    assert applied["transformation_id"] == "market-structure.v1"
    assert "market-structure.v1" in preview_text
    assert "requested breadth 0.5" in preview_text
    assert "effective breadth 0.5" in preview_text
    assert "requested dispersion 0.04" in preview_text
    assert "effective spread 0.04" in preview_text
    assert "requested sector concentration 1" in preview_text
    assert "effective sector winner concentration 1" in preview_text
    assert "market-structure.v1" in adapter._transformation_catalog_label.text()


def test_diagnostics_adapter_separates_path_liquidity_from_private_execution() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _liquidity_admittable_application()
    )
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._seed_input.setText("17")
    adapter._recipe_name_input.setText("Baseline control")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._recipe_name_input.setText("Concentrated liquidity stress")
    adapter._volume_multiplier_input.setText("0.5")
    adapter._cross_sectional_concentration_input.setText("1")
    adapter._create_liquidity_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    preview = adapter.current_view()["scenario_comparison_preview"]
    preview_text = adapter._scenario_preview_label.text()
    applied = preview["transformed"]["applied_transformations"][0]
    assert applied["transformation_id"] == "liquidity-stress.v1"
    assert "requested volume multiplier 0.5" in preview_text
    assert "effective volume multiplier 0.5" in preview_text
    assert "requested concentration 1" in preview_text
    assert "effective top volume share 0.5" in preview_text
    assert "market-path liquidity only" in preview_text
    assert "private execution effects are not applied here" in preview_text
    assert "liquidity-stress.v1" in adapter._transformation_catalog_label.text()


def test_diagnostics_adapter_refuses_to_approve_stale_visible_inputs() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("Reviewed baseline")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()

    adapter._commission_input.setText("50")
    adapter._approve_recipe_button.click()

    workbench = adapter.current_view()["scenario_recipe_workbench"]
    assert workbench["status"] == "validated"
    assert workbench["approved_version"] is None
    assert "changed" in adapter._recipe_feedback_label.text().lower()
    assert workbench["draft"]["payload_hash"] in adapter._recipe_draft_label.text()


def test_diagnostics_adapter_can_admit_and_recommend_without_storage_controls() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()

    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()

    admitted_view = adapter.current_view()
    assert admitted_view["historical_segment_catalog"]["status"] == "admitted"

    adapter._intent_input.setText("visible interval")
    adapter._recommend_button.click()

    catalog = adapter.current_view()["historical_segment_catalog"]
    assert len(catalog["recommendations"]) == 1
    visible_controls = repr(adapter.widget()).lower()
    assert "storage" not in visible_controls
    assert "duckdb" not in visible_controls


def test_desktop_shell_registers_diagnostics_as_a_primary_workspace(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    from app import panels
    from app.i18n import set_language
    from app.panels import (
        get_panel,
        list_panels,
        register_builtin_panels,
        register_ui_adapters,
        reset_registry,
    )
    from app.ui.main_window import (
        DEFAULT_PRELOAD_PANELS,
        MainWindow,
    )

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    set_language("zh_CN")
    reset_registry()
    register_builtin_panels()
    diagnostics_engine = create_engine(
        f"sqlite:///{tmp_path / 'primary-workspace.db'}",
        future=True,
    )
    register_ui_adapters(diagnostics_engine=diagnostics_engine)

    descriptors = {item["name"]: item for item in list_panels()}
    assert descriptors["diagnostics"]["title"] in {"Diagnostics", "策略诊断"}
    assert isinstance(get_panel("diagnostics"), DiagnosticsPanelAdapter)
    assert "diagnostics" in DEFAULT_PRELOAD_PANELS

    _ensure_qapp()
    window = MainWindow()
    assert window.open_panel("diagnostics") is not None
    assert window.serialize_layout()["panels"]["diagnostics"]["open"] is True
    diagnostics_page = window._workspace_pages["diagnostics"]
    diagnostics_index = window._workspace_stack.indexOf(diagnostics_page)
    assert window._nav_list.item(diagnostics_index).text() == "策略诊断"


def test_desktop_diagnostics_composition_restores_approved_recipe(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    from app.panels import (
        get_panel,
        register_builtin_panels,
        register_ui_adapters,
        reset_registry,
    )

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    database_path = tmp_path / "desktop-diagnostics.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    reset_registry()
    register_builtin_panels()
    register_ui_adapters(
        diagnostics_engine=engine,
        diagnostics_application_factory=_admittable_application,
    )
    first_adapter = get_panel("diagnostics")
    first_panel = first_adapter._logic
    first_panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = first_panel.get_view()["historical_segment_catalog"]["segments"][
        0
    ]["segment_id"]
    first_panel.create_baseline_recipe(
        name="Persistent desktop recipe",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
    )
    first_panel.validate_current_recipe()
    approved = first_panel.approve_current_recipe(actor="owner")

    reset_registry()
    register_builtin_panels()
    register_ui_adapters(
        diagnostics_engine=engine,
        diagnostics_application_factory=_admittable_application,
    )
    restarted_adapter = get_panel("diagnostics")
    restored = restarted_adapter._logic._application.get_recipe_version(
        approved["version_id"]
    )

    assert restored.to_dict() == approved


def test_diagnostics_adapter_failure_preserves_the_legacy_shell(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    from app import panels
    from app.panels import list_panels, register_builtin_panels, reset_registry

    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    original_replace_panel = panels.replace_panel

    def fail_diagnostics_registration(name: str, *args: object, **kwargs: object) -> object:
        if name == "diagnostics":
            raise RuntimeError("diagnostics adapter unavailable")
        return original_replace_panel(name, *args, **kwargs)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        panels,
        "replace_panel",
        fail_diagnostics_registration,
    )
    reset_registry()
    register_builtin_panels()

    diagnostics_engine = create_engine(
        f"sqlite:///{tmp_path / 'failed-adapter.db'}",
        future=True,
    )
    panels.register_ui_adapters(diagnostics_engine=diagnostics_engine)

    descriptors = {item["name"]: item for item in list_panels()}
    assert descriptors["diagnostics"]["created"] is False
    assert "account" in descriptors
