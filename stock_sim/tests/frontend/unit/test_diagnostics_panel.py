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
    AIRecipeDraftOutputV1,
    AdmissionCheck,
    DeterministicFakeAIRecipeAssistant,
    DiagnosticFindingExplanation,
    FiveMinuteBar,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryDiagnosticEvidenceArtifactStore,
    InMemoryMarketPathArtifactStore,
    InMemoryHistoricalSource,
    InstrumentState,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_MANIFEST,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    ScenarioDataWorldInput,
    ScenarioRecipeV1,
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
            artifacts=(SourceArtifact("market-structure-bars", "d" * 64, 28),),
            eligible_instrument_count=4,
            bar_count=28,
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
            (datetime(2024, 1, 2, 9, 40), ("10", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 45), ("10", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 50), ("9.90", "10", "10", "10")),
            (datetime(2024, 1, 2, 9, 55), ("9.75", "10", "10", "10")),
            (datetime(2024, 1, 2, 10, 0), ("9.82", "10", "10", "10")),
            (datetime(2024, 1, 2, 10, 5), ("9.84", "10", "10", "10")),
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
        evidence_artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
        recipe_assistant=_configured_recipe_assistant(),
        recipe_clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )


class _V1FindingExplanationProvider:
    def explain(self, request: object) -> tuple[DiagnosticFindingExplanation, ...]:
        findings = getattr(request, "findings")
        return (
            DiagnosticFindingExplanation(
                finding_id=str(findings[0]["finding_id"]),
                text=(
                    "Plain-language explanation grounded only in the "
                    "sealed Diagnostic Finding."
                ),
            ),
        )


def _configured_recipe_assistant() -> DeterministicFakeAIRecipeAssistant:
    return DeterministicFakeAIRecipeAssistant(
        output=AIRecipeDraftOutputV1(
            recipe=ScenarioRecipeV1(
                name="Configured V1 assistant",
                historical_segment_id="segment-fixture",
                decision_cadence_minutes=30,
                materialization_seed=17,
            )
        )
    )


def _v1_admittable_application() -> object:
    source = _MarketStructureWorkspaceSource()
    return create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        evidence_artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
        finding_explanation_provider=_V1FindingExplanationProvider(),
        recipe_assistant=_configured_recipe_assistant(),
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


def test_v1_authoring_and_product_surface_facts_are_authoritative() -> None:
    default_application = _admittable_application()
    configured_application = _v1_admittable_application()
    getattr(default_application, "start")()
    getattr(configured_application, "start")()

    default_capabilities = getattr(
        default_application,
        "recipe_authoring_capabilities",
    )()
    configured_capabilities = getattr(
        configured_application,
        "recipe_authoring_capabilities",
    )()
    inventory = getattr(
        configured_application,
        "v1_product_surface_inventory",
    )()

    assert default_capabilities["manual_authoring_available"] is True
    assert default_capabilities["ai_authoring_available"] is False
    assert configured_capabilities["ai_authoring_available"] is True
    assert configured_capabilities["ai_provider"] == "deterministic-fake"
    assert inventory.status == "verified"
    assert inventory.missing_required_commands == ()
    assert inventory.present_excluded_capabilities == ()


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


def test_headless_application_selects_the_registered_quentx_strategy() -> None:
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
    panel.create_baseline_recipe(
        name="QuentX scenario-native baseline",
        segment_id=segment_id,
        author="researcher",
        cadence_minutes=30,
        seed=17,
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    approved = panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()

    started = getattr(application, "start_baseline_strategy_run")(
        str(approved["version_id"]),
        str(materialized["artifact_hash"]),
        initial_cash=Decimal("100000"),
        order_shares=1000,
        replica_id="quentx-headless-baseline",
        strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    )
    completed = getattr(application, "complete_strategy_run")(started.run_id)

    assert completed.status == "completed"
    assert completed.specification.strategy_id == (
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID
    )
    assert completed.specification.ptrade_manifest_hash == (
        QUENTX_SCENARIO_NATIVE_MANIFEST.content_hash
    )
    assert completed.ptrade_audit is not None
    assert [
        item.to_dict() for item in completed.ptrade_audit.configuration_requests
    ] == [
        {"call": "set_slippage", "value": "5"},
        {"call": "set_commission", "value": "3"},
    ]


def test_diagnostics_panel_runs_a_comparable_two_strategy_baseline_campaign() -> None:
    panel = DiagnosticsPanel(_execution_admittable_application())  # type: ignore[arg-type]
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_baseline_recipe(
        name="Two-strategy Baseline Campaign",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=17,
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()

    campaign = panel.run_baseline_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="workspace-campaign-1",
    )
    view = panel.get_view()["baseline_campaign"]

    assert campaign["status"] == "completed"
    assert campaign["completeness"]["label"] == "2/2 complete"
    assert campaign["pinned_conditions"]["materialization_hash"] == (
        materialized["artifact_hash"]
    )
    assert campaign["shared_market_nodes"]["identical_observed_timeline"] is True
    assert [item["strategy_id"] for item in campaign["members"]] == [
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    ]
    assert {
        item["materialization_hash"] for item in campaign["members"]
    } == {materialized["artifact_hash"]}
    assert len(
        {item["run_id"] for item in campaign["members"]}
    ) == len(campaign["members"])
    assert len(campaign["equity_overlay"]) == 2
    assert len(campaign["drawdown_overlay"]) == 2
    assert view == campaign


def test_application_anchors_and_runs_an_approved_single_family_sensitivity_case() -> None:
    application = _admittable_application()
    panel = DiagnosticsPanel(application)  # type: ignore[arg-type]
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_trend_regime_recipe(
        name="Sensitivity trend level",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=17,
        direction="bullish",
        strength="0.25",
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    approved = panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()
    staged = panel.stage_current_materialization_as_sensitivity_case()

    case = getattr(application, "create_isolated_sensitivity_case")(
        str(approved["version_id"]),
        str(materialized["artifact_hash"]),
    )
    campaign = getattr(application, "run_baseline_campaign")(
        str(approved["version_id"]),
        str(materialized["artifact_hash"]),
        initial_cash=Decimal("100000"),
        order_shares=1000,
        campaign_replica_id="sensitivity-trend-attempt-1",
    )

    assert case.transformation_family == "trend-regime"
    assert case.transformation_parameters == (
        ("direction", "bullish"),
        ("strength", "0.25"),
    )
    assert case.recipe_version_id == approved["version_id"]
    assert case.materialization_hash == materialized["artifact_hash"]
    assert staged["case_id"] == case.case_id
    assert panel.get_view()["isolated_sensitivity_case_staging"][
        "case_count"
    ] == 1
    assert all(member.snapshot is not None for member in campaign.members), [
        (member.failure_code, member.failure_message) for member in campaign.members
    ]
    assert campaign.status == "completed", campaign.to_dict()
    assert {
        member.specification.materialization_hash for member in campaign.members
    } == {materialized["artifact_hash"]}


def test_application_anchors_an_approved_compound_campaign_case() -> None:
    application = _admittable_application()
    panel = DiagnosticsPanel(application)  # type: ignore[arg-type]
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_compound_recipe(
        name="Trend plus volatility stress",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=17,
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.5",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.5"},
            },
        ),
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    approved = panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()

    case = getattr(application, "create_diagnostic_campaign_case")(
        str(approved["version_id"]),
        str(materialized["artifact_hash"]),
    )

    assert case.layer == "compound"
    assert tuple(
        item.transformation_family for item in case.transformations
    ) == ("trend-regime", "volatility")
    assert case.recipe_version_id == approved["version_id"]
    assert case.materialization_hash == materialized["artifact_hash"]
    with pytest.raises(
        ValueError,
        match="exactly one transformation family",
    ):
        getattr(application, "create_isolated_sensitivity_case")(
            str(approved["version_id"]),
            str(materialized["artifact_hash"]),
        )


