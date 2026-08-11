from __future__ import annotations

import gc
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import AppContext, build_app_context
from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticTaskId,
    DiagnosticTasksContext,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    EvidenceComparisonId,
    EvidenceRecordId,
    FormalDiagnosticCampaignId,
    LiveScenarioLabAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyLibraryAdapter,
    MarketScenarioId,
    RunMonitoringContext,
    RunMonitoringSelection,
    ReproductionManifestId,
    ScenarioLabContext,
    StrategyLibraryContext,
    StrategyRunId,
    StrategyUnderTestId,
    TaskHandleId,
)
from app.features.diagnostic_tasks_application import (
    DiagnosticTaskConfigurationContentId,
)
from app.journey_recovery import (
    JOURNEY_DESTINATIONS,
    JourneyFocusReturnToken,
    JourneyDiagnosticSelection,
    JourneyEvidenceSelection,
    JourneyPresentationSelection,
    JourneyRecoveryReason,
    JourneyViewMode,
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
    encode_journey_workspace_bookmark,
    restore_journey_workspace_bookmark,
)
from app.ui.journey_workspace import JourneyWorkspaceHost
from tests.frontend.integration.test_diagnostic_tasks_workspace_route import (
    _formal_live_stack,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settle(app: QApplication) -> None:
    for _ in range(8):
        app.processEvents()


def _quick_item(root: QObject, object_name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, object_name)
    if item is None and isinstance(root, QQuickItem):
        pending = list(root.childItems())
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == object_name:
                item = candidate
                break
            pending.extend(candidate.childItems())
    assert item is not None, object_name
    return item


def _has_quick_item(root: QObject, object_name: str) -> bool:
    try:
        _quick_item(root, object_name)
    except AssertionError:
        return False
    return True


def _press(
    app: QApplication,
    host: JourneyWorkspaceHost,
    item: QQuickItem,
    key: Qt.Key = Qt.Key.Key_Space,
) -> None:
    assert item.property("enabled") is True, item.objectName()
    assert item.property("visible") is True, item.objectName()
    item.forceActiveFocus()
    QTest.keyClick(host, key)
    _settle(app)


def _click(
    app: QApplication,
    host: JourneyWorkspaceHost,
    root: QQuickItem,
    item: QQuickItem,
) -> None:
    assert item.property("enabled") is True, item.objectName()
    item.forceActiveFocus()
    _settle(app)
    point = item.mapToItem(
        root,
        QPointF(item.width() / 2, item.height() / 2),
    )
    QTest.mouseClick(
        host,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(point.x()), round(point.y())),
    )
    _settle(app)


def _wait_for(app: QApplication, predicate) -> None:
    for _ in range(300):
        _settle(app)
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("Qt event-loop condition did not become true")


