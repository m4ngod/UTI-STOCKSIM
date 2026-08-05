from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, text

from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignNodeHandoff,
    DiagnosticCampaignRunHandoff,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskLifecycle,
    DiagnosticTaskPresentation,
    DiagnosticTasksContext,
    DiagnosticTasksInventory,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    LiveDiagnosticTasksAdapter,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    MarketScenarioId,
    ReviseDiagnosticTaskConfiguration,
    RunMonitoringContext,
    RunMonitoringSelection,
    ScenarioLabContext,
    StartFormalDiagnosticCampaign,
    StrategyUnderTestId,
)
from app.features.diagnostic_setup import DiagnosticSetupSelectionCoordinator
from app.features.live_scenario_lab import LiveScenarioLabAdapter
from app.features.live_strategy_library import LiveStrategyLibraryAdapter
from app.features.scenario_lab_application import (
    ComposeFormalScenarioSetCommand,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    ResolveScenarioExecutionAssumptionsCommand,
    ScenarioExecutionAssumptionTarget,
    SelectFormalScenarioSetCommand,
)
from app.features.strategy_library import StrategyLibraryContext
from app.features.strategy_library_application import (
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
)
from app.journey_recovery import (
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
)
from app.ui.accessibility import AccessibilityPreferences
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_failed_node_retry_live_contract import (
    _FailFirstDecisionPTradeHost,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _persistent_three_layer_stack,
)
from tests.frontend.contract.test_strategy_diagnostics_v1_run_monitoring_live_contract import (
    _DirectExecutor,
)
from tests.frontend.contract.test_scenario_lab_formal_scenario_sets_live_contract import (
    _canonical,
    _formal_cases,
    _metadata,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@dataclass
class _Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def _real_feature(
    state: str,
) -> tuple[LiveDiagnosticTasksAdapter, _Clock]:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    if state != "failed":
        application.start()
    if state in {"input_unavailable", "ready", "degraded"}:
        admission = application.admit_historical_segment(source.selection)
        assert admission.segment is not None
        draft = application.create_manual_recipe_draft(
            _baseline_payload(admission.segment.segment_id),
            author="researcher",
        )
        assert application.validate_recipe_draft(draft.draft_id).is_valid
        approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
        if state in {"ready", "degraded"}:
            application.materialize_baseline_reference_path(approved.version_id)
    clock = _Clock(datetime(2030, 1, 1, tzinfo=timezone.utc))
    feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application
        ),
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
    )
    if state == "degraded":
        context = DiagnosticTasksContext.workspace()
        feature.snapshot(context)
        feature.snapshot(context)
        clock.now += timedelta(seconds=10)
    return feature, clock


def _window(
    feature: LiveDiagnosticTasksAdapter,
) -> tuple[MainWindow, DeterministicFakeRunMonitoringAdapter]:
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        diagnostic_tasks_feature=feature,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=run_monitoring,
        frontend_v2_enabled=True,
    )
    return window, run_monitoring


def _formal_inventory(tmp_path: Path) -> DiagnosticTasksInventory:
    *_, feature = _formal_live_stack(tmp_path)
    try:
        workspace = DiagnosticTasksContext.workspace()
        feature.snapshot(workspace)
        inventory = feature.snapshot(workspace).last_reliable_inventory
        assert inventory is not None
        return inventory
    finally:
        feature.close()


def _prepare_live_five_feature_setup(application, event_bridge: EventBridge):
    scenario_feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        ),
        event_bridge=event_bridge,
    )
    scenario_context = ScenarioLabContext()
    scenario_feature.snapshot(scenario_context)
    ready = scenario_feature.snapshot(scenario_context)
    baseline, isolated, compound = _formal_cases(ready)
    composed = scenario_feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, "compose-five-feature-reopen-85"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(
                    item.scenario_id for item in isolated
                ),
                compound_case_ids=tuple(
                    item.scenario_id for item in compound
                ),
            )
        )
    )
    assert composed.scenario_set is not None

    after_compose = scenario_feature.snapshot(scenario_context)
    strategy_ids = tuple(
        StrategyUnderTestId(item.strategy_id)
        for item in application.read_strategy_under_test_inventory().entries
    )
    decision_time = next(
        item.start_time
        for item in after_compose.reference_paths
        if item.path_id == baseline.path_id
    )
    resolved = scenario_feature.resolve_execution_assumptions(
        _canonical(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata=_metadata(
                    after_compose,
                    "resolve-five-feature-reopen-85",
                ),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                targets=tuple(
                    ScenarioExecutionAssumptionTarget(
                        strategy_id=strategy_id,
                        campaign_case_id=case_id,
                        decision_time=decision_time,
                    )
                    for strategy_id in strategy_ids
                    for case_id in composed.scenario_set.case_ids
                ),
            )
        )
    )
    assert resolved.resolution is not None
    after_resolution = scenario_feature.snapshot(scenario_context)
    selected = scenario_feature.select_formal_scenario_set(
        _canonical(
            SelectFormalScenarioSetCommand(
                metadata=_metadata(
                    after_resolution,
                    "select-five-feature-reopen-85",
                ),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                case_ids=composed.scenario_set.case_ids,
                originating_view_revision=after_resolution.revision,
                execution_resolution_id=resolved.resolution.resolution_id,
            )
        )
    )
    assert selected.selection_context is not None

    strategy_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        ),
        event_bridge=event_bridge,
    )
    return strategy_feature, scenario_feature


@dataclass(frozen=True)
class _EvidenceHandoff:
    context: EvidenceAndFindingsContext
    selected_case: DiagnosticCampaignCaseSelection
    selected_node: DiagnosticCampaignNodeHandoff
    selected_run: DiagnosticCampaignRunHandoff


def _authoritative_evidence_handoff(
    task: DiagnosticTaskPresentation,
) -> _EvidenceHandoff:
    campaign_id = task.handoff.campaign_id
    assert campaign_id is not None
    manifest_id = task.handoff.reproduction_manifest_id
    assert manifest_id is not None
    selected_node, selected_run = next(
        (node, run)
        for node in task.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
        if run.reproduction_manifest_id == manifest_id
    )
    selected_case = next(
        selected
        for selected in task.handoff.selected_cases
        if selected.campaign_case_id
        == selected_node.selected_campaign_case_id
    )
    return _EvidenceHandoff(
        context=EvidenceAndFindingsContext.for_selection(
            EvidenceAndFindingsSelection(
                campaign_id=campaign_id,
                run_id=selected_run.run_id,
                strategy_id=selected_run.strategy_id,
                market_scenario_id=MarketScenarioId(
                    selected_node.campaign_case_id.value
                ),
                approved_recipe_id=ApprovedScenarioRecipeId(
                    selected_case.recipe_version_id.value
                ),
                reproduction_manifest_id=manifest_id,
            )
        ),
        selected_case=selected_case,
        selected_node=selected_node,
        selected_run=selected_run,
    )


def test_available_diagnostic_evidence_hands_exact_ids_to_evidence_route(
    tmp_path,
) -> None:
    app = _app()
    workspace = DiagnosticTasksContext.workspace()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_formal_inventory(tmp_path)
    )
    approved = _approved_formal_task(diagnostic_tasks)
    diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("qml-start-command-64"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "qml-start-idempotency-64"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    diagnostic_tasks.advance_evidence_available(approved.task_id)
    task = diagnostic_tasks.snapshot(workspace).task
    assert task is not None
    handoff = _authoritative_evidence_handoff(task)
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    evidence = DeterministicFakeEvidenceAndFindingsAdapter()
    evidence.advance_to_completed(handoff.context)
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        accessibility_preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        ),
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()
    assert root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    status = root.findChild(QObject, "evidenceAccessibleStatus")
    assert status is not None
    interface = QAccessible.queryAccessibleInterface(status)
    assert interface is not None
    announced = " ".join(
        (
            interface.text(QAccessible.Text.Name),
            interface.text(QAccessible.Text.Description),
        )
    )
    for identity in (
        task.handoff.campaign_id.value,
        handoff.selected_run.run_id.value,
        handoff.selected_run.strategy_id.value,
        handoff.selected_node.campaign_case_id.value,
        handoff.selected_case.recipe_version_id.value,
        handoff.selected_run.reproduction_manifest_id.value,
    ):
        assert identity in announced

    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()