def test_application_runs_compound_only_as_a_quick_experiment() -> None:
    application = _admittable_application()
    panel = DiagnosticsPanel(application)  # type: ignore[arg-type]
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_compound_recipe(
        name="Compound-only experiment",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=17,
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.5",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.5"},
            },
        ),
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    approved = panel.approve_current_recipe(actor="owner")
    materialized = panel.materialize_current_recipe()

    planned = getattr(application, "plan_diagnostic_campaign")(
        baseline_anchor=None,
        isolated_sensitivity_set_id=None,
        compound_case_anchors=(
            (
                str(approved["version_id"]),
                str(materialized["artifact_hash"]),
            ),
        ),
        initial_cash=Decimal("100000"),
        order_shares=1000,
        campaign_replica_id="quick-compound-1",
    )
    completed = getattr(application, "resume_diagnostic_campaign")(
        planned.campaign_id
    )

    assert completed.status == "completed"
    view = completed.to_dict()
    assert view["campaign_type"] == "quick_experiment"
    assert view["formal_attribution"] == {
        "eligible": False,
        "claim_status": "not_permitted",
        "missing_layers": ["baseline", "isolated_sensitivity"],
    }
    assert view["layers"]["compound"]["completed_count"] == 1
    assert all(
        member["status"] == "completed"
        for member in view["compound_case_outcomes"][0]["members"]
    )


def test_panel_plans_and_resumes_a_staged_quick_experiment() -> None:
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    panel.create_compound_recipe(
        name="Panel compound experiment",
        segment_id=str(admitted["segment"]["segment_id"]),
        author="researcher",
        cadence_minutes=30,
        seed=17,
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.5",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.5"},
            },
        ),
        commission_bps="3",
        slippage_bps="5",
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()

    staged = panel.stage_current_materialization_as_compound_case()
    planned = panel.plan_diagnostic_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="panel-quick-1",
    )
    completed = panel.resume_diagnostic_campaign()

    assert staged["layer"] == "compound"
    assert planned["campaign_type"] == "quick_experiment"
    assert completed["status"] == "completed"
    view = panel.get_view()
    assert view["compound_campaign_case_staging"]["case_count"] == 1
    assert view["diagnostic_campaign"] == completed


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
    assert completed["ptrade_host"]["surface_version"] == "ptrade_surface.v1"
    assert len(completed["ptrade_host"]["manifest_hash"]) == 64
    assert completed["specification"]["ptrade_surface_version"] == "ptrade_surface.v1"
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


def test_diagnostics_adapter_runs_and_renders_a_two_strategy_campaign() -> None:
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
    adapter._recipe_name_input.setText("UI Baseline Campaign")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._slippage_input.setText("5")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()
    adapter._run_initial_cash_input.setText("100000")
    adapter._run_order_shares_input.setText("1000")
    adapter._run_replica_input.setText("ui-campaign-1")

    adapter._run_campaign_button.click()
    campaign = adapter.current_view()["baseline_campaign"]

    assert campaign["status"] == "completed"
    assert "2/2 complete" in adapter._campaign_status_label.text()
    equity_text = adapter._campaign_equity_overlay_view.toPlainText()
    drawdown_text = adapter._campaign_drawdown_overlay_view.toPlainText()
    assert QUENTX_SCENARIO_NATIVE_STRATEGY_ID in equity_text
    assert LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID in equity_text
    assert "Simulation Time | Strategy | Equity" in equity_text
    assert "Simulation Time | Strategy | Drawdown" in drawdown_text


