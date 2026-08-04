from __future__ import annotations

import gc
import os
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeScenarioLabAdapter,
    ScenarioLabContext,
    LiveScenarioLabAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    ScenarioCompatibilityState,
    ScenarioLabApplicationAvailability,
    ScenarioLabApplicationErrorCode,
    ScenarioLabIntegrityState,
    ScenarioReproducibilityState,
)
from app.ui.journey_workspace import JourneyWorkspaceHost
from strategy_diagnostics import (
    AdmissionCheck,
    FiveMinuteBar,
    HistoricalMarketSegment,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryMarketPathArtifactStore,
    InstrumentState,
    ScenarioDataWorldInput,
    SessionPriceLimitReference,
    ScenarioLabCompatibilityAssessment,
    ScenarioLabInventoryReason,
    ScenarioLabInventoryReasonCode,
    ScenarioLabReproducibilityAssessment,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _quick_items(root: QQuickItem) -> tuple[QQuickItem, ...]:
    found: list[QQuickItem] = []
    pending = [root]
    while pending:
        item = pending.pop()
        found.append(item)
        pending.extend(item.childItems())
    return tuple(found)


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


class _AdmittedScenarioLabSource:
    def __init__(self) -> None:
        self.selection = HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )
        self.provenance = SourceProvenance(
            provider="Scenario Lab live tracer",
            dataset="one-day-a-share",
            version="v1",
            observed_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        if selection != self.selection:
            return None
        return HistoricalSourceInspection(
            selection=selection,
            label="One admitted trading day",
            provenance=self.provenance,
            artifacts=(SourceArtifact("fixture-bars", "2" * 64, 2),),
            eligible_instrument_count=1,
            trading_day_count=1,
            bar_count=2,
            checks=tuple(
                AdmissionCheck(code, True, f"{code} passed")
                for code in _REQUIRED_ADMISSION_CHECKS
            ),
            recommendation_tags=("baseline",),
        )

    def load_scenario_data_world(
        self,
        segment: HistoricalMarketSegment,
    ) -> ScenarioDataWorldInput:
        return ScenarioDataWorldInput(
            segment_id=segment.segment_id,
            segment_content_hash=segment.content_hash,
            source_snapshot_id=segment.source_snapshot_id,
            bars=(
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 35),
                    open=Decimal("10"),
                    high=Decimal("10.3"),
                    low=Decimal("9.9"),
                    close=Decimal("10.2"),
                    volume=101,
                    amount=Decimal("1025.5"),
                ),
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 40),
                    open=Decimal("10.2"),
                    high=Decimal("10.4"),
                    low=Decimal("10.1"),
                    close=Decimal("10.35"),
                    volume=90,
                    amount=Decimal("925"),
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
                    decision_adjustment_provenance="fixture-as-of-v1",
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
                    rule_code="fixture.sh-main.ordinary.10pct",
                ),
            ),
        )


class _FailClosedArtifactStore(InMemoryMarketPathArtifactStore):
    def get(self, artifact_hash: str):
        raise ValueError("fixture immutable path integrity failure")