def test_reopen_rereads_task_handoffs_without_overriding_last_route(
    tmp_path,
) -> None:
    app = _app()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_formal_inventory(tmp_path)
    )
    approved = _approved_formal_task(diagnostic_tasks)
    diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("reopen-start-command-85"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "reopen-start-idempotency-85"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    diagnostic_tasks.advance_evidence_available(approved.task_id)
    task_context = DiagnosticTasksContext(task_id=approved.task_id)
    diagnostic_tasks.snapshot(task_context)
    task = diagnostic_tasks.snapshot(task_context).task
    assert task is not None
    expected_run = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=task.handoff.campaign_id,
            run_id=next(
                run.run_id
                for node in task.handoff.campaign_nodes
                for attempt in node.attempts
                if attempt.attempt_id == node.active_attempt_id
                for run in attempt.runs
            ),
        )
    )
    expected_evidence = _authoritative_evidence_handoff(task).context
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        diagnostic_task_id=approved.task_id,
    )
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    evidence = DeterministicFakeEvidenceAndFindingsAdapter()

    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=task_context,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    app.processEvents()

    root = host.rootObject()
    assert root is not None
    assert root.property("activeRoute") == "evidence_and_findings"
    assert host._run_monitoring._context == expected_run
    assert host._evidence_and_findings._context == expected_evidence
    assert host._diagnostic_tasks.recovery_task_id() == approved.task_id
    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()


def test_real_persisted_evidence_handoff_resolves_in_qml_without_id_remap(
    tmp_path,
) -> None:
    app = _app()
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        diagnostic_tasks,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(diagnostic_tasks)
    accepted = diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("qml-live-start-command-64"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "qml-live-start-idempotency-64"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    application.advance_diagnostic_campaign(
        accepted.affected_campaign_id.value,
        max_cases=64,
        nodes_per_batch=10_000,
    )
    workspace = DiagnosticTasksContext.workspace()
    diagnostic_tasks.snapshot(workspace)
    task = diagnostic_tasks.snapshot(workspace).task
    assert task is not None
    assert task.handoff.ready_for_evidence_and_findings
    handoff = _authoritative_evidence_handoff(task)

    bridge = EventBridge(subscribe_backend=False)
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
    )
    evidence = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        executor=_DirectExecutor(),
    )
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()
    assert root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    app.processEvents()
    status = root.findChild(QObject, "evidenceAccessibleStatus")
    assert status is not None
    status_interface = QAccessible.queryAccessibleInterface(status)
    assert status_interface is not None
    narrator_text = " ".join(
        (
            status_interface.text(QAccessible.Text.Name),
            status_interface.text(QAccessible.Text.Description),
        )
    )
    assert "ready" in narrator_text.casefold()
    for identity in (
        task.handoff.campaign_id.value,
        handoff.selected_run.run_id.value,
        handoff.selected_run.strategy_id.value,
        handoff.selected_node.campaign_case_id.value,
        handoff.selected_run.reproduction_manifest_id.value,
    ):
        assert identity in narrator_text

    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()
    bridge.stop()
    engine.dispose()