def test_diagnostics_adapter_renders_traceable_sensitivity_curves() -> None:
    _ensure_qapp()
    adapter = DiagnosticsPanelAdapter()
    adapter.widget()
    adapter._apply_view(
        {
            "isolated_sensitivity_case_staging": {
                "case_count": 12,
                "cases": [],
            },
            "isolated_sensitivity_set": {
                "sensitivity_set_id": "isolated-sensitivity-fixture",
                "status": "partial",
                "completeness": {
                    "completed_count": 1,
                    "incomplete_count": 0,
                    "pending_count": 11,
                    "total_count": 12,
                },
                "sensitivity_curves": [
                    {
                        "family": "trend-regime",
                        "strategy_id": "quentx-5.2.3-scenario-native",
                        "strategy_version": "quentx-5.2.3-scenario-native.v1",
                        "points": [
                            {
                                "case_id": "sensitivity-case-fixture",
                                "attempt_number": 1,
                                "campaign_id": "baseline-campaign-fixture",
                                "run_id": "strategy-run-fixture",
                                "recipe_version_id": "recipe-version-fixture",
                                "materialization_hash": "path-hash-fixture",
                                "parameters": {
                                    "direction": "bullish",
                                    "strength": "0.25",
                                },
                                "final_equity": "100100",
                                "max_drawdown": "0.01",
                            }
                        ],
                    }
                ],
            },
        }
    )

    assert "partial" in adapter._sensitivity_status_label.text()
    assert "1/12 complete" in adapter._sensitivity_status_label.text()
    curve_text = adapter._sensitivity_curves_view.toPlainText()
    assert "trend-regime" in curve_text
    assert "sensitivity-case-fixture" in curve_text
    assert "baseline-campaign-fixture" in curve_text
    assert "strategy-run-fixture" in curve_text
    assert "recipe-version-fixture" in curve_text
    assert "path-hash-fixture" in curve_text
    assert "strength=0.25" in curve_text


def test_diagnostics_adapter_renders_formal_campaign_layers_and_failures() -> None:
    _ensure_qapp()
    adapter = DiagnosticsPanelAdapter()
    adapter.widget()
    adapter._apply_view(
        {
            "diagnostic_campaign": {
                "campaign_id": "diagnostic-campaign-fixture",
                "campaign_type": "formal_diagnostic_campaign",
                "status": "partial",
                "formal_attribution": {
                    "eligible": True,
                    "claim_status": "pending_completion",
                    "missing_layers": [],
                },
                "progress": {
                    "completed_count": 13,
                    "incomplete_count": 1,
                    "pending_count": 1,
                    "total_count": 15,
                },
                "layers": {
                    "baseline": {
                        "status": "completed",
                        "completed_count": 1,
                        "incomplete_count": 0,
                        "pending_count": 0,
                        "total_count": 1,
                    },
                    "isolated_sensitivity": {
                        "status": "completed",
                        "completed_count": 12,
                        "incomplete_count": 0,
                        "pending_count": 0,
                        "total_count": 12,
                    },
                    "compound": {
                        "status": "partial",
                        "completed_count": 0,
                        "incomplete_count": 1,
                        "pending_count": 1,
                        "total_count": 2,
                    },
                },
                "failures": [
                    {
                        "case_id": "compound-case-failed",
                        "layer": "compound",
                        "attempt_number": 1,
                        "strategy_id": "quentx",
                        "run_id": "strategy-run-failed",
                        "code": "RuntimeError",
                        "message": "fixture compound failure",
                    }
                ],
                "compound_case_outcomes": [
                    {
                        "case_id": "compound-case-failed",
                        "status": "incomplete",
                        "attempt_number": 1,
                        "campaign_id": None,
                        "members": [],
                    },
                    {
                        "case_id": "compound-case-pending",
                        "status": "planned",
                        "attempt_number": 0,
                        "campaign_id": None,
                        "members": [],
                    },
                ],
            }
        }
    )

    status_text = adapter._diagnostic_campaign_status_label.text()
    assert "Formal Diagnostic Campaign" in status_text
    assert "13/15 complete" in status_text
    assert "pending_completion" in status_text
    details = adapter._diagnostic_campaign_details_view.toPlainText()
    assert "Baseline | completed | 1/1 complete" in details
    assert "Isolated Sensitivity | completed | 12/12 complete" in details
    assert "Compound | partial | 0/2 complete | 1 failed | 1 pending" in details
    assert "compound-case-failed" in details
    assert "quentx" in details
    assert "strategy-run-failed" in details
    assert "fixture compound failure" in details
    assert "compound-case-pending" in details


def test_application_exposes_versioned_strategy_specific_guardrails() -> None:
    application = _admittable_application()
    getattr(application, "start")()

    profiles = getattr(application, "strategy_guardrail_profiles")()

    assert [profile.strategy_id for profile in profiles] == [
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    ]
    assert profiles[0].profile_version == "quentx-balanced-diagnostics.v1"
    assert profiles[1].profile_version == (
        "live-minute-capital-preservation.v1"
    )
    assert profiles[0].profile_id != profiles[1].profile_id
    assert {
        threshold.metric_name for threshold in profiles[0].thresholds
    } >= {
        "total_return",
        "maximum_drawdown",
        "turnover",
        "instrument_concentration",
        "execution_erosion_bps",
    }


def test_application_validates_explicit_v1_strategy_guardrail_selection() -> None:
    application = _admittable_application()
    getattr(application, "start")()

    complete = getattr(application, "v1_diagnostic_configuration")()

    assert complete["status"] == "complete"
    assert complete["validation"] == {
        "complete": True,
        "errors": [],
    }
    assert [
        item["strategy_id"] for item in complete["supported_strategies"]
    ] == [
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    ]
    assert len(complete["supported_guardrail_profiles"]) == 2
    incomplete = getattr(application, "v1_diagnostic_configuration")(
        selected_strategy_ids=(QUENTX_SCENARIO_NATIVE_STRATEGY_ID,),
        selected_guardrail_profile_ids=tuple(
            complete["selected_guardrail_profile_ids"][:1]
        ),
    )
    assert incomplete["status"] == "incomplete"
    assert incomplete["validation"]["complete"] is False
    assert incomplete["validation"]["errors"] == [
        "Select both representative V1 strategies.",
        "Select one versioned guardrail profile for each V1 strategy.",
    ]

    with pytest.raises(ValueError, match="Unknown V1 strategy selection"):
        getattr(application, "v1_diagnostic_configuration")(
            selected_strategy_ids=("not-supported",),
        )