@pytest.fixture(autouse=True)
def _release_qml_hosts(monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    yield
    app = QApplication.instance()
    if app is not None:
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        gc.collect()


def _host(app_context: AppContext, **overrides) -> JourneyWorkspaceHost:
    run_feature = overrides.pop(
        "run_feature", app_context.run_monitoring_feature
    )
    arguments = {
        "context": app_context.run_monitoring_context,
        "strategy_library_feature": app_context.strategy_library_feature,
        "strategy_library_context": app_context.strategy_library_context,
        "journey_workspace_bookmark": app_context.journey_workspace_bookmark,
        "scenario_lab_feature": app_context.scenario_lab_feature,
        "scenario_lab_context": app_context.scenario_lab_context,
        "diagnostic_tasks_feature": app_context.diagnostic_tasks_feature,
        "diagnostic_tasks_context": app_context.diagnostic_tasks_context,
        "diagnostic_setup_selection_coordinator": (
            app_context.diagnostic_setup_selection_coordinator
        ),
        "evidence_feature": app_context.evidence_and_findings_feature,
        "evidence_context": app_context.evidence_and_findings_context,
        "system_health_feature": app_context.system_health_feature,
        "system_health_context": app_context.system_health_context,
        "initial_route": app_context.journey_workspace_bookmark.last_route.value,
    }
    arguments.update(overrides)
    return JourneyWorkspaceHost(run_feature, **arguments)


class _CountingSubscription:
    def __init__(self, inner, owner: "_ObservedRunFeature") -> None:
        self._inner = inner
        self._owner = owner

    @property
    def disposed(self) -> bool:
        return self._inner.disposed

    def dispose(self) -> None:
        was_disposed = self._inner.disposed
        self._inner.dispose()
        if not was_disposed:
            self._owner.dispose_count += 1


class _ObservedRunFeature:
    """Public Feature-Interface observer used only for seam evidence."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.subscribe_count = 0
        self.dispose_count = 0
        self.lifecycle_command_count = 0
        self.last_observer = None

    @property
    def interface_version(self):
        return self.inner.interface_version

    def snapshot(self, context):
        return self.inner.snapshot(context)

    def subscribe(self, context, observer):
        self.subscribe_count += 1
        self.last_observer = observer
        return _CountingSubscription(
            self.inner.subscribe(context, observer),
            self,
        )

    def pause_diagnostic_task(self, command):
        self.lifecycle_command_count += 1
        return self.inner.pause_diagnostic_task(command)

    def resume_diagnostic_task(self, command):
        self.lifecycle_command_count += 1
        return self.inner.resume_diagnostic_task(command)

    def cancel_diagnostic_task(self, command):
        self.lifecycle_command_count += 1
        return self.inner.cancel_diagnostic_task(command)

    def deliver_late(self, state) -> None:
        assert self.last_observer is not None
        self.last_observer(state)

    def close(self) -> None:
        self.inner.close()


class _ObservedFeature:
    """Count public subscription traffic while delegating the Feature API."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.subscribe_count = 0
        self.dispose_count = 0
        self.snapshot_count = 0

    def snapshot(self, context):
        self.snapshot_count += 1
        return self.inner.snapshot(context)

    def subscribe(self, context, observer):
        self.subscribe_count += 1
        return _CountingSubscription(
            self.inner.subscribe(context, observer),
            self,
        )

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _close(context: AppContext, host: JourneyWorkspaceHost) -> None:
    host.close_adapter()
    host.deleteLater()
    for feature in (
        context.strategy_library_feature,
        context.scenario_lab_feature,
        context.diagnostic_tasks_feature,
        context.run_monitoring_feature,
        context.evidence_and_findings_feature,
        context.system_health_feature,
    ):
        feature.close()


def test_public_rail_exposes_exact_six_destination_order_and_no_trading_entry(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(context)
    _settle(app)
    root = host.rootObject()
    assert root is not None

    assert host.route_order == tuple(item.route for item in JOURNEY_DESTINATIONS)
    assert tuple(item.label for item in host.destinations) == (
        "Strategy Library",
        "Scenario Lab",
        "Diagnostic Tasks",
        "Run Monitoring",
        "Evidence & Findings",
        "System Health",
    )
    navigation_names = (
        "strategyLibraryRouteNavigation",
        "scenarioLabRouteNavigation",
        "diagnosticTasksRouteNavigation",
        "runMonitoringRouteNavigation",
        "evidenceAndFindingsRouteNavigation",
        "systemHealthRouteNavigation",
    )
    navigation = tuple(root.findChild(QQuickItem, name) for name in navigation_names)
    assert all(item is not None for item in navigation)
    assert all(item.property("visible") for item in navigation if item is not None)
    assert all(item.property("enabled") for item in navigation if item is not None)
    assert not any(
        root.findChild(QObject, name) is not None
        for name in (
            "marketRouteNavigation",
            "accountRouteNavigation",
            "positionsRouteNavigation",
            "ordersRouteNavigation",
            "fillsRouteNavigation",
            "buyButton",
            "sellButton",
        )
    )

    _close(context, host)


def test_keyboard_traverses_and_activates_the_six_destinations_in_exact_order(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(context)
    host.show()
    _settle(app)
    root = host.rootObject()
    assert root is not None
    navigation_names = (
        "strategyLibraryRouteNavigation",
        "scenarioLabRouteNavigation",
        "diagnosticTasksRouteNavigation",
        "runMonitoringRouteNavigation",
        "evidenceAndFindingsRouteNavigation",
        "systemHealthRouteNavigation",
    )
    navigation = tuple(
        root.findChild(QQuickItem, name) for name in navigation_names
    )
    assert all(item is not None for item in navigation)
    navigation[0].forceActiveFocus()

    focused: list[JourneyWorkspaceRoute] = []
    for index, expected in enumerate(JourneyWorkspaceRoute):
        item = navigation[index]
        assert item.property("activeFocus") is True
        focused.append(expected)
        if index < len(navigation) - 1:
            QTest.keyClick(host, Qt.Key.Key_Down)
            _settle(app)

    visited: list[JourneyWorkspaceRoute] = []
    for index, expected in enumerate(JourneyWorkspaceRoute):
        navigation[index].forceActiveFocus()
        QTest.keyClick(host, Qt.Key.Key_Return)
        _settle(app)
        assert host.active_route is expected
        visited.append(host.active_route)

    assert tuple(focused) == tuple(JourneyWorkspaceRoute)
    assert tuple(visited) == tuple(JourneyWorkspaceRoute)
    _close(context, host)


def test_unavailable_route_is_visible_disabled_and_recovers_explicitly(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(
        context,
        strategy_library_feature=None,
        scenario_lab_feature=None,
        diagnostic_tasks_feature=None,
        evidence_feature=None,
        system_health_feature=None,
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        initial_route=JourneyWorkspaceRoute.SYSTEM_HEALTH.value,
    )
    _settle(app)
    root = host.rootObject()
    assert root is not None

    system_health = root.findChild(QQuickItem, "systemHealthRouteNavigation")
    assert system_health is not None
    assert system_health.property("visible") is True
    assert system_health.property("enabled") is False
    assert host.active_route is JourneyWorkspaceRoute.RUN_MONITORING
    assert host.recovery_state.reason is JourneyRecoveryReason.UNAVAILABLE_ROUTE
    assert host.recovery_state.safe_route is JourneyWorkspaceRoute.RUN_MONITORING
    assert host.activate_route(JourneyWorkspaceRoute.SYSTEM_HEALTH) is False
    assert host.active_route is JourneyWorkspaceRoute.RUN_MONITORING

    _close(context, host)


def test_bookmark_focus_token_restores_only_after_authoritative_route_entry(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.STRATEGY_LIBRARY,
        presentation=JourneyPresentationSelection(
            focus_return_token=JourneyFocusReturnToken(
                JourneyWorkspaceRoute.STRATEGY_LIBRARY,
                "strategyLibrarySearchInput",
            )
        ),
    )
    host = _host(
        context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.resize(1280, 720)
    host.show()
    _settle(app)
    root = host.rootObject()
    assert root is not None

    search = root.findChild(QQuickItem, "strategyLibrarySearchInput")
    assert search is not None
    assert search.property("visible") is True
    assert search.property("enabled") is True
    assert search.property("activeFocus") is True
    assert root.property("focusReturnConsumed") is True
    assert host.journey_context.presentation.focus_return_token == (
        bookmark.presentation.focus_return_token
    )

    _close(context, host)


def test_copied_wave_3_bookmark_restores_the_exact_reference_path_focus(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    _wait_for(
        app,
        lambda: bool(
            context.scenario_lab_feature.snapshot(
                context.scenario_lab_context
            ).reference_paths
        ),
    )
    scenario_state = context.scenario_lab_feature.snapshot(
        context.scenario_lab_context
    )
    assert scenario_state.reference_paths
    path_identity = scenario_state.reference_paths[0].path_id.value
    copied_wave_3_payload = json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "scenario_lab",
            "diagnostic_task_id": None,
            "scenario_focus_target": "reference_path",
            "scenario_focus_identity": path_identity,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    restored = restore_journey_workspace_bookmark(copied_wave_3_payload)
    host = _host(
        context,
        journey_workspace_bookmark=restored.bookmark,
        initial_route=restored.bookmark.last_route.value,
    )
    host.resize(1280, 720)
    host.show()
    target = _quick_item(host.rootObject(), f"scenarioLabPath-{path_identity}")
    _wait_for(app, lambda: target.property("activeFocus") is True)

    assert restored.migrated is True
    assert target.property("activeFocus") is True
    assert host.rootObject().property("focusReturnConsumed") is True

    _close(context, host)


def test_copied_wave_3_bookmark_with_missing_focus_identity_recovers_safely(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    missing_identity = "missing-reference-path-113"
    copied_wave_3_payload = json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "scenario_lab",
            "diagnostic_task_id": None,
            "scenario_focus_target": "reference_path",
            "scenario_focus_identity": missing_identity,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    restored = restore_journey_workspace_bookmark(copied_wave_3_payload)
    host = _host(
        context,
        journey_workspace_bookmark=restored.bookmark,
        initial_route=restored.bookmark.last_route.value,
    )
    host.resize(1280, 720)
    host.show()
    _settle(app)

    assert restored.migrated is True
    assert host.recovery_state.reason is JourneyRecoveryReason.MISSING_IDENTITY
    assert host.journey_context.presentation.selected_identity == missing_identity
    assert host.rootObject().property("focusReturnConsumed") is False

    _close(context, host)


def test_route_exit_disposes_once_suppresses_late_delivery_and_rereads_on_entry(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    run_context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            FormalDiagnosticCampaignId("campaign-continuity-113"),
            StrategyRunId("run-continuity-113"),
        )
    )
    context.run_monitoring_feature.advance_to_running(run_context)
    observed = _ObservedRunFeature(context.run_monitoring_feature)
    diagnostic = JourneyDiagnosticSelection(
        task_id=DiagnosticTaskId("DIAGNOSTIC-TASK-001"),
        task_revision=1,
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            "configuration-continuity-113"
        ),
        task_handle_id=TaskHandleId("TASK-HANDLE-001"),
        campaign_id=run_context.selection.campaign_id,
        campaign_revision=1,
        run_id=run_context.selection.run_id,
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.RUN_MONITORING,
        diagnostic_task_id=diagnostic.task_id,
        diagnostic_selection=diagnostic,
    )
    host = _host(
        context,
        run_feature=observed,
        context=run_context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.resize(1280, 720)
    host.show()
    _settle(app)
    root = host.rootObject()
    assert root is not None
    assert root.property("screenState") == "active"
    assert observed.subscribe_count == 1
    assert observed.dispose_count == 0
    before = observed.snapshot(run_context).last_reliable_data
    assert before is not None

    assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY) is True
    _settle(app)
    after_exit = observed.snapshot(run_context).last_reliable_data
    assert after_exit is not None
    assert after_exit.lifecycle == before.lifecycle
    assert observed.dispose_count == 1
    assert observed.lifecycle_command_count == 0

    completed = context.run_monitoring_feature.advance_to_completed(run_context)
    observed.deliver_late(completed)
    _settle(app)
    assert root.property("screenState") == "active"
    assert host.journey_context.diagnostic_selection is not None
    assert host.journey_context.diagnostic_selection.task_handle_id == (
        TaskHandleId("TASK-HANDLE-001")
    )

    assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING) is True
    _settle(app)
    assert root.property("screenState") == "terminal"
    assert observed.subscribe_count == 2
    assert observed.dispose_count == 1
    assert observed.lifecycle_command_count == 0
    assert host.journey_context.diagnostic_selection is not None
    assert host.journey_context.diagnostic_selection.task_handle_id == (
        TaskHandleId("TASK-HANDLE-001")
    )

    host.close_adapter()
    host.deleteLater()
    assert observed.dispose_count == 2
    for feature in (
        context.strategy_library_feature,
        context.scenario_lab_feature,
        context.diagnostic_tasks_feature,
        context.evidence_and_findings_feature,
        context.system_health_feature,
    ):
        feature.close()
    observed.close()


def test_host_subscribes_only_the_current_route_and_preserves_sources(tmp_path) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    observed = {
        "strategy_library_feature": _ObservedFeature(
            context.strategy_library_feature
        ),
        "scenario_lab_feature": _ObservedFeature(context.scenario_lab_feature),
        "diagnostic_tasks_feature": _ObservedFeature(
            context.diagnostic_tasks_feature
        ),
        "run_feature": _ObservedFeature(context.run_monitoring_feature),
        "evidence_feature": _ObservedFeature(
            context.evidence_and_findings_feature
        ),
        "system_health_feature": _ObservedFeature(context.system_health_feature),
    }
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.DIAGNOSTIC_TASKS
    )
    host = _host(
        context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
        **observed,
    )
    host.show()
    _wait_for(
        app,
        lambda: observed["diagnostic_tasks_feature"].subscribe_count == 1,
    )

    assert {
        key: feature.subscribe_count for key, feature in observed.items()
    } == {
        "strategy_library_feature": 0,
        "scenario_lab_feature": 0,
        "diagnostic_tasks_feature": 1,
        "run_feature": 0,
        "evidence_feature": 0,
        "system_health_feature": 0,
    }
    assert host.journey_context.source_identities

    assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY) is True
    _settle(app)
    assert observed["diagnostic_tasks_feature"].dispose_count == 1
    assert observed["strategy_library_feature"].subscribe_count == 1
    assert host.journey_context.source_identities
    assert host.journey_context.route is JourneyWorkspaceRoute.STRATEGY_LIBRARY

    host.close_adapter()
    host.deleteLater()
    for feature in observed.values():
        feature.inner.close()


def test_missing_diagnostic_identity_is_retained_but_never_reported_exact(
    tmp_path,
) -> None:
    app = _app()
    diagnostic = JourneyDiagnosticSelection(
        task_id=DiagnosticTaskId("missing-task-113"),
        task_revision=7,
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            "missing-configuration-113"
        ),
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.DIAGNOSTIC_TASKS,
        diagnostic_task_id=diagnostic.task_id,
        diagnostic_selection=diagnostic,
    )
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(
        context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.show()
    _settle(app)

    assert context.diagnostic_tasks_feature.snapshot(
        DiagnosticTasksContext(task_id=diagnostic.task_id)
    ).task is None
    assert host.journey_context.diagnostic_selection == diagnostic
    assert host.recovery_state.reason is JourneyRecoveryReason.MISSING_IDENTITY

    _close(context, host)


def test_in_session_focus_token_is_captured_and_republished_on_route_return(
    tmp_path,
) -> None:
    app = _app()
    persisted: list[JourneyWorkspaceBookmark] = []
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(context, journey_workspace_bookmark_sink=persisted.append)
    host.resize(1280, 720)
    host.show()
    _settle(app)
    assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY) is True
    _settle(app)
    search = _quick_item(host.rootObject(), "strategyLibrarySearchInput")
    search.forceActiveFocus()
    _settle(app)

    assert host.activate_route(JourneyWorkspaceRoute.SCENARIO_LAB) is True
    _settle(app)

    assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY) is True
    root = host.rootObject()
    _wait_for(
        app,
        lambda: _has_quick_item(root, "strategyLibrarySearchInput")
        and _quick_item(root, "strategyLibrarySearchInput").property(
            "activeFocus"
        )
        is True,
    )
    search = _quick_item(root, "strategyLibrarySearchInput")
    assert search.property("activeFocus") is True
    assert persisted[-1].last_route is JourneyWorkspaceRoute.STRATEGY_LIBRARY
    assert persisted[-1].presentation.focus_return_token == JourneyFocusReturnToken(
        JourneyWorkspaceRoute.STRATEGY_LIBRARY,
        "strategyLibrarySearchInput",
        None,
    )

    _close(context, host)