def test_live_qml_tracer_recovers_retries_and_reopens_exact_evidence(
    tmp_path,
) -> None:
    app = _app()
    evidence_root = tmp_path / "diagnostic-evidence"
    (
        source,
        artifact_store,
        engine,
        application,
        _diagnostic_application,
        initial_diagnostic_tasks,
    ) = _formal_live_stack(
        tmp_path,
        ptrade_host=_FailFirstDecisionPTradeHost(),
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            evidence_root
        ),
    )
    initial_diagnostic_tasks.close()
    bridge = EventBridge(subscribe_backend=False)
    strategy_feature, scenario_feature = _prepare_live_five_feature_setup(
        application,
        bridge,
    )
    setup_coordinator = DiagnosticSetupSelectionCoordinator()
    diagnostic_tasks = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application,
            setup_selection_provider=setup_coordinator.current,
        ),
        event_bridge=bridge,
    )
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
    )
    run_monitoring = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        executor=_DirectExecutor(),
    )
    evidence = LiveEvidenceAndFindingsAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        executor=_DirectExecutor(),
    )
    workspace = DiagnosticTasksContext.workspace()
    strategy_bookmarks = []
    journey_bookmarks = []
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        strategy_library_bookmark_sink=strategy_bookmarks.append,
        journey_workspace_bookmark_sink=journey_bookmarks.append,
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        diagnostic_setup_selection_coordinator=setup_coordinator,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        accessibility_preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        ),
        initial_route="strategy_library",
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()
    assert root.property("activeRoute") == "strategy_library"
    assert root.findChild(QObject, "strategyLibraryPage") is not None
    host._strategy_library.compareFormalSet()
    host._strategy_library.selectFormalSet()
    app.processEvents()
    app.processEvents()
    assert strategy_bookmarks
    assert host._strategy_library.current_formal_strategy_selection() is not None

    assert root.setProperty("activeRoute", "scenario_lab")
    app.processEvents()
    app.processEvents()
    assert root.findChild(QObject, "scenarioLabPage") is not None
    assert host._scenario_lab.current_diagnostic_selection() is not None
    assert root.setProperty("activeRoute", "diagnostic_tasks")
    app.processEvents()
    app.processEvents()
    setup_selection = setup_coordinator.current()
    assert setup_selection is not None
    expected_setup_identity = setup_selection.context_identity
    expected_setup_generation = (
        setup_selection.strategy_selection.source_generation.value
    )
    expected_scenario_selection_identity = (
        setup_selection.scenario_selection.context.selection_context_id.value
    )
    diagnostic_page = root.findChild(QObject, "diagnosticTasksPage")
    assert diagnostic_page is not None
    diagnostic_projection = diagnostic_page.property("adapter")
    announcement_spy = QSignalSpy(diagnostic_projection.announcementChanged)

    def settle() -> None:
        app.processEvents()
        app.processEvents()

    def traverse_to(
        object_name: str,
        *,
        backward: bool = False,
    ) -> QQuickItem:
        target = root.findChild(QQuickItem, object_name)
        assert target is not None
        for _ in range(64):
            if target.property("activeFocus") is True:
                assert target.property("visible") is True
                return target
            QTest.keyClick(
                host,
                (
                    Qt.Key.Key_Backtab
                    if backward
                    else Qt.Key.Key_Tab
                ),
            )
            settle()
        raise AssertionError(f"{object_name} is not keyboard reachable")

    def activate(object_name: str) -> None:
        item = root.findChild(QQuickItem, object_name)
        assert item is not None
        assert item.property("activeFocus") is True
        assert item.property("enabled") is True
        top = item.mapToItem(root, QPointF(0, 0)).y()
        assert 0 <= top
        assert top + item.property("height") <= root.property("height")
        QTest.keyClick(host, Qt.Key.Key_Space)
        settle()

    def current_task():
        diagnostic_tasks.snapshot(workspace)
        state = diagnostic_tasks.snapshot(workspace)
        assert state.task is not None
        return state.task

    def durable_identity_graph(task) -> tuple[str, ...]:
        identities = [
            task.task_id.value,
            task.configuration.content_identity.value,
            *(
                selection.strategy_id.value
                for selection in task.configuration.strategy_selections
            ),
            *(
                selection.guardrail_profile_id.value
                for selection in task.configuration.strategy_selections
            ),
            *(
                selection.recipe_version_id.value
                for selection in task.configuration.campaign_case_selections
            ),
            *(
                selection.market_scenario_id.value
                for selection in task.configuration.campaign_case_selections
            ),
            *(
                selection.campaign_case_id.value
                for selection in task.configuration.campaign_case_selections
            ),
            *(handle.identity.value for handle in task.task_handles),
        ]
        handoff = task.handoff
        if handoff.campaign_id is not None:
            identities.append(handoff.campaign_id.value)
        for node in handoff.campaign_nodes:
            identities.extend(
                (
                    node.campaign_node_id.value,
                    node.selected_campaign_case_id.value,
                    node.market_scenario_id.value,
                )
            )
            for attempt in node.attempts:
                identities.append(attempt.attempt_id.value)
                if attempt.task_handle_id is not None:
                    identities.append(attempt.task_handle_id.value)
                for run in attempt.runs:
                    identities.extend(
                        (
                            run.run_id.value,
                            run.strategy_id.value,
                        )
                    )
                    if run.reproduction_manifest_id is not None:
                        identities.append(
                            run.reproduction_manifest_id.value
                        )
        if handoff.evidence_package_id is not None:
            identities.append(handoff.evidence_package_id.value)
        if handoff.reproduction_manifest_id is not None:
            identities.append(handoff.reproduction_manifest_id.value)
        return tuple(sorted(set(identities)))

    activate("createDiagnosticTaskButton")
    activate("reviseDiagnosticTaskButton")
    activate("validateDiagnosticTaskButton")
    actor = root.findChild(QQuickItem, "diagnosticTaskApprovalActorInput")
    assert actor is not None
    assert actor.property("activeFocus") is True
    QTest.keyClicks(host, "live-qml-owner")
    QTest.keyClick(host, Qt.Key.Key_Tab)
    settle()
    activate("approveDiagnosticTaskButton")
    activate("startDiagnosticCampaignButton")

    failed_task = current_task()
    failed_node = next(
        node
        for node in failed_task.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    failed_attempt = failed_node.attempts[-1]
    assert failed_attempt.failure is not None
    assert root.property("activeRoute") == "run_monitoring"
    failed_run = failed_attempt.runs[0]
    assert root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == f"Run · {failed_run.run_id.value}"
    setup_generation_before_disconnect = (
        setup_selection.strategy_selection.source_generation.value
    )

    announcements_before_disconnect = announcement_spy.count()
    bridge.mark_disconnected()
    settle()
    assert diagnostic_projection.freshness == "fresh"
    assert host._diagnostic_tasks._subscription is None
    assert announcement_spy.count() == announcements_before_disconnect
    assert root.setProperty("activeRoute", "diagnostic_tasks")
    settle()
    assert diagnostic_projection.freshness == "disconnected"
    assert setup_coordinator.current() is None
    assert host._diagnostic_tasks._subscription is not None
    assert announcement_spy.count() == announcements_before_disconnect + 1
    announcements_before_reconnect = announcement_spy.count()
    bridge.mark_reconnected()
    settle()
    diagnostic_projection.refresh()
    settle()
    assert diagnostic_projection.freshness == "fresh"
    recovered_setup = setup_coordinator.current()
    assert recovered_setup is not None
    assert (
        recovered_setup.strategy_selection.source_generation.value
        > setup_generation_before_disconnect
    )
    assert (
        announcements_before_reconnect
        < announcement_spy.count()
        <= announcements_before_reconnect + 2
    )

    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    QTest.keyClick(host, Qt.Key.Key_Return)
    settle()
    traverse_to("retryFailedCampaignNodeButton")
    activate("retryFailedCampaignNodeButton")
    retried_task = current_task()
    retried_node = next(
        node
        for node in retried_task.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert retried_node.attempts[0] == failed_attempt
    assert len(retried_node.attempts) == 2
    assert (
        retried_node.attempts[-1].predecessor_attempt_id
        == failed_attempt.attempt_id
    )
    assert (
        retried_node.attempts[-1].lifecycle
        is DiagnosticTaskLifecycle.COMPLETED
    )
    retry_run = retried_node.attempts[-1].runs[0]
    assert root.property("activeRoute") == "run_monitoring"
    assert root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == f"Run · {retry_run.run_id.value}"

    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    QTest.keyClick(host, Qt.Key.Key_Return)
    settle()
    traverse_to("pauseDiagnosticTaskTargetButton")
    activate("pauseDiagnosticTaskTargetButton")
    assert current_task().lifecycle is DiagnosticTaskLifecycle.PAUSED
    activate("resumeDiagnosticTaskTargetButton")

    campaign_id = current_task().handoff.campaign_id
    assert campaign_id is not None
    campaign = application.advance_diagnostic_campaign(
        campaign_id.value,
        max_cases=64,
        nodes_per_batch=10_000,
    )
    assert campaign.status == "completed"
    diagnostic_projection.refresh()
    settle()
    completed_task = current_task()
    assert (
        completed_task.setup_selection_context_identity
        == expected_setup_identity
    )
    assert completed_task.handoff.ready_for_evidence_and_findings
    assert completed_task.handoff.evidence_package_id is not None
    assert completed_task.handoff.reproduction_manifest_id is not None
    authoritative_handoff = _authoritative_evidence_handoff(
        completed_task
    )
    accepted_run = authoritative_handoff.selected_run
    manifest_id = accepted_run.reproduction_manifest_id
    assert manifest_id is not None
    expected_durable_identity_graph = durable_identity_graph(completed_task)
    assert len(expected_durable_identity_graph) >= 50

    traverse_to("evidenceAndFindingsRouteNavigation")
    QTest.keyClick(host, Qt.Key.Key_Return)
    settle()
    evidence_status = root.findChild(QObject, "evidenceAccessibleStatus")
    assert evidence_status is not None
    evidence_interface = QAccessible.queryAccessibleInterface(evidence_status)
    assert evidence_interface is not None
    evidence_text = " ".join(
        (
            evidence_interface.text(QAccessible.Text.Name),
            evidence_interface.text(QAccessible.Text.Description),
        )
    )
    for identity in (
        campaign_id.value,
        accepted_run.run_id.value,
        accepted_run.strategy_id.value,
        manifest_id.value,
        completed_task.handoff.evidence_package_id.value,
    ):
        assert identity in evidence_text

    expected_identity_text = (
        f"Campaign · {campaign_id.value}",
        f"Run · {accepted_run.run_id.value}",
        manifest_id.value,
    )
    assert strategy_bookmarks
    assert journey_bookmarks
    saved_strategy_bookmark = strategy_bookmarks[-1]
    saved_journey_bookmark = journey_bookmarks[-1]
    assert saved_journey_bookmark.last_route is (
        JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    )
    assert saved_journey_bookmark.diagnostic_task_id == completed_task.task_id
    recovered_workspace = DiagnosticTasksContext(
        task_id=saved_journey_bookmark.diagnostic_task_id
    )
    host.close_adapter()
    host.close()
    remounted = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(
            focus_strategy_id=saved_strategy_bookmark.focus_strategy_id,
            selection_bookmark=saved_strategy_bookmark,
        ),
        strategy_library_bookmark_sink=strategy_bookmarks.append,
        journey_workspace_bookmark=saved_journey_bookmark,
        journey_workspace_bookmark_sink=journey_bookmarks.append,
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(
            focus_target=saved_journey_bookmark.scenario_focus_target,
            focus_identity=saved_journey_bookmark.scenario_focus_identity,
        ),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=recovered_workspace,
        diagnostic_setup_selection_coordinator=setup_coordinator,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        initial_route=saved_journey_bookmark.last_route.value,
    )
    remounted.resize(1280, 720)
    remounted.show()
    settle()
    remounted_root = remounted.rootObject()
    assert remounted_root.property("activeRoute") == "evidence_and_findings"
    remounted_status = remounted_root.findChild(
        QObject,
        "evidenceAccessibleStatus",
    )
    remounted_interface = QAccessible.queryAccessibleInterface(
        remounted_status
    )
    assert remounted_interface is not None
    assert expected_identity_text[2] in remounted_interface.text(
        QAccessible.Text.Description
    )
    assert remounted_root.setProperty("activeRoute", "run_monitoring")
    settle()
    assert remounted_root.findChild(
        QObject,
        "runMonitoringCampaignIdentity",
    ).property("text") == expected_identity_text[0]
    assert remounted_root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == expected_identity_text[1]
    assert remounted_root.setProperty("activeRoute", "strategy_library")
    settle()
    remounted_strategy = (
        remounted._strategy_library.current_formal_strategy_selection()
    )
    assert remounted_strategy is not None
    assert (
        remounted_strategy.context_identity
        == recovered_setup.strategy_selection.context_identity
    )
    assert remounted_root.setProperty("activeRoute", "scenario_lab")
    settle()
    remounted_scenario = remounted._scenario_lab.current_diagnostic_selection()
    assert remounted_scenario is not None
    assert (
        remounted_scenario.context.selection_context_id
        == setup_selection.scenario_selection.context.selection_context_id
    )
    assert remounted_root.setProperty("activeRoute", "evidence_and_findings")
    settle()

    remounted.close_adapter()
    remounted.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()
    strategy_feature.close()
    scenario_feature.close()
    bridge.stop()
    engine.dispose()

    database_path = tmp_path / "diagnostic-task-campaign.db"
    assert database_path.is_file()
    restarted_engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
    )
    assert restarted_engine is not engine
    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        evidence_artifact_store=JsonDiagnosticEvidenceArtifactStore(
            evidence_root
        ),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            5,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(restarted_engine)
    restarted_bridge = EventBridge(subscribe_backend=False)
    restarted_strategy = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            restarted_application
        ),
        event_bridge=restarted_bridge,
    )
    restarted_scenario = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            restarted_application
        ),
        event_bridge=restarted_bridge,
    )
    restarted_setup_coordinator = DiagnosticSetupSelectionCoordinator()
    restarted_tasks = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application,
            setup_selection_provider=restarted_setup_coordinator.current,
        ),
        event_bridge=restarted_bridge,
    )
    restarted_read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        restarted_application,
        restarted_engine,
    )
    restarted_monitoring = LiveRunMonitoringAdapter(
        application_read_model=restarted_read_model,
        event_bridge=restarted_bridge,
        executor=_DirectExecutor(),
    )
    restarted_evidence = LiveEvidenceAndFindingsAdapter(
        application_read_model=restarted_read_model,
        event_bridge=restarted_bridge,
        executor=_DirectExecutor(),
    )
    reopened = JourneyWorkspaceHost(
        restarted_monitoring,
        context=RunMonitoringContext.no_selection(),
        strategy_library_feature=restarted_strategy,
        strategy_library_context=StrategyLibraryContext(
            focus_strategy_id=saved_strategy_bookmark.focus_strategy_id,
            selection_bookmark=saved_strategy_bookmark,
        ),
        strategy_library_bookmark_sink=strategy_bookmarks.append,
        journey_workspace_bookmark=saved_journey_bookmark,
        journey_workspace_bookmark_sink=journey_bookmarks.append,
        scenario_lab_feature=restarted_scenario,
        scenario_lab_context=ScenarioLabContext(
            focus_target=saved_journey_bookmark.scenario_focus_target,
            focus_identity=saved_journey_bookmark.scenario_focus_identity,
        ),
        diagnostic_tasks_feature=restarted_tasks,
        diagnostic_tasks_context=recovered_workspace,
        diagnostic_setup_selection_coordinator=restarted_setup_coordinator,
        evidence_feature=restarted_evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        initial_route=saved_journey_bookmark.last_route.value,
    )
    reopened.resize(1280, 720)
    reopened.show()
    settle()
    reopened_root = reopened.rootObject()
    restarted_tasks.snapshot(recovered_workspace)
    reopened_task_state = restarted_tasks.snapshot(recovered_workspace)
    assert reopened_task_state.task is not None
    assert (
        durable_identity_graph(reopened_task_state.task)
        == expected_durable_identity_graph
    )
    assert (
        reopened_task_state.task.lifecycle
        is DiagnosticTaskLifecycle.COMPLETED
    )
    assert (
        reopened_task_state.task.setup_selection_context_identity
        == expected_setup_identity
    )
    assert (
        reopened_task_state.task.setup_strategy_source_generation
        == expected_setup_generation
    )
    assert (
        reopened_task_state.task.setup_scenario_selection_context_identity
        == expected_scenario_selection_identity
    )
    reopened_setup = restarted_setup_coordinator.current()
    assert reopened_setup is not None
    assert reopened_setup.context_identity != expected_setup_identity
    assert (
        reopened_setup.strategy_selection.source_generation.value
        > expected_setup_generation
    )
    assert (
        reopened_setup.scenario_selection.context.selection_context_id.value
        == expected_scenario_selection_identity
    )
    assert reopened_setup.configuration == setup_selection.configuration
    assert reopened_root.property("activeRoute") == "evidence_and_findings"
    reopened_status = reopened_root.findChild(
        QObject,
        "evidenceAccessibleStatus",
    )
    reopened_interface = QAccessible.queryAccessibleInterface(reopened_status)
    assert reopened_interface is not None
    assert expected_identity_text[2] in reopened_interface.text(
        QAccessible.Text.Description
    )
    assert reopened_root.setProperty("activeRoute", "run_monitoring")
    settle()
    assert reopened_root.findChild(
        QObject,
        "runMonitoringCampaignIdentity",
    ).property("text") == expected_identity_text[0]
    assert reopened_root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == expected_identity_text[1]
    assert reopened_root.setProperty("activeRoute", "evidence_and_findings")
    settle()
    reopened_status = reopened_root.findChild(
        QObject,
        "evidenceAccessibleStatus",
    )
    reopened_interface = QAccessible.queryAccessibleInterface(reopened_status)
    assert reopened_interface is not None
    assert expected_identity_text[2] in reopened_interface.text(
        QAccessible.Text.Description
    )

    reopened.close_adapter()
    reopened.close()
    restarted_tasks.close()
    restarted_monitoring.close()
    restarted_evidence.close()
    restarted_strategy.close()
    restarted_scenario.close()
    restarted_bridge.stop()
    restarted_engine.dispose()


