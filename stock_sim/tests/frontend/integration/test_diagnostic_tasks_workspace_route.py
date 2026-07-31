from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QMetaObject, QObject
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, text

from app.event_bridge import EventBridge
from app.features import (
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticTasksContext,
    LiveDiagnosticTasksAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    RunMonitoringContext,
)
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _persistent_three_layer_stack,
)
from tests.frontend.contract.test_strategy_diagnostics_v1_run_monitoring_live_contract import (
    _DirectExecutor,
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
    assert "not_yet_available" in page.property("blockingReasonsText")
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

    assert QMetaObject.invokeMethod(button, "clicked")
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

    assert QMetaObject.invokeMethod(create_button, "clicked")
    app.processEvents()
    assert " · r2 · draft · " in page.property("taskStatusText")
    assert validate_button.property("enabled") is True
    assert approve_button.property("enabled") is False

    assert QMetaObject.invokeMethod(validate_button, "clicked")
    app.processEvents()
    assert "invalid" in page.property("validationStatusText")
    assert "campaign.layer.isolated_sensitivity_required" in page.property(
        "validationStatusText"
    )
    assert "campaign.layer.compound_required" in page.property(
        "validationStatusText"
    )
    assert approve_button.property("enabled") is False

    assert QMetaObject.invokeMethod(revise_button, "clicked")
    app.processEvents()
    assert " · r3 · draft · " in page.property("taskStatusText")
    assert "has not been validated" in page.property(
        "validationStatusText"
    )
    assert "No exact-revision approval" in page.property(
        "approvalStatusText"
    )

    assert QMetaObject.invokeMethod(validate_button, "clicked")
    app.processEvents()
    assert " · r3 · awaiting_approval · " in page.property(
        "taskStatusText"
    )
    assert "valid · validation" in page.property("validationStatusText")
    assert "no findings" in page.property("validationStatusText")
    assert actor_input.setProperty("text", "qml-research-owner")
    app.processEvents()
    assert approve_button.property("enabled") is True

    assert QMetaObject.invokeMethod(approve_button, "clicked")
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

    assert QMetaObject.invokeMethod(create_button, "clicked")
    app.processEvents()
    assert QMetaObject.invokeMethod(revise_button, "clicked")
    app.processEvents()
    assert QMetaObject.invokeMethod(validate_button, "clicked")
    app.processEvents()
    assert actor_input.setProperty("text", "qml-wave2-release-owner")
    app.processEvents()
    assert QMetaObject.invokeMethod(approve_button, "clicked")
    app.processEvents()
    assert start_button.property("enabled") is True

    assert QMetaObject.invokeMethod(start_button, "clicked")
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
    assert remounted_root.property("activeRoute") == "run_monitoring"
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
    assert reopened_root.property("activeRoute") == "run_monitoring"
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
