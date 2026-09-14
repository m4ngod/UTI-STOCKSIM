"""Health and remount preserve the exact observed legacy work.

Public application advance only prepares completed evidence. The active command
uses the real embedded strategy host; no automatic scheduler is claimed here.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from app.features import (
    ApproveDiagnosticTaskConfiguration, DiagnosticActorId, ValidateDiagnosticTaskConfiguration,
    ApprovedScenarioRecipeId, DiagnosticCommandId, DiagnosticCommandIdempotencyKey,
    DiagnosticTasksContext, EvidenceAndFindingsContext, EvidenceAndFindingsSelection,
    MarketScenarioId, RunMonitoringContext, RunMonitoringSelection, StartFormalDiagnosticCampaign,
)
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.journey_recovery import JourneyWorkspaceRoute
from app.ui.accessibility import AccessibilityPreferences
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import _approved_formal_task
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import _command
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import _read_task
from tests.frontend.integration.test_research_execution_continuity import live_execution
from tests.frontend.integration.test_diagnostic_tasks_workspace_route import _authoritative_evidence_handoff
from tests.frontend.integration.test_research_resource_pages import until


@pytest.fixture
def completed_campaign_observation(live_execution):
    _, context, application, _, gate = live_execution
    gate.release.set()
    feature = context.diagnostic_tasks_feature
    approved = _approved_formal_task(feature)
    receipt = feature.start_formal_diagnostic_campaign(StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("health-member-start"),
        idempotency_key=DiagnosticCommandIdempotencyKey("health-member-start"),
        task_id=approved.task_id, expected_revision=approved.revision,
        approved_revision=approved.revision,
    ))
    assert receipt.accepted and receipt.affected_campaign_id is not None
    application.advance_diagnostic_campaign(receipt.affected_campaign_id.value,
        max_cases=64, nodes_per_batch=10_000)
    task = _read_task(feature, approved.task_id)
    node, run = next((node, run) for node in task.handoff.campaign_nodes
                    for attempt in node.attempts for run in attempt.runs
                    if run.reproduction_manifest_id is not None
                    and run.reproduction_manifest_id != task.handoff.reproduction_manifest_id)
    case = next(case for case in task.handoff.selected_cases
                if case.campaign_case_id == node.selected_campaign_case_id)
    run_context = RunMonitoringContext.for_run(RunMonitoringSelection(
        campaign_id=receipt.affected_campaign_id, run_id=run.run_id,
    ))
    evidence_context = EvidenceAndFindingsContext.for_selection(EvidenceAndFindingsSelection(
        campaign_id=receipt.affected_campaign_id, run_id=run.run_id, strategy_id=run.strategy_id,
        market_scenario_id=MarketScenarioId(node.campaign_case_id.value),
        approved_recipe_id=ApprovedScenarioRecipeId(case.recipe_version_id.value),
        reproduction_manifest_id=run.reproduction_manifest_id,
    ))
    return task, run, run_context, evidence_context


def _approve_independent_task(feature, task):
    created = feature.create_diagnostic_task(_command(task.configuration,
        command_id="exact-remount-other-create", idempotency_key="exact-remount-other-create"))
    assert created.affected_task_id is not None and created.affected_task_id != task.task_id
    other = _read_task(feature, created.affected_task_id)
    assert other is not None
    validated = feature.validate_configuration(ValidateDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId("exact-remount-other-validate"),
        idempotency_key=DiagnosticCommandIdempotencyKey("exact-remount-other-validate"),
        task_id=other.task_id, expected_revision=other.revision,
    ))
    assert validated.accepted
    other = _read_task(feature, created.affected_task_id)
    assert other is not None
    validation = other.validation
    accepted = feature.approve_configuration(ApproveDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId("exact-remount-other-approve"),
        idempotency_key=DiagnosticCommandIdempotencyKey("exact-remount-other-approve"),
        task_id=other.task_id, expected_revision=other.revision,
        validation_id=validation.validation_id, validation_revision=validation.validation_revision,
        validated_revision=validation.validated_revision,
        configuration_content_id=validation.configuration_content_identity,
        actor_id=DiagnosticActorId("wave2-release-owner"),
    ))
    assert accepted.accepted
    other = _read_task(feature, created.affected_task_id)
    assert other is not None
    return other


@pytest.mark.parametrize("size,scale", [((1426, 786), 1.0), ((960, 480), 2.0)])
def test_health_details_identify_the_exact_affected_task(live_execution, size, scale, record_property):
    app, context, _, _, _ = live_execution
    task = _approved_formal_task(context.diagnostic_tasks_feature)
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        diagnostic_tasks_feature=context.diagnostic_tasks_feature,
        diagnostic_tasks_context=DiagnosticTasksContext(task_id=task.task_id),
        system_health_feature=context.system_health_feature,
        initial_route="diagnostic_tasks", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(*size)
    host.show()
    try:
        root = host.rootObject()
        button = root.findChild(QQuickItem, "researchHealthButton")
        button.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        popup = root.findChild(QObject, "researchHealthPopup")
        until(app, lambda: task.task_id.value in popup.property("adapter").property("diagnosticIdentityText"))
        header = QAccessible.queryAccessibleInterface(button)
        assert header.role() == QAccessible.Role.Button
        header_name = header.text(QAccessible.Text.Name)
        assert header_name.startswith("只读系统状态。系统状态 · ")
        assert any(label in header_name for label in (
            "观察新鲜", "观察过期", "尚无可靠观察", "观察新旧未知",
        ))
        assert "未关联任务" not in header_name
        facts = root.findChild(QQuickItem, "researchHealthFacts")
        visible = facts.property("text")
        assert task.task_id.value in visible
        assert task.configuration.content_identity.value in visible
        accessible = QAccessible.queryAccessibleInterface(facts)
        assert accessible is not None and accessible.state().readOnly
        assert task.task_id.value in accessible.text(QAccessible.Text.Value)
        assert host.active_route.value == "diagnostic_tasks"
        record_property("logical_client", f"{host.width()}x{host.height()}")
        record_property("dpr", host.devicePixelRatioF())
        record_property("text_scale", scale)
        facts.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
            frame = host.grabFramebuffer()
            assert not frame.isNull()
            assert frame.save(str(Path(evidence_dir) / f"health-exact-scope-{host.width()}x{host.height()}-{scale}.png"))
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        assert facts.property("cursorPosition") == len(facts.property("text"))
        bottom = facts.mapToScene(facts.property("cursorRectangle").bottomRight()).y()
        assert 0 < bottom <= host.height()
        record_property("keyboard_text_end_visible", True)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        app.processEvents()
        assert not popup.property("opened") and button.hasActiveFocus()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("destination", ["run_monitoring", "evidence_and_findings"])
def test_health_impact_tracks_the_explicit_campaign_member(
    live_execution, completed_campaign_observation, destination,
):
    app, context, _, _, _ = live_execution
    feature = context.diagnostic_tasks_feature
    task, run, run_context, evidence_context = completed_campaign_observation
    task_context = DiagnosticTasksContext(task_id=task.task_id)
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature, context=run_context,
        diagnostic_tasks_feature=feature, diagnostic_tasks_context=task_context,
        evidence_feature=context.evidence_and_findings_feature, evidence_context=evidence_context,
        system_health_feature=context.system_health_feature,
        initial_route=destination, research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        root = host.rootObject()
        button = root.findChild(QQuickItem, "researchHealthButton")
        button.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        popup = root.findChild(QObject, "researchHealthPopup")
        until(app, lambda: task.task_id.value in popup.property("adapter").property("diagnosticIdentityText"))
        facts = root.findChild(QQuickItem, "researchHealthFacts")
        assert run.run_id.value in facts.property("text")
        assert host.active_route.value == destination
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_health_does_not_join_another_runs_retained_evidence(
    live_execution, completed_campaign_observation,
):
    app, context, _, _, _ = live_execution
    task, run, run_context, _ = completed_campaign_observation
    previous_evidence = _authoritative_evidence_handoff(task).context
    previous_manifest = previous_evidence.selection.reproduction_manifest_id
    assert previous_manifest is not None and previous_manifest != run.reproduction_manifest_id
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature, context=run_context,
        diagnostic_tasks_feature=context.diagnostic_tasks_feature,
        diagnostic_tasks_context=DiagnosticTasksContext(task_id=task.task_id),
        evidence_feature=context.evidence_and_findings_feature, evidence_context=previous_evidence,
        system_health_feature=context.system_health_feature,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        root = host.rootObject()
        popup = root.findChild(QObject, "researchHealthPopup")
        facts = root.findChild(QQuickItem, "researchHealthFacts")
        until(app, lambda: previous_manifest.value in popup.property("adapter").property("diagnosticIdentityText"))
        # The exact compatibility Run route remains a public typed entry.
        assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
        button = root.findChild(QQuickItem, "researchHealthButton")
        button.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        until(app, lambda: run.run_id.value in popup.property("adapter").property("diagnosticIdentityText"))
        assert previous_manifest.value not in facts.property("text")
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        app.processEvents()
        assert button.hasActiveFocus()
        assert host.activate_route(JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS)
        until(app, lambda: previous_manifest.value in popup.property("adapter").property("diagnosticIdentityText"))
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_reopening_without_a_task_selection_clears_prior_health_context(live_execution):
    app, context, _, _, _ = live_execution
    feature = context.diagnostic_tasks_feature
    task = _approved_formal_task(feature)
    hosts = []

    def open_host(task_context):
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            diagnostic_tasks_feature=feature, diagnostic_tasks_context=task_context,
            system_health_feature=context.system_health_feature,
            initial_route="diagnostic_tasks", research_shell=True,
        )
        hosts.append(host)
        host.resize(1426, 786)
        host.show()
        root = host.rootObject()
        root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        return host

    try:
        original = open_host(DiagnosticTasksContext(task_id=task.task_id))
        facts = original.rootObject().findChild(QQuickItem, "researchHealthFacts")
        until(app, lambda: task.task_id.value in facts.property("text"))
        original.close_adapter()
        original.close()
        original.deleteLater()
        hosts.remove(original)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        replacement = open_host(DiagnosticTasksContext.workspace())
        root = replacement.rootObject()
        lab = root.findChild(QQuickItem, "researchLabPage")
        popup = root.findChild(QObject, "researchHealthPopup")
        until(app, lambda: "正在读取" not in lab.property("statusText")
              and popup.property("adapter").property("phase") != "loading")
        assert root.findChild(QQuickItem, "researchLabPageList").property("count") == 0
        assert task.task_id.value not in root.findChild(QQuickItem, "researchHealthFacts").property("text")
        assert popup.property("adapter").property("diagnosticContextResolution") == "no_current_task"
    finally:
        for host in hosts:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("destination", ["run_monitoring", "evidence_and_findings"])
def test_exact_entry_remount_preserves_observation_while_other_task_runs(
    live_execution, completed_campaign_observation, destination,
):
    app, context, application, _, gate = live_execution
    feature = context.diagnostic_tasks_feature
    task, run, run_context, evidence_context = completed_campaign_observation
    task_context = DiagnosticTasksContext(task_id=task.task_id)
    # A second real, independently identified Task supplies the active command;
    # the observed Campaign above is already complete and has exact manifests.
    other = _approve_independent_task(feature, task)
    hosts = []
    worker = ThreadPoolExecutor(max_workers=1)

    def open_host():
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature, context=run_context,
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_queries=context.strategy_library_queries,
            feature_capabilities=context.feature_capabilities(),
            scenario_lab_feature=context.scenario_lab_feature,
            diagnostic_tasks_feature=feature, diagnostic_tasks_context=task_context,
            evidence_feature=context.evidence_and_findings_feature, evidence_context=evidence_context,
            system_health_feature=context.system_health_feature,
            initial_route=destination, research_shell=True,
        )
        hosts.append(host)
        host.resize(1426, 786)
        host.show()
        app.processEvents()
        return host

    try:
        original = open_host()
        root = original.rootObject()
        if destination == "run_monitoring":
            until(app, lambda: run.run_id.value in root.findChild(
                QQuickItem, "researchExistingResourceSummary").property("text"))
        else:
            page = root.findChild(QQuickItem, "researchArchivePage")
            until(app, lambda: run.run_id.value in page.property("adapter").property("pinnedIdentitiesText"))
        original.close_adapter()
        original.close()
        original.deleteLater()
        hosts.remove(original)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        gate.entered.clear()
        gate.release.clear()
        gate.expired.clear()
        pending = worker.submit(feature.start_formal_diagnostic_campaign, StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("exact-remount-other-start"),
            idempotency_key=DiagnosticCommandIdempotencyKey("exact-remount-other-start"),
            task_id=other.task_id, expected_revision=other.revision, approved_revision=other.revision,
        ))
        until(app, gate.entered.is_set)
        assert not pending.done()
        replacement = open_host()
        assert not pending.done() and not gate.expired.is_set(), (
            "Exact entry remount waited for another task's calculation")
        if destination == "run_monitoring":
            assert run.run_id.value in replacement.rootObject().findChild(
                QQuickItem, "researchExistingResourceSummary").property("text")
        else:
            selected = replacement.rootObject().findChild(QQuickItem, "researchArchivePage")
            pinned = selected.property("adapter").property("pinnedIdentitiesText")
            assert run.run_id.value in pinned and run.reproduction_manifest_id.value in pinned
        health = replacement.rootObject().findChild(QQuickItem, "researchHealthButton")
        health.forceActiveFocus()
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Space)
        app.processEvents()
        assert replacement.rootObject().findChild(QObject, "researchHealthPopup").property("opened")
        QTest.keyClick(replacement.quickWindow(), Qt.Key.Key_Escape)
        app.processEvents()
        assert health.hasActiveFocus() and not pending.done()
        gate.release.set()
        until(app, pending.done)
        result = pending.result()
        assert result.accepted and result.affected_campaign_id is not None
        assert result.affected_campaign_id != task.handoff.campaign_id
        assert application.diagnostic_campaign_status(result.affected_campaign_id.value).completed_count == 1
        if destination == "run_monitoring":
            summary = replacement.rootObject().findChild(QQuickItem, "researchExistingResourceSummary")
            until(app, lambda: "completed" in summary.property("text"))
            assert run.run_id.value in summary.property("text")
        else:
            until(app, lambda: replacement.journey_context.evidence_selection is not None)
            assert replacement.journey_context.evidence_selection.reproduction_manifest_id == run.reproduction_manifest_id
    finally:
        gate.release.set()
        worker.shutdown(wait=True)
        for host in hosts:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("destination", ["run_monitoring", "evidence_and_findings"])
def test_health_clears_an_unrelated_campaign_association(
    live_execution, completed_campaign_observation, destination,
):
    app, context, _, _, _ = live_execution
    feature = context.diagnostic_tasks_feature
    task, run, run_context, evidence_context = completed_campaign_observation
    other = _approve_independent_task(feature, task)
    started = feature.start_formal_diagnostic_campaign(StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("unrelated-start"),
        idempotency_key=DiagnosticCommandIdempotencyKey("unrelated-start"),
        task_id=other.task_id, expected_revision=other.revision, approved_revision=other.revision,
    ))
    assert started.accepted and started.affected_campaign_id is not None
    assert started.affected_campaign_id != task.handoff.campaign_id
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature, context=run_context,
        diagnostic_tasks_feature=feature,
        diagnostic_tasks_context=DiagnosticTasksContext(task_id=other.task_id),
        evidence_feature=context.evidence_and_findings_feature, evidence_context=evidence_context,
        system_health_feature=context.system_health_feature,
        initial_route="diagnostic_tasks", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        root = host.rootObject()
        popup = root.findChild(QObject, "researchHealthPopup")
        facts = root.findChild(QQuickItem, "researchHealthFacts")
        until(app, lambda: other.task_id.value in facts.property("text"))
        assert host.activate_route(JourneyWorkspaceRoute(destination))
        root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        until(app, lambda: popup.property("adapter").property("phase") != "loading")
        assert other.task_id.value not in facts.property("text")
        assert "未关联任务" in facts.property("text")
        assert popup.property("adapter").property("diagnosticContextResolution") == "no_current_task"
        assert host.active_route.value == destination
        if destination == "run_monitoring":
            summary = root.findChild(QQuickItem, "researchExistingResourceSummary")
            until(app, lambda: run.run_id.value in summary.property("text"))
        else:
            until(app, lambda: host.journey_context.evidence_selection is not None)
            assert host.journey_context.evidence_selection.reproduction_manifest_id == run.reproduction_manifest_id
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        assert host.activate_route(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS)
        until(app, lambda: other.task_id.value in facts.property("text"))
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