def _approve_baseline_recipe(application, segment_id: str) -> str:
    draft = application.create_manual_recipe_draft(
        {
            "schema_version": "scenario_recipe.v1",
            "name": "Scenario Lab live baseline",
            "historical_segment_id": segment_id,
            "transformations": [],
            "execution_conditions": {},
            "decision_cadence_minutes": 30,
            "materialization_seed": 17,
            "data_policy": "point-in-time",
            "market_rule_profile": "a-share-cash-equity.v1",
        },
        author="issue-79-tracer",
    )
    validation = application.validate_recipe_draft(draft.draft_id)
    assert validation.is_valid
    return application.approve_recipe_draft(
        draft.draft_id,
        actor="issue-79-owner",
    ).version_id


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def test_production_workspace_browses_scenario_lab_read_tracer() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    scenario_feature = DeterministicFakeScenarioLabAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(),
        initial_route="scenario_lab",
    )
    app.processEvents()
    root = host.rootObject()

    assert root is not None
    assert root.property("activeRoute") == "scenario_lab"
    assert root.findChild(QObject, "scenarioLabRouteNavigation") is not None
    assert root.findChild(QObject, "scenarioLabPage") is not None
    assert host._scenario_lab.presentationState == "ready"
    assert host._scenario_lab.historicalSegmentCount == 1
    assert host._scenario_lab.referencePathCount == 1
    assert host._scenario_lab.marketScenarioCount == 1
    assert host._scenario_lab.referencePaths[0]["pathId"] != (
        host._scenario_lab.marketScenarios[0]["scenarioId"]
    )
    segment = host._scenario_lab.historicalSegments[0]
    path = host._scenario_lab.referencePaths[0]
    scenario = host._scenario_lab.marketScenarios[0]
    assert segment["contentHash"]
    assert segment["sourceSnapshotId"]
    assert segment["sourceSnapshotContentHash"]
    assert path["segmentContentHash"]
    assert path["eligibleUniverse"]
    assert path["previewNodes"]
    assert path["previewNodes"][0]["simulationTime"]
    assert scenario["segmentContentHash"]
    assert scenario["transformations"] == []
    assert scenario["requestedExecutionAssumptions"] == {
        "commissionBps": "3",
        "slippageBps": "5",
        "maxFillFraction": "1",
        "latencyNodes": 1,
        "allowPartialFills": True,
    }
    for object_name in (
        "scenarioLabMarketFilter",
        "scenarioLabSourceFilter",
        "scenarioLabRecipeVersionFilter",
        "scenarioLabLayerFilter",
        "scenarioLabTransformationFamilyFilter",
        "scenarioLabCompatibilityFilter",
        "scenarioLabReproducibilityFilter",
        "scenarioLabReconstructionFilter",
    ):
        assert root.findChild(QObject, object_name) is not None
    visible_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    ).casefold()
    for expected in (
        "admitted historical market segments",
        "immutable reference market paths",
        "market scenario projections",
        "not recorded microstructure",
        "not yet available",
        segment["contentHash"],
        segment["sourceSnapshotId"],
        segment["sourceSnapshotContentHash"],
        path["segmentContentHash"],
        path["previewNodes"][0]["instrument"],
        scenario["recipeContentHash"],
        scenario["requestedExecutionAssumptions"]["maxFillFraction"],
        "parameter schema",
        "multiplier type decimal required true",
        "bounds min 0.5 / max 2",
        "execution_assumptions_unresolved",
        "resolve the selected strategy under test",
    ):
        assert str(expected).casefold() in visible_text
    for forbidden in (
        "buy",
        "sell",
        "submit order",
        "cancel order",
        "broker",
        "edit reproduction manifest",
    ):
        assert forbidden not in visible_text

    host._scenario_lab.setSearchText("volatility")
    app.processEvents()
    assert host._scenario_lab.transformations[0]["family"] == "volatility"
    host._scenario_lab.setMarketFilter("missing")
    app.processEvents()
    assert host._scenario_lab.historicalSegmentCount == 0
    assert host._scenario_lab.referencePathCount == 0
    assert host._scenario_lab.marketScenarioCount == 0
    host._scenario_lab.setMarketFilter("")
    host._scenario_lab.setLayerFilter("compound")
    app.processEvents()
    assert host._scenario_lab.marketScenarioCount == 0
    host._scenario_lab.setLayerFilter("")
    host._scenario_lab.setReconstructionFilter("recorded")
    app.processEvents()
    assert host._scenario_lab.referencePathCount == 0
    host._scenario_lab.setReconstructionFilter("all")
    host._scenario_lab.setSourceFilter("missing-source")
    app.processEvents()
    assert host._scenario_lab.historicalSegmentCount == 0
    assert host._scenario_lab.referencePathCount == 0
    assert host._scenario_lab.marketScenarioCount == 0
    host._scenario_lab.setSourceFilter("")
    host._scenario_lab.setRecipeVersionFilter("missing-recipe")
    app.processEvents()
    assert host._scenario_lab.marketScenarioCount == 0
    host._scenario_lab.setRecipeVersionFilter("")
    host._scenario_lab.setTransformationFamilyFilter("volatility")
    app.processEvents()
    assert host._scenario_lab.referencePathCount == 0
    assert host._scenario_lab.marketScenarioCount == 0
    assert host._scenario_lab.transformations[0]["family"] == "volatility"
    host._scenario_lab.setTransformationFamilyFilter("")
    host._scenario_lab.setCompatibilityFilter("unavailable")
    app.processEvents()
    assert host._scenario_lab.referencePathCount == 0
    assert host._scenario_lab.marketScenarioCount == 0
    host._scenario_lab.setCompatibilityFilter("")
    host._scenario_lab.setReproducibilityFilter("unavailable")
    app.processEvents()
    assert host._scenario_lab.referencePathCount == 0
    assert host._scenario_lab.marketScenarioCount == 0
    host.close_adapter()
    scenario_feature.close()
    run_feature.close()


def test_scenario_lab_route_restores_meaningful_keyboard_focus() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    scenario_feature = DeterministicFakeScenarioLabAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        scenario_lab_feature=scenario_feature,
        initial_route="scenario_lab",
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    root = host.rootObject()
    assert root is not None
    search = root.findChild(QQuickItem, "scenarioLabSearchInput")
    scenario_route = root.findChild(QQuickItem, "scenarioLabRouteNavigation")
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    assert search is not None
    assert scenario_route is not None
    assert run_route is not None

    search.forceActiveFocus()
    app.processEvents()
    assert search.property("activeFocus") is True

    run_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "run_monitoring"

    scenario_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "scenario_lab"
    assert search.property("activeFocus") is True
    host.close_adapter()
    run_feature.close()
    scenario_feature.close()


