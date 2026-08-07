from __future__ import annotations

import gc
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskTarget,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeSystemHealthAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    PauseDiagnosticTarget,
    StartFormalDiagnosticCampaign,
    StrategyDiagnosticsV1ApplicationReadModel,
    SystemHealthContext,
    SystemHealthFeature,
    diagnostics_application_identity,
)
from app.journey_recovery import JourneyWorkspaceBookmark, JourneyWorkspaceRoute
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)
from tests.frontend.system_health_support import ApplicationDrivenCacheStore
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    application = QApplication.instance()
    if application is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()


def _visible_text(root: QObject) -> str:
    return " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("visible")
        and item.property("text")
    )


def _wait_until(
    application: QApplication,
    predicate,
    *,
    timeout_ms: int = 3000,
) -> None:
    for _ in range(max(timeout_ms // 10, 1)):
        application.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    application.processEvents()
    assert predicate()


def test_app_context_composes_system_health_as_the_sixth_feature(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    try:
        assert isinstance(context.system_health_feature, SystemHealthFeature)
        assert context.system_health_feature.interface_version.render() == "1.0"
        assert context.system_health_context == SystemHealthContext()
    finally:
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_live_app_context_uses_one_diagnostics_application_for_every_adapter(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app()
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        runtime_gateway=object(),
    )
    window = None
    try:
        adapters = (
            context.strategy_diagnostics_read_model,
            context.strategy_diagnostics_tasks_application,
            context.strategy_diagnostics_library_application,
            context.strategy_diagnostics_scenario_lab_application,
            context.strategy_diagnostics_system_health_application,
        )
        canonical = context.strategy_diagnostics_application
        assert canonical is not None
        expected_identity = diagnostics_application_identity(canonical)
        assert {
            adapter.application_identity for adapter in adapters
        } == {expected_identity}
        assert isinstance(context.system_health_feature, LiveSystemHealthAdapter)

        window = MainWindow(
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_context=context.strategy_library_context,
            scenario_lab_feature=context.scenario_lab_feature,
            scenario_lab_context=context.scenario_lab_context,
            diagnostic_tasks_feature=context.diagnostic_tasks_feature,
            diagnostic_tasks_context=context.diagnostic_tasks_context,
            diagnostic_setup_selection_coordinator=(
                context.diagnostic_setup_selection_coordinator
            ),
            run_monitoring_feature=context.run_monitoring_feature,
            run_monitoring_context=context.run_monitoring_context,
            evidence_and_findings_feature=(
                context.evidence_and_findings_feature
            ),
            evidence_and_findings_context=(
                context.evidence_and_findings_context
            ),
            system_health_feature=context.system_health_feature,
            system_health_context=context.system_health_context,
            journey_workspace_bookmark=JourneyWorkspaceBookmark(
                last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
            ),
            frontend_v2_enabled=True,
        )
        app.processEvents()
        root = window.centralWidget().rootObject()
        visible = _visible_text(root)

        assert root.property("activeRoute") == "system_health"
        assert root.findChild(QObject, "systemHealthPage") is not None
        status = root.findChild(QObject, "systemHealthAccessibleStatus")
        assert status is not None
        assert "healthy" in str(status.property("accessibleName")).casefold()
        assert "Application runtime" in visible
        assert "Diagnostic queue" in visible
        assert "Diagnostic cache" in visible
        queue_card = root.findChild(QObject, "diagnosticQueueHealthCard")
        cache_card = root.findChild(QObject, "diagnosticCacheHealthCard")
        assert queue_card is not None
        assert cache_card is not None
        assert "pending" in str(queue_card.property("accessibleName")).casefold()
        assert "fallback" in str(cache_card.property("accessibleName")).casefold()
        assert "No infrastructure controls" in visible
    finally:
        if window is not None:
            window.close()
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_partial_live_composition_reuses_the_injected_diagnostics_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    diagnostics_application = create_diagnostics_application()
    diagnostics_application.start()
    tasks_application = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            diagnostics_application
        )
    )
    context = build_app_context(
        settings_path=str(tmp_path / "partial-live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        runtime_gateway=object(),
        strategy_diagnostics_application=diagnostics_application,
        strategy_diagnostics_read_model=cast(
            StrategyDiagnosticsV1ApplicationReadModel,
            SimpleNamespace(
                application_identity=diagnostics_application_identity(
                    diagnostics_application
                )
            ),
        ),
        strategy_diagnostics_tasks_application=tasks_application,
    )
    try:
        assert (
            context.strategy_diagnostics_application
            is diagnostics_application
        )
        health = context.system_health_feature.snapshot(SystemHealthContext())
        assert health.presentation.value == "healthy"
    finally:
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_partial_live_composition_requires_an_explicit_canonical_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")

    with pytest.raises(ValueError, match="explicit shared DiagnosticsApplication"):
        build_app_context(
            settings_path=str(tmp_path / "invalid-partial-settings.json"),
            run_monitoring_mode="live",
            event_bridge=EventBridge(subscribe_backend=False),
            runtime_gateway=object(),
            strategy_diagnostics_read_model=cast(
                StrategyDiagnosticsV1ApplicationReadModel,
                object(),
            ),
        )


def test_live_composition_rejects_an_adapter_owned_by_another_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    canonical = create_diagnostics_application()
    foreign = create_diagnostics_application()
    foreign.start()

    with pytest.raises(ValueError, match="does not belong"):
        build_app_context(
            settings_path=str(tmp_path / "mixed-ownership-settings.json"),
            run_monitoring_mode="live",
            event_bridge=EventBridge(subscribe_backend=False),
            runtime_gateway=object(),
            strategy_diagnostics_application=canonical,
            strategy_diagnostics_tasks_application=(
                LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                    foreign
                )
            ),
        )


def test_system_health_live_sampler_rereads_real_application_state() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    diagnostics_application = create_diagnostics_application()
    health_feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                diagnostics_application
            )
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        sampling_interval=timedelta(milliseconds=25),
    )
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        window.show()
        app.processEvents()
        root = window.centralWidget().rootObject()
        status = root.findChild(QObject, "systemHealthAccessibleStatus")
        assert status is not None
        assert "unknown" in str(status.property("accessibleName")).casefold()

        diagnostics_application.start()
        _wait_until(
            app,
            lambda: "healthy"
            in str(status.property("accessibleName")).casefold(),
        )
    finally:
        window.close()
        run_feature.close()
        health_feature.close()