def test_diagnostic_route_restores_visible_focus_after_navigation_and_recovery(
    tmp_path,
) -> None:
    app = _app()
    workspace = DiagnosticTasksContext.workspace()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_formal_inventory(tmp_path)
    )
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    evidence = DeterministicFakeEvidenceAndFindingsAdapter()
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        accessibility_preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        ),
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()
    tokens = root.findChild(QObject, "designTokens")
    scroll = root.findChild(QQuickItem, "diagnosticTasksFlickable")
    create = root.findChild(QQuickItem, "createDiagnosticTaskButton")
    configuration_actions = root.findChild(
        QObject,
        "diagnosticTaskConfigurationActionGrid",
    )
    actor = root.findChild(
        QQuickItem,
        "diagnosticTaskApprovalActorInput",
    )
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    diagnostic_route = root.findChild(
        QQuickItem,
        "diagnosticTasksRouteNavigation",
    )
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    assert tokens is not None
    assert scroll is not None
    assert create is not None
    assert configuration_actions is not None
    assert actor is not None
    assert run_route is not None
    assert diagnostic_route is not None
    assert evidence_route is not None
    evidence_label = next(
        child
        for child in evidence_route.childItems()
        if child.property("text") == "Evidence & Findings"
    )
    journey_summary = root.findChild(
        QQuickItem,
        "diagnosticTasksAccessibleSummary",
    )
    assert journey_summary is not None
    capabilities_label = next(
        child
        for child in journey_summary.findChildren(QQuickItem)
        if str(child.property("text")).startswith("Capabilities")
    )

    assert create.property("activeFocus") is True
    assert create.property("activeFocusOnTab") is True
    assert create.property("focusVisible") is True
    assert create.metaObject().indexOfSignal("invoked()") >= 0
    assert create.metaObject().indexOfSignal("clicked()") == -1
    assert create.property("height") >= tokens.property("controlHeight")
    assert configuration_actions.property("columns") == 1
    assert evidence_label.property("contentHeight") <= (
        evidence_route.property("height") - 2 * tokens.property("spaceSm")
    )
    capabilities_top = capabilities_label.mapToItem(
        journey_summary,
        QPointF(0, 0),
    ).y()
    assert (
        capabilities_top + capabilities_label.property("contentHeight")
        <= journey_summary.property("height") - tokens.property("spaceLg")
    )
    assert scroll.property("contentHeight") > scroll.property("height")
    assert scroll.property("contentY") > 0
    create_top = create.mapToItem(root, QPointF(0, 0)).y()
    assert 0 <= create_top
    assert create_top + create.property("height") <= root.property("height")

    actor.forceActiveFocus()
    app.processEvents()
    actor_top = actor.mapToItem(root, QPointF(0, 0)).y()
    assert actor.property("activeFocus") is True
    assert 0 <= actor_top
    assert actor_top + actor.property("height") <= root.property("height")

    run_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "run_monitoring"
    diagnostic_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    app.processEvents()
    assert root.property("activeRoute") == "diagnostic_tasks"
    restored_actor = root.findChild(
        QQuickItem,
        "diagnosticTaskApprovalActorInput",
    )
    restored_create = root.findChild(QQuickItem, "createDiagnosticTaskButton")
    assert restored_actor is not None
    assert restored_create is not None
    assert restored_actor is not actor
    assert restored_create.property("activeFocus") is True
    restored_actor.forceActiveFocus()
    app.processEvents()
    actor = restored_actor

    diagnostic_tasks.advance_to_disconnected()
    app.processEvents()
    app.processEvents()
    assert actor.property("activeFocus") is True
    summary = root.findChild(QObject, "diagnosticTasksAccessibleSummary")
    assert summary is not None
    summary_interface = QAccessible.queryAccessibleInterface(summary)
    assert summary_interface is not None
    disconnected_text = " ".join(
        (
            summary_interface.text(QAccessible.Text.Name),
            summary_interface.text(QAccessible.Text.Description),
        )
    )
    assert "source_disconnected" in disconnected_text
    assert "freshness disconnected" in disconnected_text
    diagnostic_tasks.advance_to_reconnected()
    app.processEvents()
    app.processEvents()
    assert actor.property("activeFocus") is True

    feature_revision = diagnostic_tasks.snapshot(workspace).revision
    host.close_adapter()
    host.close()
    remounted = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        accessibility_preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        ),
    )
    remounted.resize(1280, 720)
    remounted.show()
    app.processEvents()
    app.processEvents()
    remounted_root = remounted.rootObject()
    remounted_create = remounted_root.findChild(
        QQuickItem,
        "createDiagnosticTaskButton",
    )
    assert remounted_root.property("activeRoute") == "diagnostic_tasks"
    assert remounted_create.property("activeFocus") is True
    assert remounted_create.property("focusVisible") is True
    assert diagnostic_tasks.snapshot(workspace).revision == feature_revision
    remounted.close_adapter()
    remounted.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()