def test_exact_bookmarked_evidence_and_comparison_are_preserved_without_inference(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    evidence_context = EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("campaign-evidence-113"),
            run_id=StrategyRunId("run-evidence-113"),
            strategy_id=StrategyUnderTestId("strategy-evidence-113"),
            market_scenario_id=MarketScenarioId("scenario-evidence-113"),
            approved_recipe_id=ApprovedScenarioRecipeId("recipe-evidence-113"),
            reproduction_manifest_id=ReproductionManifestId(
                "manifest-evidence-113"
            ),
        )
    )
    context.evidence_and_findings_feature.advance_to_completed(evidence_context)
    data = context.evidence_and_findings_feature.snapshot(
        evidence_context
    ).last_reliable_data
    assert data is not None
    candidate = data.candidates[-1]
    chosen_evidence = candidate.evidence[-1].identity
    chosen_comparison = candidate.comparisons[-1].identity
    assert isinstance(chosen_evidence, EvidenceRecordId)
    assert isinstance(chosen_comparison, EvidenceComparisonId)
    finding = candidate.findings[0]
    assert finding.sensitivity_breakpoints
    breakpoint = finding.sensitivity_breakpoints[0]
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        evidence_selection=JourneyEvidenceSelection(
            evidence_package_id=data.evidence_package_id,
            evidence_id=chosen_evidence,
            comparison_id=chosen_comparison,
            finding_id=finding.identity,
            sensitivity_breakpoint_id=breakpoint.identity,
            reproduction_manifest_id=data.selection.reproduction_manifest_id,
        ),
        presentation=JourneyPresentationSelection(
            selected_identity=finding.identity.value,
            view_mode=JourneyViewMode.DETAILS,
        ),
    )
    host = _host(
        context,
        journey_workspace_bookmark=bookmark,
        evidence_context=evidence_context,
        initial_route=bookmark.last_route.value,
    )
    host.show()
    _settle(app)

    selection = host.journey_context.evidence_selection
    assert selection is not None
    assert selection.evidence_id == chosen_evidence
    assert selection.comparison_id == chosen_comparison
    assert selection.finding_id == finding.identity
    assert selection.sensitivity_breakpoint_id == breakpoint.identity
    assert (
        selection.reproduction_manifest_id
        == data.selection.reproduction_manifest_id
    )
    assert host.journey_context.presentation.selected_identity == finding.identity.value
    assert host.journey_context.presentation.view_mode is JourneyViewMode.DETAILS
    assert host.recovery_state.reason is JourneyRecoveryReason.EXACT

    _close(context, host)


