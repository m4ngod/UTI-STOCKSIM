from __future__ import annotations

import gc
import os
import re
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtGui import QAccessible, QAction
from PySide6.QtWidgets import QApplication

from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId,
    CancelDiagnosticTask,
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeScenarioLabAdapter,
    DeterministicFakeStrategyLibraryAdapter,
    DiagnosticTaskId,
    DiagnosticTasksContext,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveScenarioLabAdapter,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    LiveStrategyLibraryAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
    StrategyLibraryContext,
    StrategyUnderTestId,
)
from app.runtime_gateway import RuntimeGateway
from app.ui.main_window import MainWindow
from stock_sim.release.no_manual_trading_gate import audit_qml_text
from tests.frontend.strategy_diagnostics_v1_test_support import (
    DictionaryFixtureApplicationReadModel,
)
from strategy_diagnostics import create_diagnostics_application

UTC = timezone.utc
NOW = datetime(2030, 1, 3, 9, 30, tzinfo=UTC)
FORBIDDEN_RUNTIME_MEMBERS = (
    "submit_order",
    "place_order",
    "cancel_order",
    "replace_order",
    "bulk_order",
    "buy",
    "sell",
    "dispatch",
)
APPROVED_INTERACTIVE_NAMES = re.compile(
    r"^(?:"
    r"Open Strategy Library|"
    r"Open Scenario Lab|"
    r"Compare formal set|"
    r"Select exact formal set|"
    r"Scenario Recipe Draft name|"
    r"Select admitted Historical Market Segment|"
    r"Select registered Scenario transformation|"
    r"Closed transformation first parameter value|"
    r"Select optional second registered Scenario transformation|"
    r"Closed second transformation first parameter value|"
    r"Requested commission basis points|"
    r"Requested slippage basis points|"
    r"Requested maximum fill fraction|"
    r"Requested execution latency nodes|"
    r"Scenario decision cadence minutes|"
    r"Scenario materialization seed|"
    r"Market Rule Profile version identity|"
    r"Allow requested partial fills|"
    r"Create exact immutable Scenario Recipe Draft|"
    r"Create exact immutable Compound Scenario Recipe Draft|"
    r"Audited AI Scenario Recipe intent|"
    r"Create audited AI-assisted Scenario Recipe Draft|"
    r"Create immutable successor Recipe Draft revision|"
    r"Create immutable Compound Recipe successor revision|"
    r"Select Recipe Draft .+ for successor revision|"
    r"Validate exact Recipe Draft revision \d+|"
    r"Compose visible Campaign Cases into a Scenario Set|"
    r"Resolve requested and effective execution assumptions|"
    r"Select immutable Formal Scenario Set context|"
    r"Open Diagnostic Tasks|"
    r"Create Diagnostic Task|"
    r"Correct Configuration|"
    r"Validate Configuration|"
    r"Approve Configuration|"
    r"Start Formal Diagnostic Campaign|"
    r"Open Run Monitoring|"
    r"Open Evidence and Findings|"
    r"Open System Health|"
    r"(?:Pause|Resume|Cancel) Diagnostic Task lifecycle|"
    r"(?:Pause|Resume|Cancel) Formal Diagnostic Campaign lifecycle|"
    r"(?:Pause|Resume|Cancel) Campaign node lifecycle|"
    r"Retry failed Campaign node attempt|"
    r"Pause diagnostic task|"
    r"Resume diagnostic task|"
    r"Cancel diagnostic task|"
    r"Inspect details for .+|"
    r"Select candidate .+|"
    r"Select finding .+|"
    r"Select chart overlay .+|"
    r"Select Sensitivity Breakpoint .+|"
    r"Select diagnostic evidence point|"
    r"Filter evidence by risk|"
    r"Sort evidence by coverage|"
    r"Focus compound stress evidence|"
    r"Show (?:findings|assumptions|provenance|context) tab"
    r")$"
)


