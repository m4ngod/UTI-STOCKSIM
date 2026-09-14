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

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DiagnosticCommandId, DiagnosticCommandIdempotencyKey, DiagnosticTaskLifecycle,
    DiagnosticTasksContext, LiveStrategyDiagnosticsV1ApplicationAdapter,
    StartFormalDiagnosticCampaign,
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


@pytest.mark.parametrize("destination,navigation_name", [
    (JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS, "evidenceAndFindingsRouteNavigation"),
    (JourneyWorkspaceRoute.STRATEGY_LIBRARY, "strategyLibraryRouteNavigation"),
    (JourneyWorkspaceRoute.SCENARIO_LAB, "scenarioLabRouteNavigation"),
])
def test_real_start_completes_after_page_switch_health_overlay_and_view_disposal(
    tmp_path, monkeypatch, record_property, destination, navigation_name,
):
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
        pending = worker.submit(feature.start_formal_diagnostic_campaign,
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("research-continuity-start"),
                idempotency_key=DiagnosticCommandIdempotencyKey("research-continuity-start"),
                task_id=approved.task_id, expected_revision=approved.revision,
                approved_revision=approved.revision,
            ))
        until(app, gate.entered.is_set)
        assert not pending.done()
        root = host.rootObject()
        navigation = root.findChild(QQuickItem, navigation_name)
        navigation.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        app.processEvents()
        assert host.active_route is destination
        assert not pending.done(), "Page navigation waited for or interrupted execution"
        if destination is JourneyWorkspaceRoute.SCENARIO_LAB:
            page = root.findChild(QQuickItem, "researchScenarioPage")
            assert "正在读取场景资源" in page.property("statusText")
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
        context.close()
        auxiliary.close()
        bridge.stop()
        engine.dispose()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