def test_panel_exposes_and_enforces_v1_diagnostic_configuration() -> None:
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _admittable_application()
    )
    initial = panel.get_view()["diagnostic_configuration"]
    profile_ids = tuple(initial["selected_guardrail_profile_ids"])

    configured = panel.configure_v1_diagnostic_selection(
        strategy_ids=(QUENTX_SCENARIO_NATIVE_STRATEGY_ID,),
        guardrail_profile_ids=(profile_ids[0],),
    )

    assert configured["status"] == "incomplete"
    assert panel.get_view()["diagnostic_configuration"] == configured
    with pytest.raises(
        ValueError,
        match="Complete the V1 strategy and guardrail selection",
    ):
        panel.plan_diagnostic_campaign(
            initial_cash="100000",
            order_shares=1000,
            campaign_replica_id="blocked-incomplete-selection",
        )


def test_headless_formal_campaign_builds_and_seals_presentable_evidence() -> None:
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _market_structure_admittable_application()
    )
    admitted = panel.admit_historical_segment(
        market="mainland-a-share",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )
    segment_id = str(admitted["segment"]["segment_id"])
    common = {
        "segment_id": segment_id,
        "author": "researcher",
        "cadence_minutes": 30,
        "seed": 17,
        "commission_bps": "3",
        "slippage_bps": "5",
    }

    hourly_common = {**common, "cadence_minutes": 60}
    panel.create_baseline_recipe(
        name="Evidence hourly baseline",
        **hourly_common,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    hourly = panel.run_baseline_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="evidence-hourly-anchor",
    )
    assert {
        member["specification"]["decision_cadence_minutes"]
        for member in hourly["members"]
    } == {60}

    panel.create_baseline_recipe(name="Evidence baseline", **common)
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    panel.run_baseline_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="evidence-baseline-anchor",
    )

    def approve_materialize_and_stage() -> None:
        validation = panel.validate_current_recipe()
        assert validation["is_valid"] is True
        panel.approve_current_recipe(actor="owner")
        panel.materialize_current_recipe()
        panel.stage_current_materialization_as_sensitivity_case()

    for level, strength in enumerate(("0.10", "0.20"), start=1):
        panel.create_trend_regime_recipe(
            name=f"Trend evidence level {level}",
            direction="bullish",
            strength=strength,
            **common,
        )
        approve_materialize_and_stage()
    for level, multiplier in enumerate(("0.75", "1.25"), start=1):
        panel.create_volatility_recipe(
            name=f"Volatility evidence level {level}",
            multiplier=multiplier,
            **common,
        )
        approve_materialize_and_stage()
    for level, shock_fraction in enumerate(("0.02", "0.04"), start=1):
        panel.create_shock_recovery_recipe(
            name=f"Shock evidence level {level}",
            direction="bearish",
            gap_fraction="0.01",
            shock_fraction=shock_fraction,
            shock_duration_bars=1,
            persistence_duration_bars=0,
            recovery_duration_bars=1,
            **common,
        )
        approve_materialize_and_stage()
    for level, breadth in enumerate(("0.25", "0.75"), start=1):
        panel.create_market_structure_recipe(
            name=f"Structure evidence level {level}",
            breadth_target=breadth,
            dispersion_fraction="0.02",
            sector_concentration="0.75",
            **common,
        )
        approve_materialize_and_stage()
    for level, multiplier in enumerate(("0.50", "1.50"), start=1):
        panel.create_liquidity_recipe(
            name=f"Liquidity evidence level {level}",
            volume_multiplier=multiplier,
            cross_sectional_concentration="0.50",
            **common,
        )
        approve_materialize_and_stage()
    for level, slippage in enumerate(("25", "100"), start=1):
        panel.create_execution_stress_recipe(
            name=f"Execution evidence level {level}",
            override_commission_bps="8",
            override_slippage_bps=slippage,
            override_max_fill_fraction="1",
            override_latency_nodes=0,
            override_allow_partial_fills=True,
            rejection_mode="none",
            **common,
        )
        approve_materialize_and_stage()

    isolated = panel.plan_isolated_sensitivity_set(
        initial_cash="100000",
        order_shares=1000,
        sensitivity_set_replica_id="evidence-isolated-set",
    )
    assert isolated["completeness"]["total_count"] == 12

    panel.create_compound_recipe(
        name="Evidence compound stress",
        transformations=(
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bearish",
                    "strength": "0.20",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.25"},
            },
        ),
        **common,
    )
    panel.validate_current_recipe()
    panel.approve_current_recipe(actor="owner")
    panel.materialize_current_recipe()
    panel.stage_current_materialization_as_compound_case()
    planned = panel.plan_diagnostic_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="formal-evidence-vertical",
    )
    assert planned["campaign_type"] == "formal_diagnostic_campaign"
    completed = panel.resume_diagnostic_campaign()
    assert completed["status"] == "completed"

    evidence = panel.build_diagnostic_evidence()

    assert evidence["status"] == "sealed"
    assert evidence["campaign_id"] == completed["campaign_id"]
    assert evidence["artifact_hash"]
    assert evidence["measurement_artifact_hash"]
    metric_names = {metric["name"] for metric in evidence["metrics"]}
    assert {
        "total_return",
        "net_return",
        "benchmark_relative_return",
        "maximum_drawdown",
        "maximum_recovery_duration_minutes",
        "return_volatility",
        "turnover",
        "average_holding_duration_minutes",
        "average_cash_utilization",
        "instrument_concentration",
        "industry_concentration",
        "trade_count",
        "total_fees",
        "fill_count",
        "partial_fill_count",
        "unfilled_quantity",
        "rejection_count",
        "execution_erosion",
    } <= metric_names
    assert any(
        comparison["kind"] == "cross-strategy"
        and comparison["layer"] == "compound"
        for comparison in evidence["comparisons"]
    )
    assert evidence["sensitivity_curves"]
    assert evidence["diagnostic_findings"]
    assert "composite_score" not in repr(evidence)
    assert panel.get_view()["diagnostic_evidence"] == evidence
    reproduction = panel.get_view()["reproduction"]
    assert reproduction["status"] == "ready_to_reproduce"
    assert len(reproduction["manifests"]) == 28
    accepted_orders = [
        order
        for item in reproduction["manifests"]
        for order in item["accepted_result"]["orders"]
    ]
    assert accepted_orders
    assert all(
        datetime.fromisoformat(order["activation_time"])
        > datetime.fromisoformat(order["decision_time"])
        for order in accepted_orders
    )
    manifest = reproduction["manifests"][0]
    assert manifest["strategy_run_specification"]["recipe_version_id"]
    assert manifest["strategy_run_specification"]["strategy_version"]
    assert manifest["strategy_run_specification"]["ptrade_surface_version"]
    assert manifest["numeric_tolerance"] == "0.000001"

    report = panel.reproduce_strategy_run(
        manifest_id=str(manifest["manifest_id"])
    )

    assert report["status"] == "reproduced_exactly"
    assert report["accepted_run_id"] == report["reproduced_run_id"]
    assert report["mismatches"] == []
    assert {
        (check["category"], check["status"])
        for check in report["checks"]
    } >= {
        ("dependencies", "exact"),
        ("orders", "exact"),
        ("fills", "exact"),
        ("portfolio", "exact"),
        ("equity_curve", "exact"),
        ("metrics", "exact"),
        ("evidence", "exact"),
        ("hashes", "exact"),
    }
    assert panel.get_view()["reproduction"]["latest_report"] == report
    acceptance = panel.get_view()["v1_acceptance"]
    assert acceptance["status"] == "passed", [
        check
        for check in acceptance["checks"]
        if not check["passed"]
    ]
    assert len(acceptance["checks"]) == 10
    assert all(check["passed"] for check in acceptance["checks"])
    assert len(acceptance["excluded_capabilities"]) == 7
    assert all(
        item["status"] == "absent"
        for item in acceptance["excluded_capabilities"]
    )
    assert acceptance["subject"] == {
        "campaign_id": completed["campaign_id"],
        "evidence_package_id": evidence["evidence_package_id"],
        "evidence_artifact_hash": evidence["artifact_hash"],
        "measurement_artifact_hash": evidence[
            "measurement_artifact_hash"
        ],
        "reproduction_manifest_id": manifest["manifest_id"],
        "reproduction_attempt_id": report["attempt_id"],
        "selected_strategy_versions": acceptance["evaluated_facts"][
            "selected_strategy_versions"
        ],
        "selected_guardrail_profiles": acceptance["evaluated_facts"][
            "selected_guardrail_profiles"
        ],
        "cadence_proofs": acceptance["subject"]["cadence_proofs"],
        "product_surface_inventory_hash": acceptance[
            "evaluated_facts"
        ]["product_surface_inventory"]["content_hash"],
    }
    cadence_proofs = acceptance["subject"]["cadence_proofs"]
    assert [
        proof["decision_cadence_minutes"] for proof in cadence_proofs
    ] == [30, 60]
    assert all(len(proof["run_ids"]) == 2 for proof in cadence_proofs)
    assert all(
        len(artifact_hash) == 64
        for proof in cadence_proofs
        for artifact_hash in proof["run_artifact_hashes"]
    )
    assert acceptance["evaluated_facts"][
        "supported_decision_cadences"
    ] == [30, 60]
    assert acceptance["evaluated_facts"][
        "ai_recipe_authoring_available"
    ] is True
    assert acceptance["evaluated_facts"][
        "ai_explanation_is_limited_to_sealed_findings"
    ] is True
    assert acceptance["evaluated_facts"][
        "product_surface_inventory"
    ]["status"] == "verified"

    replacement = panel.plan_diagnostic_campaign(
        initial_cash="100000",
        order_shares=1000,
        campaign_replica_id="formal-evidence-replacement",
    )

    assert replacement["campaign_id"] != completed["campaign_id"]
    replacement_view = panel.get_view()
    assert replacement_view["diagnostic_evidence"]["status"] == "not_built"
    assert "evidence_package_id" not in replacement_view[
        "diagnostic_evidence"
    ]
    assert replacement_view["diagnostic_finding_explanations"]["status"] == (
        "not_requested"
    )
    assert replacement_view["reproduction"]["status"] == "not_available"
    assert replacement_view["reproduction"]["manifests"] == []
    assert replacement_view["reproduction"]["latest_report"] is None
    assert replacement_view["v1_acceptance"]["status"] == "pending"
    with pytest.raises(
        ValueError,
        match="No sealed Diagnostic Evidence Package",
    ):
        panel.refresh_diagnostic_evidence()
    with pytest.raises(
        ValueError,
        match="No sealed Diagnostic Evidence Package",
    ):
        panel.explain_diagnostic_findings()