class _DirectExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - Future semantics
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


class _LiveQueries:
    def get_run_monitoring_snapshot(self, run_id):
        if run_id != "RUN-SAFETY-44":
            return None
        return {
            "run_id": run_id,
            "scenario_name": "SCENARIO-SAFETY-44",
            "scenario_set_id": "SET-SAFETY-44",
            "strategy_id": "STRATEGY-SAFETY-44",
            "reproduction_manifest_id": "RM-SAFETY-44",
            "task_id": "TASK-SAFETY-44",
            "status": "running",
            "started_at": NOW - timedelta(minutes=2),
            "updated_at": NOW,
            "last_sim_day": 2,
            "last_sim_dt": NOW - timedelta(days=1),
            "completed_nodes": 2,
            "total_nodes": 5,
            "current_node_id": "NODE-SAFETY-44",
            "current_node_label": "Safety verification",
            "requested_execution": {"fee_multiplier": "1.0x"},
            "effective_execution": {"fee_multiplier": "1.6x"},
            "execution_override_reasons": {
                "fee_multiplier": "Approved recipe override"
            },
            "alerts": [],
            "market_context": ["600519.SH"],
            "account_context": ["MODEL-SAFETY-44"],
            "position_context": ["600519.SH · +100"],
            "order_context": ["ORD-SAFETY-44 · filled · read-only"],
            "fill_context": ["FILL-SAFETY-44 · 100 @ 1500"],
        }

    def get_evidence_and_findings_snapshot(self, run_id):
        if run_id != "RUN-SAFETY-44":
            return None
        return {
            "run_id": run_id,
            "revision": 44,
            "updated_at": NOW.isoformat(),
            "status": "completed",
            "selection": {
                "campaign_id": "FDC-SAFETY-44",
                "run_id": run_id,
                "strategy_id": "STRATEGY-SAFETY-44",
                "market_scenario_id": "SCENARIO-SAFETY-44",
                "approved_recipe_id": "RECIPE-SAFETY-44",
                "reproduction_manifest_id": "RM-SAFETY-44",
            },
            "candidates": [
                {
                    "candidate_id": "MODEL-SAFETY-44",
                    "label": "Safety candidate",
                    "evidence": [
                        {
                            "id": "E-SAFETY-44-BASE",
                            "coverage": "baseline",
                            "dimension": "return",
                            "label": "Safety baseline return",
                            "value": "7.4",
                            "unit": "%",
                            "availability": "complete",
                            "interpretation": "Persisted baseline evidence.",
                        },
                        {
                            "id": "E-SAFETY-44-FEE",
                            "coverage": "isolated_sensitivity",
                            "dimension": "execution",
                            "label": "Safety fee sensitivity",
                            "value": "-1.8",
                            "comparison_evidence_id": "E-SAFETY-44-BASE",
                            "comparison_value": "7.4",
                            "unit": "return delta points",
                            "availability": "complete",
                            "interpretation": "Fees reduce the result.",
                        },
                    ],
                    "comparisons": [
                        {
                            "id": "CMP-SAFETY-44-FEE",
                            "label": "Baseline versus fees",
                            "reference_evidence_id": "E-SAFETY-44-BASE",
                            "observed_evidence_id": "E-SAFETY-44-FEE",
                            "interpretation": "Fees reduce the result.",
                        }
                    ],
                    "findings": [
                        {
                            "id": "F-SAFETY-44",
                            "title": "Fee sensitivity finding",
                            "disposition": "concern",
                            "comparison_summary": "The fee case is weaker.",
                            "failure_reason": "Effective fees exceed baseline.",
                            "evidence_ids": [
                                "E-SAFETY-44-BASE",
                                "E-SAFETY-44-FEE",
                            ],
                            "comparison_ids": ["CMP-SAFETY-44-FEE"],
                            "sensitivity_breakpoints": [
                                {
                                    "id": "BP-SAFETY-44-FEE",
                                    "assumption_name": "fee_multiplier",
                                    "threshold": "1.6x",
                                    "outcome": "Return falls below the gate.",
                                    "evidence_ids": [
                                        "E-SAFETY-44-BASE",
                                        "E-SAFETY-44-FEE",
                                    ],
                                }
                            ],
                        }
                    ],
                    "execution_assumptions": [
                        {
                            "name": "fee_multiplier",
                            "requested_value": "1.0x",
                            "effective_value": "1.6x",
                            "override_reason": "Approved recipe override",
                        }
                    ],
                    "provenance": {
                        "artifact_hashes": ["sha256:safety-44"],
                        "source_run_ids": [run_id],
                        "runner_version": "evidence-runner/safety-44",
                        "build_version": "uti-stocksim/safety-44",
                        "dependencies": [
                            {
                                "name": "reproduction-manifest",
                                "version": "RM-SAFETY-44",
                                "artifact_hash": "sha256:rm-safety-44",
                            }
                        ],
                    },
                }
            ],
            "read_only_context": {
                "market": ["600519.SH"],
                "account": ["MODEL-SAFETY-44"],
                "positions": ["600519.SH · +100"],
                "orders": [
                    {
                        "id": "ORD-SAFETY-44",
                        "instrument": "600519.SH",
                        "status": "filled",
                        "diagnostic_note": "Read-only trace.",
                    }
                ],
                "fills": [
                    {
                        "id": "FILL-SAFETY-44",
                        "order_id": "ORD-SAFETY-44",
                        "instrument": "600519.SH",
                        "quantity": 100,
                        "price": "1500",
                    }
                ],
            },
        }


