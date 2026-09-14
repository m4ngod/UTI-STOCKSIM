"""Research pages observe AppContext resources through real QML input."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QAccessible, QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DiagnosticEvidencePackageId, DiagnosticTasksContext, FormalDiagnosticCampaignId,
    LiveStrategyDiagnosticsV1ApplicationAdapter, ReproductionManifestId, StrategyRunId, V1JourneySelector,
)
from app.features.scenario_lab_application import (
    CreateScenarioRecipeDraftCommand, ScenarioLabActorId, ScenarioRecipeAuthoringMode,
)
from app.features.evidence_and_findings import EvidenceAndFindingsPresentationState
from app.features.run_monitoring import Completeness, StructuredFeatureError, ViewPhase
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.accessibility import AccessibilityPreferences
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _formal_live_stack,
)
from tests.frontend.contract.test_scenario_lab_live_fake_conformance import (
    _authoring_metadata, _authoring_payload, _canonicalize_authoring,
)
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import _command, _configuration
from tests.frontend.integration.test_evidence_and_findings_route import _context as exact_evidence_context
from tests.frontend.contract.test_strategy_diagnostics_v1_evidence_and_findings_live_contract import (
    _persist_real_formal_v1_through_application,
)


def until(app, predicate):
    deadline = monotonic() + 8
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        # Let Python-backed live reads run while keeping Qt delivery responsive.
        # QTest.qWait alone starved the full sealed-evidence reader in this lane.
        sleep(0.01)
    raise AssertionError("The public resource projection did not become available")


def visible_item(root, name):
    """QML delegates may have visual parents outside QObject ownership traversal."""
    if root.objectName() == name:
        return root
    for child in root.childItems():
        if found := visible_item(child, name):
            return found
    return None


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
def test_focused_wide_source_reflows_into_visible_details(resource_context):
    app, context = resource_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
    )
    host.resize(2600, 1400)
    host.show()
    QTest.qWait(40)
    try:
        catalog = host.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        source = host.rootObject().findChild(QQuickItem, "researchScenarioPageEvidence")
        until(app, source.isVisible)
        original_source = source.property("text")
        source.forceActiveFocus()
        host.resize(960, 480)
        QTest.qWait(40)
        details = host.rootObject().findChild(QQuickItem, "researchScenarioPageDetails")
        assert not source.isVisible()
        assert details.hasActiveFocus() and details.isVisible()
        assert original_source.removeprefix("精确来源\n\n") in details.property("text")
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture(params=["live", "fake"])
def resource_context(request, tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    engine = auxiliary_feature = application = None
    if request.param == "live":
        _, _, engine, application, _, auxiliary_feature = _formal_live_stack(tmp_path)
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode=request.param,
        strategy_diagnostics_application=application,
        strategy_diagnostics_read_model=(
            LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine)
            if application is not None else None
        ),
        event_bridge=bridge,
        system_health_sampling_interval=None,
    )
    try:
        until(app, lambda: bool(context.scenario_lab_feature.snapshot(
            context.scenario_lab_context).historical_segments))
        ready = context.scenario_lab_feature.snapshot(context.scenario_lab_context)
        created = context.scenario_lab_feature.create_recipe_draft(_canonicalize_authoring(
            CreateScenarioRecipeDraftCommand(
                metadata=_authoring_metadata(ready, suffix="research-resource"),
                payload=_authoring_payload(ready),
                author_id=ScenarioLabActorId("researcher"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        ))
        assert created.draft is not None, created.receipt
        yield app, context
    finally:
        context.close()
        bridge.stop()
        if auxiliary_feature is not None:
            auxiliary_feature.close()
        if engine is not None:
            engine.dispose()
        app.processEvents()


def test_scenario_page_keyboard_reads_exact_legacy_resource_and_explains_type(resource_context):
    app, context = resource_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        until(app, lambda: bool(context.scenario_lab_feature.snapshot(
            context.scenario_lab_context).market_scenarios))
        expected = context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios[0]
        catalog = host.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        assert catalog is not None and catalog.isVisible()
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        QTest.qWait(30)
        details = host.rootObject().findChild(QQuickItem, "researchScenarioPageDetails")
        assert details.isVisible() and details.property("readOnly") is True
        assert details.hasActiveFocus()
        text = details.property("text")
        assert expected.scenario_id.value in text
        assert expected.recipe_version_id.value in text
        assert expected.recipe_content_hash in text
        assert "类型未确认" in text and "兼容只读" in text
        assert "平行场景" not in text
        assert context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios[0] == expected
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["live"], indirect=True)
@pytest.mark.parametrize("kind", ["approved", "draft"])
def test_scenario_page_distinguishes_approved_versions_from_legacy_draft_recovery(resource_context, kind):
    app, context = resource_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        until(app, lambda: bool(context.scenario_lab_feature.snapshot(
            context.scenario_lab_context).approved_recipe_versions))
        state = context.scenario_lab_feature.snapshot(context.scenario_lab_context)
        catalog = host.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        expected_count = len(state.market_scenarios) + len(state.approved_recipe_versions) + len(state.recipe_drafts)
        # A reliable Feature read does not imply queued delivery reached the QML
        # catalogue. Observe the public page projection as on other pages.
        until(app, lambda: catalog.property("count") == expected_count)
        assert catalog.property("count") == expected_count
        offset = len(state.market_scenarios)
        if kind == "draft":
            offset += len(state.approved_recipe_versions)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        for _ in range(offset):
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = host.rootObject().findChild(QQuickItem, "researchScenarioPageDetails").property("text")
        if kind == "approved":
            version = state.approved_recipe_versions[0]
            assert version.recipe_version_id.value in details
            assert version.content_hash in details
            assert version.approval.approval_id.value in details
            assert "已批准版本" in details
        else:
            draft = state.recipe_drafts[0]
            assert draft.draft_id.value in details
            assert draft.payload_hash in details
            assert "恢复资料，不是正式场景" in details
        observed = context.scenario_lab_feature.snapshot(context.scenario_lab_context)
        assert observed.approved_recipe_versions == state.approved_recipe_versions
        assert observed.recipe_drafts == state.recipe_drafts
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_lab_reads_the_explicit_persisted_task_without_creating_an_experiment(resource_context):
    app, context = resource_context
    feature = context.diagnostic_tasks_feature
    until(app, lambda: feature.snapshot(DiagnosticTasksContext.workspace()).last_reliable_inventory is not None)
    inventory = feature.snapshot(DiagnosticTasksContext.workspace()).last_reliable_inventory
    created = feature.create_diagnostic_task(_command(
        _configuration(inventory), command_id="research-task-create", idempotency_key="research-task-create",
    ))
    assert created.affected_task_id is not None, created
    task_context = DiagnosticTasksContext(task_id=created.affected_task_id)
    until(app, lambda: feature.snapshot(task_context).task is not None)
    expected = feature.snapshot(task_context).task
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        diagnostic_tasks_feature=feature, diagnostic_tasks_context=task_context,
        initial_route="diagnostic_tasks", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        app.processEvents()
        page = host.rootObject().findChild(QQuickItem, "researchLabPage")
        assert page is not None and page.isVisible()
        catalog = host.rootObject().findChild(QQuickItem, "researchLabPageList")
        until(app, lambda: catalog.property("count") == 1)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = host.rootObject().findChild(QQuickItem, "researchLabPageDetails").property("text")
        assert expected.task_id.value in details
        assert expected.configuration.content_identity.value in details
        assert expected.lifecycle.value in details
        assert "旧任务兼容" in details
        assert "不自动创建实验" in details
        assert feature.snapshot(task_context).task == expected
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
def test_archive_drills_into_original_evidence_with_values_and_provenance(resource_context):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    feature.advance_to_completed(selection)
    expected = feature.snapshot(selection).last_reliable_data
    assert expected is not None
    candidate = expected.candidates[0]
    record = candidate.evidence[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        app.processEvents()
        page = host.rootObject().findChild(QQuickItem, "researchArchivePage")
        assert page is not None and page.isVisible()
        catalog = host.rootObject().findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        text = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails").property("text")
        assert expected.evidence_package_id.value in text
        assert candidate.identity.value in text
        assert record.identity.value in text
        assert f"{record.value} {record.unit}" in text
        assert candidate.provenance.artifact_hashes[0] in text
        assert "旧证据兼容" in text and "跨实验统计尚未接入" in text
        assert feature.snapshot(selection).last_reliable_data == expected
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
def test_archive_clears_old_details_when_the_exact_reference_becomes_invalid(resource_context):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready = feature.advance_to_completed(selection)
    record = ready.last_reliable_data.candidates[0].evidence[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        catalog = host.rootObject().findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails")
        assert record.identity.value in details.property("text")
        failure = replace(
            ready, revision=ready.revision + 1, phase=ViewPhase.FAILED,
            presentation=EvidenceAndFindingsPresentationState.FAILED,
            last_reliable_data=None, completeness=Completeness.UNKNOWN,
            error=StructuredFeatureError(
                code="evidence_reference_missing", message="所选精确证据引用已失效。", retryable=False,
            ),
        )
        feature.replay_scripted_state(selection, failure)
        until(app, lambda: catalog.property("count") == 0)
        assert record.identity.value not in details.property("text")
        assert "所选精确证据引用已失效" in details.property("text")
        assert "当前没有可读取的资源" not in details.property("text")
        assert "尚未选择旧运行的证据" not in details.property("text")
        page = host.rootObject().findChild(QQuickItem, "researchArchivePage")
        assert failure.error.message in page.property("statusText")
        assert details.hasActiveFocus()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
def test_archive_reads_preserved_comparison_without_recalculating_results(resource_context):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready = feature.advance_to_completed(selection).last_reliable_data
    candidate = ready.candidates[0]
    comparison = candidate.comparisons[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        catalog = host.rootObject().findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        for _ in candidate.evidence:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails")
        text = details.property("text")
        assert comparison.identity.value in text
        assert comparison.reference_evidence_id.value in text
        assert comparison.observed_evidence_id.value in text
        assert comparison.interpretation in text
        assert ready.evidence_package_id.value in text
        assert "旧证据兼容 · 原始比较" in text
        assert feature.snapshot(selection).last_reliable_data == ready
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
def test_archive_retains_same_identity_during_disconnection_and_updates_after_recovery(resource_context):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready = feature.advance_to_completed(selection)
    record = ready.last_reliable_data.candidates[0].evidence[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        catalog = host.rootObject().findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails")
        original_text = details.property("text")
        disconnected = feature.advance_to_disconnected(selection)
        page = host.rootObject().findChild(QQuickItem, "researchArchivePage")
        until(app, lambda: disconnected.error.message in page.property("statusText"))
        assert details.property("text") == original_text
        assert details.hasActiveFocus()
        assert record.identity.value in original_text
        partial = feature.advance_to_partial(selection)
        until(app, lambda: partial.error.message in page.property("statusText"))
        assert record.identity.value in details.property("text")
        assert "可用性: partial" in details.property("text")
        feature.advance_to_completed(selection)
        until(app, lambda: "可用性: complete" in details.property("text"))
        assert details.property("text") == original_text
        assert details.hasActiveFocus()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
@pytest.mark.parametrize("size,scale", [((1426, 786), 1.0), ((960, 480), 2.0)])
@pytest.mark.parametrize("kind", ["comparison", "finding", "cross_candidate"])
def test_archive_relation_drilldown_returns_to_exact_parent_with_keyboard(
    resource_context, size, scale, kind, record_property,
):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready_state = feature.advance_to_completed(selection)
    ready = ready_state.last_reliable_data
    candidate = ready.candidates[0]
    comparison = candidate.comparisons[0]
    if kind == "cross_candidate":
        comparison = replace(comparison, reference_evidence_id=ready.candidates[1].evidence[0].identity)
        candidate = replace(candidate, comparisons=(comparison, *candidate.comparisons[1:]))
        ready = replace(ready, candidates=(candidate, *ready.candidates[1:]))
        feature.replay_scripted_state(selection, replace(
            ready_state, revision=ready_state.revision + 1, last_reliable_data=ready))
    finding = candidate.findings[0]
    reference = next(item for owner in ready.candidates for item in owner.evidence
                     if item.identity == comparison.reference_evidence_id)
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(*size)
    host.show()
    try:
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        if size[0] == 960:
            root.findChild(QQuickItem, "researchArchivePageListButton").forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        for _ in candidate.evidence:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        if kind == "finding":
            for _ in candidate.comparisons:
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = root.findChild(QQuickItem, "researchArchivePageDetails")
        if kind == "finding":
            assert finding.identity.value in details.property("text")
            assert finding.disposition.value in details.property("text")
            assert finding.failure_reason in details.property("text")
            assert finding.sensitivity_breakpoints[0].threshold in details.property("text")
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        assert comparison.identity.value in details.property("text")
        app.processEvents()
        link = visible_item(root, "researchArchivePageLink0")
        assert link is not None and link.isEnabled()
        details.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        QTest.qWait(20)
        assert link.hasActiveFocus()
        interface = QAccessible.queryAccessibleInterface(link)
        assert interface is not None and interface.isValid()
        assert reference.identity.value in interface.text(QAccessible.Text.Name)
        assert interface.role() == QAccessible.Role.Button
        assert interface.state().focusable and not interface.state().disabled
        bounds = link.mapRectToScene(link.boundingRect())
        assert bounds.top() >= 0 and bounds.bottom() <= host.height()
        if size[0] == 1426:
            host.resize(1426, 480)
            QTest.qWait(30)
            bounds = link.mapRectToScene(link.boundingRect())
            assert link.hasActiveFocus()
            assert bounds.top() >= 0 and bounds.bottom() <= host.height()
            host.resize(*size)
            QTest.qWait(30)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        assert reference.identity.value in details.property("text")
        assert f"原值: {reference.value} {reference.unit}" in details.property("text")
        back = root.findChild(QQuickItem, "researchArchivePageBack")
        assert back is not None and back.isVisible()
        back.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        assert comparison.identity.value in details.property("text")
        assert details.hasActiveFocus()
        if kind == "finding":
            back.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            assert finding.identity.value in details.property("text")
            assert details.hasActiveFocus()
        assert not back.isVisible()
        if kind == "finding":
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(20)
            assert details.property("cursorPosition") == len(details.property("text"))
            cursor = details.mapRectToScene(details.property("cursorRectangle"))
            assert cursor.top() >= 0 and cursor.bottom() <= host.height()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(20)
            cursor = details.mapRectToScene(details.property("cursorRectangle"))
            assert cursor.top() >= 0 and cursor.bottom() <= host.height()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
            if size[0] == 960:
                root.findChild(QQuickItem, "researchArchivePageListButton").forceActiveFocus()
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            catalog.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
            offset = len(candidate.evidence) + len(candidate.comparisons) + len(candidate.findings)
            next_candidate = ready.candidates[1]
            offset += len(next_candidate.evidence) + len(next_candidate.comparisons)
            for _ in range(offset):
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
            QTest.qWait(30)
            assert next_candidate.findings[0].identity.value in details.property("text")
            cursor = details.mapRectToScene(details.property("cursorRectangle"))
            assert details.property("cursorPosition") == 0
            assert cursor.top() >= 0 and cursor.bottom() <= host.height()
        assert feature.snapshot(selection).last_reliable_data == ready
        record_property("logical_client", f"{host.width()}x{host.height()}")
        record_property("dpr", host.devicePixelRatioF())
        record_property("text_scale", scale)
        record_property("evidence_package", ready.evidence_package_id.value)
        if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
            QTest.qWait(30)
            destination = Path(evidence_dir)
            destination.mkdir(parents=True, exist_ok=True)
            assert host.grabFramebuffer().save(str(destination / f"archive-{kind}-{size[0]}x{size[1]}-text{scale}.png"))
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
@pytest.mark.parametrize("source_state", ["disconnected", "invalid"])
@pytest.mark.parametrize("compact", [False, True])
def test_archive_related_focus_tracks_reliable_source_or_falls_back_on_invalidation(resource_context, source_state, compact):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready_state = feature.advance_to_completed(selection)
    ready = ready_state.last_reliable_data
    candidate = ready.candidates[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=2.0 if compact else 1.0, reduced_motion=True),
    )
    host.resize(960 if compact else 1426, 480 if compact else 786)
    host.show()
    try:
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        if compact:
            root.findChild(QQuickItem, "researchArchivePageListButton").forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        for _ in candidate.evidence:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        assert visible_item(root, "researchArchivePageLink0").hasActiveFocus()
        if source_state == "disconnected":
            updated = feature.advance_to_disconnected(selection)
        else:
            updated = feature.replay_scripted_state(selection, replace(
                ready_state, revision=ready_state.revision + 1, last_reliable_data=None,
                phase=ViewPhase.FAILED, presentation=EvidenceAndFindingsPresentationState.FAILED,
                completeness=Completeness.UNKNOWN,
                error=StructuredFeatureError(code="source_invalid", message="精确来源已失效", retryable=False),
            ))
        page = root.findChild(QQuickItem, "researchArchivePage")
        until(app, lambda: updated.error.message in page.property("statusText"))
        app.processEvents()
        details = root.findChild(QQuickItem, "researchArchivePageDetails")
        if source_state == "invalid":
            assert "精确来源已失效" in details.property("text")
            assert "当前没有可读取的资源" not in details.property("text")
            assert "尚未选择旧运行的证据" not in details.property("text")
            parent_control = root.findChild(QQuickItem, "researchArchivePageListButton") if compact else catalog
            assert parent_control.hasActiveFocus() and parent_control.isVisible()
        else:
            assert visible_item(root, "researchArchivePageLink0").hasActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
            assert "旧证据兼容 · 原始观察" in details.property("text")
            assert candidate.comparisons[0].reference_evidence_id.value in details.property("text")
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["fake"], indirect=True)
@pytest.mark.parametrize("missing", ["source", "parent"])
@pytest.mark.parametrize("compact", [False, True])
def test_archive_missing_relation_never_reuses_old_content_or_selects_another_object(resource_context, missing, compact):
    app, context = resource_context
    selection = exact_evidence_context()
    feature = context.evidence_and_findings_feature
    ready = feature.advance_to_completed(selection)
    data = ready.last_reliable_data
    candidate = data.candidates[0]
    comparison = candidate.comparisons[0]
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        evidence_feature=feature, evidence_context=selection,
        initial_route="evidence_and_findings", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=2.0 if compact else 1.0, reduced_motion=True),
    )
    host.resize(960 if compact else 1426, 480 if compact else 786)
    host.show()
    try:
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        if compact:
            root.findChild(QQuickItem, "researchArchivePageListButton").forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        for _ in candidate.evidence:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        count = catalog.property("count")
        if missing == "parent":
            changed = replace(
                candidate,
                comparisons=tuple(item for item in candidate.comparisons if item.identity != comparison.identity),
                findings=tuple(replace(finding, comparison_ids=tuple(
                    item for item in finding.comparison_ids if item != comparison.identity))
                    for finding in candidate.findings),
            )
            replacement = replace(ready, revision=ready.revision + 1,
                                  last_reliable_data=replace(data, candidates=(changed, *data.candidates[1:])))
        else:
            replacement = replace(
                ready, revision=ready.revision + 1, last_reliable_data=None,
                phase=ViewPhase.FAILED, presentation=EvidenceAndFindingsPresentationState.FAILED,
                completeness=Completeness.UNKNOWN,
                error=StructuredFeatureError(code="source_invalid", message="精确来源已失效", retryable=False),
            )
        feature.replay_scripted_state(selection, replacement)
        until(app, lambda: catalog.property("count") == (count - 1 if missing == "parent" else 0))
        root.findChild(QQuickItem, "researchArchivePageBack").forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = root.findChild(QQuickItem, "researchArchivePageDetails")
        text = details.property("text")
        assert "关联资源不可用" in text and "未选择其他对象" in text
        assert "旧证据兼容 · 原始观察" not in text
        assert "旧证据兼容 · 原始比较" not in text
        parent_control = root.findChild(QQuickItem, "researchArchivePageListButton") if compact else catalog
        assert parent_control.hasActiveFocus() and parent_control.isVisible()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("kind", ["record", "comparison", "finding"])
def test_archive_reads_sealed_file_backed_evidence_through_app_context(tmp_path, request, monkeypatch, kind):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    application, engine, campaign, run, package, manifest, _ = _persist_real_formal_v1_through_application(
        tmp_path / "sealed.sqlite", tmp_path / "artifacts", seal_evidence=True,
        register_cleanup=request.addfinalizer,
    )
    assert package is not None and manifest is not None
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine)
    exact = read_model.resolve_journey(V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(package.evidence_package_id),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )).value
    assert exact is not None
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"), run_monitoring_mode="live",
        strategy_diagnostics_application=application,
        strategy_diagnostics_read_model=read_model, event_bridge=bridge,
        system_health_sampling_interval=None,
    )
    request.addfinalizer(context.close)
    request.addfinalizer(bridge.stop)
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature, context=exact.run_context,
        evidence_feature=context.evidence_and_findings_feature, evidence_context=exact.evidence_context,
        initial_route="evidence_and_findings", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        feature = context.evidence_and_findings_feature
        until(app, lambda: feature.snapshot(exact.evidence_context).last_reliable_data is not None
              or feature.snapshot(exact.evidence_context).error is not None)
        observed = feature.snapshot(exact.evidence_context)
        expected = observed.last_reliable_data
        assert expected is not None, observed.error
        page = host.rootObject().findChild(QQuickItem, "researchArchivePage")
        catalog = host.rootObject().findChild(QQuickItem, "researchArchivePageList")
        until(app, lambda: catalog.property("count") > 0)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        candidate = expected.candidates[0]
        if kind != "record":
            assert candidate.comparisons
            for _ in candidate.evidence:
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        if kind == "finding":
            assert candidate.findings
            for _ in candidate.comparisons:
                QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        text = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails").property("text")
        assert package.evidence_package_id in text
        assert manifest.manifest_id in text
        if kind == "record":
            record = candidate.evidence[0]
            assert record.identity.value in text and f"{record.value} {record.unit}" in text
        elif kind == "comparison":
            comparison = candidate.comparisons[0]
            assert comparison.identity.value in text
            assert comparison.reference_evidence_id.value in text
            assert comparison.observed_evidence_id.value in text
            assert comparison.interpretation in text
        else:
            finding = candidate.findings[0]
            assert finding.identity.value in text and finding.title in text
            assert finding.comparison_summary in text and finding.disposition.value in text
        assert expected.candidates[0].provenance.artifact_hashes[0] in text
        assert application.diagnostic_evidence_status(package.evidence_package_id) == package
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        context.close()
        bridge.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["live"], indirect=True)
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_open_resource_drawer_reflows_without_losing_exact_selection_or_focus(
    resource_context, scale, record_property,
):
    app, context = resource_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(2600, 1400)
    host.show()
    try:
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0)
        scenarios = context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios
        assert len(scenarios) >= 2, "The live fixture must expose a non-default Scenario"
        expected = scenarios[1]
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = root.findChild(QQuickItem, "researchScenarioPageDetails")
        assert expected.scenario_id.value in details.property("text")
        selected_index = catalog.property("currentIndex")
        assert selected_index == 1
        drawer = root.findChild(QObject, "researchScenarioPageDrawer")
        toggle = root.findChild(QQuickItem, "researchScenarioPageListButton")
        catalog.forceActiveFocus()

        for step, (width, height) in enumerate(((960, 480), (960, 540), (2600, 1400), (960, 480))):
            host.resize(width, height)
            until(app, lambda: bool(drawer.property("opened")) == (width == 960)
                  and catalog.hasActiveFocus() and catalog.isVisible())
            assert catalog.property("currentIndex") == selected_index
            assert expected.scenario_id.value in details.property("text")
            bounds = catalog.mapRectToScene(catalog.boundingRect())
            assert bounds.width() > 0 and 0 <= bounds.left() < host.width()
            assert bounds.height() > 0 and 0 <= bounds.top() < host.height()
            assert bounds.right() <= host.width() and bounds.bottom() <= host.height()
            record_property(f"client_step_{step}", f"{host.width()}x{host.height()}")

        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        until(app, lambda: not drawer.property("opened") and toggle.hasActiveFocus())
        assert toggle.isVisible()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        until(app, lambda: drawer.property("opened") and catalog.hasActiveFocus())
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        until(app, lambda: details.hasActiveFocus() and not drawer.property("opened"))
        assert expected.scenario_id.value in details.property("text")
        assert context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios[1] == expected
        record_property("dpr", host.devicePixelRatioF())
        record_property("text_scale", scale)
        record_property("source_revision", context.scenario_lab_feature.snapshot(context.scenario_lab_context).source_revision.value)
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("resource_context", ["live"], indirect=True)
@pytest.mark.parametrize("size,scale", [((960, 480), 2.0), ((960, 540), 1.0), ((2600, 1400), 1.0)])
def test_resource_layout_keeps_exact_details_and_accessible_controls_reachable(
    resource_context, size, scale, record_property,
):
    app, context = resource_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(*size)
    host.show()
    QTest.qWait(60)
    try:
        until(app, lambda: bool(context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios))
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchScenarioPageList")
        until(app, lambda: catalog.property("count") > 0)
        toggle = root.findChild(QQuickItem, "researchScenarioPageListButton")
        drawer = root.findChild(QObject, "researchScenarioPageDrawer")
        if size[0] == 960:
            page = root.findChild(QQuickItem, "researchScenarioPage")
            assert toggle.isVisible() and toggle.isEnabled(), (
                host.width(), root.width(), page.width(), page.property("compact"),
                page.property("listMinimumWidth"), page.property("detailMinimumWidth"),
            )
            toggle.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            until(app, lambda: drawer.property("opened"))
            assert catalog.hasActiveFocus()
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        details = root.findChild(QQuickItem, "researchScenarioPageDetails")
        assert details.isVisible() and details.hasActiveFocus()
        assert details.width() > 0 and details.height() > 0
        interface = QAccessible.queryAccessibleInterface(details)
        assert interface is not None and interface.isValid()
        assert "精确资源详情" in interface.text(QAccessible.Text.Name)
        assert interface.state().readOnly
        expected = context.scenario_lab_feature.snapshot(context.scenario_lab_context).market_scenarios[0]
        if size[0] == 2600:
            evidence = root.findChild(QQuickItem, "researchScenarioPageEvidence")
            assert evidence is not None and evidence.isVisible()
            assert expected.recipe_content_hash in evidence.property("text")
        else:
            assert expected.recipe_content_hash in details.property("text")
            assert not drawer.property("opened")
            toggle.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
            until(app, lambda: not drawer.property("opened"))
            assert toggle.hasActiveFocus()
        record_property("logical_client", f"{host.width()}x{host.height()}")
        record_property("dpr", host.devicePixelRatioF())
        record_property("text_scale", scale)
        record_property("source_revision", context.scenario_lab_feature.snapshot(context.scenario_lab_context).source_revision.value)
        if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
            QTest.qWait(60)
            destination = Path(evidence_dir)
            destination.mkdir(parents=True, exist_ok=True)
            assert host.grabFramebuffer().save(str(destination / f"research-scenario-{size[0]}x{size[1]}-text{scale}.png"))
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
