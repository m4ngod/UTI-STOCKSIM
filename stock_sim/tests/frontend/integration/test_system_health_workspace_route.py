from __future__ import annotations

import gc
import json
import os
import shutil
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
from sqlalchemy import create_engine, text

import persistence.models_imports as persistence_models

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features.diagnostic_tasks_application import (
    CreateDiagnosticTask,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskConfiguration,
    DiagnosticTasksApplicationCommandRejectionReason,
    HistoricalMarketSegmentId,
)
from app.features.run_monitoring import SourceGenerationId
from app.features.scenario_lab_application import (
    CreateScenarioRecipeDraftCommand,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    RequestedExecutionAssumptionsProjection,
    ScenarioLabActorId,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandId,
    ScenarioLabCommandMetadata,
    ScenarioLabIdempotencyIdentity,
    ScenarioRecipeAuthoringMode,
    ScenarioRecipeDataPolicy,
    ScenarioRecipeDraftPayload,
)
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken
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
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests(tmp_path, monkeypatch):
    lock_path = (
        Path(__file__).parents[3]
        / "stock_sim"
        / "release"
        / "frontend_v2_toolchain.lock.json"
    )
    release_manifest = tmp_path / "dependency-manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "toolchain_lock": json.loads(lock_path.read_text(encoding="utf-8")),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_RELEASE_MANIFEST_PATH",
        str(release_manifest),
    )
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


def _close_context(context) -> None:
    context.strategy_library_feature.close()
    context.scenario_lab_feature.close()
    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()
    context.system_health_feature.close()


def _system_health_window(context) -> MainWindow:
    return MainWindow(
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
        evidence_and_findings_feature=context.evidence_and_findings_feature,
        evidence_and_findings_context=context.evidence_and_findings_context,
        system_health_feature=context.system_health_feature,
        system_health_context=context.system_health_context,
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )


def test_real_file_persistence_and_version_health_render_through_qml(tmp_path) -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    database = tmp_path / "controlled-health-fixture.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    seed_application = create_diagnostics_application()
    seed_application.start()
    seed_application.initialize_persistence(engine)
    diagnostics_application = create_diagnostics_application()
    diagnostics_application.start()
    diagnostics_application.initialize_persistence(engine)
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            diagnostics_application,
            current_manifest_format_provider=(
                lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
            ),
        ),
        event_bridge=EventBridge(subscribe_backend=False),
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
        visible = _visible_text(root)
        accessible = root.findChild(QObject, "systemHealthAccessibleStatus")

        assert accessible is not None
        assert "Persistence Health healthy" in str(
            accessible.property("accessibleName")
        )
        assert "availability available" in str(
            accessible.property("accessibleName")
        )
        assert "Version Health healthy" in str(
            accessible.property("accessibleName")
        )
        assert "Release binding compatible" in str(
            accessible.property("accessibleName")
        )
        for expected in (
            "DIAGNOSTIC PERSISTENCE",
            "Persistence freshness · fresh",
            "Durable read",
            "Durable write",
            "Reopen verification · verified",
            "VERSION COMPATIBILITY",
            "stock-sim/0.0.1",
            "SystemHealthFeature 1.0",
            "sha256:",
            "Release binding compatible",
            "reproduction-manifest.v1",
        ):
            assert expected in visible
        for forbidden in (
            str(database),
            database.name,
            "sqlite+pysqlite://",
            "SELECT ",
            "Traceback",
        ):
            assert forbidden not in visible
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
        engine.dispose()


def test_narrator_distinguishes_release_incompatibility_from_manifest_compatibility(
    tmp_path,
) -> None:
    app = _app()
    lock_path = (
        Path(__file__).parents[3]
        / "stock_sim"
        / "release"
        / "frontend_v2_toolchain.lock.json"
    )
    original_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    changed_lock = json.loads(json.dumps(original_lock))
    changed_lock["toolchain"]["python"] = "99.99.99"
    lock_fixture = tmp_path / "changed-lock.json"
    lock_fixture.write_text(json.dumps(changed_lock), encoding="utf-8")
    database = tmp_path / "narrator-release-health.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    seed = create_diagnostics_application()
    seed.start()
    seed.initialize_persistence(engine)
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    run_feature = DeterministicFakeRunMonitoringAdapter()
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            dependency_lock_path=lock_fixture,
            release_manifest_provider=(
                lambda: {"schema_version": 1, "toolchain_lock": original_lock}
            ),
            current_manifest_format_provider=(
                lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
            ),
        ),
        event_bridge=EventBridge(subscribe_backend=False),
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
        accessible = root.findChild(QObject, "systemHealthAccessibleStatus")

        assert accessible is not None
        narration = str(accessible.property("accessibleName"))
        assert "Release binding incompatible" in narration
        assert "Version Health incompatible" in narration
        assert "Reproduction Manifest compatible" in narration
        assert lock_fixture.name not in narration
        assert database.name not in narration
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
        engine.dispose()