class _DiagnosticTasks:
    def __init__(self):
        self.calls = []

    def get_arena(self, task_id):
        if task_id != "TASK-SAFETY-44":
            return None
        return {"status": "RUNNING"}

    def pause_arena(self, task_id):
        self.calls.append(("pause_diagnostic_task", task_id))

    def resume_arena(self, task_id):
        self.calls.append(("resume_diagnostic_task", task_id))

    def cancel_diagnostic_task(self, task_id):
        self.calls.append(("cancel_diagnostic_task", task_id))

    def cancel_order(self, order_id):
        self.calls.append(("cancel_order", order_id))
        raise AssertionError("Diagnostic cancellation reached order cancel")


def _run_context():
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-SAFETY-44"),
            run_id=StrategyRunId("RUN-SAFETY-44"),
        )
    )


def _evidence_context():
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-SAFETY-44"),
            run_id=StrategyRunId("RUN-SAFETY-44"),
            strategy_id=StrategyUnderTestId("STRATEGY-SAFETY-44"),
            market_scenario_id=MarketScenarioId("SCENARIO-SAFETY-44"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-SAFETY-44"),
            reproduction_manifest_id=ReproductionManifestId("RM-SAFETY-44"),
        )
    )


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture(params=("deterministic_fake", "live"))
def mounted_v2_mode(request):
    app = QApplication.instance() or QApplication([])
    controller = _DiagnosticTasks()
    diagnostic_feature = DeterministicFakeDiagnosticTasksAdapter()
    bridge = None
    if request.param == "deterministic_fake":
        strategy_feature = DeterministicFakeStrategyLibraryAdapter()
        scenario_feature = DeterministicFakeScenarioLabAdapter()
        run_feature = DeterministicFakeRunMonitoringAdapter()
        evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
        run_feature.advance_to_running(_run_context())
        evidence_feature.advance_to_completed(_evidence_context())
    else:
        gateway = RuntimeGateway()
        gateway._queries = _LiveQueries()
        bridge = EventBridge(subscribe_backend=False)
        strategy_application = create_diagnostics_application()
        strategy_application.start()
        strategy_feature = LiveStrategyLibraryAdapter(
            application=(
                LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
                    strategy_application
                )
            ),
            event_bridge=bridge,
            clock=lambda: NOW,
        )
        scenario_feature = LiveScenarioLabAdapter(
            application=(
                LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
                    strategy_application
                )
            ),
            event_bridge=bridge,
            clock=lambda: NOW,
        )
        run_feature = LiveRunMonitoringAdapter(
            application_read_model=DictionaryFixtureApplicationReadModel(
                gateway._queries
            ),
            event_bridge=bridge,
            clock=lambda: NOW,
            executor=_DirectExecutor(),
        )
        evidence_feature = LiveEvidenceAndFindingsAdapter(
            application_read_model=DictionaryFixtureApplicationReadModel(
                gateway._queries,
                evidence_context=_evidence_context(),
            ),
            event_bridge=bridge,
            clock=lambda: NOW,
            executor=_DirectExecutor(),
        )
        run_feature.snapshot(_run_context())
        evidence_feature.snapshot(_evidence_context())
    window = MainWindow(
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        scenario_lab_feature=scenario_feature,
        diagnostic_tasks_feature=diagnostic_feature,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        run_monitoring_feature=run_feature,
        run_monitoring_context=_run_context(),
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=_evidence_context(),
        frontend_v2_enabled=True,
    )
    window.resize(1280, 720)
    window.show()
    app.processEvents()
    app.processEvents()
    yield request.param, window, run_feature, evidence_feature, controller
    window.close()
    strategy_feature.close()
    scenario_feature.close()
    diagnostic_feature.close()
    run_feature.close()
    evidence_feature.close()
    if bridge is not None:
        bridge.stop()
    app.processEvents()