def test_bookmarked_evidence_selection_waits_for_authoritative_feature_state(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    evidence_context = EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("campaign-late-evidence-113"),
            run_id=StrategyRunId("run-late-evidence-113"),
            strategy_id=StrategyUnderTestId("strategy-late-evidence-113"),
            market_scenario_id=MarketScenarioId("scenario-late-evidence-113"),
            approved_recipe_id=ApprovedScenarioRecipeId(
                "recipe-late-evidence-113"
            ),
            reproduction_manifest_id=ReproductionManifestId(
                "manifest-late-evidence-113"
            ),
        )
    )
    completed = context.evidence_and_findings_feature.advance_to_completed(
        evidence_context
    )
    data = completed.last_reliable_data
    assert data is not None
    candidate = data.candidates[-1]
    finding = candidate.findings[0]
    breakpoint = finding.sensitivity_breakpoints[0]
    durable = JourneyEvidenceSelection(
        evidence_package_id=data.evidence_package_id,
        evidence_id=candidate.evidence[-1].identity,
        comparison_id=candidate.comparisons[-1].identity,
        finding_id=finding.identity,
        sensitivity_breakpoint_id=breakpoint.identity,
        reproduction_manifest_id=data.selection.reproduction_manifest_id,
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        evidence_selection=durable,
        presentation=JourneyPresentationSelection(
            selected_identity=finding.identity.value,
            view_mode=JourneyViewMode.DETAILS,
        ),
    )
    late_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    host = _host(
        context,
        evidence_feature=late_feature,
        evidence_context=evidence_context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.show()
    _settle(app)

    assert host.recovery_state.reason is JourneyRecoveryReason.UNAVAILABLE_IDENTITY
    assert host.journey_context.evidence_selection == durable

    late_feature.advance_to_completed(evidence_context)
    _wait_for(
        app,
        lambda: host.recovery_state.reason is JourneyRecoveryReason.EXACT,
    )

    assert host.journey_context.evidence_selection == durable
    assert host.journey_context.presentation.selected_identity == finding.identity.value
    assert host.journey_context.presentation.view_mode is JourneyViewMode.DETAILS

    _close(context, host)


def test_evidence_revisions_do_not_reread_inactive_diagnostic_inventory(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    observed_diagnostic = _ObservedFeature(context.diagnostic_tasks_feature)
    evidence_context = EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("campaign-fast-evidence-118"),
            run_id=StrategyRunId("run-fast-evidence-118"),
            strategy_id=StrategyUnderTestId("strategy-fast-evidence-118"),
            market_scenario_id=MarketScenarioId("scenario-fast-evidence-118"),
            approved_recipe_id=ApprovedScenarioRecipeId("recipe-fast-evidence-118"),
            reproduction_manifest_id=ReproductionManifestId(
                "manifest-fast-evidence-118"
            ),
        )
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    )
    host = _host(
        context,
        diagnostic_tasks_feature=observed_diagnostic,
        evidence_context=evidence_context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.show()
    _settle(app)
    reads_before_evidence = observed_diagnostic.snapshot_count

    context.evidence_and_findings_feature.advance_to_completed(evidence_context)
    _wait_for(app, lambda: host.journey_context.evidence_selection is not None)

    assert observed_diagnostic.snapshot_count == reads_before_evidence
    assert host.activate_route(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS) is True
    _settle(app)
    assert observed_diagnostic.snapshot_count == reads_before_evidence + 1

    _close(context, host)


def test_host_construction_reads_each_setup_feature_once(tmp_path) -> None:
    _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    observed_strategy = _ObservedFeature(context.strategy_library_feature)
    observed_scenario = _ObservedFeature(context.scenario_lab_feature)
    observed_diagnostic = _ObservedFeature(context.diagnostic_tasks_feature)
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    )

    host = _host(
        context,
        strategy_library_feature=observed_strategy,
        scenario_lab_feature=observed_scenario,
        diagnostic_tasks_feature=observed_diagnostic,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )

    assert observed_strategy.snapshot_count == 1
    assert observed_scenario.snapshot_count == 1
    assert observed_diagnostic.snapshot_count == 1

    _close(context, host)