def test_keyboard_completes_five_route_journey_with_narrator_identity_summary(
    tmp_path,
) -> None:
    app = _app()
    workspace = DiagnosticTasksContext.workspace()
    (
        _source,
        _artifact_store,
        engine,
        application,
        _diagnostic_application,
        initial_diagnostic_tasks,
    ) = _formal_live_stack(tmp_path)
    initial_diagnostic_tasks.snapshot(workspace)
    initial_inventory = initial_diagnostic_tasks.snapshot(
        workspace
    ).last_reliable_inventory
    assert initial_inventory is not None
    initial_diagnostic_tasks.close()
    bridge = EventBridge(subscribe_backend=False)
    strategy_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        ),
        event_bridge=bridge,
    )
    scenario_feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        ),
        event_bridge=bridge,
    )
    setup_coordinator = DiagnosticSetupSelectionCoordinator()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=initial_inventory,
        fail_first_campaign_node=True,
    )
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    evidence = DeterministicFakeEvidenceAndFindingsAdapter()
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        diagnostic_setup_selection_coordinator=setup_coordinator,
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        accessibility_preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        ),
        initial_route="strategy_library",
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()

    def find_quick_item(object_name: str) -> QQuickItem | None:
        direct = root.findChild(QQuickItem, object_name)
        if direct is not None:
            return direct
        pending = list(root.childItems())
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def traverse_to(
        object_name: str,
        *,
        backward: bool = False,
    ) -> QQuickItem:
        target = find_quick_item(object_name)
        assert target is not None, [
            item.objectName()
            for item in root.childItems()
            if object_name.split("-")[0] in item.objectName()
        ]
        visited: list[str] = []
        for _ in range(512):
            if target.property("activeFocus") is True:
                assert target.property("visible") is True
                return target
            focused = app.focusObject()
            visited.append(
                "<none>"
                if focused is None
                else focused.objectName() or type(focused).__name__
            )
            QTest.keyClick(
                host,
                (
                    Qt.Key.Key_Backtab
                    if backward
                    else Qt.Key.Key_Tab
                ),
            )
            app.processEvents()
            app.processEvents()
        raise AssertionError(
            f"{object_name} was not keyboard reachable; visited={visited}"
        )

    def settle() -> None:
        app.processEvents()
        app.processEvents()

    def wait_until(predicate) -> None:
        for _ in range(200):
            settle()
            if predicate():
                return
            QTest.qWait(5)
        raise AssertionError("Qt event-loop condition did not become true")

    def activate_setup(
        object_name: str,
        *,
        key: Qt.Key = Qt.Key.Key_Space,
    ) -> QQuickItem:
        item = find_quick_item(object_name)
        assert item is not None
        assert item.property("enabled") is True
        assert item.property("activeFocus") is True
        assert item.property("visible") is True
        item_top = item.mapToItem(root, QPointF(0, 0)).y()
        assert 0 <= item_top
        assert item_top + item.property("height") <= root.property("height")
        QTest.keyClick(host, key)
        settle()
        return item

    assert root.property("activeRoute") == "strategy_library"
    traverse_to("strategyLibraryCompareFormalSet")
    activate_setup("strategyLibraryCompareFormalSet")
    traverse_to("strategyLibrarySelectFormalSet")
    activate_setup("strategyLibrarySelectFormalSet")
    assert host._strategy_library.selectionStatus == "current"

    traverse_to("scenarioLabRouteNavigation", backward=True)
    activate_setup(
        "scenarioLabRouteNavigation",
        key=Qt.Key.Key_Return,
    )
    assert root.property("activeRoute") == "scenario_lab"
    draft_count_before = host._scenario_lab.recipeDraftCount
    handle_count_before = host._scenario_lab.taskHandleCount
    transformation = traverse_to("scenarioLabRecipeTransformationInput")
    QTest.keyClick(host, Qt.Key.Key_Space)
    settle()
    QTest.keyClick(host, Qt.Key.Key_Down)
    QTest.keyClick(host, Qt.Key.Key_Return)
    settle()
    assert transformation.property("currentIndex") > 0
    assert str(transformation.property("currentValue"))
    slippage = traverse_to("scenarioLabRecipeSlippageInput")
    QTest.keyClick(host, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(host, "5")
    settle()
    assert slippage.property("text") == "5"

    traverse_to("scenarioLabCreateRecipeDraftButton")
    activate_setup("scenarioLabCreateRecipeDraftButton")
    assert host._scenario_lab.recipeDraftCount == draft_count_before + 1
    draft = host._scenario_lab.recipeDrafts[-1]
    validate_name = "scenarioLabValidateRecipeDraft-" + draft["draftId"]
    traverse_to(validate_name)
    activate_setup(validate_name)
    validation = host._scenario_lab.recipeValidations[-1]
    assert validation["draftId"] == draft["draftId"]
    assert validation["valid"] is True

    approve_name = "scenarioLabApproveRecipe-" + validation["validationId"]
    traverse_to(approve_name)
    activate_setup(approve_name)
    approved = next(
        item
        for item in host._scenario_lab.approvedRecipeVersions
        if item["validationId"] == validation["validationId"]
    )

    materialize_name = (
        "scenarioLabMaterializeApprovedRecipe-"
        + approved["recipeVersionId"]
    )
    traverse_to(materialize_name)
    activate_setup(materialize_name)
    wait_until(
        lambda: host._scenario_lab.taskHandleCount == handle_count_before + 1
        and host._scenario_lab.taskHandles[-1]["terminal"]
    )
    recipe_task_handle = host._scenario_lab.taskHandles[-1]
    assert recipe_task_handle["phase"] == "completed"
    assert recipe_task_handle["targetIdentity"] == approved["recipeVersionId"]
    materialized_case = next(
        item
        for item in host._scenario_lab.marketScenarios
        if item["pathId"] == recipe_task_handle["resultIdentity"]
    )

    traverse_to("scenarioLabComposeVisibleScenarioSetButton")
    activate_setup("scenarioLabComposeVisibleScenarioSetButton")
    assert host._scenario_lab.scenarioSets, (
        host._scenario_lab.scenarioCommandMessage
    )
    composed_set = host._scenario_lab.scenarioSets[-1]
    assert composed_set["eligibility"] == "formal_campaign_eligible"
    assert materialized_case["scenarioId"] in composed_set["caseIds"]
    traverse_to("scenarioLabResolveExecutionAssumptionsButton")
    activate_setup("scenarioLabResolveExecutionAssumptionsButton")
    traverse_to("scenarioLabSelectFormalScenarioSetButton")
    activate_setup("scenarioLabSelectFormalScenarioSetButton")
    scenario_selection = host._scenario_lab.current_diagnostic_selection()
    assert scenario_selection is not None
    assert materialized_case["scenarioId"] in {
        item.scenario_id.value for item in scenario_selection.market_scenarios
    }

    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    activate_setup(
        "diagnosticTasksRouteNavigation",
        key=Qt.Key.Key_Return,
    )
    assert root.property("activeRoute") == "diagnostic_tasks"
    assert setup_coordinator.current() is not None
    diagnostic_page = root.findChild(QObject, "diagnosticTasksPage")
    assert diagnostic_page is not None
    diagnostic_projection = diagnostic_page.property("adapter")
    assert hasattr(diagnostic_projection, "announcementChanged")
    announcement_spy = QSignalSpy(diagnostic_projection.announcementChanged)

    def activate(object_name: str) -> QQuickItem:
        item = find_quick_item(object_name)
        assert item is not None
        assert item.property("enabled") is True
        assert item.property("activeFocus") is True
        assert item.property("visible") is True
        item_top = item.mapToItem(root, QPointF(0, 0)).y()
        assert 0 <= item_top
        assert item_top + item.property("height") <= root.property("height")
        announcement_count = announcement_spy.count()
        QTest.keyClick(host, Qt.Key.Key_Space)
        app.processEvents()
        app.processEvents()
        assert announcement_spy.count() == announcement_count + 1
        return item

    traverse_to("createDiagnosticTaskButton")
    activate("createDiagnosticTaskButton")
    assert root.findChild(
        QQuickItem,
        "reviseDiagnosticTaskButton",
    ).property("activeFocus") is True
    activate("reviseDiagnosticTaskButton")
    activate("validateDiagnosticTaskButton")
    actor = root.findChild(
        QQuickItem,
        "diagnosticTaskApprovalActorInput",
    )
    assert actor is not None
    assert actor.property("activeFocus") is True
    QTest.keyClicks(host, "keyboard-research-owner")
    app.processEvents()
    QTest.keyClick(host, Qt.Key.Key_Tab)
    app.processEvents()
    approve = root.findChild(QQuickItem, "approveDiagnosticTaskButton")
    assert approve.property("activeFocus") is True
    activate("approveDiagnosticTaskButton")
    assert root.findChild(
        QQuickItem,
        "startDiagnosticCampaignButton",
    ).property("activeFocus") is True
    activate("startDiagnosticCampaignButton")
    assert root.property("activeRoute") == "run_monitoring"

    task = diagnostic_tasks.snapshot(workspace).task
    assert task is not None
    assert task.handoff.campaign_id is not None
    selected_materialized_case = next(
        selected
        for selected in task.handoff.selected_cases
        if selected.campaign_case_id.value == materialized_case["scenarioId"]
    )
    assert selected_materialized_case.recipe_version_id.value == (
        approved["recipeVersionId"]
    )
    assert recipe_task_handle["taskHandleId"] in {
        item["taskHandleId"] for item in host._scenario_lab.taskHandles
    }
    run_context = next(
        RunMonitoringContext.for_run(
            RunMonitoringSelection(
                campaign_id=task.handoff.campaign_id,
                run_id=run.run_id,
            )
        )
        for node in task.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
    )
    run_monitoring.advance_to_running(run_context)
    app.processEvents()
    run_status = root.findChild(QObject, "runMonitoringAccessibleStatus")
    assert run_status is not None
    assert "active" in QAccessible.queryAccessibleInterface(
        run_status
    ).text(QAccessible.Text.Name).casefold()

    diagnostic_route = root.findChild(
        QQuickItem,
        "diagnosticTasksRouteNavigation",
    )
    assert diagnostic_route is not None
    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "diagnostic_tasks"
    traverse_to("retryFailedCampaignNodeButton")
    activate("retryFailedCampaignNodeButton")
    assert root.property("activeRoute") == "run_monitoring"
    retried = diagnostic_tasks.snapshot(workspace).task
    assert retried is not None
    assert retried.handoff.campaign_id is not None
    active_retry_run = next(
        run
        for node in retried.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
        if len(node.attempts) > 1
    )
    retry_run_context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=retried.handoff.campaign_id,
            run_id=active_retry_run.run_id,
        )
    )
    run_monitoring.advance_to_running(retry_run_context)
    app.processEvents()
    retry_run_identity = root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    )
    assert retry_run_identity is not None
    assert retry_run_identity.property("text") == (
        f"Run · {active_retry_run.run_id.value}"
    )
    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    app.processEvents()
    pause_after_retry = root.findChild(
        QQuickItem,
        "pauseDiagnosticTaskTargetButton",
    )
    diagnostic_page = root.findChild(QObject, "diagnosticTasksPage")
    remembered_after_retry = diagnostic_page.property("lastFocusedItem")
    create_after_retry = root.findChild(
        QQuickItem,
        "createDiagnosticTaskButton",
    )
    assert create_after_retry.property("activeFocus") is True, (
        remembered_after_retry.objectName(),
        pause_after_retry.property("enabled"),
        root.property("activeRoute"),
    )
    assert remembered_after_retry is create_after_retry
    traverse_to("pauseDiagnosticTaskTargetButton")
    activate("pauseDiagnosticTaskTargetButton")
    assert root.findChild(
        QQuickItem,
        "resumeDiagnosticTaskTargetButton",
    ).property("activeFocus") is True
    activate("resumeDiagnosticTaskTargetButton")

    current = diagnostic_tasks.snapshot(workspace).task
    assert current is not None
    announcement_count = announcement_spy.count()
    diagnostic_tasks.advance_evidence_available(current.task_id)
    task = diagnostic_tasks.snapshot(workspace).task
    assert task is not None
    handoff = _authoritative_evidence_handoff(task)
    evidence.advance_to_completed(handoff.context)
    app.processEvents()
    app.processEvents()
    assert announcement_spy.count() == announcement_count + 1

    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    assert evidence_route is not None
    traverse_to("evidenceAndFindingsRouteNavigation")
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "evidence_and_findings"
    candidate = root.property("evidenceInitialFocusItem")
    assert candidate is not None
    assert candidate.property("activeFocus") is True

    traverse_to("diagnosticTasksRouteNavigation", backward=True)
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    summary = root.findChild(QObject, "diagnosticTasksAccessibleSummary")
    announcement = root.findChild(
        QObject,
        "diagnosticTasksAnnouncement",
    )
    assert summary is not None
    assert announcement is not None
    summary_interface = QAccessible.queryAccessibleInterface(summary)
    announcement_interface = QAccessible.queryAccessibleInterface(
        announcement
    )
    assert summary_interface is not None
    assert announcement_interface is not None
    assert summary_interface.role() == QAccessible.Role.StatusBar
    assert (
        summary_interface.text(QAccessible.Text.Name)
        == "Diagnostic Tasks status"
    )
    assert announcement_interface.role() == QAccessible.Role.AlertMessage
    semantic_announcement_count = announcement_spy.count()
    assert semantic_announcement_count >= 9
    diagnostic_projection.refresh()
    diagnostic_projection.refresh()
    app.processEvents()
    app.processEvents()
    assert announcement_spy.count() == semantic_announcement_count
    narrator_text = " ".join(
        (
            summary_interface.text(QAccessible.Text.Name),
            summary_interface.text(QAccessible.Text.Description),
            announcement_interface.text(QAccessible.Text.Name),
        )
    )
    for expected in (
        task.task_id.value,
        task.handoff.campaign_id.value,
        handoff.selected_run.run_id.value,
        handoff.selected_run.reproduction_manifest_id.value,
            "TaskHandle",
            "completed",
            "Evidence available",
            "Capabilities",
            "create available",
            "pause unavailable",
        ):
        assert expected.casefold() in narrator_text.casefold()

    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()
    strategy_feature.close()
    scenario_feature.close()
    bridge.stop()
    engine.dispose()