def test_real_diagnostic_queue_lifecycle_reaches_the_visible_qml_card(
    tmp_path,
) -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        task_feature,
    ) = _formal_live_stack(tmp_path)
    bridge = EventBridge(subscribe_backend=False)
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        ),
        event_bridge=bridge,
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        sampling_interval=None,
    )
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        window.show()
        root = window.centralWidget().rootObject()
        queue_card = root.findChild(QObject, "diagnosticQueueHealthCard")
        assert queue_card is not None
        _wait_until(
            app,
            lambda: "healthy" in str(
                queue_card.property("accessibleName")
            ).casefold(),
        )

        approved = _approved_formal_task(task_feature)
        accepted = task_feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("start-command-qml-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "start-idempotency-qml-health-110"
                ),
                task_id=approved.task_id,
                expected_revision=approved.revision,
                approved_revision=approved.revision,
            )
        )
        assert accepted.accepted
        bridge.on_snapshot({"feature": "diagnostic_tasks"})
        bridge.flush(force=True)
        _wait_until(
            app,
            lambda: (
                "degraded" in str(
                    queue_card.property("accessibleName")
                ).casefold()
                and "pending 0" not in str(
                    queue_card.property("accessibleName")
                ).casefold()
                and "running 0" not in str(
                    queue_card.property("accessibleName")
                ).casefold()
            ),
        )

        running = _read_task(task_feature, approved.task_id)
        paused = task_feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId("pause-command-qml-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-idempotency-qml-health-110"
                ),
                target=DiagnosticTaskTarget(approved.task_id),
                expected_revision=running.revision,
            )
        )
        assert paused.accepted
        bridge.on_snapshot({"feature": "diagnostic_tasks"})
        bridge.flush(force=True)
        _wait_until(
            app,
            lambda: "blocked 0" not in str(
                queue_card.property("accessibleName")
            ).casefold(),
        )
        assert "diagnostic work is paused" in _visible_text(root).casefold()
    finally:
        window.close()
        task_feature.close()
        run_feature.close()
        health_feature.close()