def _interactive_accessible_names(root):
    names = []
    for item in (root, *root.findChildren(QObject)):
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is None or not interface.isValid():
            continue
        if interface.role() not in {
            QAccessible.Role.Button,
            QAccessible.Role.Slider,
        }:
            continue
        name = interface.text(QAccessible.Text.Name).strip()
        assert name, f"Interactive object {item.objectName()!r} is unnamed"
        names.append(name)
    return tuple(names)


def _runtime_surface_text(root):
    values = []
    for item in (root, *root.findChildren(QObject)):
        if item.objectName():
            values.append(item.objectName())
        if item.metaObject().indexOfProperty("text") >= 0:
            value = item.property("text")
            if value:
                values.append(str(value))
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is not None and interface.isValid():
            name = interface.text(QAccessible.Text.Name)
            if name:
                values.append(name)
    return "\n".join(values)


def test_qml_object_tree_navigation_and_runtime_surface_are_safe(
    mounted_v2_mode,
):
    mode, window, run_feature, evidence_feature, _controller = mounted_v2_mode
    app = QApplication.instance()
    assert app is not None
    host = window.centralWidget()
    root = host.rootObject()

    root.setProperty("activeRoute", "strategy_library")
    app.processEvents()
    app.processEvents()
    strategy_names = _interactive_accessible_names(root)
    assert "Open Strategy Library" in strategy_names
    strategy_repeater = root.findChild(
        QObject,
        "strategyLibraryEntryRepeater",
    )
    assert strategy_repeater is not None
    assert strategy_repeater.property("count") == 2

    names = list(strategy_names)
    for route, status_name in (
        ("strategy_library", "strategyLibraryAccessibleStatus"),
        ("scenario_lab", "scenarioLabAccessibleStatus"),
        ("diagnostic_tasks", "diagnosticTasksAccessibleStatus"),
        ("run_monitoring", "runMonitoringAccessibleStatus"),
        ("evidence_and_findings", "evidenceAccessibleStatus"),
    ):
        root.setProperty("activeRoute", route)
        app.processEvents()
        app.processEvents()
        status = root.findChild(QObject, status_name)
        assert status is not None
        status_interface = QAccessible.queryAccessibleInterface(status)
        assert status_interface is not None
        assert status_interface.role() == QAccessible.Role.StatusBar
        assert status_interface.text(QAccessible.Text.Name).strip()
        assert status_interface.text(QAccessible.Text.Description).strip()
        names.extend(_interactive_accessible_names(root))
        assert (
            audit_qml_text(
                f"{mode}-{route}-runtime-object-tree",
                _runtime_surface_text(root),
            )
            == ()
        )

    names = tuple(names)
    assert names
    unapproved_names = sorted(
        {
            name
            for name in names
            if APPROVED_INTERACTIVE_NAMES.fullmatch(name) is None
        }
    )
    assert unapproved_names == []
    assert any(name == "Cancel diagnostic task" for name in names)
    candidate = root.property("evidenceInitialFocusItem")
    finding = root.property("evidenceFindingFocusItem")
    candidate_interface = QAccessible.queryAccessibleInterface(candidate)
    finding_interface = QAccessible.queryAccessibleInterface(finding)
    assert candidate_interface is not None
    assert finding_interface is not None
    assert candidate_interface.text(QAccessible.Text.Name).startswith(
        "Select candidate "
    )
    assert finding_interface.text(QAccessible.Text.Name).startswith("Select finding ")
    assert (
        audit_qml_text(
            f"{mode}-runtime-object-tree",
            _runtime_surface_text(root),
        )
        == ()
    )

    route_objects = {
        item.objectName()
        for item in root.findChildren(QObject)
        if item.objectName().endswith("RouteNavigation")
    }
    assert route_objects == {
        "strategyLibraryRouteNavigation",
        "scenarioLabRouteNavigation",
        "diagnosticTasksRouteNavigation",
        "runMonitoringRouteNavigation",
        "evidenceAndFindingsRouteNavigation",
        "systemHealthRouteNavigation",
    }
    assert root.property("activeRoute") == "evidence_and_findings"
    assert window.menuBar().actions() == []
    assert window.findChildren(QAction) == []
    assert window.open_panel("market") is None
    assert window.open_panel("account") is None
    assert window.open_panel("orders") is None
    assert window.list_open() == []

    for adapter in (
        host._run_monitoring,
        host._evidence_and_findings,
        run_feature,
        evidence_feature,
    ):
        for member in FORBIDDEN_RUNTIME_MEMBERS:
            assert not hasattr(adapter, member), (
                f"{mode} exposed fallback {type(adapter).__name__}.{member}"
            )