def test_revision_conflict_announces_authoritative_reread_and_invalid_approval(
    tmp_path,
) -> None:
    app = _app()
    workspace = DiagnosticTasksContext.workspace()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_formal_inventory(tmp_path)
    )
    approved = _approved_formal_task(diagnostic_tasks)
    task_context = DiagnosticTasksContext(task_id=approved.task_id)
    diagnostic_tasks.snapshot(task_context)
    approved_state = diagnostic_tasks.snapshot(task_context).task
    assert approved_state is not None
    diagnostic_tasks.snapshot(workspace)
    diagnostic_tasks.snapshot(workspace)
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()

    external = diagnostic_tasks.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId("external-revise-command-64"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "external-revise-idempotency-64"
            ),
            task_id=approved.task_id,
            expected_revision=approved_state.revision,
            configuration=type(approved_state.configuration).create(
                strategy_selections=(
                    approved_state.configuration.strategy_selections
                ),
                campaign_case_selections=(
                    approved_state.configuration.campaign_case_selections[0],
                ),
            ),
        )
    )
    assert external.rejection_reason is None, external.message

    revise = root.findChild(
        QQuickItem,
        "reviseDiagnosticTaskButton",
    )
    assert revise is not None
    assert revise.property("enabled") is True
    revise.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    app.processEvents()

    current = diagnostic_tasks.snapshot(workspace).task
    assert current is not None
    assert current.revision > approved_state.revision
    assert current.approval is None
    summary = root.findChild(QObject, "diagnosticTasksAccessibleSummary")
    announcement = root.findChild(
        QObject,
        "diagnosticTasksAnnouncement",
    )
    summary_interface = QAccessible.queryAccessibleInterface(summary)
    announcement_interface = QAccessible.queryAccessibleInterface(
        announcement
    )
    assert summary_interface is not None
    assert announcement_interface is not None
    narrator_text = " ".join(
        (
            summary_interface.text(QAccessible.Text.Name),
            summary_interface.text(QAccessible.Text.Description),
            announcement_interface.text(QAccessible.Text.Name),
        )
    ).casefold()
    assert "expected revision" in narrator_text
    assert "authoritative" in narrator_text
    assert "approval unavailable" in narrator_text
    assert f"r{current.revision}" in narrator_text

    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()


