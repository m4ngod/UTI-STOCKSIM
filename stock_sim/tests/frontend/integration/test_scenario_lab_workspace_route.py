from __future__ import annotations

import gc
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import monotonic

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
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyLibraryAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    ScenarioCompatibilityState,
    ScenarioLabApplicationAvailability,
    ScenarioLabApplicationErrorCode,
    ScenarioLabIntegrityState,
    ScenarioReproducibilityState,
)
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _formal_live_stack,
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


def _process_until(
    app: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Qt event-loop condition did not become true")


def test_scenario_lab_qml_authoring_controls_bind_only_typed_exact_identities() -> None:
    source = (
        Path(__file__).parents[3] / "app" / "ui" / "qml" / "ScenarioLabPage.qml"
    ).read_text(encoding="utf-8")

    assert "Approve exact validated revision" in source
    assert "adapter.approveRecipeValidation(" in source
    assert "modelData.validationId" in source
    assert (
        "Approval binds this exact Draft revision, payload hash, validation, "
        "and dependency identities"
    ) in source
    assert "Select for successor Draft" in source
    assert "adapter.selectApprovedRecipeVersion(" in source
    assert "Creates no mutation until the explicit successor Draft action" in source
    assert "adapter.materializeApprovedRecipeVersion(" in source
    assert "modelData.recipeVersionId" in source
    assert "adapter.retryMaterialization(" in source
    assert "modelData.attemptId" in source
    assert "modelData.taskHandleId" in source
    assert "adapter.composeVisibleScenarioSet()" in source
    assert "adapter.resolveLatestScenarioSet()" in source
    assert "adapter.selectLatestFormalScenarioSet()" in source
    assert "after-Decision-Time" in source
    assert "Quick Experiment" in source
    assert "requested " in source and " effective " in source


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
        "scenarioLabRecipeAuthoringPanel",
        "scenarioLabCreateRecipeDraftButton",
        "scenarioLabReviseRecipeDraftButton",
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
        "exact scenario recipe draft authoring",
        "manual authoring is always available",
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


def test_production_workspace_authors_materializes_and_remounts_exact_recipes() -> None:
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
    root.setWidth(1440)
    root.setHeight(1200)
    app.processEvents()
    segment_id = host._scenario_lab.historicalSegments[0]["segmentId"]

    host._scenario_lab.createRecipeDraft(
        "QML exact baseline",
        segment_id,
        "",
        "3",
        "0",
        "1",
        "",
        0,
        30,
        80,
        True,
        "a-share-cash-equity.v1",
    )
    app.processEvents()
    assert host._scenario_lab.recipeDraftCount == 1
    created = host._scenario_lab.recipeDrafts[0]
    assert created["revision"] == 1
    assert created["historicalSegmentId"] == segment_id
    assert created["dataPolicy"] == "point_in_time"
    assert root.findChild(QObject, "scenarioLabRecipeDraftRepeater") is not None

    host._scenario_lab.selectRecipeDraft(created["draftId"])
    host._scenario_lab.reviseSelectedRecipeDraft(
        "QML exact successor",
        "volatility-scaling.v1",
        "4",
        "1",
        "0.5",
        "1.2",
        1,
        30,
        81,
        True,
        "a-share-cash-equity.v1",
    )
    app.processEvents()
    assert host._scenario_lab.recipeDraftCount == 2
    revised = host._scenario_lab.recipeDrafts[-1]
    assert revised["revision"] == 2
    assert revised["predecessorDraftId"] == created["draftId"]
    assert revised["transformations"] == [
        {
            "transformationId": "volatility-scaling.v1",
            "implementationVersion": "draft-selection",
            "parameters": [
                {"name": "multiplier", "kind": "decimal", "value": "1.2"}
            ],
        }
    ]

    host._scenario_lab.validateRecipeDraft(revised["draftId"])
    app.processEvents()
    assert host._scenario_lab.recipeValidationCount == 1
    validation = host._scenario_lab.recipeValidations[0]
    assert validation["draftId"] == revised["draftId"]
    assert validation["valid"] is True
    assert validation["dependencies"]["historicalSegmentId"] == segment_id
    assert validation["dependencies"]["recipeSchemaHash"]
    assert validation["dependencies"]["transformationImplementations"]
    assert validation["dependencies"]["dataPolicy"] == "point_in_time"
    assert root.findChild(QObject, "scenarioLabRecipeValidationRepeater") is not None
    validation_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for exact_identity in (
        validation["validationId"],
        revised["payloadHash"],
        validation["dependencies"]["historicalSegmentId"],
        validation["dependencies"]["sourceSnapshotId"],
        validation["dependencies"]["recipeSchemaHash"],
        validation["dependencies"]["transformationCatalogHash"],
        validation["dependencies"]["marketRuleProfileHash"],
        validation["dependencies"]["dataPolicy"],
    ):
        assert exact_identity in validation_text
    for exact_identity in (
        *validation["dependencies"]["transformationImplementations"],
        *validation["dependencies"]["causalityRules"],
    ):
        assert exact_identity in validation_text
    for observation in validation["dependencies"]["compatibilityObservations"]:
        assert observation["subject"] in validation_text
        assert observation["explanation"] in validation_text
    assert "accepted" in host._scenario_lab.recipeCapabilityMessage

    host._scenario_lab.approveRecipeValidation(validation["validationId"])
    app.processEvents()
    assert host._scenario_lab.approvedRecipeVersionCount == 1
    approved = host._scenario_lab.approvedRecipeVersions[0]
    assert approved["recipeId"]
    assert approved["recipeVersionId"]
    assert approved["versionNumber"] == 1
    assert approved["contentHash"] == revised["payloadHash"]
    assert approved["approvalId"]
    assert approved["draftId"] == revised["draftId"]
    assert approved["validationId"] == validation["validationId"]
    assert approved["dependencyBindingAvailable"] is True
    assert approved["authorityState"] == "current"
    assert approved["canMaterialize"] is True
    assert approved["historicalSegmentId"] == segment_id
    assert approved["recipeSchemaHash"]
    assert approved["materializationSeed"] == revised["materializationSeed"]
    assert approved["transformations"][0]["transformationId"] == (
        "volatility-scaling.v1"
    )
    assert approved["transformationImplementations"] == (
        validation["dependencies"]["transformationImplementations"]
    )
    assert approved["dataPolicy"] == validation["dependencies"]["dataPolicy"]
    assert approved["causalityRules"] == validation["dependencies"]["causalityRules"]
    assert approved["compatibilityObservations"] == (
        validation["dependencies"]["compatibilityObservations"]
    )
    assert root.findChild(QObject, "scenarioLabApprovedRecipeRepeater") is not None
    approved_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for exact_identity in (
        approved["recipeId"],
        approved["recipeVersionId"],
        approved["contentHash"],
        approved["approvalId"],
        approved["draftId"],
        approved["validationId"],
        approved["historicalSegmentContentHash"],
        approved["sourceSnapshotContentHash"],
        approved["transformationCatalogHash"],
        approved["marketRuleProfileHash"],
        approved["dataPolicy"],
        str(approved["materializationSeed"]),
        approved["transformations"][0]["transformationId"],
    ):
        assert exact_identity in approved_text
    for exact_identity in (
        *approved["transformationImplementations"],
        *approved["causalityRules"],
    ):
        assert exact_identity in approved_text
    for observation in approved["compatibilityObservations"]:
        assert observation["subject"] in approved_text
        assert observation["explanation"] in approved_text

    path_count_before = host._scenario_lab.referencePathCount
    host._scenario_lab.materializeApprovedRecipeVersion(
        approved["recipeVersionId"]
    )
    _process_until(
        app,
        lambda: host._scenario_lab.taskHandleCount == 1
        and host._scenario_lab.taskHandles[0]["terminal"],
    )
    assert host._scenario_lab.referencePathCount == path_count_before + 1
    assert host._scenario_lab.taskHandleCount == 1
    task_handle = host._scenario_lab.taskHandles[0]
    assert task_handle["operation"] == "materialize_reference_path"
    assert task_handle["targetIdentity"] == approved["recipeVersionId"]
    assert task_handle["phase"] == "completed"
    assert task_handle["progressPercent"] == 100
    assert task_handle["terminal"] is True
    assert task_handle["resultKind"] == "reference_market_path"
    assert task_handle["resultIdentity"]
    assert root.findChild(QObject, "scenarioLabTaskHandleRepeater") is not None
    task_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for exact_identity in (
        task_handle["taskHandleId"],
        task_handle["attemptId"],
        task_handle["targetIdentity"],
        task_handle["resultIdentity"],
    ):
        assert exact_identity in task_text

    scenario_feature.fail_next_materialization()
    host._scenario_lab.materializeApprovedRecipeVersion(
        approved["recipeVersionId"]
    )
    _process_until(
        app,
        lambda: host._scenario_lab.taskHandleCount == 2
        and host._scenario_lab.taskHandles[-1]["terminal"],
    )
    assert host._scenario_lab.taskHandleCount == 2
    failed_handle = host._scenario_lab.taskHandles[-1]
    assert failed_handle["phase"] == "failed"
    assert failed_handle["retryable"] is True
    assert failed_handle["errorCode"] == "scenario_materialization_failed"
    assert host._scenario_lab.canRetryMaterialization is True
    host._scenario_lab.retryMaterialization(
        failed_handle["attemptId"],
        failed_handle["taskHandleId"],
    )
    _process_until(
        app,
        lambda: host._scenario_lab.taskHandleCount == 3
        and host._scenario_lab.taskHandles[-1]["terminal"],
    )
    assert host._scenario_lab.taskHandleCount == 3
    retried_handle = host._scenario_lab.taskHandles[-1]
    assert retried_handle["phase"] == "completed"
    assert retried_handle["predecessorTaskHandleId"] == (
        failed_handle["taskHandleId"]
    )
    assert retried_handle["attemptId"] != failed_handle["attemptId"]
    task_history = host._scenario_lab.taskHandles

    host._scenario_lab.selectApprovedRecipeVersion(approved["recipeVersionId"])
    assert host._scenario_lab.selectedRecipeVersionId == approved["recipeVersionId"]
    host._scenario_lab.reviseSelectedRecipeDraft(
        "QML immutable successor",
        "volatility-scaling.v1",
        "4",
        "1",
        "0.5",
        "1.3",
        1,
        30,
        82,
        True,
        "a-share-cash-equity.v1",
    )
    app.processEvents()
    successor = host._scenario_lab.recipeDrafts[-1]
    assert successor["revision"] == 3
    assert successor["predecessorDraftId"] == revised["draftId"]
    assert successor["basedOnRecipeVersionId"] == approved["recipeVersionId"]
    assert host._scenario_lab.approvedRecipeVersions[0] == approved

    host.close_adapter()
    remounted = JourneyWorkspaceHost(
        run_feature,
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(),
        initial_route="scenario_lab",
    )
    app.processEvents()
    assert remounted._scenario_lab.approvedRecipeVersionCount == 1
    assert remounted._scenario_lab.approvedRecipeVersions[0] == approved
    assert remounted._scenario_lab.recipeDrafts[-1] == successor
    assert remounted._scenario_lab.taskHandleCount == 3
    assert remounted._scenario_lab.taskHandles == task_history
    assert task_handle["resultIdentity"] in {
        item["pathId"] for item in remounted._scenario_lab.referencePaths
    }
    remounted.close_adapter()
    scenario_feature.close()
    run_feature.close()


@pytest.mark.parametrize("configured", (False, True))
def test_production_workspace_exposes_only_configured_audited_ai_authoring(
    configured: bool,
) -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    scenario_feature = DeterministicFakeScenarioLabAdapter(
        ai_authoring_available=configured,
        ai_provider="deterministic-fake" if configured else None,
        ai_model="deterministic-recipe-fixture.v1" if configured else None,
    )
    host = JourneyWorkspaceHost(
        run_feature,
        scenario_lab_feature=scenario_feature,
        initial_route="scenario_lab",
    )
    app.processEvents()
    root = host.rootObject()
    assert root is not None
    button = root.findChild(QObject, "scenarioLabCreateAiRecipeDraftButton")
    intent = root.findChild(QObject, "scenarioLabAiRecipeIntentInput")
    assert button is not None
    assert intent is not None
    assert host._scenario_lab.canCreateAiAssistedRecipeDraft is configured
    assert ("deterministic-fake" in host._scenario_lab.aiAuthoringStatus) is configured

    host._scenario_lab.createAiAssistedRecipeDraft(
        "Draft the exact admitted baseline for diagnostic review."
    )
    app.processEvents()

    assert host._scenario_lab.recipeDraftCount == (1 if configured else 0)
    if configured:
        assert host._scenario_lab.recipeDrafts[0]["authoringMode"] == "ai_assisted"
        assert host._scenario_lab.recipeDrafts[0]["assistantAttemptId"]
    else:
        assert "unavailable" in host._scenario_lab.recipeCapabilityMessage.casefold()
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


def test_production_qml_composes_resolves_and_selects_formal_scenario_context(
    tmp_path,
) -> None:
    app = _app()
    _, _, engine, application, _, _ = _formal_live_stack(tmp_path)
    strategy_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        )
    )
    scenario_feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )
    run_feature = DeterministicFakeRunMonitoringAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        scenario_lab_feature=scenario_feature,
        initial_route="scenario_lab",
    )
    app.processEvents()
    assert host._strategy_library is not None
    assert host._scenario_lab is not None

    host._strategy_library.compareFormalSet()
    host._strategy_library.selectFormalSet()
    app.processEvents()
    assert host._strategy_library.selectionStatus == "current"

    host._scenario_lab.composeVisibleScenarioSet()
    app.processEvents()
    assert host._scenario_lab.scenarioSetCount == 1
    assert host._scenario_lab.scenarioSets[0]["eligibility"] == (
        "formal_campaign_eligible"
    )

    host._scenario_lab.resolveLatestScenarioSet()
    app.processEvents()
    assert host._scenario_lab.executionResolutionCount == 1
    assert host._scenario_lab.executionResolutions[0][
        "formalHandoffEligible"
    ]
    targets = host._scenario_lab.executionResolutions[0]["targets"]
    assert targets
    assert all(
        item["afterDecisionTime"] > item["decisionTime"]
        and item["activationTime"] >= item["afterDecisionTime"]
        for item in targets
    )

    host._scenario_lab.selectLatestFormalScenarioSet()
    app.processEvents()
    assert host._scenario_lab.selectionContextCount == 1
    assert host._scenario_lab.selectionContexts[0]["status"] == "current"
    root = host.rootObject()
    assert root is not None
    assert root.findChild(
        QQuickItem,
        "scenarioLabComposeVisibleScenarioSetButton",
    ) is not None
    assert root.findChild(
        QQuickItem,
        "scenarioLabResolveExecutionAssumptionsButton",
    ) is not None
    assert root.findChild(
        QQuickItem,
        "scenarioLabSelectFormalScenarioSetButton",
    ) is not None
    _process_until(
        app,
        lambda: root.findChild(
            QQuickItem,
            "scenarioLabSelectionContextRepeater",
        ) is not None,
    )

    host.close_adapter()
    strategy_feature.close()
    scenario_feature.close()
    run_feature.close()
    engine.dispose()


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

    def scenario_recipe_draft_revisions(self):
        return self._delegate.scenario_recipe_draft_revisions()

    def scenario_recipe_validation_history(self):
        return self._delegate.scenario_recipe_validation_history()

    def scenario_recipe_approval_history(self):
        return self._delegate.scenario_recipe_approval_history()

    def scenario_materialization_task_handles(self):
        return self._delegate.scenario_materialization_task_handles()

    def scenario_lab_formal_scenario_sets(self):
        return self._delegate.scenario_lab_formal_scenario_sets()

    def scenario_lab_execution_resolutions(self):
        return self._delegate.scenario_lab_execution_resolutions()

    def scenario_lab_selection_contexts(self):
        return self._delegate.scenario_lab_selection_contexts()

    def recipe_authoring_capabilities(self):
        return self._delegate.recipe_authoring_capabilities()

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
