"""Real in-flight computation is not owned by a research page observation.

The caller thread controls when a public command is submitted; it is not evidence
of a new automatic Experiment scheduler. A gate at the strategy-host boundary
holds a real embedded invocation, then delegates its actual calculation.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId, EvidenceAndFindingsContext, EvidenceAndFindingsSelection,
    DiagnosticCommandId, DiagnosticCommandIdempotencyKey, DiagnosticTaskLifecycle,
    DiagnosticTasksContext, LiveStrategyDiagnosticsV1ApplicationAdapter,
    MarketScenarioId, RunMonitoringContext, RunMonitoringSelection, StartFormalDiagnosticCampaign,
)
from app.journey_recovery import JourneyWorkspaceRoute
from app.ui.journey_workspace import JourneyWorkspaceHost
from strategy_diagnostics import EmbeddedProductionPTradeStrategyHost
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task, _formal_live_stack,
)
from tests.frontend.integration.test_research_resource_pages import until


class HeldEmbeddedInvocation:
    """Delay one external host invocation, without replacing its computation."""

    def __init__(self):
        self.entered = Event()
        self.release = Event()
        self.expired = Event()
        self.delegate = EmbeddedProductionPTradeStrategyHost()

    @property
    def adapter_version(self):
        return self.delegate.adapter_version

    def invoke(self, invocation):
        if invocation.event == "decision" and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(10):
                self.expired.set()
                raise RuntimeError("The test failed to release the held strategy invocation")
        return self.delegate.invoke(invocation)


@pytest.fixture
def live_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    gate = HeldEmbeddedInvocation()
    _, _, engine, application, _, auxiliary = _formal_live_stack(tmp_path, ptrade_host=gate)
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"), run_monitoring_mode="live",
        strategy_diagnostics_application=application,
        strategy_diagnostics_read_model=LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine),
        event_bridge=bridge, system_health_sampling_interval=None,
    )
    try:
        yield app, context, application, engine, gate
    finally:
        gate.release.set()
        context.close()
        auxiliary.close()
        bridge.stop()
        engine.dispose()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("destination", ["run_monitoring", "evidence_and_findings"])
@pytest.mark.parametrize("explicit_member", [True, False])
def test_hidden_task_initial_read_preserves_explicit_or_recovers_missing_observation(
    live_execution, destination, explicit_member,
):
    app, context, application, _, gate = live_execution
    gate.release.set()
    feature = context.diagnostic_tasks_feature
    approved = _approved_formal_task(feature)
    receipt = feature.start_formal_diagnostic_campaign(StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("exact-member-start"),
        idempotency_key=DiagnosticCommandIdempotencyKey("exact-member-start"),
        task_id=approved.task_id, expected_revision=approved.revision,
        approved_revision=approved.revision,
    ))
    assert receipt.accepted and receipt.affected_campaign_id is not None
    # Prepare persisted records through the application API. This explicit test
    # setup is not evidence of an automatic campaign scheduler.
    application.advance_diagnostic_campaign(
        receipt.affected_campaign_id.value, max_cases=64, nodes_per_batch=10_000,
    )
    selected_task = DiagnosticTasksContext(task_id=approved.task_id)
    task = feature.snapshot(selected_task).task
    assert task is not None and task.handoff.ready_for_evidence_and_findings
    # A different completed member of the SAME campaign is a legal exact
    # observation, even when the task's default handoff points elsewhere.
    node, run = next(
        (node, run)
        for node in task.handoff.campaign_nodes
        for attempt in node.attempts if attempt.attempt_id == node.active_attempt_id
        for run in attempt.runs
        if run.reproduction_manifest_id is not None
        and (run.reproduction_manifest_id != task.handoff.reproduction_manifest_id) is explicit_member
    )
    selected_case = next(case for case in task.handoff.selected_cases
                         if case.campaign_case_id == node.selected_campaign_case_id)
    run_context = RunMonitoringContext.for_run(RunMonitoringSelection(
        campaign_id=receipt.affected_campaign_id, run_id=run.run_id,
    ))
    evidence_context = EvidenceAndFindingsContext.for_selection(EvidenceAndFindingsSelection(
        campaign_id=receipt.affected_campaign_id, run_id=run.run_id,
        strategy_id=run.strategy_id, market_scenario_id=MarketScenarioId(node.campaign_case_id.value),
        approved_recipe_id=ApprovedScenarioRecipeId(selected_case.recipe_version_id.value),
        reproduction_manifest_id=run.reproduction_manifest_id,
    ))
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        context=run_context if explicit_member else RunMonitoringContext.no_selection(),
        diagnostic_tasks_feature=feature, diagnostic_tasks_context=selected_task,
        evidence_feature=context.evidence_and_findings_feature,
        evidence_context=evidence_context if explicit_member else EvidenceAndFindingsContext.no_selection(),
        initial_route=destination, research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        root = host.rootObject()
        lab = root.findChild(QQuickItem, "researchLabPage")
        lab_list = root.findChild(QQuickItem, "researchLabPageList")
        until(app, lambda: lab_list.property("count") > 0
              and "正在读取" not in lab.property("statusText"))
        assert host.active_route.value == destination
        if destination == "run_monitoring":
            summary = root.findChild(QQuickItem, "researchExistingResourceSummary")
            assert run.run_id.value in summary.property("text")
        else:
            catalog = root.findChild(QQuickItem, "researchArchivePageList")
            until(app, lambda: catalog.property("count") > 0)
            catalog.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
            details = root.findChild(QQuickItem, "researchArchivePageDetails").property("text")
            assert run.run_id.value in details
            until(app, lambda: host.journey_context.evidence_selection is not None)
            assert host.journey_context.evidence_selection.reproduction_manifest_id == run.reproduction_manifest_id
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("destination,navigation_name,warm_scenario", [
    (JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS, "evidenceAndFindingsRouteNavigation", False),
    (JourneyWorkspaceRoute.STRATEGY_LIBRARY, "strategyLibraryRouteNavigation", False),
    (JourneyWorkspaceRoute.SCENARIO_LAB, "scenarioLabRouteNavigation", False),
    (JourneyWorkspaceRoute.SCENARIO_LAB, "scenarioLabRouteNavigation", True),
])
def test_real_start_completes_after_page_switch_health_overlay_and_view_disposal(
    live_execution, record_property, destination, navigation_name, warm_scenario,
):
    app, context, application, _, gate = live_execution
    host = probe = None
    worker = ThreadPoolExecutor(max_workers=1)
    try:
        feature = context.diagnostic_tasks_feature
        approved = _approved_formal_task(feature)
        selected = DiagnosticTasksContext(task_id=approved.task_id)
        observed = []
        probe = feature.subscribe(selected, observed.append)
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_queries=context.strategy_library_queries,
            feature_capabilities=context.feature_capabilities(),
            scenario_lab_feature=context.scenario_lab_feature,
            diagnostic_tasks_feature=feature, diagnostic_tasks_context=selected,
            evidence_feature=context.evidence_and_findings_feature,
            system_health_feature=context.system_health_feature,
            initial_route="diagnostic_tasks", research_shell=True,
        )
        host.resize(1426, 786)
        host.show()
        app.processEvents()
        root = host.rootObject()
        previous_details = None
        if warm_scenario:
            # A deliberate previously observed resource, not a cold-start probe.
            assert host.activate_route(JourneyWorkspaceRoute.SCENARIO_LAB)
            catalog = root.findChild(QQuickItem, "researchScenarioPageList")
            page = root.findChild(QQuickItem, "researchScenarioPage")
            until(app, lambda: catalog.property("count") > 0
                  and "正在读取" not in page.property("statusText"))
            catalog.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
            previous_details = root.findChild(QQuickItem, "researchScenarioPageDetails").property("text")
            assert previous_details
            assert host.activate_route(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS)
        pending = worker.submit(feature.start_formal_diagnostic_campaign,
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("research-continuity-start"),
                idempotency_key=DiagnosticCommandIdempotencyKey("research-continuity-start"),
                task_id=approved.task_id, expected_revision=approved.revision,
                approved_revision=approved.revision,
            ))
        until(app, gate.entered.is_set)
        assert not pending.done()
        navigation = root.findChild(QQuickItem, navigation_name)
        navigation.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        app.processEvents()
        assert host.active_route is destination
        assert not pending.done(), "Page navigation waited for or interrupted execution"
        if destination is JourneyWorkspaceRoute.SCENARIO_LAB:
            page = root.findChild(QQuickItem, "researchScenarioPage")
            assert "正在读取场景资源" in page.property("statusText")
            if warm_scenario:
                assert "stale" in page.property("statusText")
                assert root.findChild(QQuickItem, "researchScenarioPageDetails").property("text") == previous_details
        health = root.findChild(QQuickItem, "researchHealthButton")
        health.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        app.processEvents()
        assert root.findChild(QObject, "researchHealthPopup").property("opened")
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        app.processEvents()
        assert health.hasActiveFocus()
        host.close_adapter()
        host.close()
        assert not pending.done()
        assert not gate.expired.is_set()
        assert not probe.disposed, "Disposing the view must not close the application Feature"

        gate.release.set()
        until(app, pending.done)
        accepted = pending.result()
        assert accepted.accepted and accepted.affected_task_id == approved.task_id
        assert accepted.affected_campaign_id is not None
        state = feature.snapshot(selected)
        assert state.task is not None
        assert state.task.task_id == approved.task_id
        assert state.task.lifecycle is DiagnosticTaskLifecycle.RUNNING
        assert state.task.handoff.campaign_id == accepted.affected_campaign_id
        assert observed[-1] == state
        campaign = application.diagnostic_campaign_status(accepted.affected_campaign_id.value)
        assert campaign.completed_count == 1
        completed = [case for case in campaign.cases if case.status == "completed"]
        assert len(completed) == 1 and completed[0].attempts
        members = completed[0].attempts[-1].to_dict()["members"]
        assert members
        for member in members:
            run = application.strategy_run_status(str(member["run_id"]))
            assert run.ptrade_audit is not None
            assert run.ptrade_audit.host_adapter_versions == (gate.adapter_version,)
        record_property("campaign_id", accepted.affected_campaign_id.value)
        record_property("completed_real_cases", 1)
        record_property("host_adapter_version", gate.adapter_version)
        record_property("input_configuration", approved.configuration.content_identity.value)
    finally:
        gate.release.set()
        worker.shutdown(wait=True)
        if probe is not None:
            probe.dispose()
        if host is not None:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_cold_scenario_wait_does_not_claim_a_reliable_previous_observation(live_execution):
    app, context, _, engine, _ = live_execution
    entered, release, expired = Event(), Event(), Event()
    host = None

    def hold_database_read(connection, cursor, statement, parameters, execution_context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            entered.set()
            if not release.wait(10):
                expired.set()
                raise RuntimeError("The test failed to release the held initial inventory read")

    event.listen(engine, "before_cursor_execute", hold_database_read)
    try:
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            scenario_lab_feature=context.scenario_lab_feature,
            initial_route="scenario_lab", research_shell=True,
        )
        host.resize(1426, 786)
        host.show()
        page = host.rootObject().findChild(QQuickItem, "researchScenarioPage")
        catalog = host.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        # The exposed source generation becomes available only after the typed
        # first (loading) observation has reached the QML page.
        until(app, lambda: entered.is_set()
              and page.property("adapter").property("sourceGeneration") is not None)
        assert not expired.is_set()
        assert catalog.property("count") == 0
        assert "正在读取场景资源" in page.property("statusText")
        assert "保留上次有效观察" not in page.property("statusText")
        release.set()
        until(app, lambda: catalog.property("count") > 0
              and "正在读取" not in page.property("statusText"))
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", hold_database_read)
        if host is not None:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_scenario_database_read_failure_ends_waiting_and_preserves_stale_content(live_execution):
    app, context, _, engine, _ = live_execution
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        initial_route="scenario_lab", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    fault_installed = False

    def fail_database_read(connection, cursor, statement, parameters, execution_context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            raise OperationalError(statement, parameters, RuntimeError("private-database-location"))

    try:
        root = host.rootObject()
        page = root.findChild(QQuickItem, "researchScenarioPage")
        catalog = root.findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0 and "正在读取" not in page.property("statusText"))
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = root.findChild(QQuickItem, "researchScenarioPageDetails")
        previous = details.property("text")
        assert previous
        assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
        event.listen(engine, "before_cursor_execute", fail_database_read)
        fault_installed = True
        assert host.activate_route(JourneyWorkspaceRoute.SCENARIO_LAB)
        until(app, lambda: "场景资源观察暂不可用" in page.property("statusText"))
        assert "正在读取" not in page.property("statusText")
        assert "stale" in page.property("statusText")
        assert "private-database-location" not in page.property("statusText")
        assert details.property("text") == previous
        event.remove(engine, "before_cursor_execute", fail_database_read)
        fault_installed = False
        assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
        assert host.activate_route(JourneyWorkspaceRoute.SCENARIO_LAB)
        until(app, lambda: "fresh" in page.property("statusText")
              and "正在读取" not in page.property("statusText")
              and "暂不可用" not in page.property("statusText"))
        assert details.property("text") == previous
    finally:
        if fault_installed:
            event.remove(engine, "before_cursor_execute", fail_database_read)
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("all_features", [False, True])
def test_research_view_remount_is_responsive_during_real_computation(live_execution, all_features):
    app, context, application, _, gate = live_execution
    feature = context.diagnostic_tasks_feature
    approved = _approved_formal_task(feature)
    hosts = []
    worker = ThreadPoolExecutor(max_workers=1)

    def open_scenario():
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            strategy_library_feature=context.strategy_library_feature if all_features else None,
            strategy_library_queries=context.strategy_library_queries if all_features else None,
            feature_capabilities=context.feature_capabilities() if all_features else None,
            scenario_lab_feature=context.scenario_lab_feature,
            diagnostic_tasks_feature=feature if all_features else None,
            diagnostic_tasks_context=DiagnosticTasksContext(task_id=approved.task_id) if all_features else None,
            evidence_feature=context.evidence_and_findings_feature if all_features else None,
            system_health_feature=context.system_health_feature,
            initial_route="scenario_lab", research_shell=True,
        )
        hosts.append(host)
        host.resize(1426, 786)
        host.show()
        app.processEvents()
        return host

    try:
        original = open_scenario()
        catalog = original.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0)
        original.close_adapter()
        original.close()
        original.deleteLater()
        hosts.remove(original)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        pending = worker.submit(feature.start_formal_diagnostic_campaign,
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("scenario-remount-start"),
                idempotency_key=DiagnosticCommandIdempotencyKey("scenario-remount-start"),
                task_id=approved.task_id, expected_revision=approved.revision,
                approved_revision=approved.revision,
            ))
        until(app, gate.entered.is_set)
        assert not pending.done()
        replacement = open_scenario()
        assert not pending.done() and not gate.expired.is_set(), (
            "Reopening Scenario waited for the active calculation")
        page = replacement.rootObject().findChild(QQuickItem, "researchScenarioPage")
        assert "正在读取场景资源" in page.property("statusText")
        health = replacement.rootObject().findChild(QQuickItem, "researchHealthButton")
        health.forceActiveFocus()
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Space)
        app.processEvents()
        assert replacement.rootObject().findChild(QObject, "researchHealthPopup").property("opened")
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Escape)
        app.processEvents()
        assert health.hasActiveFocus()
        assert not pending.done()
        gate.release.set()
        until(app, pending.done)
        receipt = pending.result()
        assert receipt.accepted and receipt.affected_task_id == approved.task_id
        assert receipt.affected_campaign_id is not None
        assert application.diagnostic_campaign_status(receipt.affected_campaign_id.value).completed_count == 1
        catalog = replacement.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0
              and "正在读取" not in page.property("statusText"))
        catalog.forceActiveFocus()
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Return)
        assert replacement.rootObject().findChild(QQuickItem, "researchScenarioPageDetails").property("text")
    finally:
        gate.release.set()
        worker.shutdown(wait=True)
        for host in hosts:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