def test_breakpoint_from_another_finding_is_explicitly_incompatible(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    evidence_context = EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("campaign-mismatch-113"),
            run_id=StrategyRunId("run-mismatch-113"),
            strategy_id=StrategyUnderTestId("strategy-mismatch-113"),
            market_scenario_id=MarketScenarioId("scenario-mismatch-113"),
            approved_recipe_id=ApprovedScenarioRecipeId("recipe-mismatch-113"),
            reproduction_manifest_id=ReproductionManifestId(
                "manifest-mismatch-113"
            ),
        )
    )
    completed = context.evidence_and_findings_feature.advance_to_completed(
        evidence_context
    )
    data = completed.last_reliable_data
    assert data is not None
    candidate = data.candidates[0]
    finding_with_breakpoint = candidate.findings[0]
    other_finding = candidate.findings[1]
    breakpoint = finding_with_breakpoint.sensitivity_breakpoints[0]
    incompatible = JourneyEvidenceSelection(
        evidence_package_id=data.evidence_package_id,
        finding_id=other_finding.identity,
        sensitivity_breakpoint_id=breakpoint.identity,
        reproduction_manifest_id=data.selection.reproduction_manifest_id,
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        evidence_selection=incompatible,
        presentation=JourneyPresentationSelection(
            selected_identity=other_finding.identity.value,
            view_mode=JourneyViewMode.FINDINGS,
        ),
    )
    host = _host(
        context,
        evidence_context=evidence_context,
        journey_workspace_bookmark=bookmark,
        initial_route=bookmark.last_route.value,
    )
    host.show()
    _settle(app)

    assert host.recovery_state.reason is JourneyRecoveryReason.INCOMPATIBLE_IDENTITY
    assert host.journey_context.evidence_selection == incompatible

    _close(context, host)