def test_gui_signals_complete_full_v1_acceptance_workflow() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(  # type: ignore[arg-type]
        _v1_admittable_application()
    )
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()

    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._commission_input.setText("3")
    adapter._slippage_input.setText("5")
    adapter._run_initial_cash_input.setText("100000")
    adapter._run_order_shares_input.setText("1000")
    adapter._apply_diagnostic_configuration_button.click()
    assert adapter.current_view()["diagnostic_configuration"]["status"] == (
        "complete"
    )

    def approve_materialize(button: object, name: str) -> None:
        adapter._recipe_name_input.setText(name)
        getattr(button, "click")()
        adapter._validate_recipe_button.click()
        assert adapter.current_view()["scenario_recipe_workbench"][
            "validation"
        ]["is_valid"] is True
        adapter._approve_recipe_button.click()
        adapter._materialize_recipe_button.click()
        assert adapter.current_view()["scenario_recipe_workbench"][
            "status"
        ] == "materialized"

    adapter._cadence_input.setText("60")
    approve_materialize(
        adapter._create_recipe_button,
        "GUI hourly baseline",
    )
    adapter._run_replica_input.setText("gui-hourly-baseline")
    adapter._run_campaign_button.click()
    hourly_campaign = adapter.current_view()["baseline_campaign"]
    assert hourly_campaign["status"] == "completed"
    assert {
        member["specification"]["decision_cadence_minutes"]
        for member in hourly_campaign["members"]
    } == {60}

    adapter._cadence_input.setText("30")
    approve_materialize(
        adapter._create_recipe_button,
        "GUI V1 baseline",
    )
    adapter._run_replica_input.setText("gui-v1-baseline")
    adapter._run_campaign_button.click()
    assert adapter.current_view()["baseline_campaign"]["status"] == "completed"

    for level, strength in enumerate(("0.10", "0.20"), start=1):
        adapter._trend_direction_input.setText("bullish")
        adapter._trend_strength_input.setText(strength)
        approve_materialize(
            adapter._create_trend_recipe_button,
            f"GUI trend {level}",
        )
        adapter._stage_sensitivity_case_button.click()
    for level, multiplier in enumerate(("0.75", "1.25"), start=1):
        adapter._volatility_multiplier_input.setText(multiplier)
        approve_materialize(
            adapter._create_volatility_recipe_button,
            f"GUI volatility {level}",
        )
        adapter._stage_sensitivity_case_button.click()
    for level, shock_fraction in enumerate(("0.02", "0.04"), start=1):
        adapter._shock_direction_input.setText("bearish")
        adapter._gap_fraction_input.setText("0.01")
        adapter._shock_fraction_input.setText(shock_fraction)
        adapter._shock_duration_input.setText("1")
        adapter._persistence_duration_input.setText("0")
        adapter._recovery_duration_input.setText("1")
        approve_materialize(
            adapter._create_shock_recovery_recipe_button,
            f"GUI shock recovery {level}",
        )
        adapter._stage_sensitivity_case_button.click()
    for level, breadth in enumerate(("0.25", "0.75"), start=1):
        adapter._breadth_target_input.setText(breadth)
        adapter._dispersion_fraction_input.setText("0.02")
        adapter._sector_concentration_input.setText("0.75")
        approve_materialize(
            adapter._create_market_structure_recipe_button,
            f"GUI market structure {level}",
        )
        adapter._stage_sensitivity_case_button.click()
    for level, multiplier in enumerate(("0.50", "1.50"), start=1):
        adapter._volume_multiplier_input.setText(multiplier)
        adapter._cross_sectional_concentration_input.setText("0.50")
        approve_materialize(
            adapter._create_liquidity_recipe_button,
            f"GUI liquidity {level}",
        )
        adapter._stage_sensitivity_case_button.click()
    for level, slippage in enumerate(("25", "100"), start=1):
        adapter._execution_override_commission_input.setText("8")
        adapter._execution_override_slippage_input.setText(slippage)
        adapter._execution_override_fill_fraction_input.setText("1")
        adapter._execution_override_latency_input.setText("0")
        adapter._execution_override_partial_input.setText("true")
        adapter._execution_rejection_mode_input.setText("none")
        approve_materialize(
            adapter._create_execution_stress_recipe_button,
            f"GUI execution stress {level}",
        )
        adapter._stage_sensitivity_case_button.click()

    staged = adapter.current_view()["isolated_sensitivity_case_staging"]
    assert staged["case_count"] == 12
    adapter._run_replica_input.setText("gui-v1-isolated")
    adapter._plan_sensitivity_set_button.click()
    assert adapter.current_view()["isolated_sensitivity_set"][
        "completeness"
    ]["total_count"] == 12

    adapter._trend_direction_input.setText("bearish")
    adapter._trend_strength_input.setText("0.20")
    adapter._volatility_multiplier_input.setText("1.25")
    approve_materialize(
        adapter._create_compound_recipe_button,
        "GUI V1 compound",
    )
    adapter._stage_compound_case_button.click()
    adapter._run_replica_input.setText("gui-v1-formal")
    adapter._plan_diagnostic_campaign_button.click()
    assert adapter.current_view()["diagnostic_campaign"][
        "campaign_type"
    ] == "formal_diagnostic_campaign"
    adapter._resume_diagnostic_campaign_button.click()
    assert adapter.current_view()["diagnostic_campaign"]["status"] == (
        "completed"
    )

    adapter._build_diagnostic_evidence_button.click()
    assert adapter.current_view()["diagnostic_evidence"]["status"] == "sealed"
    adapter._explain_diagnostic_findings_button.click()
    assert adapter.current_view()["diagnostic_finding_explanations"][
        "status"
    ] == "available"
    assert adapter._reproduction_manifest_input.text()
    reproduced_manifest_id = adapter._reproduction_manifest_input.text()
    adapter._reproduce_strategy_run_button.click()

    view = adapter.current_view()
    assert view["reproduction"]["latest_report"]["status"] == (
        "reproduced_exactly"
    )
    acceptance = view["v1_acceptance"]
    assert acceptance["status"] == "passed"
    assert len(acceptance["checks"]) == 10
    assert all(check["passed"] for check in acceptance["checks"])
    assert len(acceptance["excluded_capabilities"]) == 7
    assert all(
        item["status"] == "absent"
        for item in acceptance["excluded_capabilities"]
    )
    assert acceptance["subject"]["campaign_id"] == view[
        "diagnostic_campaign"
    ]["campaign_id"]
    assert acceptance["subject"]["evidence_package_id"] == view[
        "diagnostic_evidence"
    ]["evidence_package_id"]
    assert acceptance["subject"]["evidence_artifact_hash"] == view[
        "diagnostic_evidence"
    ]["artifact_hash"]
    assert acceptance["subject"]["reproduction_manifest_id"] == (
        reproduced_manifest_id
    )
    assert acceptance["subject"]["reproduction_attempt_id"] == view[
        "reproduction"
    ]["latest_report"]["attempt_id"]
    assert [
        proof["decision_cadence_minutes"]
        for proof in acceptance["subject"]["cadence_proofs"]
    ] == [30, 60]
    assert acceptance["evaluated_facts"][
        "supported_decision_cadences"
    ] == [30, 60]
    assert acceptance["evaluated_facts"][
        "ai_recipe_authoring_available"
    ] is True
    assert acceptance["evaluated_facts"][
        "ai_explanation_is_limited_to_sealed_findings"
    ] is True
    assert acceptance["evaluated_facts"][
        "product_surface_inventory"
    ]["status"] == "verified"
    assert len(view["reproduction"]["manifests"]) == 28
    gui_accepted_orders = [
        order
        for item in view["reproduction"]["manifests"]
        for order in item["accepted_result"]["orders"]
    ]
    assert gui_accepted_orders
    assert all(
        datetime.fromisoformat(order["activation_time"])
        > datetime.fromisoformat(order["decision_time"])
        for order in gui_accepted_orders
    )
    manifest = view["reproduction"]["manifests"][0]
    pinned = manifest["strategy_run_specification"]
    assert pinned["recipe_version_id"]
    assert pinned["strategy_version"]
    assert pinned["execution_conditions"]["requested"]
    assert pinned["execution_conditions"]["effective"]
    assert view["diagnostic_evidence"]["diagnostic_findings"]
    assert view["diagnostic_evidence"]["sensitivity_curves"]
    assert len(view["baseline_campaign"]["equity_overlay"]) == 2
    assert len(view["baseline_campaign"]["drawdown_overlay"]) == 2

    configuration_text = (
        adapter._diagnostic_configuration_view.toPlainText()
    )
    assert QUENTX_SCENARIO_NATIVE_STRATEGY_ID in configuration_text
    assert LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID in configuration_text
    assert "quentx-balanced-diagnostics.v1" in configuration_text
    assert "live-minute-capital-preservation.v1" in configuration_text
    assert "PTrade" in configuration_text
    assert "Source: BaoStock / workspace-fixture / v1" in (
        adapter._provenance_label.text()
    )
    assert "trend-regime.v1" in adapter._scenario_preview_label.text()
    assert "volatility-scaling.v1" in adapter._scenario_preview_label.text()
    assert "Formal Diagnostic Campaign: completed" in (
        adapter._diagnostic_campaign_status_label.text()
    )
    assert "Diagnostic Findings" in (
        adapter._diagnostic_evidence_details_view.toPlainText()
    )
    assert "Plain-language explanation grounded only" in (
        adapter._diagnostic_evidence_details_view.toPlainText()
    )
    reproduction_text = adapter._reproduction_details_view.toPlainText()
    assert "Requested execution" in reproduction_text
    assert "Effective execution" in reproduction_text
    assert "No mismatches" in reproduction_text
    assert "V1 acceptance: passed" in (
        adapter._v1_acceptance_status_label.text()
    )
    acceptance_text = adapter._v1_acceptance_details_view.toPlainText()
    assert acceptance_text.count("PASSED |") == 10
    assert acceptance_text.count("ABSENT |") == 7