def test_real_backend_inventory_traces_through_live_feature_into_qml() -> None:
    app = _app()
    source = _AdmittedScenarioLabSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    assert admission.source_snapshot is not None
    recipe_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
    )
    path = application.materialize_baseline_reference_path(recipe_version_id)
    backend_inventory = application.read_diagnostic_campaign_case_inventory()
    assert len(backend_inventory.available_cases) == 1
    backend_case = backend_inventory.available_cases[0]

    scenario_application = (
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)
    )
    scenario_feature = LiveScenarioLabAdapter(application=scenario_application)
    run_feature = DeterministicFakeRunMonitoringAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        scenario_lab_feature=scenario_feature,
        initial_route="scenario_lab",
    )
    app.processEvents()

    assert host._scenario_lab.historicalSegments[0]["segmentId"] == (
        admission.segment.segment_id
    )
    assert (
        scenario_feature.snapshot(ScenarioLabContext())
        .historical_segments[0]
        .source_snapshot_content_hash
        == admission.source_snapshot.content_hash
    )
    assert host._scenario_lab.referencePaths[0]["pathId"] == path.artifact_hash
    assert host._scenario_lab.marketScenarios[0]["scenarioId"] == (
        backend_case.case_id
    )
    assert host._scenario_lab.marketScenarios[0]["pathId"] == path.artifact_hash
    assert backend_case.case_id != path.artifact_hash
    assert host._scenario_lab.referencePaths[0]["integrity"] == "verified"
    assert host._scenario_lab.referencePaths[0]["previewNodeCount"] == 1
    host.close_adapter()
    scenario_feature.close()
    run_feature.close()


def test_live_application_fails_closed_when_path_preview_integrity_fails() -> None:
    source = _AdmittedScenarioLabSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=_FailClosedArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    recipe_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
    )
    application.materialize_baseline_reference_path(recipe_version_id)

    result = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        application
    ).read_inventory()

    assert result.availability is ScenarioLabApplicationAvailability.PARTIAL
    assert result.inventory is not None
    assert result.inventory.reference_paths[0].integrity is (
        ScenarioLabIntegrityState.FAILED
    )
    assert result.inventory.reference_paths[0].preview is None
    assert result.inventory.market_scenarios[0].compatibility is (
        ScenarioCompatibilityState.UNAVAILABLE
    )
    assert result.inventory.market_scenarios[0].scenario_id.value.startswith(
        "campaign-case-"
    )


class _AssessmentOverrideApplication:
    def __init__(self, delegate, inventory) -> None:
        self._delegate = delegate
        self._inventory = inventory

    def read_diagnostic_campaign_case_inventory(self):
        return self._inventory

    def transformation_catalog_view(self):
        return self._delegate.transformation_catalog_view()

    def preview_reference_market_path(self, path_id, *, at_time=None):
        return self._delegate.preview_reference_market_path(
            path_id,
            at_time=at_time,
        )


def _materialized_assessment_fixture():
    source = _AdmittedScenarioLabSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    recipe_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
    )
    application.materialize_baseline_reference_path(recipe_version_id)
    return application, application.read_diagnostic_campaign_case_inventory()


def test_live_application_maps_backend_owned_compatibility_and_reproducibility() -> None:
    application, inventory = _materialized_assessment_fixture()
    path_assessment = replace(
        inventory.path_assessments[0],
        compatibility=ScenarioLabCompatibilityAssessment.INCOMPATIBLE,
        reproducibility=ScenarioLabReproducibilityAssessment.NONREPRODUCIBLE,
        reasons=(
            ScenarioLabInventoryReason(
                code=ScenarioLabInventoryReasonCode.PATH_RECIPE_INCOMPATIBLE,
                summary="Fixture backend assessment.",
                corrective_guidance="Select a compatible fixture Recipe.",
            ),
        ),
    )
    case_assessment = replace(
        inventory.case_assessments[0],
        compatibility=ScenarioLabCompatibilityAssessment.INCOMPATIBLE,
        reproducibility=ScenarioLabReproducibilityAssessment.NONREPRODUCIBLE,
        reasons=(
            ScenarioLabInventoryReason(
                code=ScenarioLabInventoryReasonCode.PATH_RECIPE_INCOMPATIBLE,
                summary="Fixture backend assessment.",
                corrective_guidance="Select a compatible fixture Recipe.",
            ),
        ),
    )
    overridden = replace(
        inventory,
        path_assessments=(path_assessment,),
        case_assessments=(case_assessment,),
    )

    result = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        _AssessmentOverrideApplication(application, overridden)
    ).read_inventory()

    assert result.inventory is not None
    assert result.inventory.reference_paths[0].compatibility is (
        ScenarioCompatibilityState.INCOMPATIBLE
    )
    assert result.inventory.reference_paths[0].reproducibility is (
        ScenarioReproducibilityState.NONREPRODUCIBLE
    )
    assert result.inventory.market_scenarios[0].compatibility is (
        ScenarioCompatibilityState.INCOMPATIBLE
    )
    assert result.inventory.market_scenarios[0].reproducibility is (
        ScenarioReproducibilityState.NONREPRODUCIBLE
    )
    reason = result.inventory.market_scenarios[0].unavailability_reasons[0]
    assert reason.code.value == "reference_path_recipe_incompatible"
    assert reason.summary == "Fixture backend assessment."
    assert reason.corrective_guidance == "Select a compatible fixture Recipe."