def test_real_feature_selections_keep_exact_typed_ids_across_corresponding_routes(
    tmp_path,
) -> None:
    app = _app()
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    context.strategy_library_feature.close()
    context.scenario_lab_feature.close()
    context.diagnostic_tasks_feature.close()
    workspace = DiagnosticTasksContext.workspace()
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _diagnostics_application,
        initial_tasks,
    ) = _formal_live_stack(tmp_path)
    initial_tasks.snapshot(workspace)
    inventory = initial_tasks.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    initial_tasks.close()
    bridge = EventBridge(subscribe_backend=False)
    context.strategy_library_feature = LiveStrategyLibraryAdapter(
        application=LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            application
        ),
        event_bridge=bridge,
    )
    context.strategy_library_context = StrategyLibraryContext()
    context.scenario_lab_feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        ),
        event_bridge=bridge,
    )
    context.scenario_lab_context = ScenarioLabContext()
    context.diagnostic_tasks_feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=inventory,
    )
    context.diagnostic_tasks_context = workspace
    host = _host(context)
    host.resize(1280, 720)
    host.show()
    _settle(app)
    root = host.rootObject()
    assert root is not None

    _press(
        app,
        host,
        _quick_item(root, "strategyLibraryCompareFormalSet"),
    )
    _press(
        app,
        host,
        _quick_item(root, "strategyLibrarySelectFormalSet"),
    )
    strategy = host.journey_context.strategy_selection
    assert strategy is not None
    assert strategy.strategy_under_test.strategy_id.value
    assert strategy.strategy_under_test.strategy_version
    assert strategy.comparison_strategies

    assert host.activate_route(JourneyWorkspaceRoute.SCENARIO_LAB) is True
    _settle(app)
    transformation = _quick_item(root, "scenarioLabRecipeTransformationInput")
    transformation.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Space)
    QTest.keyClick(host, Qt.Key.Key_Down)
    QTest.keyClick(host, Qt.Key.Key_Return)
    slippage = _quick_item(root, "scenarioLabRecipeSlippageInput")
    slippage.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(host, "5")
    _press(
        app,
        host,
        _quick_item(root, "scenarioLabCreateRecipeDraftButton"),
    )
    scenario_state = context.scenario_lab_feature.snapshot(
        context.scenario_lab_context
    )
    assert scenario_state.recipe_drafts
    draft_control_name = (
        "scenarioLabValidateRecipeDraft-"
        + scenario_state.recipe_drafts[-1].draft_id.value
    )
    _wait_for(
        app,
        lambda: _has_quick_item(root, draft_control_name),
    )
    _press(
        app,
        host,
        _quick_item(root, draft_control_name),
    )
    scenario_state = context.scenario_lab_feature.snapshot(
        context.scenario_lab_context
    )
    assert scenario_state.recipe_validations
    validation = scenario_state.recipe_validations[-1]
    validation_control_name = (
        "scenarioLabApproveRecipe-"
        + validation.validation_id.value
    )
    _wait_for(
        app,
        lambda: _has_quick_item(root, validation_control_name),
    )
    _press(
        app,
        host,
        _quick_item(root, validation_control_name),
    )
    scenario_state = context.scenario_lab_feature.snapshot(
        context.scenario_lab_context
    )
    assert scenario_state.approved_recipe_versions
    approved = next(
        item
        for item in scenario_state.approved_recipe_versions
        if item.approval.validation_id == validation.validation_id
    )
    materialize_control_name = (
        "scenarioLabMaterializeApprovedRecipe-"
        + approved.recipe_version_id.value
    )
    _wait_for(
        app,
        lambda: _has_quick_item(root, materialize_control_name),
    )
    _press(
        app,
        host,
        _quick_item(root, materialize_control_name),
    )
    _wait_for(
        app,
        lambda: bool(
            context.scenario_lab_feature.snapshot(
                context.scenario_lab_context
            ).task_handles
        )
        and context.scenario_lab_feature.snapshot(
            context.scenario_lab_context
        ).task_handles[-1].terminal,
    )
    compose = _quick_item(root, "scenarioLabComposeVisibleScenarioSetButton")
    _wait_for(app, lambda: compose.property("enabled") is True)
    _click(app, host, root, compose)
    scenario_state = context.scenario_lab_feature.snapshot(
        context.scenario_lab_context
    )
    assert scenario_state.scenario_sets, _quick_item(
        root,
        "scenarioLabScenarioCommandStatus",
    ).property("text")
    assert scenario_state.scenario_sets[-1].formal_handoff_eligible, (
        scenario_state.scenario_sets[-1].missing_requirements
    )
    resolve = _quick_item(root, "scenarioLabResolveExecutionAssumptionsButton")
    _wait_for(app, lambda: resolve.property("enabled") is True)
    _click(app, host, root, resolve)
    select_scenario = _quick_item(
        root,
        "scenarioLabSelectFormalScenarioSetButton",
    )
    _wait_for(app, lambda: select_scenario.property("enabled") is True)
    _click(app, host, root, select_scenario)
    scenario = host.journey_context.scenario_selection
    assert scenario is not None
    assert scenario.reference_market_path_ids
    assert scenario.recipe_drafts
    assert scenario.approved_recipe_versions
    assert approved.recipe_version_id in {
        item.recipe_version_id for item in scenario.approved_recipe_versions
    }
    assert scenario.materialized_scenario_set_id is not None

    assert host.activate_route(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS) is True
    _settle(app)
    for control in (
        "createDiagnosticTaskButton",
        "reviseDiagnosticTaskButton",
        "validateDiagnosticTaskButton",
    ):
        _press(app, host, _quick_item(root, control))
    actor = _quick_item(root, "diagnosticTaskApprovalActorInput")
    actor.forceActiveFocus()
    QTest.keyClicks(host, "issue-113-owner")
    _press(app, host, _quick_item(root, "approveDiagnosticTaskButton"))
    _press(app, host, _quick_item(root, "startDiagnosticCampaignButton"))
    _settle(app)

    running_task = context.diagnostic_tasks_feature.snapshot(
        context.diagnostic_tasks_context
    ).task
    assert running_task is not None
    context.diagnostic_tasks_feature.advance_evidence_available(
        running_task.task_id
    )
    _settle(app)
    assert host.activate_route(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS) is True
    _settle(app)
    authoritative_task = context.diagnostic_tasks_feature.snapshot(
        context.diagnostic_tasks_context
    ).task
    assert authoritative_task is not None
    diagnostic = host.journey_context.diagnostic_selection
    assert diagnostic is not None
    assert diagnostic.task_id == authoritative_task.task_id
    assert diagnostic.task_revision == authoritative_task.revision
    assert diagnostic.configuration_content_id == (
        authoritative_task.configuration.content_identity
    )
    assert diagnostic.task_handle_id == authoritative_task.task_handles[-1].identity
    assert diagnostic.campaign_id == authoritative_task.handoff.campaign_id
    assert diagnostic.campaign_revision == authoritative_task.handoff.campaign_revision
    assert diagnostic.run_id is not None

    assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING) is True
    assert host.activate_route(
        JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    ) is True
    _settle(app)
    manifest_id = authoritative_task.handoff.reproduction_manifest_id
    assert manifest_id is not None
    selected_cases = {
        item.campaign_case_id: item
        for item in authoritative_task.handoff.selected_cases
    }
    evidence_context = next(
        EvidenceAndFindingsContext.for_selection(
            EvidenceAndFindingsSelection(
                campaign_id=authoritative_task.handoff.campaign_id,
                run_id=run.run_id,
                strategy_id=run.strategy_id,
                market_scenario_id=MarketScenarioId(
                    node.campaign_case_id.value
                ),
                approved_recipe_id=ApprovedScenarioRecipeId(
                    selected_cases[
                        node.selected_campaign_case_id
                    ].recipe_version_id.value
                ),
                reproduction_manifest_id=run.reproduction_manifest_id,
            )
        )
        for node in authoritative_task.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
        if run.reproduction_manifest_id == manifest_id
    )
    context.evidence_and_findings_feature.advance_to_completed(evidence_context)
    _settle(app)
    authoritative_evidence = context.evidence_and_findings_feature.snapshot(
        evidence_context
    ).last_reliable_data
    assert authoritative_evidence is not None
    evidence = host.journey_context.evidence_selection
    assert evidence is not None
    assert evidence.evidence_package_id == (
        authoritative_evidence.evidence_package_id
    )
    assert evidence.reproduction_manifest_id == (
        authoritative_task.handoff.reproduction_manifest_id
    )
    assert evidence.evidence_id is None
    assert evidence.comparison_id is None
    assert evidence.finding_id is not None
    assert evidence.sensitivity_breakpoint_id is not None

    assert host.activate_route(JourneyWorkspaceRoute.SYSTEM_HEALTH) is True
    _wait_for(
        app,
        lambda: host.recovery_state.reason
        in {
            JourneyRecoveryReason.EXACT,
            JourneyRecoveryReason.NO_CURRENT_TASK,
        },
    )
    health = host.journey_context.diagnostic_selection
    assert health is not None
    assert health.task_id == authoritative_task.task_id
    assert health.task_handle_id == authoritative_task.task_handles[-1].identity

    _close(context, host)
    bridge.stop()


