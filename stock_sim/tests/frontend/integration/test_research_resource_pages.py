"""Research pages observe AppContext resources through real QML input."""

from __future__ import annotations

import os
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


def test_archive_reads_sealed_file_backed_evidence_through_app_context(tmp_path, request, monkeypatch):
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
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        text = host.rootObject().findChild(QQuickItem, "researchArchivePageDetails").property("text")
        record = expected.candidates[0].evidence[0]
        assert package.evidence_package_id in text
        assert manifest.manifest_id in text
        assert record.identity.value in text and f"{record.value} {record.unit}" in text
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