@pytest.mark.parametrize("assessment_kind", ("path", "case"))
def test_live_application_fails_closed_on_misaligned_assessment_identity(
    assessment_kind: str,
) -> None:
    application, inventory = _materialized_assessment_fixture()
    if assessment_kind == "path":
        overridden = replace(
            inventory,
            path_assessments=(
                replace(
                    inventory.path_assessments[0],
                    path_identity="wrong-path-identity",
                ),
            ),
        )
    else:
        overridden = replace(
            inventory,
            case_assessments=(
                replace(
                    inventory.case_assessments[0],
                    campaign_case_identity="wrong-case-identity",
                ),
            ),
        )

    result = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        _AssessmentOverrideApplication(application, overridden)
    ).read_inventory()

    assert result.availability is ScenarioLabApplicationAvailability.FAILED
    assert result.inventory is None
    assert result.error is not None
    assert result.error.code is ScenarioLabApplicationErrorCode.INVENTORY_READ_FAILED


def test_nonbaseline_case_maps_exact_baseline_identity_across_recipe_versions() -> None:
    source = _AdmittedScenarioLabSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    baseline_version_id = _approve_baseline_recipe(
        application,
        admission.segment.segment_id,
    )
    transformed_draft = application.create_manual_recipe_draft(
        {
            "schema_version": "scenario_recipe.v1",
            "name": "Scenario Lab isolated sensitivity",
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
        },
        author="issue-79-tracer",
    )
    assert application.validate_recipe_draft(transformed_draft.draft_id).is_valid
    transformed_version_id = application.approve_recipe_draft(
        transformed_draft.draft_id,
        actor="issue-79-owner",
    ).version_id
    compound_draft = application.create_manual_recipe_draft(
        {
            "schema_version": "scenario_recipe.v1",
            "name": "Scenario Lab compound sensitivity",
            "historical_segment_id": admission.segment.segment_id,
            "transformations": [
                {
                    "transformation_id": "trend-regime.v1",
                    "parameters": {"direction": "bullish", "strength": "0.75"},
                },
                {
                    "transformation_id": "volatility-scaling.v1",
                    "parameters": {"multiplier": "1.25"},
                },
            ],
            "execution_conditions": {},
            "decision_cadence_minutes": 30,
            "materialization_seed": 17,
            "data_policy": "point-in-time",
            "market_rule_profile": "a-share-cash-equity.v1",
        },
        author="issue-79-tracer",
    )
    assert application.validate_recipe_draft(compound_draft.draft_id).is_valid
    compound_version_id = application.approve_recipe_draft(
        compound_draft.draft_id,
        actor="issue-79-owner",
    ).version_id
    application.materialize_reference_path(baseline_version_id)
    application.materialize_reference_path(transformed_version_id)
    application.materialize_reference_path(compound_version_id)

    result = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
        application
    ).read_inventory()

    assert result.inventory is not None
    baseline = next(
        item for item in result.inventory.market_scenarios if item.layer.value == "baseline"
    )
    isolated = next(
        item
        for item in result.inventory.market_scenarios
        if item.layer.value == "isolated_sensitivity"
    )
    compound = next(
        item for item in result.inventory.market_scenarios if item.layer.value == "compound"
    )
    assert isolated.recipe_version_id != baseline.recipe_version_id
    assert isolated.baseline_scenario_id == baseline.scenario_id
    assert isolated.compatibility is ScenarioCompatibilityState.COMPATIBLE
    assert compound.recipe_version_id != baseline.recipe_version_id
    assert compound.baseline_scenario_id == baseline.scenario_id
    assert compound.compatibility is ScenarioCompatibilityState.COMPATIBLE