@pytest.mark.parametrize(
    ("transition", "expected"),
    (
        ("advance_context_to_missing", JourneyRecoveryReason.MISSING_IDENTITY),
        (
            "advance_context_to_superseded",
            JourneyRecoveryReason.SUPERSEDED_IDENTITY,
        ),
        (
            "advance_context_to_incompatible",
            JourneyRecoveryReason.INCOMPATIBLE_IDENTITY,
        ),
        (
            "advance_context_to_unavailable",
            JourneyRecoveryReason.UNAVAILABLE_IDENTITY,
        ),
    ),
)
def test_system_health_context_recovery_is_explicit_and_never_substitutes_identity(
    tmp_path,
    transition: str,
    expected: JourneyRecoveryReason,
) -> None:
    app = _app()
    diagnostic = JourneyDiagnosticSelection(
        task_id=DiagnosticTaskId("diagnostic-task-recovery-113"),
        task_revision=4,
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            "configuration-recovery-113"
        ),
        task_handle_id=TaskHandleId("task-handle-recovery-113"),
    )
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH,
        diagnostic_task_id=diagnostic.task_id,
        diagnostic_selection=diagnostic,
    )
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "journey_workspace_bookmark_json": (
                    encode_journey_workspace_bookmark(bookmark)
                )
            }
        ),
        encoding="utf-8",
    )
    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(context)
    host.show()
    _wait_for(
        app,
        lambda: host.recovery_state.reason is JourneyRecoveryReason.EXACT,
    )

    getattr(context.system_health_feature, transition)()
    _wait_for(app, lambda: host.recovery_state.reason is expected)

    assert host.active_route is JourneyWorkspaceRoute.SYSTEM_HEALTH
    assert host.journey_context.diagnostic_selection == diagnostic
    assert expected.value in host.recovery_state.reason.value
    assert host.recovery_state.explanation
    status = _quick_item(host.rootObject(), "journeyRecoveryStatus")
    assert status.property("visible") is True
    assert host.recovery_state.safe_route is JourneyWorkspaceRoute.SYSTEM_HEALTH

    _close(context, host)