def test_copied_manifest_incompatibility_renders_safe_diagnostic_impact(
    tmp_path,
) -> None:
    app = _app()
    source = tmp_path / "supported-manifest.json"
    source.write_text(
        json.dumps({"schema_version": "reproduction-manifest.v1"}),
        encoding="utf-8",
    )
    fixture = tmp_path / "manifest-incompatible-copy.json"
    shutil.copy2(source, fixture)
    fixture.write_text(
        json.dumps({"schema_version": "reproduction-manifest.v999"}),
        encoding="utf-8",
    )
    database = tmp_path / "controlled-health.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    seed_application = create_diagnostics_application()
    seed_application.start()
    seed_application.initialize_persistence(engine)
    diagnostics_application = create_diagnostics_application()
    diagnostics_application.start()
    diagnostics_application.initialize_persistence(engine)
    run_feature = DeterministicFakeRunMonitoringAdapter()
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            diagnostics_application,
            current_manifest_format_provider=(
                lambda: str(
                    json.loads(fixture.read_text(encoding="utf-8"))["schema_version"]
                )
            ),
        ),
        event_bridge=EventBridge(subscribe_backend=False),
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
        visible = _visible_text(root)
        accessible = root.findChild(QObject, "systemHealthAccessibleStatus")

        assert accessible is not None
        assert "System Health incompatible" in str(
            accessible.property("accessibleName")
        )
        assert "Version Health incompatible" in str(
            accessible.property("accessibleName")
        )
        assert "affected reproduction_manifest" in visible
        assert "recovery compatible_artifact_required" in visible
        for forbidden in (fixture.name, str(fixture.parent), database.name):
            assert forbidden not in visible
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("fixture_kind", "expected_presentation", "expected_recovery"),
    (
        ("unavailable", "unavailable", "automatic_retry"),
        ("schema_incompatible", "incompatible", "compatible_build_required"),
    ),
)
def test_app_context_copied_persistence_failure_reaches_qml_safely(
    tmp_path,
    monkeypatch,
    fixture_kind: str,
    expected_presentation: str,
    expected_recovery: str,
) -> None:
    app = _app()
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    source = tmp_path / "source.sqlite3"
    source_engine = create_engine(f"sqlite+pysqlite:///{source.as_posix()}")
    source_application = create_diagnostics_application()
    source_application.start()
    source_application.initialize_persistence(source_engine)
    source_engine.dispose()
    fixture = tmp_path / f"{fixture_kind}-copy.sqlite3"
    shutil.copy2(source, fixture)
    if fixture_kind == "unavailable":
        fixture.write_bytes(b"controlled unavailable fixture")
    else:
        fixture_setup = create_engine(f"sqlite+pysqlite:///{fixture.as_posix()}")
        with fixture_setup.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO diagnostic_schema_migrations "
                    "(revision, applied_at_utc) VALUES "
                    "(:revision, :applied_at_utc)"
                ),
                {
                    "revision": "9999_controlled_future_revision",
                    "applied_at_utc": datetime(2030, 1, 1, tzinfo=timezone.utc).isoformat(),
                },
            )
        fixture_setup.dispose()
    fixture_engine = create_engine(f"sqlite+pysqlite:///{fixture.as_posix()}")
    monkeypatch.setattr(persistence_models, "engine", fixture_engine)
    context = build_app_context(
        settings_path=str(tmp_path / f"{fixture_kind}-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        runtime_gateway=object(),
    )
    window = None
    try:
        state = context.system_health_feature.snapshot(SystemHealthContext())
        assert state.presentation.value == expected_presentation
        application = context.strategy_diagnostics_application
        tasks_application = context.strategy_diagnostics_tasks_application
        scenario_application = (
            context.strategy_diagnostics_scenario_lab_application
        )
        assert application is not None
        assert tasks_application is not None
        assert isinstance(
            scenario_application,
            LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
        )
        backend_calls = []
        monkeypatch.setattr(
            application,
            "create_diagnostic_task",
            lambda *_args, **_kwargs: backend_calls.append("task"),
        )
        monkeypatch.setattr(
            application,
            "create_scenario_recipe_draft_command",
            lambda *_args, **_kwargs: backend_calls.append("scenario"),
        )
        task_result = tasks_application.create_diagnostic_task(
            CreateDiagnosticTask(
                command_id=DiagnosticCommandId("health-command-task"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "health-idempotency-task"
                ),
                configuration=DiagnosticTaskConfiguration.create(
                    strategy_selections=(),
                    campaign_case_selections=(),
                ),
            )
        )
        scenario_result = scenario_application.create_recipe_draft(
            CreateScenarioRecipeDraftCommand(
                metadata=ScenarioLabCommandMetadata(
                    command_id=ScenarioLabCommandId("health-command-scenario"),
                    idempotency_identity=ScenarioLabIdempotencyIdentity(
                        "health-idempotency-scenario"
                    ),
                    canonical_content_identity=ScenarioLabCommandContentIdentity(
                        "health-content-scenario"
                    ),
                    expected_source_revision=SourceRevisionToken("0" * 64),
                    expected_source_generation=SourceGenerationId(1),
                ),
                payload=ScenarioRecipeDraftPayload(
                    name="Health blocked draft",
                    historical_segment_id=HistoricalMarketSegmentId(
                        "health-segment"
                    ),
                    transformations=(),
                    requested_execution_assumptions=(
                        RequestedExecutionAssumptionsProjection(
                            commission_bps="3",
                            slippage_bps="0",
                            max_fill_fraction="1",
                            latency_nodes=0,
                            allow_partial_fills=True,
                        )
                    ),
                    decision_cadence_minutes=30,
                    materialization_seed=17,
                    data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
                    market_rule_profile_version="a-share-cash-equity.v1",
                ),
                author_id=ScenarioLabActorId("health-actor"),
                authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            )
        )
        assert task_result.rejection_reason is (
            DiagnosticTasksApplicationCommandRejectionReason.PERSISTENCE_FAILURE
        )
        assert scenario_result.receipt.disposition is (
            ScenarioLabCommandDisposition.UNAVAILABLE
        )
        assert backend_calls == []
        window = _system_health_window(context)
        window.show()
        app.processEvents()
        root = window.centralWidget().rootObject()
        visible = _visible_text(root)
        accessible = root.findChild(QObject, "systemHealthAccessibleStatus")

        assert accessible is not None
        narrator = str(accessible.property("accessibleName")).casefold()
        assert f"system health {expected_presentation}" in narrator
        assert f"persistence health {expected_presentation}" in narrator
        assert f"recovery {expected_recovery}" in visible.casefold()
        exposed = (narrator + " " + visible.casefold())
        for forbidden in (
            fixture.name.casefold(),
            str(fixture.parent).casefold(),
            "sqlite+pysqlite",
            "select ",
            "traceback",
        ):
            assert forbidden not in exposed
    finally:
        if window is not None:
            window.close()
        _close_context(context)
        fixture_engine.dispose()


def test_copied_reopened_persistence_stale_and_recovered_reach_qml(
    tmp_path,
) -> None:
    app = _app()
    source = tmp_path / "source.sqlite3"
    source_engine = create_engine(f"sqlite+pysqlite:///{source.as_posix()}")
    source_application = create_diagnostics_application()
    source_application.start()
    source_application.initialize_persistence(source_engine)
    source_engine.dispose()
    fixture = tmp_path / "reopened-copy.sqlite3"
    shutil.copy2(source, fixture)
    engine = create_engine(f"sqlite+pysqlite:///{fixture.as_posix()}")
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    bridge = EventBridge(subscribe_backend=False)
    run_feature = DeterministicFakeRunMonitoringAdapter()
    health_feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: now[0],
            current_manifest_format_provider=(
                lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
            ),
        ),
        event_bridge=bridge,
        clock=lambda: now[0],
        freshness_threshold=timedelta(seconds=5),
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
        accessible = root.findChild(QObject, "systemHealthAccessibleStatus")
        assert accessible is not None
        assert "reopen verification · verified" in _visible_text(root).casefold()

        bridge.mark_disconnected()
        now[0] += timedelta(seconds=6)
        health_feature.snapshot(SystemHealthContext())
        app.processEvents()
        stale_visible = _visible_text(root).casefold()
        stale_narrator = str(accessible.property("accessibleName")).casefold()
        assert "system health stale" in stale_narrator
        assert "persistence health stale" in stale_narrator
        assert "freshness stale" in stale_narrator

        bridge.mark_reconnected()
        app.processEvents()
        assert "system health recovered" in str(
            accessible.property("accessibleName")
        ).casefold()
        for forbidden in (fixture.name.casefold(), str(fixture.parent).casefold()):
            assert forbidden not in stale_visible
            assert forbidden not in stale_narrator
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
        engine.dispose()


def test_app_context_does_not_swallow_post_migration_initialization_failure(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'post-migration.sqlite3').as_posix()}"
    )
    monkeypatch.setattr(persistence_models, "engine", engine)
    application = create_diagnostics_application()
    initialize = application.initialize_persistence

    def fail_after_initialization(target_engine):
        initialize(target_engine)
        raise RuntimeError("controlled post-migration failure")

    monkeypatch.setattr(
        application,
        "initialize_persistence",
        fail_after_initialization,
    )
    try:
        with pytest.raises(RuntimeError, match="post-migration failure"):
            build_app_context(
                settings_path=str(tmp_path / "post-migration-settings.json"),
                run_monitoring_mode="live",
                event_bridge=EventBridge(subscribe_backend=False),
                runtime_gateway=object(),
                strategy_diagnostics_application=application,
            )
    finally:
        engine.dispose()


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
        assert health.presentation.value == "unknown"
        assert health.components[1].availability.value == "unknown"
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


def test_system_health_timer_rereads_real_application_state() -> None:
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
        QTest.qWait(1100)
        app.processEvents()

        assert "healthy" in str(status.property("accessibleName")).casefold()
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