def test_diagnostics_adapter_renders_sealed_multidimensional_evidence() -> None:
    _ensure_qapp()
    adapter = DiagnosticsPanelAdapter()
    adapter.widget()
    adapter._apply_view(
        {
            "diagnostic_evidence": {
                "status": "sealed",
                "evidence_package_id": "diagnostic-evidence-fixture",
                "artifact_hash": "a" * 64,
                "measurement_artifact_hash": "b" * 64,
                "metrics": [
                    {
                        "strategy_id": QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                        "layer": "baseline",
                        "case_id": "baseline-case",
                        "name": "total_return",
                        "value": "0.12",
                    },
                    {
                        "strategy_id": QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                        "layer": "compound",
                        "case_id": "compound-case",
                        "name": "execution_erosion_bps",
                        "value": "84",
                    },
                ],
                "comparisons": [
                    {
                        "kind": "cross-strategy",
                        "metric_name": "total_return",
                        "case_id": "compound-case",
                        "subject_strategy_id": (
                            QUENTX_SCENARIO_NATIVE_STRATEGY_ID
                        ),
                        "control_strategy_id": (
                            LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID
                        ),
                        "delta": "0.04",
                    }
                ],
                "guardrail_breaches": [
                    {
                        "strategy_id": QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                        "case_id": "compound-case",
                        "metric_name": "execution_erosion_bps",
                        "metric_value": "84",
                        "threshold": {
                            "operator": "greater_than",
                            "value": "75",
                        },
                    }
                ],
                "sensitivity_breakpoints": [
                    {
                        "strategy_id": QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                        "transformation_family": "liquidity",
                        "metric_name": "execution_erosion_bps",
                        "bounded_interval": {
                            "lower_parameters": {"level": "1"},
                            "upper_parameters": {"level": "2"},
                        },
                    }
                ],
                "diagnostic_findings": [
                    {
                        "kind": "weakness",
                        "finding_id": "diagnostic-finding-fixture",
                        "statement": (
                            "Execution erosion crossed the selected guardrail."
                        ),
                    }
                ],
            },
            "diagnostic_finding_explanations": {
                "status": "available",
                "explanations": [
                    {
                        "finding_id": "diagnostic-finding-fixture",
                        "text": "The sealed finding is sensitive to liquidity.",
                    }
                ],
            },
            "reproduction": {
                "status": "reproducibility_invalid",
                "message": (
                    "The pinned execution environment changed; no fallback "
                    "was used."
                ),
                "manifests": [
                    {
                        "manifest_id": "reproduction-manifest-fixture",
                        "run_id": "strategy-run-fixture",
                        "numeric_tolerance": "0.000001",
                        "strategy_run_specification": {
                            "strategy_id": (
                                QUENTX_SCENARIO_NATIVE_STRATEGY_ID
                            ),
                            "strategy_version": "1.0.0",
                            "recipe_version_id": "recipe-version-fixture",
                            "materialization_hash": "c" * 64,
                            "source_snapshot_id": "snapshot-fixture",
                            "code_identity": "strategy-diagnostics.v1",
                        },
                    }
                ],
                "latest_report": {
                    "attempt_id": "reproduction-attempt-fixture",
                    "status": "reproducibility_invalid",
                    "accepted_run_id": "strategy-run-fixture",
                    "reproduced_run_id": None,
                    "checks": [
                        {
                            "category": "dependencies",
                            "status": "mismatch",
                            "message": (
                                "A pinned dependency is missing or changed."
                            ),
                        }
                    ],
                    "mismatches": [
                        {
                            "code": "dependency.code_identity_changed",
                            "path": "code_identity",
                            "expected": "strategy-diagnostics.v1",
                            "actual": "strategy-diagnostics.v2",
                            "message": (
                                "Pinned diagnostic code identity changed."
                            ),
                        }
                    ],
                },
            },
        }
    )

    status = adapter._diagnostic_evidence_status_label.text()
    assert "sealed" in status
    assert "2 metrics" in status
    assert "1 comparisons" in status
    assert "1 guardrail crossings" in status
    assert "1 sensitivity breakpoints" in status
    assert "1 findings" in status
    details = adapter._diagnostic_evidence_details_view.toPlainText()
    assert "No universal composite score or strategy ranking" in details
    assert "total_return | 0.12" in details
    assert (
        f"cross-strategy | {QUENTX_SCENARIO_NATIVE_STRATEGY_ID} | "
        f"{LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID} | compound-case | "
        "total_return | 0.04"
    ) in details
    assert "execution_erosion_bps | 84 | greater_than | 75" in details
    assert "liquidity | execution_erosion_bps" in details
    assert "diagnostic-finding-fixture" in details
    assert "The sealed finding is sensitive to liquidity." in details
    reproduction_status = adapter._reproduction_status_label.text()
    assert "reproducibility_invalid" in reproduction_status
    assert "1 manifests" in reproduction_status
    assert (
        adapter._reproduction_manifest_input.text()
        == "reproduction-manifest-fixture"
    )
    reproduction_details = adapter._reproduction_details_view.toPlainText()
    assert (
        f"{QUENTX_SCENARIO_NATIVE_STRATEGY_ID}@1.0.0"
        in reproduction_details
    )
    assert "recipe-version-fixture" in reproduction_details
    assert "reproducibility_invalid" in reproduction_details
    assert "dependency.code_identity_changed | code_identity" in (
        reproduction_details
    )
    assert "expected=strategy-diagnostics.v1" in reproduction_details
    assert "actual=strategy-diagnostics.v2" in reproduction_details


