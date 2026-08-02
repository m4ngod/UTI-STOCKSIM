"""Installed-package black-box entry point for the Frontend V2 release gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from time import monotonic, sleep
from typing import Any

PRODUCTION_PATH = (
    "DiagnosticsApplication",
    "FileBackedV1Persistence",
    "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
    "LiveDiagnosticTasksAdapter",
    "LiveStrategyDiagnosticsV1ApplicationAdapter",
    "EventBridge",
    "LiveRunMonitoringAdapter",
    "LiveEvidenceAndFindingsAdapter",
    "JourneyWorkspaceHost",
)
WAVE2_ACCEPTED_COMMAND_KINDS = (
    "create_diagnostic_task",
    "revise_configuration",
    "validate_configuration",
    "approve_configuration",
    "start_formal_diagnostic_campaign",
)

EXPECTED_JOURNEY = (
    (
        "launched_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "disconnected_run",
        "run_monitoring",
        "terminal",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "disconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "reconnected_pending_run",
        "run_monitoring",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_pending_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "reconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
)
_APPROVED_INTERACTIVE_NAMES = re.compile(
    r"^(?:"
    r"Open Diagnostic Tasks|"
    r"Open Run Monitoring|"
    r"Open Evidence and Findings|"
    r"Create Diagnostic Task|"
    r"Correct Configuration|"
    r"Validate Configuration|"
    r"Approve Configuration|"
    r"Start Formal Diagnostic Campaign|"
    r"(?:Pause|Resume|Cancel) Diagnostic Task lifecycle|"
    r"(?:Pause|Resume|Cancel) Formal Diagnostic Campaign lifecycle|"
    r"(?:Pause|Resume|Cancel) Campaign node lifecycle|"
    r"Retry failed Campaign node attempt|"
    r"Pause diagnostic task|"
    r"Resume diagnostic task|"
    r"Cancel diagnostic task|"
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
_PACKAGED_NON_ACTION_FOCUS_OBJECT_NAMES = frozenset(
    {"diagnosticTaskApprovalActorInput"}
)


class RendererLane(str, Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"


@dataclass(frozen=True, slots=True)
class SmokeStateObservation:
    stage: str
    route: str
    run_state: str
    evidence_state: str
    run_freshness: str
    evidence_freshness: str
    run_phase: str
    evidence_phase: str
    run_revision: str
    evidence_revision: str
    source_generation: str
    headline: str
    detail: str
    screenshot: str | None


@dataclass(frozen=True, slots=True)
class PackageSmokeResult:
    schema_version: int
    source_commit: str
    renderer_lane: RendererLane
    graphics_api: str
    production_path: tuple[str, ...]
    campaign_identity: str
    case_identity: str
    run_identity: str
    strategy_identity: str
    approved_recipe_identity: str
    evidence_package_identity: str
    reproduction_manifest_identity: str
    artifact_hashes: tuple[str, ...]
    persistence_kind: str
    persistence_reopened: bool
    application_read_model_interface: str
    active_feature_interfaces: tuple[str, ...]
    campaign_status: str
    run_status: str
    evidence_status: str
    expected_identity_graph: tuple[str, ...]
    feature_identity_graph: tuple[str, ...]
    qml_identity_graph_checkpoints: dict[str, tuple[str, ...]]
    evidence_identity_sets: dict[str, tuple[str, ...]]
    persisted_manifest_identities: tuple[str, ...]
    persisted_run_identities: tuple[str, ...]
    raw_artifact_hashes: tuple[str, ...]
    keyboard_navigation_verified: bool
    accessibility_preferences_verified: bool
    accessibility_announcements: tuple[str, ...]
    old_generation_rejected: bool
    authoritative_reconnect_verified: bool
    routes_rendered: tuple[str, ...]
    connection_transitions: tuple[str, ...]
    observations: tuple[SmokeStateObservation, ...]
    manual_trading_action_count: int
    read_only_context_visible: bool
    errors: tuple[str, ...]
    clean_exit: bool
    fixture_kind: str = "sealed_completed_v1"
    task_created_after_install: bool = False
    campaign_created_after_install: bool = False
    diagnostic_task_identity: str = ""
    accepted_command_kinds: tuple[str, ...] = ()
    task_handle_identities: tuple[str, ...] = ()
    writable_persistence_verified: bool = False
    application_reopened: bool = False
    background_continuation_verified: bool = False
    task_cancel_order_isolation_verified: bool = False


def configure_renderer_environment(renderer_lane: RendererLane) -> None:
    if renderer_lane is RendererLane.SOFTWARE:
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QSG_RHI_BACKEND"] = "software"
        return
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ["QSG_RHI_BACKEND"] = "d3d11"


def _configure_smoke_route_identity(
    *,
    campaign_id: str,
    run_id: str,
    strategy_id: str,
    case_id: str,
    recipe_id: str,
    evidence_package_id: str,
    manifest_id: str,
) -> dict[str, str | None]:
    route_identity = {
        "STOCKSIM_FRONTEND_V2": "1",
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID": campaign_id,
        "STOCKSIM_FRONTEND_V2_RUN_ID": run_id,
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID": strategy_id,
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID": case_id,
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID": recipe_id,
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID": evidence_package_id,
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID": manifest_id,
        "STOCKSIM_TEXT_SCALE_PERCENT": "200",
        "STOCKSIM_REDUCED_MOTION": "1",
        "STOCKSIM_HIGH_CONTRAST": "1",
    }
    previous = {name: os.environ.get(name) for name in route_identity}
    os.environ.update(route_identity)
    return previous


def _configure_wave2_smoke_environment() -> dict[str, str | None]:
    environment = {
        "STOCKSIM_FRONTEND_V2": "1",
        "STOCKSIM_TEXT_SCALE_PERCENT": "200",
        "STOCKSIM_REDUCED_MOTION": "1",
        "STOCKSIM_HIGH_CONTRAST": "1",
    }
    identity_names = (
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "STOCKSIM_FRONTEND_V2_RUN_ID",
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID",
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID",
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID",
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID",
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
    )
    previous = {
        name: os.environ.get(name)
        for name in (*environment, *identity_names)
    }
    for name in identity_names:
        os.environ.pop(name, None)
    os.environ.update(environment)
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _create_production_window(
    *,
    event_bridge: Any,
    settings_path: Path,
    runtime_gateway: Any | None = None,
    strategy_diagnostics_read_model: Any | None = None,
    strategy_diagnostics_tasks_application: Any | None = None,
) -> tuple[Any, Any, Any]:
    from app.app_context import build_app_context
    from app.ui.main_window import MainWindow

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="live",
        event_bridge=event_bridge,
        runtime_gateway=runtime_gateway,
        strategy_diagnostics_read_model=strategy_diagnostics_read_model,
        strategy_diagnostics_tasks_application=(
            strategy_diagnostics_tasks_application
        ),
    )
    window = None
    try:
        window = MainWindow(
            diagnostic_tasks_feature=context.diagnostic_tasks_feature,
            diagnostic_tasks_context=context.diagnostic_tasks_context,
            run_monitoring_feature=context.run_monitoring_feature,
            run_monitoring_context=context.run_monitoring_context,
            evidence_and_findings_feature=(
                context.evidence_and_findings_feature
            ),
            evidence_and_findings_context=(
                context.evidence_and_findings_context
            ),
            frontend_v2_enabled=True,
        )
        if not window.journey_workspace_active:
            raise RuntimeError(
                "Production AppContext did not mount the Journey Workspace"
            )
    except BaseException:
        workspace = (
            None
            if window is None
            else getattr(window, "_journey_workspace", None)
        )
        cleanup_actions = (
            (
                workspace.close_adapter
                if workspace is not None
                else None
            ),
            window.close if window is not None else None,
            context.diagnostic_tasks_feature.close,
            context.run_monitoring_feature.close,
            context.evidence_and_findings_feature.close,
        )
        for action in cleanup_actions:
            if action is None:
                continue
            try:
                action()
            except BaseException:
                pass
        raise
    return context, window, window._journey_workspace


def _key_click(host: Any, key: Any, modifiers: Any) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QKeyEvent

    for event_type in (
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
    ):
        QCoreApplication.sendEvent(
            host,
            QKeyEvent(event_type, key, modifiers),
        )


def _type_text_with_keyboard(host: Any, text: str) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    for character in text:
        for event_type in (
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
        ):
            QCoreApplication.sendEvent(
                host,
                QKeyEvent(
                    event_type,
                    Qt.Key.Key_unknown,
                    Qt.KeyboardModifier.NoModifier,
                    character,
                ),
            )


@contextmanager
def _serialized_application_access(
    application: Any,
) -> Iterator[None]:
    from app.features._diagnostics_application_access import (
        shared_diagnostics_application_access_gate,
    )

    with shared_diagnostics_application_access_gate(application):
        yield


def _focus_with_keyboard(
    *,
    app: Any,
    host: Any,
    target: Any,
    backwards: bool = False,
) -> None:
    from PySide6.QtCore import Qt

    for _ in range(80):
        if target.property("activeFocus"):
            return
        _key_click(
            host,
            Qt.Key.Key_Tab,
            (
                Qt.KeyboardModifier.ShiftModifier
                if backwards
                else Qt.KeyboardModifier.NoModifier
            ),
        )
        app.processEvents()
    raise RuntimeError(
        "Keyboard focus did not reach "
        f"{target.property('objectName')!r}"
    )


def _navigate_route(
    *,
    app: Any,
    host: Any,
    root: Any,
    route: str,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtQuick import QQuickItem

    object_name = {
        "diagnostic_tasks": "diagnosticTasksRouteNavigation",
        "run_monitoring": "runMonitoringRouteNavigation",
        "evidence_and_findings": (
            "evidenceAndFindingsRouteNavigation"
        ),
    }[route]
    target = root.findChild(QQuickItem, object_name)
    if target is None:
        raise RuntimeError(f"Route control is unavailable: {object_name}")
    if root.property("activeRoute") != route:
        _focus_with_keyboard(
            app=app,
            host=host,
            target=target,
            backwards=route == "run_monitoring",
        )
        _key_click(
            host,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        _settle_until(
            app,
            lambda: root.property("activeRoute") == route,
            f"keyboard navigation to {route}",
        )


def _qml_semantic_values(item: Any) -> tuple[str, ...]:
    meta = item.metaObject()
    values: list[str] = []
    for property_name in (
        "text",
        "accessibleName",
        "accessibleDescription",
    ):
        if meta.indexOfProperty(property_name) < 0:
            continue
        value = item.property(property_name)
        if value:
            values.append(str(value))
    return tuple(dict.fromkeys(values))


def _visible_and_accessible_text(root: Any) -> str:
    from PySide6.QtCore import QObject

    rendered: list[str] = []
    for item in (root, *root.findChildren(QObject)):
        meta = item.metaObject()
        visible = (
            bool(item.property("visible"))
            if meta.indexOfProperty("visible") >= 0
            else True
        )
        if visible:
            rendered.extend(_qml_semantic_values(item))
    return "\n".join(rendered)


def _focus_accessible_name_with_keyboard(
    *,
    app: Any,
    host: Any,
    accessible_name: str,
) -> Any:
    from PySide6.QtCore import Qt

    quick_window = host.quickWindow()
    if quick_window is None:
        raise RuntimeError("Journey Workspace Quick Window is unavailable")
    if not host.hasFocus():
        host.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
    for _ in range(120):
        item = quick_window.activeFocusItem()
        if item is None:
            _key_click(
                host,
                Qt.Key.Key_Tab,
                Qt.KeyboardModifier.NoModifier,
            )
            app.processEvents()
            continue
        if any(
            value.casefold() == accessible_name.casefold()
            for value in _qml_semantic_values(item)
        ):
            return item
        _key_click(
            host,
            Qt.Key.Key_Tab,
            Qt.KeyboardModifier.NoModifier,
        )
        app.processEvents()
    raise RuntimeError(
        "Keyboard focus did not reach accessible control "
        f"{accessible_name!r}"
    )


def _keyboard_accessible_focus_cycle(
    *,
    app: Any,
    host: Any,
    steps: int = 120,
) -> str:
    from PySide6.QtCore import Qt

    quick_window = host.quickWindow()
    if quick_window is None:
        raise RuntimeError("Journey Workspace Quick Window is unavailable")
    rendered: list[str] = []
    for _ in range(steps):
        item = quick_window.activeFocusItem()
        if item is not None:
            rendered.extend(_qml_semantic_values(item))
        _key_click(
            host,
            Qt.Key.Key_Tab,
            Qt.KeyboardModifier.NoModifier,
        )
        app.processEvents()
    return "\n".join(value for value in rendered if value)


def _collect_qml_identity_checkpoint(
    *,
    app: Any,
    host: Any,
    root: Any,
    expected: tuple[str, ...],
) -> tuple[str, ...]:
    from PySide6.QtCore import Qt

    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    rendered = [
        _visible_and_accessible_text(root),
        _keyboard_accessible_focus_cycle(
            app=app,
            host=host,
        ),
    ]
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="evidence_and_findings",
    )
    rendered.append(_visible_and_accessible_text(root))
    candidate_controls = tuple(
        item
        for item in (
            root.property("evidenceInitialFocusItem"),
            root.property("evidenceSecondCandidateFocusItem"),
        )
        if item is not None
    )
    if not candidate_controls:
        raise RuntimeError("No QML Evidence candidate control is available")
    for candidate in candidate_controls:
        candidate_name = str(candidate.property("accessibleName") or "")
        if not candidate_name:
            raise RuntimeError(
                "Evidence candidate lacks a packaged accessible name"
            )
        candidate = _focus_accessible_name_with_keyboard(
            app=app,
            host=host,
            accessible_name=candidate_name,
        )
        _key_click(
            host,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        app.processEvents()
        for tab_name in (
            "Findings",
            "Assumptions",
            "Provenance",
            "Context",
        ):
            _focus_accessible_name_with_keyboard(
                app=app,
                host=host,
                accessible_name=f"Show {tab_name.casefold()} tab",
            )
            _key_click(
                host,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            )
            app.processEvents()
            rendered.append(_visible_and_accessible_text(root))
            if tab_name == "Findings":
                rendered.append(
                    _keyboard_accessible_focus_cycle(
                        app=app,
                        host=host,
                    )
                )
        rendered.append(
            _keyboard_accessible_focus_cycle(
                app=app,
                host=host,
            )
        )
    qml_text = "\n".join(rendered)
    return tuple(
        identity for identity in expected if identity in qml_text
    )


def _typed_string_values(value: Any) -> tuple[str, ...]:
    values: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            values.append(item)
            return
        if isinstance(item, Enum):
            visit(item.value)
            return
        if is_dataclass(item) and not isinstance(item, type):
            for field in fields(item):
                visit(getattr(item, field.name))
            return
        if isinstance(item, (tuple, list, set, frozenset)):
            for member in item:
                visit(member)

    visit(value)
    return tuple(values)


def _feature_identity_graph(
    *,
    context: Any,
    expected: tuple[str, ...],
    diagnostic_tasks_adapter: Any | None = None,
) -> tuple[str, ...]:
    run_context = context.run_monitoring_context
    evidence_context = context.evidence_and_findings_context
    if diagnostic_tasks_adapter is not None:
        handed_off_run_context = diagnostic_tasks_adapter.monitoring_context()
        handed_off_evidence_context = diagnostic_tasks_adapter.evidence_context()
        if handed_off_run_context is not None:
            run_context = handed_off_run_context
        if handed_off_evidence_context is not None:
            evidence_context = handed_off_evidence_context
    diagnostic_state = context.diagnostic_tasks_feature.snapshot(
        context.diagnostic_tasks_context
    )
    run_state = context.run_monitoring_feature.snapshot(
        run_context
    )
    evidence_state = context.evidence_and_findings_feature.snapshot(
        evidence_context
    )
    feature_text = "\n".join(
        _typed_string_values(
            (diagnostic_state, run_state, evidence_state)
        )
    )
    return tuple(
        identity for identity in expected if identity in feature_text
    )


def _accessibility_preferences_verified(root: Any) -> bool:
    from PySide6.QtCore import QObject

    tokens = root.findChild(QObject, "designTokens")
    return bool(
        tokens is not None
        and tokens.property("textScale") == 2.0
        and tokens.property("durationForMotion") == 0
        and tokens.property("highContrast") is True
    )


def _accessible_announcement(root: Any, object_name: str) -> str:
    from PySide6.QtCore import QObject

    item = root.findChild(QObject, object_name)
    if item is None:
        raise RuntimeError(
            f"Accessible status object is unavailable: {object_name}"
        )
    values = [
        value
        for child in (item, *item.findChildren(QObject))
        for value in _qml_semantic_values(child)
    ]
    if not values:
        raise RuntimeError(
            f"Accessible status content is unavailable: {object_name}"
        )
    return " ".join(dict.fromkeys(values))


def _start_installed_wave2_commands(
    *,
    app: Any,
    host: Any,
    root: Any,
    context: Any,
    application: Any,
) -> tuple[Any, tuple[str, ...]]:
    from PySide6.QtCore import Qt
    from PySide6.QtQuick import QQuickItem

    from app.features import (
        DiagnosticTaskLifecycle,
    )

    workspace = context.diagnostic_tasks_context
    feature = context.diagnostic_tasks_feature
    projection = host._diagnostic_tasks
    if projection is None:
        raise RuntimeError("Diagnostic Tasks QML Adapter is unavailable")

    def current_task() -> Any | None:
        feature.snapshot(workspace)
        return feature.snapshot(workspace).task

    def activate(
        object_name: str,
        *,
        completed: Callable[[], bool],
    ) -> None:
        target = root.findChild(QQuickItem, object_name)
        if target is None:
            raise RuntimeError(
                f"Installed Diagnostic Tasks action is absent: {object_name}"
            )
        _settle_until(
            app,
            lambda: bool(target.property("enabled")),
            f"{object_name} enabled",
        )
        _focus_with_keyboard(
            app=app,
            host=host,
            target=target,
        )
        _key_click(
            host,
            Qt.Key.Key_Space,
            Qt.KeyboardModifier.NoModifier,
        )
        _settle_until(
            app,
            completed,
            f"{object_name} authoritative completion",
        )

    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    _settle_until(
        app,
        lambda: projection.property("presentationState") == "ready",
        "installed authoritative Diagnostic Tasks inventory",
    )
    if projection.property("reproductionManifestStatus") != (
        "not_yet_available"
    ):
        raise RuntimeError(
            "Installed input fixture predicted a Reproduction Manifest "
            "before the Campaign was created"
        )

    activate(
        "createDiagnosticTaskButton",
        completed=lambda: current_task() is not None,
    )
    created = current_task()
    if created is None:
        raise RuntimeError("Installed QML did not create a Diagnostic Task")
    created_revision = created.revision

    activate(
        "reviseDiagnosticTaskButton",
        completed=lambda: bool(
            (task := current_task()) is not None
            and task.revision > created_revision
        ),
    )
    activate(
        "validateDiagnosticTaskButton",
        completed=lambda: bool(
            (task := current_task()) is not None
            and task.validation.state.value == "valid"
        ),
    )

    actor = root.findChild(
        QQuickItem,
        "diagnosticTaskApprovalActorInput",
    )
    if actor is None:
        raise RuntimeError("Installed approval actor input is unavailable")
    _focus_with_keyboard(
        app=app,
        host=host,
        target=actor,
    )
    _type_text_with_keyboard(host, "installed-release-owner")
    app.processEvents()
    activate(
        "approveDiagnosticTaskButton",
        completed=lambda: bool(
            (task := current_task()) is not None
            and task.lifecycle is DiagnosticTaskLifecycle.APPROVED
        ),
    )
    activate(
        "startDiagnosticCampaignButton",
        completed=lambda: bool(
            (task := current_task()) is not None
            and task.handoff.campaign_id is not None
        ),
    )
    running = current_task()
    if running is None or running.handoff.campaign_id is None:
        raise RuntimeError(
            "Installed QML did not start a Formal Diagnostic Campaign"
        )

    with _serialized_application_access(application):
        started_campaign = application.diagnostic_campaign_status(
            running.handoff.campaign_id.value
        )
    first_incomplete = next(
        (
            case
            for case in started_campaign.cases
            if case.status == "incomplete"
        ),
        None,
    )
    if first_incomplete is not None:
        raise RuntimeError(
            "Installed Campaign start produced an incomplete first node: "
            + json.dumps(
                first_incomplete.attempts[-1].to_dict(),
                sort_keys=True,
            )
        )
    if started_campaign.status == "completed":
        raise RuntimeError(
            "Installed Campaign reached terminal state before background "
            "continuation and recovery were exercised"
        )
    if (
        running.handoff.evidence_package_id is not None
        or running.handoff.reproduction_manifest_id is not None
    ):
        raise RuntimeError(
            "Installed Campaign exposed Evidence or a Reproduction Manifest "
            "before terminal completion"
        )
    return running, WAVE2_ACCEPTED_COMMAND_KINDS


def _complete_installed_wave2_campaign(
    *,
    app: Any,
    host: Any,
    context: Any,
    application: Any,
    diagnostic_task_id: str,
) -> tuple[Any, bool, str]:
    from app.features import (
        CancelDiagnosticTarget,
        DiagnosticCommandId,
        DiagnosticCommandIdempotencyKey,
        DiagnosticTaskLifecycle,
        DiagnosticTaskTarget,
        DiagnosticTasksCommandDisposition,
        DiagnosticTasksContext,
        DiagnosticTaskId,
    )

    workspace = DiagnosticTasksContext(
        task_id=DiagnosticTaskId(diagnostic_task_id)
    )
    feature = context.diagnostic_tasks_feature
    projection = host._diagnostic_tasks
    if projection is None:
        raise RuntimeError("Diagnostic Tasks QML Adapter is unavailable")

    def current_task() -> Any | None:
        feature.snapshot(workspace)
        return feature.snapshot(workspace).task

    running = current_task()
    if running is None or running.handoff.campaign_id is None:
        raise RuntimeError(
            "Installed nonterminal Diagnostic Task is unavailable after reopen"
        )

    with _serialized_application_access(application):
        completed_campaign = application.advance_diagnostic_campaign(
            running.handoff.campaign_id.value,
            max_cases=64,
            nodes_per_batch=10_000,
        )
    if completed_campaign.status != "completed":
        raise RuntimeError(
            "Installed Formal Diagnostic Campaign did not reach terminal "
            f"state: status={completed_campaign.status}; cases="
            f"{tuple((case.layer, case.status) for case in completed_campaign.cases)}"
        )
    projection.refresh()
    _settle_until(
        app,
        lambda: bool(
            (task := current_task()) is not None
            and task.lifecycle is DiagnosticTaskLifecycle.COMPLETED
            and task.handoff.evidence_package_id is not None
            and task.handoff.reproduction_manifest_id is not None
        ),
        "installed Diagnostic Task evidence handoff",
    )
    completed = current_task()
    if completed is None:
        raise RuntimeError("Installed completed Diagnostic Task is unavailable")
    evidence_context = projection.evidence_context()
    evidence_selection = (
        None if evidence_context is None else evidence_context.selection
    )
    if (
        evidence_selection is None
        or evidence_selection.reproduction_manifest_id is None
    ):
        raise RuntimeError(
            "Installed QML projection did not emit an Evidence handoff"
        )

    cancellation_result = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId(
                "installed-terminal-diagnostic-cancel-probe"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "installed-terminal-diagnostic-cancel-probe"
            ),
            target=DiagnosticTaskTarget(completed.task_id),
            expected_revision=completed.revision,
        )
    )
    after_probe = current_task()
    cancel_isolation_verified = bool(
        cancellation_result.disposition
        is DiagnosticTasksCommandDisposition.REJECTED
        and cancellation_result.task_handle is None
        and after_probe is not None
        and after_probe.task_id == completed.task_id
        and after_probe.revision == completed.revision
        and after_probe.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    )
    if not cancel_isolation_verified:
        raise RuntimeError(
            "Installed diagnostic cancellation did not fail closed at "
            "the terminal typed Diagnostic Task target"
        )
    return (
        completed,
        cancel_isolation_verified,
        evidence_selection.reproduction_manifest_id.value,
    )


def _assert_running_wave2_public_state(
    *,
    application: Any,
    diagnostic_task_id: str,
    campaign_id: str,
    task_handle_identities: tuple[str, ...],
) -> Any:
    with _serialized_application_access(application):
        task = application.get_diagnostic_task(diagnostic_task_id)
        campaign = application.diagnostic_campaign_status(campaign_id)
    if task is None:
        raise RuntimeError(
            "The installed Diagnostic Task is unavailable through public "
            "Application behavior"
        )
    handoff = task.campaign_handoff
    observed_handles = tuple(
        handle.task_handle_id for handle in task.task_handles
    )
    task_lifecycle = getattr(task.lifecycle, "value", str(task.lifecycle))
    campaign_lifecycle = (
        None
        if handoff is None
        else getattr(
            handoff.campaign_lifecycle,
            "value",
            str(handoff.campaign_lifecycle),
        )
    )
    if (
        task.task_id != diagnostic_task_id
        or task_lifecycle != "running"
        or observed_handles != task_handle_identities
        or handoff is None
        or handoff.campaign_id != campaign_id
        or campaign_lifecycle != "running"
        or handoff.evidence_package_id is not None
        or handoff.reproduction_manifest_id is not None
        or campaign.status == "completed"
        or not any(case.status != "completed" for case in campaign.cases)
    ):
        raise RuntimeError(
            "Installed nonterminal task/Campaign continuity changed: "
            f"task={task.task_id!r}/{task_lifecycle!r}, "
            f"handles={observed_handles!r}, "
            f"campaign={None if handoff is None else handoff.campaign_id!r}/"
            f"{campaign.status!r}/{campaign_lifecycle!r}"
        )
    return task


def _completed_wave2_fixture(
    *,
    input_fixture: Any,
    task: Any,
    selected_manifest_id: str,
) -> Any:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FileBackedFormalV1ReleaseFixture,
    )

    campaign_id = task.handoff.campaign_id
    evidence_package_id = task.handoff.evidence_package_id
    if (
        campaign_id is None
        or evidence_package_id is None
        or not selected_manifest_id
    ):
        raise RuntimeError(
            "Completed installed task lacks Campaign/evidence/manifest handoff"
        )
    application = input_fixture.application
    with _serialized_application_access(application):
        package = application.diagnostic_evidence_status(
            evidence_package_id.value
        )
        manifests = tuple(
            application.reproduction_manifests(evidence_package_id.value)
        )
    selected_manifest = next(
        (
            candidate
            for candidate in manifests
            if candidate.manifest_id == selected_manifest_id
        ),
        None,
    )
    if selected_manifest is None:
        raise RuntimeError(
            "Installed Reproduction Manifest did not resolve publicly"
        )
    with _serialized_application_access(application):
        selected_run = application.strategy_run_status(
            selected_manifest.run_id
        )
        campaign = application.diagnostic_campaign_status(
            campaign_id.value
        )
    return FileBackedFormalV1ReleaseFixture(
        application=application,
        engine=input_fixture.engine,
        campaign=campaign,
        selected_run=selected_run,
        evidence_package=package,
        selected_manifest=selected_manifest,
        manifests=manifests,
        database_path=input_fixture.database_path,
        artifact_root=input_fixture.artifact_root,
    )


def run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str = "development-smoke",
    capture_images: bool = True,
    fixture_archive_path: Path | None = None,
) -> PackageSmokeResult:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    cleanup_errors: list[str] = []
    lifecycle_checks: list[Callable[[], bool]] = []
    with ExitStack() as cleanup:
        if (
            fixture_archive_path is None
            or fixture_archive_path.name
            == WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
        ):
            result = _run_wave2_smoke_journey(
                report_dir=report_dir,
                renderer_lane=renderer_lane,
                source_commit=source_commit,
                capture_images=capture_images,
                fixture_archive_path=fixture_archive_path,
                cleanup=cleanup,
                cleanup_errors=cleanup_errors,
                lifecycle_checks=lifecycle_checks,
            )
        else:
            result = _run_smoke_journey(
                report_dir=report_dir,
                renderer_lane=renderer_lane,
                source_commit=source_commit,
                capture_images=capture_images,
                fixture_archive_path=fixture_archive_path,
                cleanup=cleanup,
                cleanup_errors=cleanup_errors,
                lifecycle_checks=lifecycle_checks,
            )
    clean_exit = bool(
        not cleanup_errors
        and lifecycle_checks
        and all(check() for check in lifecycle_checks)
    )
    errors = tuple(cleanup_errors)
    if not clean_exit and not errors:
        errors = ("Release smoke resource lifecycle did not close cleanly",)
    finalized = replace(
        result,
        errors=errors,
        clean_exit=clean_exit,
    )
    _write_smoke_report(
        finalized,
        report_dir / "smoke-report.json",
    )
    return finalized


def _run_wave2_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str,
    capture_images: bool,
    fixture_archive_path: Path | None,
    cleanup: ExitStack,
    cleanup_errors: list[str],
    lifecycle_checks: list[Callable[[], bool]],
) -> PackageSmokeResult:
    return _run_smoke_journey(
        report_dir=report_dir,
        renderer_lane=renderer_lane,
        source_commit=source_commit,
        capture_images=capture_images,
        fixture_archive_path=fixture_archive_path,
        cleanup=cleanup,
        cleanup_errors=cleanup_errors,
        lifecycle_checks=lifecycle_checks,
        wave2_mode=True,
    )


def _run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str,
    capture_images: bool,
    fixture_archive_path: Path | None,
    cleanup: ExitStack,
    cleanup_errors: list[str],
    lifecycle_checks: list[Callable[[], bool]],
    wave2_mode: bool = False,
) -> PackageSmokeResult:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import EventBridge
    from app.features import (
        ACTIVE_FEATURE_INTERFACES,
        LiveStrategyDiagnosticsV1ApplicationAdapter,
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        create_file_backed_formal_v1_release_fixture,
        create_file_backed_wave2_release_input_fixture,
        extract_sealed_formal_v1_release_fixture_archive,
        extract_sealed_wave2_release_input_fixture_archive,
        open_sealed_formal_v1_release_fixture,
        open_sealed_wave2_release_input_fixture,
        reopen_active_wave2_release_input_fixture,
        reopen_completed_wave2_release_fixture,
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    fixture: Any
    if wave2_mode and fixture_archive_path is None:
        persistence_root = report_dir / "v1-persistence"
        fixture = create_file_backed_wave2_release_input_fixture(
            database_path=(
                persistence_root / "strategy-diagnostics-v1.sqlite3"
            ),
            artifact_root=persistence_root / "artifacts",
        )
    elif wave2_mode:
        runtime_root = Path(
            cleanup.enter_context(
                tempfile.TemporaryDirectory(prefix="uti-wave2-runtime-")
            )
        )
        lifecycle_checks.append(
            _path_absent_check(runtime_root)
        )
        persistence_root = runtime_root / "v1-persistence"
        if fixture_archive_path is None:
            raise RuntimeError("Wave 2 input fixture archive is unavailable")
        extract_sealed_wave2_release_input_fixture_archive(
            archive_path=fixture_archive_path,
            bundle_root=persistence_root,
        )
        fixture = open_sealed_wave2_release_input_fixture(
            bundle_root=persistence_root,
            expected_source_commit=source_commit,
        )
    elif fixture_archive_path is None:
        persistence_root = report_dir / "v1-persistence"
        fixture = create_file_backed_formal_v1_release_fixture(
            database_path=(
                persistence_root / "strategy-diagnostics-v1.sqlite3"
            ),
            artifact_root=persistence_root / "artifacts",
        )
    else:
        runtime_root = Path(
            cleanup.enter_context(
                tempfile.TemporaryDirectory(prefix="uti-v1-runtime-")
            )
        )
        lifecycle_checks.append(
            _path_absent_check(runtime_root)
        )
        persistence_root = runtime_root / "v1-persistence"
        extract_sealed_formal_v1_release_fixture_archive(
            archive_path=fixture_archive_path,
            bundle_root=persistence_root,
        )
        fixture = open_sealed_formal_v1_release_fixture(
            bundle_root=persistence_root,
            expected_source_commit=source_commit,
        )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "Strategy Diagnostics V1 fixture",
        fixture.close,
    )
    lifecycle_checks.append(_closed_check(fixture))
    if wave2_mode:
        campaign_id = ""
        case_id = ""
        run_id = ""
        strategy_id = ""
        recipe_id = ""
        evidence_package_id = ""
        manifest_id = ""
        evidence_status = ""
        expected_identity_graph: tuple[str, ...] = ()
    else:
        specification = fixture.selected_run.specification
        campaign_id = fixture.campaign.campaign_id
        case_id = fixture.selected_manifest.case_id
        run_id = fixture.selected_run.run_id
        strategy_id = specification.strategy_id
        recipe_id = specification.recipe_version_id
        evidence_package_id = fixture.evidence_package.evidence_package_id
        manifest_id = fixture.selected_manifest.manifest_id
        evidence_status = str(
            fixture.evidence_package.sealed_payload()["status"]
        )
        expected_identity_graph = fixture.expected_identity_graph
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        fixture.application,
        fixture.engine,
    )
    diagnostic_tasks_application = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            fixture.application
        )
    )
    interface_version = read_model.interface_version
    application_interface = (
        "StrategyDiagnosticsV1ApplicationReadModel/"
        f"{interface_version.major}.{interface_version.minor}"
    )
    active_interfaces = tuple(
        f"{descriptor.name.value}/{descriptor.version.render()}"
        for descriptor in ACTIVE_FEATURE_INTERFACES
    )

    app = QApplication.instance() or QApplication([])
    bridge = EventBridge(subscribe_backend=False)
    previous_environment = (
        _configure_wave2_smoke_environment()
        if wave2_mode
        else _configure_smoke_route_identity(
            campaign_id=campaign_id,
            run_id=run_id,
            strategy_id=strategy_id,
            case_id=case_id,
            recipe_id=recipe_id,
            evidence_package_id=evidence_package_id,
            manifest_id=manifest_id,
        )
    )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "release environment",
        lambda: _restore_environment(previous_environment),
    )
    lifecycle_checks.append(_environment_restored_check(previous_environment))
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "EventBridge",
        bridge.stop,
    )
    bridge.start()
    lifecycle_checks.append(_bridge_stopped_check(bridge))
    observations: list[SmokeStateObservation] = []
    qml_identity_graph_checkpoints: dict[str, tuple[str, ...]] = {}
    accessibility_announcements: list[str] = []
    accessibility_preferences: list[bool] = []
    keyboard_routes: set[str] = set()

    def feature_authority_signature() -> tuple[object, ...]:
        run_state = context.run_monitoring_feature.snapshot(
            context.run_monitoring_context
        )
        evidence_state = context.evidence_and_findings_feature.snapshot(
            context.evidence_and_findings_context
        )
        return (
            run_state.source.generation.value,
            run_state.last_reliable_data,
            evidence_state.source.generation.value,
            evidence_state.last_reliable_data,
        )

    def register_mount(
        *,
        context: Any,
        window: Any,
        host: Any,
    ) -> Callable[[], None]:
        state = {"closed": False}

        def close_mount() -> None:
            if state["closed"]:
                return
            _close_mount(
                app=app,
                context=context,
                window=window,
                host=host,
                errors=cleanup_errors,
            )
            state["closed"] = True

        cleanup.callback(close_mount)
        def mount_closed() -> bool:
            return bool(
                state["closed"]
                and _mount_is_closed(context, window, host)
            )

        lifecycle_checks.append(mount_closed)
        return close_mount

    context, window, host = _create_production_window(
        event_bridge=bridge,
        strategy_diagnostics_read_model=read_model,
        strategy_diagnostics_tasks_application=diagnostic_tasks_application,
        settings_path=report_dir / "frontend-v2-settings.json",
    )
    close_initial_mount = register_mount(
        context=context,
        window=window,
        host=host,
    )
    window.setObjectName("frontendV2PackageWindow")
    window.resize(1280, 720)
    window.show()
    app.processEvents()
    root = host.rootObject()
    if root is None:
        raise RuntimeError("Journey Workspace root object is unavailable")
    accessibility_preferences.append(
        _accessibility_preferences_verified(root)
    )

    diagnostic_task_identity = ""
    accepted_command_kinds: tuple[str, ...] = ()
    task_handle_identities: tuple[str, ...] = ()
    cancel_order_isolation_verified = False
    application_reopened = False
    writable_persistence_verified = False
    background_continuation_verified = False
    if wave2_mode:
        input_fixture: Any = fixture
        (
            running_task,
            accepted_command_kinds,
        ) = _start_installed_wave2_commands(
            app=app,
            host=host,
            root=root,
            context=context,
            application=input_fixture.application,
        )
        diagnostic_task_identity = running_task.task_id.value
        task_handle_identities = tuple(
            handle.identity.value
            for handle in running_task.task_handles
        )
        running_campaign_id = running_task.handoff.campaign_id
        if running_campaign_id is None:
            raise RuntimeError(
                "Installed running Diagnostic Task lacks a Campaign identity"
            )
        campaign_id = running_campaign_id.value
        _assert_running_wave2_public_state(
            application=input_fixture.application,
            diagnostic_task_id=diagnostic_task_identity,
            campaign_id=campaign_id,
            task_handle_identities=task_handle_identities,
        )

        for route in (
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        ):
            _navigate_route(
                app=app,
                host=host,
                root=root,
                route=route,
            )
            keyboard_routes.add(route)
            expected_route = route
            _settle_until(
                app,
                lambda: root.property("activeRoute") == expected_route,
                f"nonterminal {route} route",
            )
            _assert_running_wave2_public_state(
                application=input_fixture.application,
                diagnostic_task_id=diagnostic_task_identity,
                campaign_id=campaign_id,
                task_handle_identities=task_handle_identities,
            )

        preterminal_generation = bridge.connection_generation
        bridge.mark_disconnected()
        for route in (
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        ):
            _navigate_route(
                app=app,
                host=host,
                root=root,
                route=route,
            )
            expected_route = route
            _settle_until(
                app,
                lambda: root.property("activeRoute") == expected_route,
                f"disconnected nonterminal {route} route",
            )
            _assert_running_wave2_public_state(
                application=input_fixture.application,
                diagnostic_task_id=diagnostic_task_identity,
                campaign_id=campaign_id,
                task_handle_identities=task_handle_identities,
            )

        preterminal_connection = bridge.mark_reconnected()
        monitoring_context = host._diagnostic_tasks.monitoring_context()
        monitoring_selection = (
            None
            if monitoring_context is None
            else monitoring_context.selection
        )
        if (
            monitoring_selection is None
            or monitoring_selection.run_id is None
        ):
            raise RuntimeError(
                "Installed nonterminal Campaign did not hand off a Run "
                "Monitoring identity"
            )
        preterminal_run_id = monitoring_selection.run_id.value
        bridge.on_snapshot(
            {"run_id": preterminal_run_id},
            generation=preterminal_connection.generation,
        )
        bridge.flush(force=True)
        app.processEvents()
        preterminal_current_signature = feature_authority_signature()
        bridge.on_snapshot(
            {"run_id": preterminal_run_id},
            generation=preterminal_generation,
        )
        bridge.flush(force=True)
        app.processEvents()
        preterminal_old_generation_rejected = bool(
            feature_authority_signature() == preterminal_current_signature
        )
        if not preterminal_old_generation_rejected:
            raise RuntimeError(
                "A stale EventBridge generation changed the nonterminal "
                "typed Feature state"
            )

        close_initial_mount()
        input_fixture.close()
        fixture = reopen_active_wave2_release_input_fixture(
            bundle_root=persistence_root,
            diagnostic_task_id=diagnostic_task_identity,
            campaign_id=campaign_id,
        )
        cleanup.callback(
            _record_cleanup,
            cleanup_errors,
            "reopened active installed Wave 2 fixture",
            fixture.close,
        )
        lifecycle_checks.append(_closed_check(fixture))
        input_fixture = fixture
        _assert_running_wave2_public_state(
            application=input_fixture.application,
            diagnostic_task_id=diagnostic_task_identity,
            campaign_id=campaign_id,
            task_handle_identities=task_handle_identities,
        )
        read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
            input_fixture.application,
            input_fixture.engine,
        )
        diagnostic_tasks_application = (
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                input_fixture.application
            )
        )
        application_reopened = True
        context, window, host = _create_production_window(
            event_bridge=bridge,
            strategy_diagnostics_read_model=read_model,
            strategy_diagnostics_tasks_application=(
                diagnostic_tasks_application
            ),
            settings_path=report_dir / "frontend-v2-settings.json",
        )
        close_initial_mount = register_mount(
            context=context,
            window=window,
            host=host,
        )
        window.setObjectName("frontendV2PackageActiveRemountWindow")
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        root = host.rootObject()
        if root is None:
            raise RuntimeError(
                "Nonterminal remounted Journey Workspace is unavailable"
            )
        accessibility_preferences.append(
            _accessibility_preferences_verified(root)
        )
        for route in (
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        ):
            _navigate_route(
                app=app,
                host=host,
                root=root,
                route=route,
            )
            expected_route = route
            _settle_until(
                app,
                lambda: root.property("activeRoute") == expected_route,
                f"reopened nonterminal {route} route",
            )
            _assert_running_wave2_public_state(
                application=input_fixture.application,
                diagnostic_task_id=diagnostic_task_identity,
                campaign_id=campaign_id,
                task_handle_identities=task_handle_identities,
            )
        background_continuation_verified = True

        (
            completed_task,
            cancel_order_isolation_verified,
            selected_manifest_id,
        ) = _complete_installed_wave2_campaign(
            app=app,
            host=host,
            context=context,
            application=input_fixture.application,
            diagnostic_task_id=diagnostic_task_identity,
        )
        completed_handle_identities = tuple(
            handle.identity.value
            for handle in completed_task.task_handles
        )
        if completed_handle_identities != task_handle_identities:
            raise RuntimeError(
                "Installed TaskHandle identities changed while the Campaign "
                "continued to terminal state"
            )
        fixture = _completed_wave2_fixture(
            input_fixture=input_fixture,
            task=completed_task,
            selected_manifest_id=selected_manifest_id,
        )
        specification = fixture.selected_run.specification
        campaign_id = fixture.campaign.campaign_id
        case_id = fixture.selected_manifest.case_id
        run_id = fixture.selected_run.run_id
        strategy_id = specification.strategy_id
        recipe_id = specification.recipe_version_id
        evidence_package_id = fixture.evidence_package.evidence_package_id
        manifest_id = fixture.selected_manifest.manifest_id
        evidence_status = str(
            fixture.evidence_package.sealed_payload()["status"]
        )
        expected_identity_graph = tuple(
            sorted(
                {
                    diagnostic_task_identity,
                    *task_handle_identities,
                    *fixture.expected_identity_graph,
                }
            )
        )
        _configure_smoke_route_identity(
            campaign_id=campaign_id,
            run_id=run_id,
            strategy_id=strategy_id,
            case_id=case_id,
            recipe_id=recipe_id,
            evidence_package_id=evidence_package_id,
            manifest_id=manifest_id,
        )

    feature_identity_graph: tuple[str, ...] = ()

    def observe(
        stage: str,
        route: str,
        run_state: str,
        evidence_state: str,
        run_freshness: str,
        evidence_freshness: str,
    ) -> None:
        _navigate_route(
            app=app,
            host=host,
            root=root,
            route=route,
        )
        keyboard_routes.add(route)
        run_adapter = host._run_monitoring
        evidence_adapter = host._evidence_and_findings
        if evidence_adapter is None:
            raise RuntimeError(
                "Evidence & Findings Adapter is unavailable"
            )
        try:
            _settle_until(
                app,
                lambda: (
                    root.property("activeRoute") == route
                    and root.property("screenState") == run_state
                    and root.property("evidenceScreenState")
                    == evidence_state
                    and run_adapter.property("freshness")
                    == run_freshness
                    and evidence_adapter.property("freshness")
                    == evidence_freshness
                ),
                (
                    f"{stage}: expected {route}/{run_state}/"
                    f"{evidence_state}/{run_freshness}/"
                    f"{evidence_freshness}"
                ),
            )
        except RuntimeError as error:
            raise RuntimeError(
                f"{error}; observed "
                f"{root.property('activeRoute')}/"
                f"{root.property('screenState')}/"
                f"{root.property('evidenceScreenState')}/"
                f"{run_adapter.property('freshness')}/"
                f"{evidence_adapter.property('freshness')}"
            ) from error
        host.update()
        quick_window = host.quickWindow()
        if quick_window is not None:
            quick_window.update()
        observations.append(
            _observe_state(
                app=app,
                root=root,
                host=host,
                report_dir=report_dir,
                stage=stage,
                route=route,
                capture_images=capture_images,
            )
        )
        checkpoint = _collect_qml_identity_checkpoint(
            app=app,
            host=host,
            root=root,
            expected=expected_identity_graph,
        )
        qml_identity_graph_checkpoints[stage] = checkpoint
        if checkpoint != expected_identity_graph:
            missing = tuple(
                identity
                for identity in expected_identity_graph
                if identity not in checkpoint
            )
            raise RuntimeError(
                f"{stage}: QML semantic identity graph is missing "
                f"{missing}"
            )

    observe(*EXPECTED_JOURNEY[0])
    observe(*EXPECTED_JOURNEY[1])
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    keyboard_routes.add("diagnostic_tasks")
    diagnostic_tasks_adapter = host._diagnostic_tasks
    if diagnostic_tasks_adapter is None:
        raise RuntimeError("Diagnostic Tasks Adapter is unavailable")
    try:
        _settle_until(
            app,
            lambda: (
                root.property("activeRoute") == "diagnostic_tasks"
                and diagnostic_tasks_adapter.property("presentationState")
                in {"ready", "input_unavailable", "empty"}
            ),
            "authoritative Diagnostic Tasks route",
        )
    except RuntimeError as error:
        raise RuntimeError(
            f"{error}; observed {root.property('activeRoute')}/"
            f"{diagnostic_tasks_adapter.property('presentationState')}/"
            f"{diagnostic_tasks_adapter.property('statusText')}"
        ) from error
    diagnostic_route_text = "\n".join(
        (
            str(diagnostic_tasks_adapter.property("strategyCatalogText")),
            str(diagnostic_tasks_adapter.property("recipeCatalogText")),
                str(diagnostic_tasks_adapter.property("marketScenarioCatalogText")),
                str(diagnostic_tasks_adapter.property("blockingReasonsText")),
                str(
                    diagnostic_tasks_adapter.property(
                        "reproductionManifestStatus"
                    )
                ),
            )
        )
    for required_text in (
        "required fixed input",
        "compatibility",
        "guardrail",
        "source",
        "comparison",
        "execution policy",
    ):
        if required_text not in diagnostic_route_text:
            raise RuntimeError(
                "Diagnostic Tasks production route omitted authoritative "
                f"inventory detail: {required_text}"
            )
    expected_manifest_status = (
        "available" if wave2_mode else "not_yet_available"
    )
    if diagnostic_tasks_adapter.property(
        "reproductionManifestStatus"
    ) != expected_manifest_status:
        raise RuntimeError(
            "Diagnostic Tasks exposed an invalid Reproduction Manifest state"
        )
    accessibility_announcements.append(
        _accessible_announcement(root, "diagnosticTasksAccessibleStatus")
    )
    feature_identity_graph = _feature_identity_graph(
        context=context,
        expected=expected_identity_graph,
        diagnostic_tasks_adapter=diagnostic_tasks_adapter,
    )
    if feature_identity_graph != expected_identity_graph:
        missing = tuple(
            identity
            for identity in expected_identity_graph
            if identity not in feature_identity_graph
        )
        raise RuntimeError(
            "Typed Feature identity graph does not match the reopened V1 "
            f"evidence graph; missing {missing}"
        )

    old_generation = bridge.connection_generation
    bridge.mark_disconnected()
    observe(*EXPECTED_JOURNEY[2])
    observe(*EXPECTED_JOURNEY[3])
    accessibility_announcements.extend(
        (
            _accessible_announcement(
                root,
                "runMonitoringAccessibleStatus",
            ),
            _accessible_announcement(root, "evidenceAccessibleStatus"),
        )
    )

    connection = bridge.mark_reconnected()
    observe(*EXPECTED_JOURNEY[4])
    observe(*EXPECTED_JOURNEY[5])
    state_before_old_generation = feature_authority_signature()
    bridge.on_snapshot(
        {"run_id": run_id},
        generation=old_generation,
    )
    bridge.flush(force=True)
    app.processEvents()
    state_after_old_generation = feature_authority_signature()
    old_generation_rejected = bool(
        state_after_old_generation == state_before_old_generation
        and state_after_old_generation[0] == connection.generation.value
        and state_after_old_generation[2] == connection.generation.value
    )
    if not old_generation_rejected:
        raise RuntimeError(
            "A stale EventBridge generation changed the typed Feature state"
        )

    bridge.on_snapshot(
        {"run_id": run_id},
        generation=connection.generation,
    )
    bridge.flush(force=True)
    observe(*EXPECTED_JOURNEY[6])
    observe(*EXPECTED_JOURNEY[7])
    authoritative_reconnect_verified = bool(
        tuple(
            (
                item.stage,
                item.run_freshness,
                item.evidence_freshness,
            )
            for item in observations[-2:]
        )
        == (
            ("reconnected_terminal_run", "fresh", "fresh"),
            ("reconnected_evidence", "fresh", "fresh"),
        )
    )
    if not authoritative_reconnect_verified:
        raise RuntimeError(
            "The current EventBridge generation did not restore fresh state"
        )
    accessibility_announcements.extend(
        (
            _accessible_announcement(
                root,
                "runMonitoringAccessibleStatus",
            ),
            _accessible_announcement(root, "evidenceAccessibleStatus"),
        )
    )

    close_initial_mount()

    if wave2_mode:
        input_fixture.close()
        fixture = reopen_completed_wave2_release_fixture(
            bundle_root=persistence_root,
            campaign_id=campaign_id,
            evidence_package_id=evidence_package_id,
            selected_manifest_id=manifest_id,
        )
        cleanup.callback(
            _record_cleanup,
            cleanup_errors,
            "reopened installed Wave 2 fixture",
            fixture.close,
        )
        lifecycle_checks.append(_closed_check(fixture))
        with _serialized_application_access(fixture.application):
            reopened_task = fixture.application.get_diagnostic_task(
                diagnostic_task_identity
            )
        reopened_task_identity = (
            None if reopened_task is None else reopened_task.task_id
        )
        reopened_handle_identities = (
            ()
            if reopened_task is None
            else tuple(
                handle.task_handle_id
                for handle in reopened_task.task_handles
            )
        )
        reopened_campaign_identity = (
            None
            if reopened_task is None
            or reopened_task.campaign_handoff is None
            else reopened_task.campaign_handoff.campaign_id
        )
        reopened_evidence_identity = (
            None
            if reopened_task is None
            or reopened_task.campaign_handoff is None
            else reopened_task.campaign_handoff.evidence_package_id
        )
        reopened_manifest_identity = (
            None
            if reopened_task is None
            or reopened_task.campaign_handoff is None
            else reopened_task.campaign_handoff.reproduction_manifest_id
        )
        writable_persistence_verified = bool(
            reopened_task is not None
            and reopened_task_identity == diagnostic_task_identity
            and reopened_handle_identities == task_handle_identities
            and reopened_campaign_identity == campaign_id
            and reopened_evidence_identity == evidence_package_id
            and reopened_manifest_identity == manifest_id
        )
        if not writable_persistence_verified:
            raise RuntimeError(
                "Installed task/Campaign/TaskHandle identities did not "
                "survive a real Application reopen; "
                f"task={reopened_task_identity!r}/"
                f"{diagnostic_task_identity!r}, "
                f"handles={reopened_handle_identities!r}/"
                f"{task_handle_identities!r}, "
                f"campaign={reopened_campaign_identity!r}/"
                f"{campaign_id!r}, "
                f"evidence={reopened_evidence_identity!r}/"
                f"{evidence_package_id!r}, "
                f"manifest={reopened_manifest_identity!r}/"
                f"{manifest_id!r}"
            )
        read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
            fixture.application,
            fixture.engine,
        )
        diagnostic_tasks_application = (
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                fixture.application
            )
        )
        application_reopened = True

    context, window, host = _create_production_window(
        event_bridge=bridge,
        strategy_diagnostics_read_model=read_model,
        strategy_diagnostics_tasks_application=diagnostic_tasks_application,
        settings_path=report_dir / "frontend-v2-settings.json",
    )
    register_mount(
        context=context,
        window=window,
        host=host,
    )
    window.setObjectName("frontendV2PackageRemountWindow")
    window.resize(1280, 720)
    window.show()
    app.processEvents()
    root = host.rootObject()
    if root is None:
        raise RuntimeError(
            "Remounted Journey Workspace root object is unavailable"
        )
    accessibility_preferences.append(
        _accessibility_preferences_verified(root)
    )
    observe(*EXPECTED_JOURNEY[8])
    observe(*EXPECTED_JOURNEY[9])

    remounted_feature_graph = _feature_identity_graph(
        context=context,
        expected=expected_identity_graph,
        diagnostic_tasks_adapter=host._diagnostic_tasks,
    )
    if remounted_feature_graph != feature_identity_graph:
        raise RuntimeError(
            "Remounted typed Feature identity graph changed"
        )

    graphics_api = _graphics_api_name(host)
    manual_action_count = _unapproved_interactive_action_count(root)
    read_only_context_visible = _read_only_context_visible(host)

    result = PackageSmokeResult(
        schema_version=2,
        source_commit=source_commit,
        renderer_lane=renderer_lane,
        graphics_api=graphics_api,
        production_path=PRODUCTION_PATH,
        campaign_identity=campaign_id,
        case_identity=case_id,
        run_identity=run_id,
        strategy_identity=strategy_id,
        approved_recipe_identity=recipe_id,
        evidence_package_identity=evidence_package_id,
        reproduction_manifest_identity=manifest_id,
        artifact_hashes=fixture.artifact_hashes,
        persistence_kind="sqlite+json+parquet",
        persistence_reopened=True,
        application_read_model_interface=application_interface,
        active_feature_interfaces=active_interfaces,
        campaign_status=fixture.campaign.status,
        run_status=fixture.selected_run.status,
        evidence_status=evidence_status,
        expected_identity_graph=expected_identity_graph,
        feature_identity_graph=feature_identity_graph,
        qml_identity_graph_checkpoints=qml_identity_graph_checkpoints,
        evidence_identity_sets=fixture.evidence_identity_sets,
        persisted_manifest_identities=tuple(
            sorted(manifest.manifest_id for manifest in fixture.manifests)
        ),
        persisted_run_identities=tuple(
            sorted(manifest.run_id for manifest in fixture.manifests)
        ),
        raw_artifact_hashes=fixture.raw_artifact_hashes,
        keyboard_navigation_verified=keyboard_routes == {
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        },
        accessibility_preferences_verified=bool(
            accessibility_preferences
            and all(accessibility_preferences)
        ),
        accessibility_announcements=tuple(
            accessibility_announcements
        ),
        old_generation_rejected=old_generation_rejected,
        authoritative_reconnect_verified=(
            authoritative_reconnect_verified
        ),
        routes_rendered=(
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        ),
        connection_transitions=(
            "connected",
            "disconnected",
            "reconnected",
            "remounted",
            "closed",
        ),
        observations=tuple(observations),
        manual_trading_action_count=manual_action_count,
        read_only_context_visible=read_only_context_visible,
        errors=(),
        clean_exit=False,
        fixture_kind=(
            "authoritative_writable_wave2_inputs"
            if wave2_mode
            else "sealed_completed_v1"
        ),
        task_created_after_install=wave2_mode,
        campaign_created_after_install=wave2_mode,
        diagnostic_task_identity=diagnostic_task_identity,
        accepted_command_kinds=accepted_command_kinds,
        task_handle_identities=task_handle_identities,
        writable_persistence_verified=writable_persistence_verified,
        application_reopened=application_reopened,
        background_continuation_verified=(
            background_continuation_verified
        ),
        task_cancel_order_isolation_verified=(
            cancel_order_isolation_verified
        ),
    )
    return result


def _close_mount(
    *,
    app: Any,
    context: Any,
    window: Any,
    host: Any,
    errors: list[str] | None = None,
) -> None:
    observed_errors = errors if errors is not None else []
    # Hide and drain first so Qt Quick has stopped rendering. Then unload QML
    # while its context adapters are alive, close the window after the adapter
    # shutdown is idempotent, and only then close the typed Features. The smoke
    # journey retains Python references for its final lifecycle audit, so
    # deferred C++ deletion must not be forced here.
    for label, action in (
        ("MainWindow hide", window.hide),
        ("Qt event drain before QML teardown", app.processEvents),
        ("QML Adapter", host.close_adapter),
        ("Qt event drain after QML teardown", app.processEvents),
        ("MainWindow", window.close),
        ("Qt event drain after MainWindow close", app.processEvents),
        (
            "Diagnostic Tasks Feature",
            context.diagnostic_tasks_feature.close,
        ),
        ("Run Monitoring Feature", context.run_monitoring_feature.close),
        (
            "Evidence and Findings Feature",
            context.evidence_and_findings_feature.close,
        ),
        ("Qt event drain after Feature teardown", app.processEvents),
    ):
        try:
            action()
        except BaseException as error:
            observed_errors.append(
                f"{label} cleanup failed: {type(error).__name__}"
            )
    if errors is None and observed_errors:
        raise RuntimeError("; ".join(observed_errors))


def _record_cleanup(
    errors: list[str],
    label: str,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except BaseException as error:
        errors.append(f"{label} cleanup failed: {type(error).__name__}")


def _path_absent_check(path: Path) -> Callable[[], bool]:
    def path_is_absent() -> bool:
        return not path.exists()

    return path_is_absent


def _closed_check(resource: Any) -> Callable[[], bool]:
    def resource_is_closed() -> bool:
        return bool(resource.closed)

    return resource_is_closed


def _environment_restored_check(
    previous: dict[str, str | None],
) -> Callable[[], bool]:
    def environment_is_restored() -> bool:
        return all(
            (
                os.environ.get(name) == value
                if value is not None
                else name not in os.environ
            )
            for name, value in previous.items()
        )

    return environment_is_restored


def _bridge_stopped_check(bridge: Any) -> Callable[[], bool]:
    def bridge_is_stopped() -> bool:
        return bool(
            not bridge._running
            and (bridge._th is None or not bridge._th.is_alive())
        )

    return bridge_is_stopped


def _mount_is_closed(
    context: Any,
    window: Any,
    host: Any,
) -> bool:
    return bool(
        getattr(host, "_workspace_closed", False)
        and getattr(context.diagnostic_tasks_feature, "_closed", False)
        and getattr(context.run_monitoring_feature, "_closed", False)
        and getattr(
            context.evidence_and_findings_feature,
            "_closed",
            False,
        )
        and not window.isVisible()
    )


def _settle_until(
    app: Any,
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            app.processEvents()
            return
        sleep(0.01)
    raise RuntimeError(f"Timed out waiting for {description}")


def _observe_state(
    *,
    app: Any,
    root: Any,
    host: Any,
    report_dir: Path,
    stage: str,
    route: str,
    capture_images: bool,
) -> SmokeStateObservation:
    run_adapter = host._run_monitoring
    evidence_adapter = host._evidence_and_findings
    if evidence_adapter is None:
        raise RuntimeError("Evidence & Findings Adapter is unavailable")
    observed = _snapshot_observed_state(
        root=root,
        run_adapter=run_adapter,
        evidence_adapter=evidence_adapter,
    )
    screenshot_name = None
    if capture_images:
        screenshot_name = f"{stage}.png"
        _capture_qml_frame(
            host,
            report_dir / screenshot_name,
            app=app,
        )
        observed_after_capture = _snapshot_observed_state(
            root=root,
            run_adapter=run_adapter,
            evidence_adapter=evidence_adapter,
        )
        if observed_after_capture != observed:
            changed_fields = ", ".join(
                key
                for key in observed
                if observed[key] != observed_after_capture[key]
            )
            raise RuntimeError(
                f"{stage}: state changed during frame capture "
                f"({changed_fields})"
            )
    return SmokeStateObservation(
        stage=stage,
        route=route,
        run_state=observed["run_state"],
        evidence_state=observed["evidence_state"],
        run_freshness=observed["run_freshness"],
        evidence_freshness=observed["evidence_freshness"],
        run_phase=observed["run_phase"],
        evidence_phase=observed["evidence_phase"],
        run_revision=observed["run_revision"],
        evidence_revision=observed["evidence_revision"],
        source_generation=observed["source_generation"],
        headline=observed["headline"],
        detail=observed["detail"],
        screenshot=screenshot_name,
    )


def _snapshot_observed_state(
    *,
    root: Any,
    run_adapter: Any,
    evidence_adapter: Any,
) -> dict[str, str]:
    return {
        "run_state": str(root.property("screenState")),
        "evidence_state": str(root.property("evidenceScreenState")),
        "run_freshness": str(run_adapter.property("freshness")),
        "evidence_freshness": str(evidence_adapter.property("freshness")),
        "run_phase": str(run_adapter.property("phase")),
        "evidence_phase": str(evidence_adapter.property("phase")),
        "run_revision": str(run_adapter.property("revisionText")),
        "evidence_revision": str(evidence_adapter.property("revisionText")),
        "source_generation": str(
            run_adapter.property("sourceGenerationText")
        ),
        "headline": str(root.property("headline")),
        "detail": str(root.property("detail")),
    }


def _unapproved_interactive_action_count(root: Any) -> int:
    from PySide6.QtCore import QObject

    count = 0
    for item in (root, *root.findChildren(QObject)):
        meta = item.metaObject()
        object_name = str(item.property("objectName") or "")
        if object_name in _PACKAGED_NON_ACTION_FOCUS_OBJECT_NAMES:
            continue
        if meta.indexOfProperty("accessibleName") >= 0:
            name = str(item.property("accessibleName") or "").strip()
        else:
            name = ""
        keyboard_action = bool(
            meta.indexOfProperty("activeFocusOnTab") >= 0
            and item.property("activeFocusOnTab")
        )
        if not name:
            if keyboard_action:
                count += 1
            continue
        if not _APPROVED_INTERACTIVE_NAMES.fullmatch(name):
            count += 1
    return count


def _read_only_context_visible(host: Any) -> bool:
    run_text = str(
        host._run_monitoring.property("diagnosticContextText")
    )
    evidence_adapter = host._evidence_and_findings
    if evidence_adapter is None:
        return False
    evidence_text = str(evidence_adapter.property("readOnlyContextText"))
    return (
        "Orders" in run_text
        and "Fills" in run_text
        and "read-only evidence traces" in evidence_text
    )


def _capture_qml_frame(
    host: Any,
    screenshot_path: Path,
    *,
    app: Any | None = None,
) -> None:
    if app is not None:
        quick_window = host.quickWindow()
        if quick_window is None:
            raise RuntimeError("QML render window is unavailable")
        rendered = []

        def frame_rendered() -> None:
            rendered.append(True)

        quick_window.afterRendering.connect(frame_rendered)
        try:
            host.update()
            quick_window.update()
            deadline = monotonic() + 1.0
            while not rendered and monotonic() < deadline:
                app.processEvents()
                sleep(0.005)
        finally:
            quick_window.afterRendering.disconnect(frame_rendered)
        if not rendered:
            raise RuntimeError("Timed out waiting for a fresh QML frame")
    image = host.grabFramebuffer()
    if image.isNull() or not image.save(str(screenshot_path), "PNG"):
        raise RuntimeError(f"Failed to capture {screenshot_path}")


def _graphics_api_name(host: Any) -> str:
    quick_window = host.quickWindow()
    if quick_window is None:
        return "unavailable"
    graphics_api = quick_window.rendererInterface().graphicsApi()
    return getattr(graphics_api, "name", str(graphics_api))


def _write_smoke_report(
    result: PackageSmokeResult,
    report_path: Path,
) -> None:
    payload = asdict(result)
    payload["renderer_lane"] = result.renderer_lane.value
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_interactive() -> int:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import (
        start_frontend_bridge,
        stop_frontend_bridge,
    )

    app = QApplication.instance() or QApplication([])
    bridge = start_frontend_bridge()
    os.environ["STOCKSIM_FRONTEND_V2"] = "1"
    context, window, _host = _create_production_window(
        event_bridge=bridge,
        settings_path=Path("frontend-v2-settings.json"),
    )
    window.resize(1024, 640)
    app.aboutToQuit.connect(context.diagnostic_tasks_feature.close)
    app.aboutToQuit.connect(context.run_monitoring_feature.close)
    app.aboutToQuit.connect(context.evidence_and_findings_feature.close)
    app.aboutToQuit.connect(stop_frontend_bridge)
    window.show()
    return int(app.exec())


def _installed_fixture_archive_path() -> Path:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    return (
        Path(sys.argv[0]).resolve().parent
        / WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = tuple(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--renderer-lane",
        choices=tuple(lane.value for lane in RendererLane),
        default=RendererLane.HARDWARE.value,
    )
    parser.add_argument("--smoke-report-dir", type=Path)
    parser.add_argument("--fixture-archive", type=Path)
    parser.add_argument("--source-commit", default="unbound")
    parser.add_argument("--no-images", action="store_true")
    arguments = parser.parse_args(raw_arguments)
    renderer_lane = RendererLane(arguments.renderer_lane)
    configure_renderer_environment(renderer_lane)
    if arguments.smoke_report_dir is not None:
        fixture_archive_path = arguments.fixture_archive
        if fixture_archive_path is None and "__compiled__" in globals():
            fixture_archive_path = _installed_fixture_archive_path()
        result = run_smoke_journey(
            report_dir=arguments.smoke_report_dir,
            renderer_lane=renderer_lane,
            source_commit=arguments.source_commit,
            capture_images=not arguments.no_images,
            fixture_archive_path=fixture_archive_path,
        )
        return (
            0
            if (
                not result.errors
                and result.clean_exit
                and result.manual_trading_action_count == 0
                and result.read_only_context_visible
                and result.fixture_kind
                == "authoritative_writable_wave2_inputs"
                and result.task_created_after_install
                and result.campaign_created_after_install
                and bool(result.diagnostic_task_identity.strip())
                and result.accepted_command_kinds
                == WAVE2_ACCEPTED_COMMAND_KINDS
                and len(result.task_handle_identities) >= 3
                and all(
                    identity.strip()
                    for identity in result.task_handle_identities
                )
                and len(set(result.task_handle_identities))
                == len(result.task_handle_identities)
                and result.writable_persistence_verified
                and result.application_reopened
                and result.background_continuation_verified
                and result.task_cancel_order_isolation_verified
            )
            else 1
        )
    return _run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
