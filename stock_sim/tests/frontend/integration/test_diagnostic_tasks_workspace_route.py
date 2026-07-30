from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.features import (
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticTasksContext,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
)
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _RecipeFixtureSource,
    _baseline_payload,
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