def test_order_and_fill_evidence_renders_only_as_non_editable_context(
    mounted_v2_mode,
):
    _mode, window, _run_feature, _evidence_feature, _controller = mounted_v2_mode
    app = QApplication.instance()
    assert app is not None
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    app.processEvents()

    context_panel = root.findChild(QObject, "evidenceContextPanel")
    assert context_panel is not None
    context_text = " ".join(
        str(item.property("text"))
        for item in context_panel.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0 and item.property("text")
    )
    assert "ORD-" in context_text
    assert "FILL-" in context_text
    assert all(
        forbidden_class not in item.metaObject().className()
        for item in context_panel.findChildren(QObject)
        for forbidden_class in (
            "TextInput",
            "TextEdit",
            "SpinBox",
            "ComboBox",
        )
    )


def test_live_cancel_diagnostic_task_cannot_reach_order_cancellation():
    queries = _LiveQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    controller = _DiagnosticTasks()
    adapter = LiveRunMonitoringAdapter(
        application_read_model=DictionaryFixtureApplicationReadModel(queries),
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    state = adapter.snapshot(_run_context())
    data = state.last_reliable_data
    assert data is not None
    assert data.task_id is None

    result = adapter.cancel_diagnostic_task(
        CancelDiagnosticTask(
            target_id=DiagnosticTaskId("TASK-SAFETY-44"),
            expected_revision=state.revision,
        )
    )

    assert result.accepted is False
    assert result.task is None
    assert controller.calls == []
    adapter.close()
    bridge.stop()