def test_real_cache_behaviors_reach_stale_fallback_incompatible_and_recovered_qml(
) -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    source = _RecipeFixtureSource()
    store = ApplicationDrivenCacheStore(
        clock=clock,
        fallback_on_first_put=True,
        incompatible_on_second_put=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=clock,
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    first_payload = _baseline_payload(admission.segment.segment_id)
    first_draft = application.create_manual_recipe_draft(
        first_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(first_draft.draft_id).is_valid
    first_approved = application.approve_recipe_draft(
        first_draft.draft_id,
        actor="owner",
    )
    application.materialize_baseline_reference_path(first_approved.version_id)

    second_payload = _baseline_payload(admission.segment.segment_id)
    second_payload["name"] = "QML incompatible cache publication"
    second_payload["materialization_seed"] = 19
    second_draft = application.create_manual_recipe_draft(
        second_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(second_draft.draft_id).is_valid
    second_approved = application.approve_recipe_draft(
        second_draft.draft_id,
        actor="owner",
    )
    bridge = EventBridge(subscribe_backend=False)
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=clock,
        ),
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
        sampling_interval=None,
    )
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        window.show()
        root = window.centralWidget().rootObject()
        cache_card = root.findChild(QObject, "diagnosticCacheHealthCard")
        assert cache_card is not None
        _wait_until(
            app,
            lambda: all(
                value
                in str(cache_card.property("accessibleName")).casefold()
                for value in ("fallback", "active", "compatible")
            ),
        )

        now[0] += timedelta(seconds=6)
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _wait_until(
            app,
            lambda: "diagnostic cache stale"
            in str(cache_card.property("accessibleName")).casefold(),
        )

        with pytest.raises(ValueError):
            application.materialize_baseline_reference_path(
                second_approved.version_id
            )
        bridge.on_snapshot({"feature": "scenario_lab"})
        bridge.flush(force=True)
        _wait_until(
            app,
            lambda: "incompatible"
            in str(cache_card.property("accessibleName")).casefold(),
        )

        bridge.mark_disconnected()
        application.list_materialized_market_paths()
        bridge.mark_reconnected()
        _wait_until(
            app,
            lambda: (
                "diagnostic cache healthy"
                in str(cache_card.property("accessibleName")).casefold()
                and "recovery recovered" in _visible_text(root).casefold()
            ),
        )
    finally:
        window.close()
        run_feature.close()
        health_feature.close()


def test_system_health_qml_surface_has_no_web_or_control_plane_imports() -> None:
    page = Path(__file__).parents[3] / "app" / "ui" / "qml" / "SystemHealthPage.qml"
    source = page.read_text(encoding="utf-8").casefold()
    workspace = page.with_name("JourneyWorkspace.qml").read_text(
        encoding="utf-8"
    ).casefold()

    for forbidden in (
        "webengine",
        "webview",
        "restart",
        "reconnect",
        "clear cache",
        "purge",
        "migrate",
        "buy",
        "sell",
        "broker",
        "submit order",
        "task payload",
        "traceback",
        "credential",
    ):
        assert forbidden not in source
    assert "ontriggered: systemhealth.refresh" not in workspace
    assert "timer" not in source


def test_system_health_keyboard_focus_enters_and_leaves_the_read_only_page() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    health_feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        host = window.centralWidget()
        window.show()
        app.processEvents()
        root = host.rootObject()
        status = root.findChild(QQuickItem, "systemHealthAccessibleStatus")
        route = root.findChild(QQuickItem, "systemHealthRouteNavigation")

        assert status is not None and route is not None
        assert status.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Backtab)
        app.processEvents()
        assert route.property("activeFocus") is True
        health_feature.publish_authoritative_observation()
        app.processEvents()
        assert route.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Return)
        app.processEvents()
        assert status.property("activeFocus") is True
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
