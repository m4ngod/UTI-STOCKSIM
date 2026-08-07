from __future__ import annotations

import gc
import os
import time
from datetime import date, datetime, timedelta, timezone
from threading import get_ident
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
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeSystemHealthAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    StrategyDiagnosticsV1ApplicationReadModel,
    SystemHealthContext,
    SystemHealthFeature,
    diagnostics_application_identity,
)
from app.journey_recovery import JourneyWorkspaceBookmark, JourneyWorkspaceRoute
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
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


def _process_until(app: QApplication, predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
    raise AssertionError("Timed out waiting for the externally visible QML state")


def _application_with_admitted_source():
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    checks = (
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
    inspection = HistoricalSourceInspection(
        selection=selection,
        label="A-share diagnostic interval",
        provenance=SourceProvenance(
            provider="BaoStock",
            dataset="local-a-share-fixture",
            version="fixture-2026-07-21",
            observed_at=datetime(2026, 7, 21, 23, 0, tzinfo=timezone.utc),
        ),
        artifacts=(
            SourceArtifact(
                name="daily-unadjusted",
                content_hash="1" * 64,
                row_count=60,
            ),
        ),
        eligible_instrument_count=120,
        trading_day_count=2,
        bar_count=60,
        checks=tuple(
            AdmissionCheck(code=code, passed=True, summary=f"{code} passed.")
            for code in checks
        ),
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()
    assert application.admit_historical_segment(selection).status == "admitted"
    return application


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
        assert "unavailable" in str(status.property("accessibleName")).casefold()
        source_status = root.findChild(QObject, "dataSourceAccessibleStatus")
        assert source_status is not None
        assert "unavailable" in str(
            source_status.property("accessibleName")
        ).casefold()
        assert "Application runtime" in visible
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
        assert health.presentation.value == "unavailable"
        assert health.components[0].classification.value == "healthy"
        assert health.diagnostic_data_source.classification.value == "unavailable"
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


def test_system_health_event_delivery_rereads_real_application_state() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    diagnostics_application = create_diagnostics_application()
    bridge = EventBridge(subscribe_backend=False)
    health_feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                diagnostics_application
            )
        ),
        event_bridge=bridge,
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
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _process_until(
            app,
            lambda: "unavailable"
            in str(status.property("accessibleName")).casefold(),
        )

        assert "Application runtime · healthy" in _visible_text(root)
        assert "No admitted diagnostic data source" in _visible_text(root)
    finally:
        window.close()
        run_feature.close()
        health_feature.close()


def test_real_data_source_health_recovery_is_visible_and_filters_bad_deliveries() -> None:
    app = _app()
    ui_thread = get_ident()
    qt_delivery_threads: list[int] = []
    run_feature = DeterministicFakeRunMonitoringAdapter()
    diagnostics_application = _application_with_admitted_source()
    bridge = EventBridge(subscribe_backend=False)
    health_feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                diagnostics_application
            )
        ),
        event_bridge=bridge,
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
        host = window.centralWidget()
        host._system_health.stateChanged.connect(  # type: ignore[attr-defined]
            lambda: qt_delivery_threads.append(get_ident())
        )
        root = host.rootObject()
        source_status = root.findChild(QObject, "dataSourceAccessibleStatus")
        source_revision = root.findChild(QObject, "dataSourceRevisionText")
        source_identity = root.findChild(QObject, "dataSourceIdentityText")
        assert source_status is not None
        assert source_revision is not None
        assert source_identity is not None
        assert "connected" in str(source_status.property("accessibleName"))
        assert "fresh" in str(source_status.property("accessibleName"))
        assert source_revision.property("text") == "Accepted · r1 · g1"
        reliable_identity = str(source_identity.property("text"))
        assert "admitted-source-" in reliable_identity

        bridge.mark_disconnected()
        _process_until(
            app,
            lambda: "disconnected"
            in str(source_status.property("accessibleName")),
        )
        assert "last reliable" in _visible_text(root).casefold()
        assert source_identity.property("text") == reliable_identity

        bridge.mark_fallback_active()
        _process_until(
            app,
            lambda: "fallback active"
            in str(source_status.property("accessibleName")),
        )
        reconnecting = str(source_status.property("accessibleName"))
        assert "reconnecting" in reconnecting
        assert "recovered" not in reconnecting
        assert source_revision.property("text") == "Accepted · r1 · g1"

        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 99,
                "endpoint": "redis://user:secret@private-host",
                "token": "never-render-this",
            },
            generation=1,
        )
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 1,
            },
            generation=2,
        )
        bridge.flush(force=True)
        app.processEvents()
        assert source_revision.property("text") == "Accepted · r1 · g1"

        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 2,
            },
            generation=2,
        )
        terminal_delivery_started = time.monotonic()
        bridge.flush(force=True)
        _process_until(
            app,
            lambda: "recovered"
            in str(source_status.property("accessibleName")),
        )
        assert time.monotonic() - terminal_delivery_started <= 0.1
        assert source_revision.property("text") == "Accepted · r2 · g2"

        recovered = str(source_status.property("accessibleName"))
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 2,
            },
            generation=2,
        )
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 1,
            },
            generation=2,
        )
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 100,
            },
            generation=1,
        )
        bridge.flush(force=True)
        app.processEvents()
        assert source_revision.property("text") == "Accepted · r2 · g2"
        assert source_status.property("accessibleName") == recovered

        exposed = (
            _visible_text(root)
            + " "
            + " ".join(
                str(item.property("accessibleName"))
                for item in root.findChildren(QObject)
                if item.metaObject().indexOfProperty("accessibleName") >= 0
            )
        ).casefold()
        for forbidden in (
            "redis://",
            "private-host",
            "never-render-this",
            "cookie",
            "connection string",
        ):
            assert forbidden not in exposed
        assert qt_delivery_threads
        assert set(qt_delivery_threads) == {ui_thread}
    finally:
        window.close()
        run_feature.close()
        health_feature.close()


def test_system_health_qml_surface_has_no_web_or_control_plane_imports() -> None:
    page = Path(__file__).parents[3] / "app" / "ui" / "qml" / "SystemHealthPage.qml"
    source = page.read_text(encoding="utf-8").casefold()

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
    ):
        assert forbidden not in source

    workspace = page.with_name("JourneyWorkspace.qml").read_text(encoding="utf-8")
    assert "onTriggered: systemHealth.refresh()" not in workspace


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


def test_stale_failed_recovery_is_accessible_and_keyboard_focusable() -> None:
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
        runtime_status = root.findChild(QQuickItem, "systemHealthAccessibleStatus")
        source_status = root.findChild(QQuickItem, "dataSourceAccessibleStatus")
        assert runtime_status is not None and source_status is not None

        health_feature.advance_clock(timedelta(seconds=31))
        health_feature.advance_to_disconnected()
        health_feature.advance_data_source_to_fallback()
        health_feature.fail_next_data_source_reread()
        health_feature.deliver_data_source_revision(2)
        app.processEvents()

        accessible = str(source_status.property("accessibleName"))
        assert "stale" in accessible
        assert "fallback active" in accessible
        assert "failed_recovery" in accessible
        assert "partial" in str(runtime_status.property("accessibleName"))

        assert runtime_status.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Tab)
        app.processEvents()
        assert source_status.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Backtab)
        app.processEvents()
        assert runtime_status.property("activeFocus") is True
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