def test_no_current_task_is_an_explicit_safe_system_health_state(tmp_path) -> None:
    app = _app()
    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
    )
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "journey_workspace_bookmark_json": (
                    encode_journey_workspace_bookmark(bookmark)
                )
            }
        ),
        encoding="utf-8",
    )
    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(context)
    host.show()
    _wait_for(
        app,
        lambda: host.recovery_state.reason
        is JourneyRecoveryReason.NO_CURRENT_TASK,
    )

    assert host.active_route is JourneyWorkspaceRoute.SYSTEM_HEALTH
    assert host.journey_context.diagnostic_selection is None
    assert "No current Diagnostic Task" in host.recovery_state.explanation
    _close(context, host)


def test_invalid_bookmark_recovery_reaches_the_public_product_surface(
    tmp_path,
) -> None:
    app = _app()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"journey_workspace_bookmark_json": '{"route":"orders"}'}),
        encoding="utf-8",
    )
    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    host = _host(
        context,
        initial_recovery_state=context.journey_workspace_restore.recovery,
    )
    host.show()
    _settle(app)

    assert host.recovery_state.reason is JourneyRecoveryReason.INVALID_BOOKMARK
    assert host.active_route is JourneyWorkspaceRoute.STRATEGY_LIBRARY
    status = _quick_item(host.rootObject(), "journeyRecoveryStatus")
    assert status.property("visible") is True
    assert "invalid" in str(status.property("text")).casefold()
    _close(context, host)