def test_failed_node_retry_is_keyboard_accessible_and_exposes_attempt_lineage(
    tmp_path,
) -> None:
    app = _app()
    workspace = DiagnosticTasksContext.workspace()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_formal_inventory(tmp_path),
        fail_first_campaign_node=True,
    )
    approved = _approved_formal_task(diagnostic_tasks)
    diagnostic_tasks.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("qml-start-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "qml-start-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    window = MainWindow(
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=workspace,
        run_monitoring_feature=DeterministicFakeRunMonitoringAdapter(),
        run_monitoring_context=RunMonitoringContext.no_selection(),
        frontend_v2_enabled=True,
    )
    window.show()
    app.processEvents()
    app.processEvents()
    root = window.centralWidget().rootObject()
    assert root.setProperty("activeRoute", "diagnostic_tasks")
    app.processEvents()
    retry_button = root.findChild(QObject, "retryFailedCampaignNodeButton")
    attempt_history = root.findChild(
        QObject,
        "failedCampaignNodeAttemptHistory",
    )
    assert retry_button is not None
    assert attempt_history is not None
    assert retry_button.property("enabled") is True
    assert retry_button.property("activeFocusOnTab") is True
    before = attempt_history.property("text")
    assert "attempt 1" in before
    assert "failed" in before
    assert "failure" in before

    assert QMetaObject.invokeMethod(retry_button, "invoked")
    app.processEvents()
    app.processEvents()

    after = attempt_history.property("text")
    assert "attempt 1" in after
    assert "attempt 2" in after
    assert "completed" in after
    assert "predecessor" in after
    assert "TaskHandle" in after
    assert retry_button.property("enabled") is False
    window.close()
    diagnostic_tasks.close()


def test_real_diagnostic_tasks_route_renders_loading_before_first_delivery() -> None:
    app = _app()
    feature, _ = _real_feature("ready")
    window, run_monitoring = _window(feature)
    window.show()
    root = window.centralWidget().rootObject()
    page = root.findChild(QObject, "diagnosticTasksPage")

    assert page is not None
    assert page.property("stateTitle") == "Loading authoritative inputs"

    app.processEvents()
    assert page.property("stateTitle") == "Authoritative inputs are ready"
    window.close()
    feature.close()
    run_monitoring.close()


@pytest.mark.parametrize(
    ("state", "expected_title"),
    [
        ("empty", "No authoritative inputs are registered"),
        (
            "input_unavailable",
            "Required authoritative inputs are unavailable",
        ),
        ("ready", "Authoritative inputs are ready"),
        ("degraded", "Showing last reliable authoritative inputs"),
        ("failed", "Authoritative input read failed"),
    ],
)
def test_real_diagnostic_tasks_route_renders_each_terminal_inventory_state(
    state: str,
    expected_title: str,
) -> None:
    app = _app()
    feature, _ = _real_feature(state)
    window, run_monitoring = _window(feature)
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()
    page = root.findChild(QObject, "diagnosticTasksPage")

    assert page is not None
    assert page.property("stateTitle") == expected_title

    window.close()
    feature.close()
    run_monitoring.close()


def test_diagnostic_tasks_is_the_active_typed_qml_workspace_route() -> None:
    app = _app()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter()
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=run_monitoring,
        frontend_v2_enabled=True,
    )
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()

    visible_text = " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )

    assert root.property("activeRoute") == "diagnostic_tasks"
    assert root.findChild(QObject, "diagnosticTasksRouteNavigation") is not None
    page = root.findChild(QObject, "diagnosticTasksPage")
    assert page is not None
    assert root.findChild(QObject, "diagnosticTasksAccessibleStatus") is not None
    assert "Diagnostic Tasks" in visible_text
    assert "quentx-scenario-native" in page.property("strategyCatalogText")
    assert "required fixed input" in page.property("strategyCatalogText")
    assert "compatibility" in page.property("strategyCatalogText")
    assert "thresholds" in page.property("strategyCatalogText")
    assert "scenario-recipe-baseline-v1" in page.property("recipeCatalogText")
    assert "catalog" in page.property("recipeCatalogText")
    market_text = page.property("marketScenarioCatalogText")
    assert "source" in market_text
    assert "materializer" in market_text
    assert "numeric tolerance" in market_text
    assert "normalization" in market_text
    assert "execution-stress" not in market_text
    assert "comparison" in market_text
    assert "execution policy" in market_text
    assert page.property("stateTitle") == "Authoritative inputs are ready"
    assert page.property("blockingReasonsText") == "No blocking reason."
    assert page.property("reproductionManifestStatus") == "not_yet_available"
    for forbidden in (
        "Buy",
        "Sell",
        "Submit order",
        "Cancel order",
        "Replace order",
        "Bulk order",
    ):
        assert forbidden.casefold() not in visible_text.casefold()

    window.close()
    diagnostic_tasks.close()
    run_monitoring.close()


def test_workspace_route_exit_disposes_subscription_and_remounts_page(
) -> None:
    app = _app()
    diagnostic_tasks = DeterministicFakeDiagnosticTasksAdapter()
    run_monitoring = DeterministicFakeRunMonitoringAdapter()
    evidence = DeterministicFakeEvidenceAndFindingsAdapter()
    host = JourneyWorkspaceHost(
        run_monitoring,
        context=RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        evidence_feature=evidence,
        evidence_context=EvidenceAndFindingsContext.no_selection(),
        initial_route="evidence_and_findings",
    )
    host.show()
    app.processEvents()
    app.processEvents()
    root = host.rootObject()
    diagnostic_loader = root.findChild(QObject, "diagnosticTasksPageLoader")
    assert diagnostic_loader is not None

    assert root.property("activeRoute") == "evidence_and_findings"
    assert root.findChild(QObject, "evidenceResearchFlickable") is not None
    assert diagnostic_loader.property("item") is None
    assert host._evidence_and_findings._subscription is not None
    assert host._diagnostic_tasks._subscription is None

    assert root.setProperty("activeRoute", "diagnostic_tasks")
    app.processEvents()
    app.processEvents()
    diagnostic_page = diagnostic_loader.property("item")
    assert diagnostic_page is not None
    assert host._diagnostic_tasks._subscription is not None
    assert host._evidence_and_findings._subscription is None

    assert root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    app.processEvents()
    assert diagnostic_loader.property("item") is None
    assert host._diagnostic_tasks._subscription is None
    assert host._evidence_and_findings._subscription is not None

    assert root.setProperty("activeRoute", "diagnostic_tasks")
    app.processEvents()
    app.processEvents()
    remounted_page = diagnostic_loader.property("item")
    assert remounted_page is not None
    assert remounted_page is not diagnostic_page

    host.close_adapter()
    host.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    evidence.close()


def test_qml_create_persists_task_handle_across_remount_and_application_reopen(
    tmp_path,
) -> None:
    app = _app()
    source = _RecipeFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'qml-diagnostic-task.db'}",
        future=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            2,
            tzinfo=timezone.utc,
        ),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)
    feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application
        )
    )
    window, run_monitoring = _window(feature)
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()
    page = root.findChild(QObject, "diagnosticTasksPage")
    button = root.findChild(QObject, "createDiagnosticTaskButton")
    assert page is not None
    assert button is not None
    assert button.property("enabled") is True

    assert QMetaObject.invokeMethod(button, "invoked")
    app.processEvents()

    task_text = page.property("taskStatusText")
    handle_text = page.property("taskHandleText")
    assert "diagnostic-task-" in task_text
    assert " · r2 · draft · " in task_text
    assert "diagnostic-task-handle-" in handle_text
    assert " · completed · 100% · diagnostic_task_created · " in handle_text
    window.close()
    run_monitoring.close()

    remounted_window, remounted_monitoring = _window(feature)
    remounted_window.show()
    app.processEvents()
    remounted_page = remounted_window.centralWidget().rootObject().findChild(
        QObject,
        "diagnosticTasksPage",
    )
    assert remounted_page is not None
    assert remounted_page.property("taskStatusText") == task_text
    assert remounted_page.property("taskHandleText") == handle_text
    remounted_window.close()
    remounted_monitoring.close()
    feature.close()

    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            3,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(engine)
    restarted_feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application
        )
    )
    restarted_window, restarted_monitoring = _window(restarted_feature)
    restarted_window.show()
    app.processEvents()
    restarted_page = restarted_window.centralWidget().rootObject().findChild(
        QObject,
        "diagnosticTasksPage",
    )

    assert restarted_page is not None
    assert restarted_page.property("taskStatusText") == task_text
    assert restarted_page.property("taskHandleText") == handle_text
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_tasks")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_campaigns")
        ).scalar_one() == 0
    restarted_window.close()
    restarted_feature.close()
    restarted_monitoring.close()


def test_qml_corrects_validates_and_approves_exact_persisted_revision(
    tmp_path,
) -> None:
    app = _app()
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    window, run_monitoring = _window(feature)
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()
    page = root.findChild(QObject, "diagnosticTasksPage")
    create_button = root.findChild(QObject, "createDiagnosticTaskButton")
    revise_button = root.findChild(QObject, "reviseDiagnosticTaskButton")
    validate_button = root.findChild(QObject, "validateDiagnosticTaskButton")
    approve_button = root.findChild(QObject, "approveDiagnosticTaskButton")
    actor_input = root.findChild(QObject, "diagnosticTaskApprovalActorInput")
    assert page is not None
    assert create_button is not None
    assert revise_button is not None
    assert validate_button is not None
    assert approve_button is not None
    assert actor_input is not None

    assert QMetaObject.invokeMethod(create_button, "invoked")
    app.processEvents()
    assert " · r2 · draft · " in page.property("taskStatusText")
    assert validate_button.property("enabled") is True
    assert approve_button.property("enabled") is False

    assert QMetaObject.invokeMethod(validate_button, "invoked")
    app.processEvents()
    assert "invalid" in page.property("validationStatusText")
    assert "campaign.layer.isolated_sensitivity_required" in page.property(
        "validationStatusText"
    )
    assert "campaign.layer.compound_required" in page.property(
        "validationStatusText"
    )
    assert approve_button.property("enabled") is False

    assert QMetaObject.invokeMethod(revise_button, "invoked")
    app.processEvents()
    assert " · r3 · draft · " in page.property("taskStatusText")
    assert "has not been validated" in page.property(
        "validationStatusText"
    )
    assert "No exact-revision approval" in page.property(
        "approvalStatusText"
    )

    assert QMetaObject.invokeMethod(validate_button, "invoked")
    app.processEvents()
    assert " · r3 · awaiting_approval · " in page.property(
        "taskStatusText"
    )
    assert "valid · validation" in page.property("validationStatusText")
    assert "no findings" in page.property("validationStatusText")
    assert actor_input.setProperty("text", "qml-research-owner")
    app.processEvents()
    assert approve_button.property("enabled") is True

    assert QMetaObject.invokeMethod(approve_button, "invoked")
    app.processEvents()
    task_text = page.property("taskStatusText")
    validation_text = page.property("validationStatusText")
    approval_text = page.property("approvalStatusText")
    handle_text = page.property("taskHandleText")
    assert " · r3 · approved · " in task_text
    assert "qml-research-owner" in approval_text
    assert "diagnostic-task-validation-" in validation_text
    assert "diagnostic-task-approval-" in approval_text
    assert "diagnostic_task_configuration_valid" in handle_text

    window.close()
    run_monitoring.close()
    feature.close()
    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            5,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(engine)
    restarted_feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application
        )
    )
    restarted_window, restarted_monitoring = _window(restarted_feature)
    restarted_window.show()
    app.processEvents()
    restarted_page = restarted_window.centralWidget().rootObject().findChild(
        QObject,
        "diagnosticTasksPage",
    )
    assert restarted_page is not None
    assert restarted_page.property("taskStatusText") == task_text
    assert restarted_page.property("validationStatusText") == validation_text
    assert restarted_page.property("approvalStatusText") == approval_text
    assert restarted_page.property("taskHandleText") == handle_text
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM diagnostic_task_configuration_revisions"
            )
        ).scalar_one() == 3
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_validations")
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_approvals")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_recipe_approvals")
        ).scalar_one() == 3
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_mutation_commands")
        ).scalar_one() == 4
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_campaigns")
        ).scalar_one() == 0
    restarted_window.close()
    restarted_feature.close()
    restarted_monitoring.close()