def test_diagnostics_adapter_runs_a_staged_compound_quick_experiment() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("UI compound experiment")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._cadence_input.setText("30")
    adapter._seed_input.setText("17")
    adapter._slippage_input.setText("5")
    adapter._trend_direction_input.setText("bearish")
    adapter._trend_strength_input.setText("0.5")
    adapter._volatility_multiplier_input.setText("1.5")
    adapter._run_initial_cash_input.setText("100000")
    adapter._run_order_shares_input.setText("1000")
    adapter._run_replica_input.setText("ui-quick-compound-1")

    adapter._create_compound_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()
    adapter._stage_compound_case_button.click()
    adapter._plan_diagnostic_campaign_button.click()
    adapter._resume_diagnostic_campaign_button.click()

    campaign = adapter.current_view()["diagnostic_campaign"]
    assert campaign["campaign_type"] == "quick_experiment"
    assert campaign["status"] == "completed"
    assert campaign["formal_attribution"]["claim_status"] == "not_permitted"
    assert "Quick Experiment" in adapter._diagnostic_campaign_status_label.text()
    assert "1/1 complete" in adapter._diagnostic_campaign_status_label.text()


def test_diagnostics_adapter_explains_campaign_policy_before_launch() -> None:
    _ensure_qapp()
    panel = DiagnosticsPanel(_admittable_application())  # type: ignore[arg-type]
    adapter = DiagnosticsPanelAdapter().bind(panel)
    adapter.widget()
    adapter._market_input.setText("mainland-a-share")
    adapter._start_date_input.setText("2024-01-02")
    adapter._end_date_input.setText("2024-01-02")
    adapter._admit_button.click()
    adapter._recipe_name_input.setText("Default single-run recipe")
    adapter._recipe_author_input.setText("researcher")
    adapter._recipe_actor_input.setText("owner")
    adapter._create_recipe_button.click()
    adapter._validate_recipe_button.click()
    adapter._approve_recipe_button.click()
    adapter._materialize_recipe_button.click()

    adapter._run_campaign_button.click()

    assert adapter.current_view()["baseline_campaign"]["status"] == "not_started"
    assert "slippage 5 bps" in adapter._campaign_status_label.text()
    assert "commission 3 bps" in adapter._campaign_status_label.text()


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