def test_qml_starts_approved_campaign_and_hands_real_run_to_monitoring(
    tmp_path,
) -> None:
    app = _app()
    (
        source,
        artifact_store,
        engine,
        application,
        _application_adapter,
        diagnostic_tasks,
    ) = _formal_live_stack(tmp_path)
    bridge = EventBridge(subscribe_backend=False)
    run_monitoring = LiveRunMonitoringAdapter(
        application_read_model=LiveStrategyDiagnosticsV1ApplicationAdapter(
            application,
            engine,
        ),
        event_bridge=bridge,
        executor=_DirectExecutor(),
    )
    window = MainWindow(
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=run_monitoring,
        run_monitoring_context=RunMonitoringContext.no_selection(),
        frontend_v2_enabled=True,
    )
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()
    create_button = root.findChild(QObject, "createDiagnosticTaskButton")
    revise_button = root.findChild(QObject, "reviseDiagnosticTaskButton")
    validate_button = root.findChild(QObject, "validateDiagnosticTaskButton")
    approve_button = root.findChild(QObject, "approveDiagnosticTaskButton")
    actor_input = root.findChild(QObject, "diagnosticTaskApprovalActorInput")
    start_button = root.findChild(QObject, "startDiagnosticCampaignButton")
    assert create_button is not None
    assert revise_button is not None
    assert validate_button is not None
    assert approve_button is not None
    assert actor_input is not None
    assert start_button is not None

    assert QMetaObject.invokeMethod(create_button, "invoked")
    app.processEvents()
    assert QMetaObject.invokeMethod(revise_button, "invoked")
    app.processEvents()
    assert QMetaObject.invokeMethod(validate_button, "invoked")
    app.processEvents()
    assert actor_input.setProperty("text", "qml-wave2-release-owner")
    app.processEvents()
    assert QMetaObject.invokeMethod(approve_button, "invoked")
    app.processEvents()
    assert start_button.property("enabled") is True

    assert QMetaObject.invokeMethod(start_button, "invoked")
    app.processEvents()
    app.processEvents()

    task = diagnostic_tasks.snapshot(DiagnosticTasksContext.workspace()).task
    assert task is not None
    assert task.handoff.ready_for_run_monitoring
    campaign_id = task.handoff.campaign_id
    assert campaign_id is not None
    run_id = next(
        run.run_id
        for node in task.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    campaign_text = root.findChild(QObject, "runMonitoringCampaignIdentity")
    run_text = root.findChild(QObject, "runMonitoringRunIdentity")
    assert root.property("activeRoute") == "run_monitoring"
    assert campaign_text is not None
    assert run_text is not None
    assert campaign_text.property("text") == f"Campaign · {campaign_id.value}"
    assert run_text.property("text") == f"Run · {run_id.value}"

    diagnostic_navigation = root.findChild(
        QObject,
        "diagnosticTasksRouteNavigation",
    )
    assert diagnostic_navigation is not None
    assert root.setProperty("activeRoute", "diagnostic_tasks")
    app.processEvents()
    app.processEvents()
    assert root.property("activeRoute") == "diagnostic_tasks"
    diagnostic_loader = root.findChild(QObject, "diagnosticTasksPageLoader")
    assert diagnostic_loader is not None
    active_diagnostic_page = diagnostic_loader.property("item")
    assert active_diagnostic_page is not None
    lifecycle_panel = active_diagnostic_page.findChild(
        QObject,
        "diagnosticLifecyclePanel",
    )
    pause_task = active_diagnostic_page.findChild(
        QObject,
        "pauseDiagnosticTaskTargetButton",
    )
    resume_task = active_diagnostic_page.findChild(
        QObject,
        "resumeDiagnosticTaskTargetButton",
    )
    pause_campaign = active_diagnostic_page.findChild(
        QObject,
        "pauseFormalDiagnosticCampaignTargetButton",
    )
    resume_campaign = active_diagnostic_page.findChild(
        QObject,
        "resumeFormalDiagnosticCampaignTargetButton",
    )
    pause_node = active_diagnostic_page.findChild(
        QObject,
        "pauseCampaignNodeTargetButton",
    )
    resume_node = active_diagnostic_page.findChild(
        QObject,
        "resumeCampaignNodeTargetButton",
    )
    cancel_node = active_diagnostic_page.findChild(
        QObject,
        "cancelCampaignNodeTargetButton",
    )
    assert lifecycle_panel is not None
    assert pause_task is not None
    assert resume_task is not None
    assert pause_campaign is not None
    assert resume_campaign is not None
    assert pause_node is not None
    assert resume_node is not None
    assert cancel_node is not None

    assert pause_task.property("enabled") is True
    assert QMetaObject.invokeMethod(pause_task, "invoked")
    app.processEvents()
    paused_task = diagnostic_tasks.snapshot(
        DiagnosticTasksContext.workspace()
    ).task
    assert paused_task is not None
    assert paused_task.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert resume_task.property("enabled") is True
    assert QMetaObject.invokeMethod(resume_task, "invoked")
    app.processEvents()

    assert pause_campaign.property("enabled") is True
    assert QMetaObject.invokeMethod(pause_campaign, "invoked")
    app.processEvents()
    assert resume_campaign.property("enabled") is True
    assert QMetaObject.invokeMethod(resume_campaign, "invoked")
    app.processEvents()

    assert pause_node.property("enabled") is True
    assert QMetaObject.invokeMethod(pause_node, "invoked")
    app.processEvents()
    assert resume_node.property("enabled") is True
    assert QMetaObject.invokeMethod(resume_node, "invoked")
    app.processEvents()
    assert cancel_node.property("enabled") is True
    assert QMetaObject.invokeMethod(cancel_node, "invoked")
    app.processEvents()

    window.close()
    remounted = MainWindow(
        diagnostic_tasks_feature=diagnostic_tasks,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=run_monitoring,
        run_monitoring_context=RunMonitoringContext.no_selection(),
        frontend_v2_enabled=True,
    )
    remounted.show()
    app.processEvents()
    app.processEvents()
    remounted_root = remounted.centralWidget().rootObject()
    assert remounted_root.property("activeRoute") == "diagnostic_tasks"
    assert remounted_root.setProperty("activeRoute", "run_monitoring")
    app.processEvents()
    app.processEvents()
    assert remounted_root.findChild(
        QObject,
        "runMonitoringCampaignIdentity",
    ).property("text") == f"Campaign · {campaign_id.value}"
    assert remounted_root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == f"Run · {run_id.value}"
    remounted.close()
    diagnostic_tasks.close()
    run_monitoring.close()
    bridge.stop()

    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            3,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(engine)
    restarted_tasks = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application
        )
    )
    restarted_bridge = EventBridge(subscribe_backend=False)
    restarted_monitoring = LiveRunMonitoringAdapter(
        application_read_model=LiveStrategyDiagnosticsV1ApplicationAdapter(
            restarted_application,
            engine,
        ),
        event_bridge=restarted_bridge,
        executor=_DirectExecutor(),
    )
    reopened = MainWindow(
        diagnostic_tasks_feature=restarted_tasks,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=restarted_monitoring,
        run_monitoring_context=RunMonitoringContext.no_selection(),
        frontend_v2_enabled=True,
    )
    reopened.show()
    app.processEvents()
    app.processEvents()
    reopened_root = reopened.centralWidget().rootObject()
    assert reopened_root.property("activeRoute") == "diagnostic_tasks"
    assert reopened_root.setProperty("activeRoute", "run_monitoring")
    app.processEvents()
    app.processEvents()
    assert reopened_root.findChild(
        QObject,
        "runMonitoringCampaignIdentity",
    ).property("text") == f"Campaign · {campaign_id.value}"
    assert reopened_root.findChild(
        QObject,
        "runMonitoringRunIdentity",
    ).property("text") == f"Run · {run_id.value}"
    reopened.close()
    restarted_tasks.close()
    restarted_monitoring.close()
    restarted_bridge.stop()
