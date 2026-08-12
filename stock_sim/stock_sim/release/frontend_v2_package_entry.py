"""Installed-package black-box entry point for the Frontend V2 release gate."""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from functools import partial
from pathlib import Path
from threading import current_thread
from time import monotonic, perf_counter_ns, sleep
from typing import Any

from stock_sim.release.frontend_v2_interactive_actions import (
    APPROVED_INTERACTIVE_NAMES as _APPROVED_INTERACTIVE_NAMES,
)

PRODUCTION_PATH = (
    "DiagnosticsApplication",
    "FileBackedV1Persistence",
    "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
    "LiveStrategyLibraryAdapter",
    "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
    "LiveScenarioLabAdapter",
    "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
    "LiveDiagnosticTasksAdapter",
    "LiveStrategyDiagnosticsV1ApplicationAdapter",
    "EventBridge",
    "LiveRunMonitoringAdapter",
    "LiveEvidenceAndFindingsAdapter",
    "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
    "LiveSystemHealthAdapter",
    "JourneyWorkspaceHost",
)
ACTIVE_JOURNEY_ROUTES = (
    "strategy_library",
    "scenario_lab",
    "diagnostic_tasks",
    "run_monitoring",
    "evidence_and_findings",
    "system_health",
)
WAVE2_ACCEPTED_COMMAND_KINDS = (
    "create_diagnostic_task",
    "revise_configuration",
    "validate_configuration",
    "approve_configuration",
    "start_formal_diagnostic_campaign",
)
WAVE3_ACCEPTED_SETUP_COMMAND_KINDS = (
    "compare_formal_strategy_set",
    "select_formal_strategy_set",
    "create_recipe_draft",
    "validate_recipe_draft",
    "approve_recipe",
    "materialize_reference_path",
    "compose_formal_scenario_set",
    "resolve_execution_assumptions",
    "select_formal_scenario_set",
)

# Compiled smoke terminates the process immediately after its report is
# accepted. Keep deferred PySide/SQLAlchemy owners strongly reachable until
# that boundary: releasing their final Python wrapper references while main()
# returns can run native destructors before _run_process_entry() terminates.
_PROCESS_EXIT_RETAINED_NATIVE_RESOURCES: list[Any] = []


def _retain_native_resources_until_process_exit(*resources: Any) -> None:
    _PROCESS_EXIT_RETAINED_NATIVE_RESOURCES.extend(resources)


def _terminate_compiled_smoke_process(exit_code: int) -> None:
    if os.name != "nt":
        os._exit(exit_code)

    # os._exit() still crosses the Windows CRT/DLL detach boundary. A
    # quiesced Nuitka/PySide smoke can otherwise report success and then trip
    # a latent Qt static-destructor access violation before the parent
    # observes its exit code. TerminateProcess is intentionally restricted to
    # the compiled certification path after all typed resources have passed
    # their logical lifecycle audit; interactive and source paths retain
    # normal QApplication/Python teardown.
    import ctypes

    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process: Any = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = ctypes.c_void_p
    terminate_process: Any = kernel32.TerminateProcess
    terminate_process.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    terminate_process.restype = ctypes.c_int
    process = get_current_process()
    if not terminate_process(process, exit_code):
        raise ctypes.WinError(ctypes.get_last_error())
    raise RuntimeError("Windows process termination unexpectedly returned")


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
        "fresh",
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
        "stale",
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
_PACKAGED_NON_ACTION_FOCUS_OBJECT_NAMES = frozenset(
    {
        "diagnosticTaskApprovalActorInput",
        "scenarioLabSearchInput",
        "scenarioLabAiRecipeIntentInput",
        "scenarioLabMarketFilter",
        "scenarioLabSourceFilter",
        "scenarioLabRecipeVersionFilter",
        "scenarioLabLayerFilter",
        "scenarioLabTransformationFamilyFilter",
        "scenarioLabCompatibilityFilter",
        "scenarioLabReproducibilityFilter",
        "scenarioLabReconstructionFilter",
        "systemHealthAccessibleStatus",
    }
)
_PACKAGED_NON_ACTION_FOCUS_PARENT_OBJECT_NAMES = frozenset(
    {
        "strategyLibraryAvailabilityFilter",
        "scenarioLabMarketFilter",
        "scenarioLabSourceFilter",
        "scenarioLabRecipeVersionFilter",
        "scenarioLabLayerFilter",
        "scenarioLabTransformationFamilyFilter",
        "scenarioLabCompatibilityFilter",
        "scenarioLabRecipeCadenceInput",
        "scenarioLabRecipeLatencyInput",
        "scenarioLabRecipeSeedInput",
        "scenarioLabRecipeSegmentInput",
        "scenarioLabRecipeTransformationInput",
        "scenarioLabReproducibilityFilter",
        "scenarioLabReconstructionFilter",
    }
)


class RendererLane(str, Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"


class CertificationScope(str, Enum):
    SOURCE_VALIDATION = "source-validation"
    INSTALLED = "installed"
    PACKAGE_ASSEMBLY = "package-assembly"


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
class InstalledWave3SetupEvidence:
    strategy_selection_context_identity: str
    recipe_draft_identity: str
    recipe_validation_identity: str
    approved_recipe_identity: str
    materialization_task_handle_identity: str
    materialized_path_identity: str
    materialized_scenario_identity: str
    formal_scenario_set_identity: str
    scenario_selection_context_identity: str
    setup_selection_context_identity: str
    installed_setup_command_kinds: tuple[str, ...]
    recipe_draft_identities: tuple[str, ...]
    recipe_validation_identities: tuple[str, ...]
    approved_recipe_identities: tuple[str, ...]
    materialization_task_handle_identities: tuple[str, ...]
    materialized_path_identities: tuple[str, ...]
    materialized_scenario_identities: tuple[str, ...]


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
    strategy_selection_created_after_install: bool = False
    recipe_draft_created_after_install: bool = False
    recipe_validation_created_after_install: bool = False
    recipe_approval_created_after_install: bool = False
    reference_path_materialized_after_install: bool = False
    scenario_set_created_after_install: bool = False
    scenario_selection_created_after_install: bool = False
    strategy_selection_context_identity: str = ""
    recipe_draft_identity: str = ""
    recipe_validation_identity: str = ""
    materialization_task_handle_identity: str = ""
    materialized_path_identity: str = ""
    materialized_scenario_identity: str = ""
    terminal_campaign_case_identity: str = ""
    terminal_selected_campaign_case_identity: str = ""
    terminal_node_market_scenario_identity: str = ""
    terminal_campaign_node_lifecycle: str = ""
    terminal_case_manifest_binding_verified: bool = False
    installed_setup_ledger_reopened: bool = False
    reopened_installed_setup_ledger: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    formal_scenario_set_identity: str = ""
    scenario_selection_context_identity: str = ""
    setup_selection_context_identity: str = ""
    installed_setup_command_kinds: tuple[str, ...] = ()
    installed_recipe_draft_identities: tuple[str, ...] = ()
    installed_recipe_validation_identities: tuple[str, ...] = ()
    installed_approved_recipe_identities: tuple[str, ...] = ()
    installed_materialization_task_handle_identities: tuple[str, ...] = ()
    installed_materialized_path_identities: tuple[str, ...] = ()
    installed_materialized_scenario_identities: tuple[str, ...] = ()
    task_created_after_install: bool = False
    campaign_created_after_install: bool = False
    diagnostic_task_identity: str = ""
    accepted_command_kinds: tuple[str, ...] = ()
    task_handle_identities: tuple[str, ...] = ()
    installed_setup: InstalledWave3SetupEvidence | None = None
    writable_persistence_verified: bool = False
    application_reopened: bool = False
    background_continuation_verified: bool = False
    task_cancel_order_isolation_verified: bool = False
    queued_state_observed: bool = False
    running_state_observed: bool = False
    partial_state_observed: bool = False
    controlled_failure_observed: bool = False
    safe_failure_reason_verified: bool = False
    retry_idempotency_verified: bool = False
    duplicate_work_count: int = -1
    terminal_completion_observed: bool = False
    system_health_context_verified: bool = False
    system_health_identity_graph: tuple[str, ...] = ()
    system_health_accessibility_verified: bool = False
    focus_restoration_verified: bool = False
    accessibility_checkpoints: tuple[dict[str, Any], ...] = ()
    installed_accessibility_verified: bool = False
    no_color_only_meaning_verified: bool = False
    chart_narrative_table_revision_verified: bool = False
    manual_trading_route_audits: tuple[dict[str, Any], ...] = ()
    certification_scope: str = CertificationScope.SOURCE_VALIDATION.value


def configure_renderer_environment(renderer_lane: RendererLane) -> None:
    # The production QML customizes every control surface.  Pinning the
    # non-native Basic style avoids the Windows native-style fallback path and
    # keeps the two renderer lanes on the same QML control implementation.
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
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
    strategy_diagnostics_application: Any | None = None,
    strategy_diagnostics_read_model: Any | None = None,
    strategy_diagnostics_tasks_application: Any | None = None,
    strategy_diagnostics_library_application: Any | None = None,
    strategy_diagnostics_scenario_lab_application: Any | None = None,
    strategy_diagnostics_system_health_application: Any | None = None,
    diagnostic_setup_selection_coordinator: Any | None = None,
) -> tuple[Any, Any, Any]:
    from app.app_context import build_app_context
    from app.ui.main_window import MainWindow

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="live",
        event_bridge=event_bridge,
        runtime_gateway=runtime_gateway,
        strategy_diagnostics_application=strategy_diagnostics_application,
        strategy_diagnostics_read_model=strategy_diagnostics_read_model,
        strategy_diagnostics_tasks_application=(
            strategy_diagnostics_tasks_application
        ),
        strategy_diagnostics_library_application=(
            strategy_diagnostics_library_application
        ),
        strategy_diagnostics_scenario_lab_application=(
            strategy_diagnostics_scenario_lab_application
        ),
        strategy_diagnostics_system_health_application=(
            strategy_diagnostics_system_health_application
        ),
        diagnostic_setup_selection_coordinator=(
            diagnostic_setup_selection_coordinator
        ),
    )
    window = None
    try:
        window = MainWindow(
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_context=context.strategy_library_context,
            strategy_library_bookmark_sink=(
                getattr(
                    context,
                    "persist_strategy_library_bookmark",
                    None,
                )
            ),
            journey_workspace_bookmark=(
                getattr(context, "journey_workspace_bookmark", None)
            ),
            journey_workspace_bookmark_sink=(
                getattr(
                    context,
                    "persist_journey_workspace_bookmark",
                    None,
                )
            ),
            scenario_lab_feature=context.scenario_lab_feature,
            scenario_lab_context=context.scenario_lab_context,
            diagnostic_tasks_feature=context.diagnostic_tasks_feature,
            diagnostic_tasks_context=context.diagnostic_tasks_context,
            diagnostic_setup_selection_coordinator=(
                getattr(
                    context,
                    "diagnostic_setup_selection_coordinator",
                    diagnostic_setup_selection_coordinator,
                )
            ),
            run_monitoring_feature=context.run_monitoring_feature,
            run_monitoring_context=context.run_monitoring_context,
            evidence_and_findings_feature=(
                context.evidence_and_findings_feature
            ),
            evidence_and_findings_context=(
                context.evidence_and_findings_context
            ),
            system_health_feature=getattr(
                context,
                "system_health_feature",
                None,
            ),
            system_health_context=getattr(
                context,
                "system_health_context",
                None,
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
            (
                context.strategy_library_feature.close
                if hasattr(context, "strategy_library_feature")
                else None
            ),
            (
                context.scenario_lab_feature.close
                if hasattr(context, "scenario_lab_feature")
                else None
            ),
            context.diagnostic_tasks_feature.close,
            context.run_monitoring_feature.close,
            context.evidence_and_findings_feature.close,
            (
                context.system_health_feature.close
                if hasattr(context, "system_health_feature")
                else None
            ),
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


def _serialized_application_access(
    application: Any,
) -> Any:
    from app.features._diagnostics_application_access import (
        shared_diagnostics_application_access_gate,
    )

    return shared_diagnostics_application_access_gate(application)


def _focus_with_keyboard(
    *,
    app: Any,
    host: Any,
    target: Any,
    backwards: bool = False,
) -> None:
    from PySide6.QtCore import Qt

    for _ in range(512):
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


def _find_quick_item(root: Any, object_name: str) -> Any | None:
    from PySide6.QtQuick import QQuickItem

    direct = root.findChild(QQuickItem, object_name)
    if direct is not None:
        return direct
    pending = list(root.childItems())
    while pending:
        item = pending.pop()
        if item.objectName() == object_name:
            return item
        pending.extend(item.childItems())
    return None


def _navigate_route(
    *,
    app: Any,
    host: Any,
    root: Any,
    route: str,
) -> None:
    from PySide6.QtCore import Qt
    object_name = {
        "strategy_library": "strategyLibraryRouteNavigation",
        "scenario_lab": "scenarioLabRouteNavigation",
        "diagnostic_tasks": "diagnosticTasksRouteNavigation",
        "run_monitoring": "runMonitoringRouteNavigation",
        "evidence_and_findings": "evidenceAndFindingsRouteNavigation",
        "system_health": "systemHealthRouteNavigation",
    }[route]
    target = _find_quick_item(root, object_name)
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


def _route_focus_is_visible(root: Any, route: str) -> bool:
    focus_property = {
        "strategy_library": "strategyLibraryInitialFocusItem",
        "scenario_lab": "scenarioLabInitialFocusItem",
        "diagnostic_tasks": "diagnosticTasksInitialFocusItem",
        "run_monitoring": "runMonitoringInitialFocusItem",
        "evidence_and_findings": "evidenceInitialFocusItem",
        "system_health": "systemHealthInitialFocusItem",
    }.get(route)
    if focus_property is None:
        return False
    item = root.property(focus_property)
    return bool(
        item is not None
        and item.property("visible")
        and item.property("activeFocus")
        and item.property("focusVisible")
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
    from PySide6.QtCore import QObject, Qt

    quick_window = host.quickWindow()
    if quick_window is None:
        raise RuntimeError("Journey Workspace Quick Window is unavailable")
    content_item = quick_window.contentItem()
    keyboard_search_limit = 120
    if content_item is not None:
        keyboard_search_limit = max(
            keyboard_search_limit,
            len(content_item.findChildren(QObject)) + 1,
        )
    if not host.hasFocus():
        host.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
    for _ in range(keyboard_search_limit):
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
        f"{accessible_name!r} after {keyboard_search_limit} steps"
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

    original_route = str(root.property("activeRoute"))
    quick_window = host.quickWindow()
    if quick_window is None:
        raise RuntimeError("Journey Workspace Quick Window is unavailable")
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
    checkpoint = tuple(
        identity for identity in expected if identity in qml_text
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route=original_route,
    )
    app.processEvents()
    restored_focus = quick_window.activeFocusItem()
    if restored_focus is None or not restored_focus.property("visible"):
        raise RuntimeError(
            "Restored QML route has no meaningful visible keyboard focus"
        )
    return checkpoint


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
    expect_controlled_failure: bool = False,
) -> tuple[Any, tuple[str, ...], InstalledWave3SetupEvidence]:
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
        try:
            _settle_until(
                app,
                lambda: _find_quick_item(root, object_name) is not None,
                f"{object_name} instantiated",
            )
        except RuntimeError as error:
            related_actions = tuple(
                str(item.property("objectName"))
                for item in root.findChildren(QQuickItem)
                if object_name.split("-", maxsplit=1)[0]
                in str(item.property("objectName"))
            )
            raise RuntimeError(
                f"{error}; related QML actions: {related_actions!r}"
            ) from error
        target = _find_quick_item(root, object_name)
        if target is None:
            raise RuntimeError(
                f"Installed Journey action is absent: {object_name}"
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
        try:
            _settle_until(
                app,
                completed,
                f"{object_name} authoritative completion",
            )
        except RuntimeError as error:
            raise RuntimeError(
                f"{error}; Diagnostic Tasks status: "
                f"{projection.property('commandStatusText')}"
            ) from error

    strategy_projection = host._strategy_library
    scenario_projection = host._scenario_lab
    if strategy_projection is None or scenario_projection is None:
        raise RuntimeError(
            "Installed Strategy Library or Scenario Lab Adapter is unavailable"
        )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="strategy_library",
    )
    _settle_until(
        app,
        lambda: strategy_projection.property("presentationState") == "ready",
        "installed authoritative Strategy Library inventory",
    )
    activate(
        "strategyLibraryCompareFormalSet",
        completed=lambda: strategy_projection.property("comparisonCount") >= 2,
    )
    activate(
        "strategyLibrarySelectFormalSet",
        completed=lambda: strategy_projection.property("selectionStatus")
        == "current",
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="scenario_lab",
    )
    _settle_until(
        app,
        lambda: scenario_projection.property("presentationState") == "ready",
        "installed authoritative Scenario Lab inventory",
    )
    def set_text_input(object_name: str, value: str) -> None:
        target = _find_quick_item(root, object_name)
        if target is None:
            raise RuntimeError(
                f"Installed Journey text input is absent: {object_name}"
            )
        _focus_with_keyboard(app=app, host=host, target=target)
        _key_click(
            host,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier,
        )
        _type_text_with_keyboard(host, value)
        _settle_until(
            app,
            lambda: str(target.property("text")) == value,
            f"{object_name} exact keyboard input",
        )

    def set_combo_index(object_name: str, index: int) -> None:
        target = _find_quick_item(root, object_name)
        if target is None:
            raise RuntimeError(
                f"Installed Journey selector is absent: {object_name}"
            )
        _focus_with_keyboard(app=app, host=host, target=target)
        _key_click(
            host,
            Qt.Key.Key_Space,
            Qt.KeyboardModifier.NoModifier,
        )
        _key_click(
            host,
            Qt.Key.Key_Home,
            Qt.KeyboardModifier.NoModifier,
        )
        for _ in range(index):
            _key_click(
                host,
                Qt.Key.Key_Down,
                Qt.KeyboardModifier.NoModifier,
            )
        _key_click(
            host,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        _settle_until(
            app,
            lambda: int(target.property("currentIndex")) == index,
            f"{object_name} closed catalog selection",
        )

    set_text_input("scenarioLabRecipeSlippageInput", "5")
    catalog = tuple(scenario_projection.transformations)
    catalog_index = {
        str(item["transformationId"]): index
        for index, item in enumerate(catalog, start=1)
    }
    formal_transformation_ids = (
        "trend-regime.v1",
        "volatility-scaling.v1",
        "shock-recovery.v1",
        "market-structure.v1",
        "liquidity-stress.v1",
        "execution-stress.v1",
    )
    if set(catalog_index) != set(formal_transformation_ids):
        raise RuntimeError(
            "Installed closed transformation catalog does not match the "
            "formal bounded sweep"
        )

    def transformation_level_hints(
        transformation_id: str,
    ) -> tuple[str, str]:
        entry = next(
            item
            for item in catalog
            if item["transformationId"] == transformation_id
        )
        parameter = entry["parameters"][0]
        choices = tuple(str(value) for value in parameter["choices"])
        if len(choices) >= 2:
            return choices[0], choices[-1]
        minimum = str(parameter["minimum"])
        maximum = str(parameter["maximum"])
        if not minimum or not maximum or minimum == maximum:
            raise RuntimeError(
                "Installed formal transformation lacks two closed first-"
                f"parameter levels: {transformation_id}"
            )
        return minimum, maximum

    def author_validate_approve_materialize(
        *,
        name: str,
        primary_transformation_id: str = "",
        primary_parameter_hint: str = "",
        secondary_transformation_id: str = "",
        secondary_parameter_hint: str = "",
    ) -> tuple[dict[str, Any], ...]:
        draft_count = int(scenario_projection.property("recipeDraftCount"))
        validation_count = int(
            scenario_projection.property("recipeValidationCount")
        )
        approved_count = int(
            scenario_projection.property("approvedRecipeVersionCount")
        )
        handle_count = int(scenario_projection.property("taskHandleCount"))
        prior_draft_ids = {
            str(item["draftId"])
            for item in scenario_projection.recipeDrafts
        }
        set_text_input("scenarioLabRecipeNameInput", name)
        set_combo_index(
            "scenarioLabRecipeTransformationInput",
            0
            if not primary_transformation_id
            else catalog_index[primary_transformation_id],
        )
        set_text_input(
            "scenarioLabRecipeTransformationParameterInput",
            primary_parameter_hint,
        )
        set_combo_index(
            "scenarioLabRecipeSecondaryTransformationInput",
            0
            if not secondary_transformation_id
            else catalog_index[secondary_transformation_id],
        )
        set_text_input(
            "scenarioLabRecipeSecondaryTransformationParameterInput",
            secondary_parameter_hint,
        )
        activate(
            (
                "scenarioLabCreateCompoundRecipeDraftButton"
                if secondary_transformation_id
                else "scenarioLabCreateRecipeDraftButton"
            ),
            completed=lambda: scenario_projection.property("recipeDraftCount")
            == draft_count + 1,
        )
        recipe_draft = next(
            item
            for item in scenario_projection.recipeDrafts
            if str(item["draftId"]) not in prior_draft_ids
        )
        recipe_draft_id = str(recipe_draft["draftId"])
        activate(
            "scenarioLabValidateRecipeDraft-" + recipe_draft_id,
            completed=lambda: scenario_projection.property(
                "recipeValidationCount"
            )
            == validation_count + 1,
        )
        recipe_validation = next(
            item
            for item in scenario_projection.recipeValidations
            if str(item["draftId"]) == recipe_draft_id
        )
        if (
            str(recipe_validation["draftId"]) != recipe_draft_id
            or recipe_validation["valid"] is not True
        ):
            raise RuntimeError(
                "Installed Recipe validation did not accept the exact Draft"
            )
        recipe_validation_id = str(recipe_validation["validationId"])
        activate(
            "scenarioLabApproveRecipe-" + recipe_validation_id,
            completed=lambda: scenario_projection.property(
                "approvedRecipeVersionCount"
            )
            == approved_count + 1,
        )
        approved_recipe = next(
            item
            for item in scenario_projection.approvedRecipeVersions
            if item["validationId"] == recipe_validation_id
        )
        approved_recipe_id = str(approved_recipe["recipeVersionId"])
        activate(
            "scenarioLabMaterializeApprovedRecipe-" + approved_recipe_id,
            completed=lambda: bool(
                scenario_projection.property("taskHandleCount")
                == handle_count + 1
                and any(
                    item["targetIdentity"] == approved_recipe_id
                    and item["terminal"]
                    for item in scenario_projection.taskHandles
                )
            ),
        )
        materialization_handle = next(
            item
            for item in scenario_projection.taskHandles
            if item["targetIdentity"] == approved_recipe_id
        )
        if (
            materialization_handle["phase"] != "completed"
            or materialization_handle["targetIdentity"]
            != approved_recipe_id
        ):
            raise RuntimeError(
                "Installed Recipe materialization did not complete for the "
                "approved version"
            )
        materialized_path_id = str(
            materialization_handle["resultIdentity"]
        )
        materialized_scenario = next(
            item
            for item in scenario_projection.marketScenarios
            if item["pathId"] == materialized_path_id
            and item["recipeVersionId"] == approved_recipe_id
        )
        return (
            recipe_draft,
            recipe_validation,
            approved_recipe,
            materialization_handle,
            materialized_scenario,
        )

    materialized_records = [
        author_validate_approve_materialize(
            name="Installed formal baseline control"
        )
    ]
    for transformation_id in formal_transformation_ids:
        for level, parameter_hint in enumerate(
            transformation_level_hints(transformation_id),
            start=1,
        ):
            materialized_records.append(
                author_validate_approve_materialize(
                    name=(
                        f"Installed {transformation_id} bounded level {level}"
                    ),
                    primary_transformation_id=transformation_id,
                    primary_parameter_hint=parameter_hint,
                )
            )
    primary_id, secondary_id = formal_transformation_ids[:2]
    materialized_records.append(
        author_validate_approve_materialize(
            name="Installed trend and volatility formal compound",
            primary_transformation_id=primary_id,
            primary_parameter_hint=transformation_level_hints(primary_id)[0],
            secondary_transformation_id=secondary_id,
            secondary_parameter_hint=(
                transformation_level_hints(secondary_id)[1]
            ),
        )
    )
    (
        recipe_draft,
        recipe_validation,
        approved_recipe,
        materialization_handle,
        materialized_scenario,
    ) = materialized_records[0]
    recipe_draft_id = str(recipe_draft["draftId"])
    recipe_validation_id = str(recipe_validation["validationId"])
    approved_recipe_id = str(approved_recipe["recipeVersionId"])
    materialized_path_id = str(materialization_handle["resultIdentity"])
    materialized_scenario_id = str(materialized_scenario["scenarioId"])
    scenario_set_count = int(scenario_projection.property("scenarioSetCount"))
    activate(
        "scenarioLabComposeVisibleScenarioSetButton",
        completed=lambda: scenario_projection.property("scenarioSetCount")
        == scenario_set_count + 1,
    )
    formal_scenario_set = scenario_projection.scenarioSets[-1]
    if (
        formal_scenario_set["eligibility"]
        != "formal_campaign_eligible"
        or materialized_scenario_id not in formal_scenario_set["caseIds"]
    ):
        raise RuntimeError(
            "Installed Formal Scenario Set omitted the materialized case; "
            f"case={materialized_scenario!r}; "
            f"set={formal_scenario_set!r}; "
            f"visible_cases={scenario_projection.marketScenarios!r}"
        )
    activate(
        "scenarioLabResolveExecutionAssumptionsButton",
        completed=lambda: scenario_projection.property(
            "executionResolutionCount"
        )
        >= 1,
    )
    activate(
        "scenarioLabSelectFormalScenarioSetButton",
        completed=lambda: scenario_projection.property("selectionContextCount")
        >= 1,
    )
    scenario_selection = scenario_projection.current_diagnostic_selection()
    if scenario_selection is None or materialized_scenario_id not in {
        item.scenario_id.value
        for item in scenario_selection.market_scenarios
    }:
        raise RuntimeError(
            "Installed formal Scenario selection omitted the materialized case"
        )
    scenario_selection_context_id = (
        scenario_selection.context.selection_context_id.value
    )

    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    _settle_until(
        app,
        lambda: bool(projection.property("setupSelectionReady"))
        and projection.property("presentationState") == "ready",
        "installed exact Diagnostic Tasks setup selection",
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

    original_strategy_selection = strategy_projection.property(
        "selectionContextId"
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="strategy_library",
    )
    activate(
        "strategyLibrarySelectFormalSet",
        completed=lambda: bool(
            strategy_projection.property("selectionContextId")
        )
        and strategy_projection.property("selectionContextId")
        != original_strategy_selection,
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    _settle_until(
        app,
        lambda: bool(projection.property("setupSelectionReady")),
        "installed corrected exact setup selection",
    )

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
    setup_selection = context.diagnostic_setup_selection_coordinator.current()
    if setup_selection is None:
        raise RuntimeError(
            "Installed Diagnostic Task lost its exact setup selection"
        )
    installed_bindings = {
        str(record[4]["scenarioId"]): (
            str(record[2]["recipeVersionId"]),
            str(record[3]["resultIdentity"]),
        )
        for record in materialized_records
    }
    setup_bindings = {
        item.campaign_case_id.value: (
            item.recipe_version_id.value,
            item.market_scenario_id.value,
        )
        for item in setup_selection.configuration.campaign_case_selections
    }
    selected_bindings = {
        item.campaign_case_id.value: (
            item.recipe_version_id.value,
            item.market_scenario_id.value,
        )
        for item in running.handoff.selected_cases
    }
    if (
        setup_bindings != installed_bindings
        or selected_bindings != installed_bindings
    ):
        raise RuntimeError(
            "Installed Recipe/path/case identities did not reach the "
            "Diagnostic Task Campaign handoff"
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
    controlled_failed_nodes = tuple(
        node
        for node in running.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    expected_incomplete = bool(
        expect_controlled_failure
        and first_incomplete is not None
        and len(controlled_failed_nodes) == 1
    )
    if first_incomplete is not None and not expected_incomplete:
        last_attempt = (
            None
            if not first_incomplete.attempts
            else first_incomplete.attempts[-1]
        )
        raise RuntimeError(
            "Installed Campaign start produced an unexpected incomplete "
            "node; safe_summary="
            f"layer={first_incomplete.layer!r}, "
            f"case_status={first_incomplete.status!r}, "
            "attempt_status="
            f"{None if last_attempt is None else last_attempt.status!r}"
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
    setup_evidence = InstalledWave3SetupEvidence(
        strategy_selection_context_identity=(
            setup_selection.strategy_selection.context_identity
        ),
        recipe_draft_identity=recipe_draft_id,
        recipe_validation_identity=recipe_validation_id,
        approved_recipe_identity=approved_recipe_id,
        materialization_task_handle_identity=str(
            materialization_handle["taskHandleId"]
        ),
        materialized_path_identity=materialized_path_id,
        materialized_scenario_identity=materialized_scenario_id,
        formal_scenario_set_identity=str(
            formal_scenario_set["scenarioSetId"]
        ),
        scenario_selection_context_identity=(
            scenario_selection_context_id
        ),
        setup_selection_context_identity=setup_selection.context_identity,
        installed_setup_command_kinds=(
            WAVE3_ACCEPTED_SETUP_COMMAND_KINDS
        ),
        recipe_draft_identities=tuple(
            str(record[0]["draftId"])
            for record in materialized_records
        ),
        recipe_validation_identities=tuple(
            str(record[1]["validationId"])
            for record in materialized_records
        ),
        approved_recipe_identities=tuple(
            str(record[2]["recipeVersionId"])
            for record in materialized_records
        ),
        materialization_task_handle_identities=tuple(
            str(record[3]["taskHandleId"])
            for record in materialized_records
        ),
        materialized_path_identities=tuple(
            str(record[3]["resultIdentity"])
            for record in materialized_records
        ),
        materialized_scenario_identities=tuple(
            str(record[4]["scenarioId"])
            for record in materialized_records
        ),
    )
    return running, WAVE2_ACCEPTED_COMMAND_KINDS, setup_evidence


def _quiesce_installed_wave2_mount(
    *,
    close_mount: Callable[[], None],
    cleanup_errors: list[str],
    operation: str,
) -> None:
    previous_error_count = len(cleanup_errors)
    close_mount()
    mount_errors = tuple(cleanup_errors[previous_error_count:])
    if mount_errors:
        raise RuntimeError(
            f"Installed {operation} mount quiescence failed: "
            + "; ".join(mount_errors)
        )


def _reopen_active_installed_wave2_fixture_after_frontend_quiescence(
    *,
    close_mount: Callable[[], None],
    stop_event_bridge: Callable[[], None],
    close_fixture: Callable[[], None],
    reopen_fixture: Callable[[], Any],
    cleanup_errors: list[str],
) -> Any:
    _quiesce_installed_wave2_mount(
        close_mount=close_mount,
        cleanup_errors=cleanup_errors,
        operation="active Application reopen",
    )
    stop_event_bridge()
    close_fixture()
    return reopen_fixture()


def _advance_installed_wave2_campaign_after_mount_quiescence(
    *,
    application: Any,
    campaign_id: str,
    close_mount: Callable[[], None],
    stop_event_bridge: Callable[[], None],
    cleanup_errors: list[str],
) -> None:
    _quiesce_installed_wave2_mount(
        close_mount=close_mount,
        cleanup_errors=cleanup_errors,
        operation="terminal continuation",
    )
    stop_event_bridge()
    with _serialized_application_access(application):
        completed_campaign = application.advance_diagnostic_campaign(
            campaign_id,
            max_cases=64,
            nodes_per_batch=10_000,
        )
    if completed_campaign.status != "completed":
        raise RuntimeError(
            "Installed Formal Diagnostic Campaign did not reach terminal "
            f"state: status={completed_campaign.status}; cases="
            f"{tuple((case.layer, case.status) for case in completed_campaign.cases)}"
        )


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

    terminal_task = current_task()
    if terminal_task is None or terminal_task.handoff.campaign_id is None:
        raise RuntimeError(
            "Installed terminal Diagnostic Task is unavailable after remount"
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


def _retry_installed_controlled_failure(
    *,
    app: Any,
    host: Any,
    root: Any,
    context: Any,
    task: Any,
    capture_accessibility: Callable[[str], None] | None = None,
) -> tuple[Any, bool, bool, int]:
    """Observe and retry one real failed Campaign node via its typed Feature."""

    from app.features import (
        DiagnosticCommandId,
        DiagnosticCommandIdempotencyKey,
        DiagnosticTaskId,
        DiagnosticTaskLifecycle,
        DiagnosticTasksCommandDisposition,
        DiagnosticTasksContext,
        RetryFailedCampaignNode,
        TaskPhase,
    )

    failed_nodes = tuple(
        node
        for node in task.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    if len(failed_nodes) != 1:
        raise RuntimeError(
            "Issue #118 certification requires exactly one controlled "
            "failed Campaign node"
        )
    failed_node = failed_nodes[0]
    if not failed_node.attempts:
        raise RuntimeError("Controlled failed Campaign node has no attempt")
    failed_attempt = failed_node.attempts[-1]
    failure = failed_attempt.failure
    safe_failure_text = "" if failure is None else (
        f"{failure.code} {failure.message}"
    )
    forbidden_failure_markers = (
        "traceback",
        "sqlite://",
        ".sqlite3",
        "token=",
        "password=",
        "secret=",
        "select ",
        "insert ",
        "update ",
        "delete ",
        "powershell",
        "cmd.exe",
        "\\users\\",
    )
    safe_failure_reason_verified = bool(
        failure is not None
        and failure.code.strip()
        and failure.message.strip()
        and failure.retryable
        and not any(
            marker in safe_failure_text.casefold()
            for marker in forbidden_failure_markers
        )
    )
    if not safe_failure_reason_verified:
        raise RuntimeError(
            "Controlled Campaign failure did not expose a safe redacted reason"
        )

    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    projection = host._diagnostic_tasks
    if projection is None:
        raise RuntimeError("Diagnostic Tasks QML Adapter is unavailable")
    projection.refresh()
    _settle_until(
        app,
        lambda: bool(
            root.property("activeRoute") == "diagnostic_tasks"
            and projection.property("presentationState")
            in {"ready", "partial"}
        ),
        "controlled Diagnostic Task failure presentation",
    )
    accessible_failure = _accessible_announcement(
        root,
        "diagnosticTasksAccessibleSummary",
    ).casefold()
    accessible_history = _accessible_announcement(
        root,
        "failedCampaignNodeAttemptHistory",
    ).casefold()
    if (
        "fail" not in accessible_failure
        or failure.code.casefold() not in accessible_history
        or failure.message.casefold() not in accessible_history
    ):
        raise RuntimeError(
            "Controlled Diagnostic Task failure was not exposed accessibly"
        )
    retry_control = _find_quick_item(root, "retryFailedCampaignNodeButton")
    if retry_control is None or not retry_control.property("enabled"):
        raise RuntimeError(
            "Retry failed Campaign node keyboard control was unavailable"
        )
    _focus_with_keyboard(
        app=app,
        host=host,
        target=retry_control,
    )
    _settle_until(
        app,
        lambda: bool(retry_control.property("activeFocus")),
        "visible failed Campaign attempt history",
    )
    if capture_accessibility is not None:
        capture_accessibility("failed")

    feature = context.diagnostic_tasks_feature
    retry_command = RetryFailedCampaignNode(
        command_id=DiagnosticCommandId(
            "issue-118-installed-retry-command"
        ),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "issue-118-installed-retry-idempotency"
        ),
        task_id=task.task_id,
        campaign_node_id=failed_node.campaign_node_id,
        failed_attempt_id=failed_attempt.attempt_id,
        expected_revision=failed_node.revision,
    )
    accepted = feature.retry_failed_campaign_node(retry_command)
    replay = feature.retry_failed_campaign_node(
        replace(
            retry_command,
            command_id=DiagnosticCommandId(
                "issue-118-installed-retry-lost-response"
            ),
        )
    )
    retry_idempotency_verified = bool(
        accepted.disposition
        is DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
        and accepted.task_handle is not None
        and accepted.task_handle.phase is TaskPhase.QUEUED
        and accepted.affected_campaign_attempt_id is not None
        and replay.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
        and replay.task_handle is not None
        and replay.task_handle.identity == accepted.task_handle.identity
        and replay.affected_campaign_attempt_id
        == accepted.affected_campaign_attempt_id
    )
    if not retry_idempotency_verified:
        raise RuntimeError(
            "DiagnosticTasksFeature retry was not an idempotent queued handoff"
        )
    projection.refresh()
    app.processEvents()
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="run_monitoring",
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="diagnostic_tasks",
    )
    def recovery_status_is_visible() -> bool:
        snapshot = host.accessibility_snapshot()
        recovery_text = snapshot.diagnostic_task_handle_text.casefold()
        return bool(
            root.property("activeRoute") == "diagnostic_tasks"
            and _route_focus_is_visible(root, "diagnostic_tasks")
            and snapshot.diagnostic_tasks_presentation in {"ready", "partial"}
            and "recover" in recovery_text
            and "progress" in recovery_text
        )

    _settle_until(
        app,
        recovery_status_is_visible,
        "visible Diagnostic Task recovery progress after retry",
    )
    if capture_accessibility is not None:
        capture_accessibility("recovering")

    workspace = DiagnosticTasksContext(
        task_id=DiagnosticTaskId(task.task_id.value)
    )
    feature.snapshot(workspace)
    retried = feature.snapshot(workspace).task
    if retried is None:
        raise RuntimeError("Retried Diagnostic Task is unavailable")
    retried_node = next(
        (
            node
            for node in retried.handoff.campaign_nodes
            if node.campaign_node_id == failed_node.campaign_node_id
        ),
        None,
    )
    if retried_node is None:
        raise RuntimeError("Retried Campaign node is unavailable")
    unique_attempt_ids = {
        attempt.attempt_id for attempt in retried_node.attempts
    }
    duplicate_work_count = (
        len(retried_node.attempts) - len(unique_attempt_ids)
    )
    if (
        len(retried_node.attempts) != len(failed_node.attempts) + 1
        or duplicate_work_count != 0
    ):
        raise RuntimeError("Diagnostic Task retry produced duplicate work")
    return (
        retried,
        safe_failure_reason_verified,
        retry_idempotency_verified,
        duplicate_work_count,
    )


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


def _close_release_fixture(
    fixture: Any,
    *,
    defer_native_teardown: bool,
) -> None:
    if defer_native_teardown:
        _retain_native_resources_until_process_exit(fixture)
        fixture.close(dispose_engine=False)
        return
    fixture.close()


def _packaged_fixture_persistence_root(
    *,
    report_dir: Path,
    cleanup: ExitStack,
    cleanup_errors: list[str],
    lifecycle_checks: list[Callable[[], bool]],
    defer_native_teardown: bool,
    temporary_directory_prefix: str,
) -> Path:
    if defer_native_teardown:
        return report_dir / "v1-persistence"
    runtime_root = Path(
        tempfile.mkdtemp(prefix=temporary_directory_prefix)
    )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "temporary persistence root",
        partial(_cleanup_temporary_persistence_root, runtime_root),
    )
    lifecycle_checks.append(_path_absent_check(runtime_root))
    return runtime_root / "v1-persistence"


def run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str = "development-smoke",
    capture_images: bool = True,
    fixture_archive_path: Path | None = None,
    defer_native_teardown: bool = False,
    issue_118_certification: bool = True,
    certification_scope: CertificationScope = (
        CertificationScope.SOURCE_VALIDATION
    ),
) -> PackageSmokeResult:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    if (
        "__compiled__" not in globals()
        and certification_scope is not CertificationScope.SOURCE_VALIDATION
    ):
        raise ValueError(
            "Source smoke cannot claim a compiled certification scope"
        )

    cleanup_errors: list[str] = []
    lifecycle_checks: list[Callable[[], bool]] = []
    with ExitStack() as cleanup:
        if (
            fixture_archive_path is None
            or fixture_archive_path.name
            == WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE
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
                defer_native_teardown=defer_native_teardown,
                issue_118_certification=issue_118_certification,
                certification_scope=certification_scope,
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
                defer_native_teardown=defer_native_teardown,
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


def _shutdown_smoke_application(
    errors: list[str],
    *,
    run_qt_teardown: bool = True,
) -> None:
    from PySide6.QtWidgets import QApplication

    if not run_qt_teardown:
        return
    app = QApplication.instance()
    if app is None:
        return
    actions: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("closeAllWindows", app.closeAllWindows),
        ("shutdown", app.shutdown),
    )
    for label, action in actions:
        try:
            action()
        except BaseException as error:
            errors.append(
                f"QApplication {label} failed: "
                f"{type(error).__name__}"
            )
    if QApplication.instance() is not None:
        errors.append("QApplication remained alive after shutdown")


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
    defer_native_teardown: bool,
    issue_118_certification: bool,
    certification_scope: CertificationScope,
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
        defer_native_teardown=defer_native_teardown,
        issue_118_certification=issue_118_certification,
        certification_scope=certification_scope,
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
    defer_native_teardown: bool = False,
    issue_118_certification: bool = False,
    certification_scope: CertificationScope = (
        CertificationScope.SOURCE_VALIDATION
    ),
) -> PackageSmokeResult:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import EventBridge
    from app.features import (
        ACTIVE_FEATURE_INTERFACES,
        LiveStrategyDiagnosticsV1ApplicationAdapter,
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
        LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    )
    from app.features.diagnostic_setup import (
        DiagnosticSetupSelectionCoordinator,
    )
    from stock_sim.release.frontend_v2_accessibility import (
        ACCESSIBILITY_CHECKPOINT_BINDINGS,
        InstalledAccessibilityCheckpointClock,
        capture_installed_accessibility_checkpoint,
        summarize_installed_accessibility_checkpoints,
        validate_installed_accessibility_checkpoints,
    )
    from stock_sim.release.frontend_v2_runtime_safety import (
        capture_no_manual_trading_route_audit,
        validate_no_manual_trading_route_audits,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        ReleaseCertificationFailFirstPTradeStrategyHost,
        create_file_backed_formal_v1_release_fixture,
        create_file_backed_wave2_release_input_fixture,
        extract_sealed_formal_v1_release_fixture_archive,
        extract_sealed_wave2_release_input_fixture_archive,
        open_sealed_formal_v1_release_fixture,
        open_sealed_wave2_release_input_fixture,
        reopen_active_wave2_release_input_fixture,
        reopen_completed_wave2_release_fixture,
    )

    installed_package_certification = bool(
        "__compiled__" in globals()
        and certification_scope is CertificationScope.INSTALLED
    )

    certification_ptrade_host = (
        ReleaseCertificationFailFirstPTradeStrategyHost()
        if wave2_mode and issue_118_certification
        else None
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
            ptrade_host=certification_ptrade_host,
        )
    elif wave2_mode:
        persistence_root = _packaged_fixture_persistence_root(
            report_dir=report_dir,
            cleanup=cleanup,
            cleanup_errors=cleanup_errors,
            lifecycle_checks=lifecycle_checks,
            defer_native_teardown=defer_native_teardown,
            temporary_directory_prefix="uti-wave3-runtime-",
        )
        if fixture_archive_path is None:
            raise RuntimeError(
                "Wave 3 authoritative input fixture archive is unavailable"
            )
        extract_sealed_wave2_release_input_fixture_archive(
            archive_path=fixture_archive_path,
            bundle_root=persistence_root,
        )
        fixture = open_sealed_wave2_release_input_fixture(
            bundle_root=persistence_root,
            expected_source_commit=source_commit,
            ptrade_host=certification_ptrade_host,
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
        persistence_root = _packaged_fixture_persistence_root(
            report_dir=report_dir,
            cleanup=cleanup,
            cleanup_errors=cleanup_errors,
            lifecycle_checks=lifecycle_checks,
            defer_native_teardown=defer_native_teardown,
            temporary_directory_prefix="uti-v1-runtime-",
        )
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
        partial(
            _close_release_fixture,
            fixture,
            defer_native_teardown=defer_native_teardown,
        ),
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
    terminal_campaign_case_identity = ""
    terminal_selected_campaign_case_identity = ""
    terminal_node_market_scenario_identity = ""
    terminal_campaign_node_lifecycle = ""
    terminal_case_manifest_binding_verified = False
    installed_setup_ledger_reopened = False
    reopened_installed_setup_ledger: dict[str, tuple[str, ...]] = {}
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        fixture.application,
        fixture.engine,
    )
    setup_coordinator = DiagnosticSetupSelectionCoordinator()
    diagnostic_tasks_application = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            fixture.application,
            setup_selection_provider=setup_coordinator.current,
        )
    )
    strategy_library_application = (
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            fixture.application
        )
    )
    scenario_lab_application = (
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            fixture.application
        )
    )
    system_health_application = (
        LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
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
    if not defer_native_teardown:
        cleanup.callback(
            _record_cleanup,
            cleanup_errors,
            "release environment",
            lambda: _restore_environment(previous_environment),
        )
        lifecycle_checks.append(
            _environment_restored_check(previous_environment)
        )
    retired_mounts: list[tuple[Any, dict[str, bool]]] = []
    mount_closers: list[Callable[[], None]] = []

    def schedule_retired_mount_releases() -> None:
        for mounted_window, state in tuple(retired_mounts):
            release_error_count = len(cleanup_errors)
            _schedule_closed_mount_release(
                app=app,
                window=mounted_window,
                errors=cleanup_errors,
            )
            state["release_scheduled"] = (
                len(cleanup_errors) == release_error_count
            )
        retired_mounts.clear()

    # ExitStack callbacks run in reverse registration order. Mount callbacks
    # are registered below, so an exceptional exit first quiesces each mount,
    # then stops the shared EventBridge, and only then schedules deferred
    # native QObject deletion for the owning QApplication.
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "retired QML mount release scheduling",
        schedule_retired_mount_releases,
    )
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
    accessibility_checkpoints: list[dict[str, Any]] = []
    accessibility_checkpoint_clock = (
        InstalledAccessibilityCheckpointClock()
    )
    manual_trading_route_audits: list[dict[str, Any]] = []
    keyboard_routes: set[str] = set()

    def capture_manual_trading_audit(*, route: str, stage: str) -> None:
        if not issue_118_certification:
            return
        audit = capture_no_manual_trading_route_audit(
            root,
            route=route,
            stage=stage,
        )
        manual_trading_route_audits.append(audit)
        if audit.get("forbidden_action_count", 0) > 0:
            raise RuntimeError(
                "Installed no-manual-trading capability detected; "
                "redacted provenance: "
                + json.dumps(
                    {
                        "route": audit.get("route"),
                        "stage": audit.get("stage"),
                        "forbidden_actions": audit.get(
                            "forbidden_actions",
                            [],
                        ),
                    },
                    sort_keys=True,
                )
            )

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
        mount_objects = [context, window, host]
        state = {
            "attempted": False,
            "closed": False,
            "release_scheduled": False,
        }

        def close_mount() -> None:
            if state["attempted"]:
                return
            state["attempted"] = True
            mounted_context, mounted_window, mounted_host = mount_objects
            try:
                _close_mount(
                    app=app,
                    context=mounted_context,
                    window=mounted_window,
                    host=mounted_host,
                    errors=cleanup_errors,
                )
                state["closed"] = _mount_is_closed(
                    mounted_context,
                    mounted_window,
                    mounted_host,
                )
                if not state["closed"]:
                    cleanup_errors.append(
                        "QML mount lifecycle audit failed before release"
                    )
                retired_mounts.append((mounted_window, state))
            finally:
                if defer_native_teardown:
                    _retain_native_resources_until_process_exit(
                        mounted_context,
                        mounted_window,
                        mounted_host,
                    )
                mount_objects.clear()

        cleanup.callback(close_mount)
        mount_closers.append(close_mount)

        def mount_closed() -> bool:
            return bool(
                state["closed"]
                and state["release_scheduled"]
                and not mount_objects
            )

        lifecycle_checks.append(mount_closed)
        return close_mount

    context, window, host = _create_production_window(
        event_bridge=bridge,
        strategy_diagnostics_application=fixture.application,
        strategy_diagnostics_read_model=read_model,
        strategy_diagnostics_tasks_application=diagnostic_tasks_application,
        strategy_diagnostics_library_application=strategy_library_application,
        strategy_diagnostics_scenario_lab_application=scenario_lab_application,
        strategy_diagnostics_system_health_application=(
            system_health_application
        ),
        diagnostic_setup_selection_coordinator=setup_coordinator,
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

    def _checkpoint_matches_current_projection(
        checkpoint: str,
        snapshot: Any,
    ) -> bool:
        if checkpoint == "loading":
            return snapshot.run_presentation == "loading"
        if checkpoint == "empty":
            return snapshot.diagnostic_tasks_presentation == "empty"
        if checkpoint == "failed":
            return snapshot.diagnostic_failed_attempt_present
        if checkpoint == "recovering":
            recovery_text = snapshot.diagnostic_task_handle_text.casefold()
            return "recover" in recovery_text and "progress" in recovery_text
        if checkpoint == "partial":
            return snapshot.system_health_completeness == "partial"
        if checkpoint == "disconnected":
            return bool(
                snapshot.system_health_data_source_connection
                == "disconnected"
                or snapshot.system_health_freshness == "disconnected"
            )
        if checkpoint == "stale":
            return bool(
                snapshot.system_health_data_source_freshness == "stale"
                or snapshot.system_health_freshness == "stale"
            )
        if checkpoint == "completed":
            return snapshot.run_presentation == "terminal"
        return False

    def _wait_for_external_uia_ack(
        *,
        sequence: int,
        checkpoint: str,
        snapshot_identity: str,
    ) -> None:
        configured_root = os.environ.get(
            "UTI_STOCKSIM_UIA_CHECKPOINT_ACK_DIR",
            "",
        ).strip()
        if not configured_root:
            return
        ack_root = Path(configured_root).resolve()
        if ack_root != report_dir.resolve():
            raise RuntimeError(
                "Installed UIA checkpoint acknowledgement root is invalid"
            )
        ack_path = ack_root / (
            f"uia-checkpoint-{sequence:02d}-{checkpoint}.json"
        )
        if ack_path.exists():
            raise RuntimeError(
                "Installed UIA checkpoint acknowledgement was pre-existing"
            )
        deadline = monotonic() + 30.0
        while monotonic() < deadline and not ack_path.is_file():
            app.processEvents()
            sleep(0.05)
        if not ack_path.is_file():
            raise RuntimeError(
                "Installed UIA checkpoint acknowledgement timed out"
            )
        try:
            acknowledgement = json.loads(
                ack_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError) as error:
            raise RuntimeError(
                "Installed UIA checkpoint acknowledgement is invalid"
            ) from error
        if (
            acknowledgement.get("snapshot_identity") != snapshot_identity
            or acknowledgement.get("checkpoint") != checkpoint
            or acknowledgement.get("sequence") != sequence
            or acknowledgement.get("passed") is not True
        ):
            raise RuntimeError(
                "Installed UIA checkpoint acknowledgement did not match"
            )

    def capture_accessibility(checkpoint: str) -> None:
        if not (wave2_mode and issue_118_certification):
            return
        sequence = len(accessibility_checkpoints) + 1
        route = str(root.property("activeRoute") or "")
        snapshot = host.accessibility_snapshot()
        run_revision = snapshot.run_revision
        evidence_revision = snapshot.evidence_revision
        if (
            re.fullmatch(r"r\d+", run_revision) is None
            or re.fullmatch(r"r\d+", evidence_revision) is None
        ):
            raise RuntimeError(
                "Installed accessibility projection revision was invalid"
            )
        if not _checkpoint_matches_current_projection(checkpoint, snapshot):
            raise RuntimeError(
                "Installed accessibility checkpoint did not match the "
                "current public product projection"
            )
        try:
            status_object_name, status_semantic_term = (
                ACCESSIBILITY_CHECKPOINT_BINDINGS[checkpoint]
            )
        except KeyError as error:
            raise RuntimeError(
                "Installed accessibility checkpoint binding was unavailable"
            ) from error
        quick_window = root.window()
        window_device_pixel_ratio = (
            0.0
            if quick_window is None
            else float(quick_window.devicePixelRatio())
        )
        if installed_package_certification and (
            not math.isfinite(window_device_pixel_ratio)
            or window_device_pixel_ratio != 2.0
        ):
            raise RuntimeError(
                "Installed accessibility Qt window scale was not 200 percent"
            )
        window_scale_percent = int(round(window_device_pixel_ratio * 100.0))
        snapshot_identity = (
            f"uia:{sequence}:{checkpoint}:{route}:"
            f"{run_revision}:{evidence_revision}:"
            f"{status_object_name}:{status_semantic_term}:"
            f"scale{window_scale_percent}"
        )
        marker_properties = {
            "installedAccessibilityCheckpointSequence": sequence,
            "installedAccessibilityCheckpointState": checkpoint,
            "installedAccessibilityCheckpointRoute": route,
            "installedAccessibilityRunRevision": run_revision,
            "installedAccessibilityEvidenceRevision": evidence_revision,
            "installedAccessibilityStatusObjectName": status_object_name,
            "installedAccessibilityStatusSemanticTerm": (
                status_semantic_term
            ),
            "installedAccessibilityWindowScalePercent": (
                window_scale_percent
            ),
        }
        if not all(
            root.setProperty(name, value)
            for name, value in marker_properties.items()
        ):
            raise RuntimeError(
                "Installed accessibility checkpoint marker is unavailable"
            )
        app.processEvents()
        checkpoint_evidence = capture_installed_accessibility_checkpoint(
            root,
            checkpoint=checkpoint,
            sequence=sequence,
            snapshot_identity=snapshot_identity,
            route=route,
            run_revision=run_revision,
            evidence_revision=evidence_revision,
            status_object_name=status_object_name,
            status_semantic_term=status_semantic_term,
            captured_at_utc=accessibility_checkpoint_clock.capture(),
        )
        accessibility_checkpoints.append(checkpoint_evidence)
        if (
            checkpoint_evidence.get("non_color_cue_verified") is not True
            or not checkpoint_evidence.get("non_color_cues")
        ):
            raise RuntimeError(
                "Installed accessibility checkpoint lacked a visible "
                "non-color semantic cue; redacted checkpoint summary: "
                + json.dumps(
                    summarize_installed_accessibility_checkpoints(
                        (checkpoint_evidence,)
                    ),
                    sort_keys=True,
                )
            )
        _wait_for_external_uia_ack(
            sequence=sequence,
            checkpoint=checkpoint,
            snapshot_identity=snapshot_identity,
        )

    capture_accessibility("loading")
    accessibility_preferences.append(
        _accessibility_preferences_verified(root)
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="strategy_library",
    )
    keyboard_routes.add("strategy_library")
    strategy_library_adapter = host._strategy_library
    if strategy_library_adapter is None:
        raise RuntimeError("Strategy Library Adapter is unavailable")
    _settle_until(
        app,
        lambda: (
            strategy_library_adapter.property("presentationState")
            in {"ready", "partial"}
            and strategy_library_adapter.property("entryCount") == 2
        ),
        "authoritative Strategy Library route",
    )
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="scenario_lab",
    )
    keyboard_routes.add("scenario_lab")
    scenario_lab_adapter = host._scenario_lab
    if scenario_lab_adapter is None:
        raise RuntimeError("Scenario Lab Adapter is unavailable")
    _settle_until(
        app,
        lambda: (
            scenario_lab_adapter.property("presentationState")
            in {"empty", "ready", "partial"}
        ),
        "authoritative Scenario Lab route",
    )
    capture_accessibility("empty")

    diagnostic_task_identity = ""
    accepted_command_kinds: tuple[str, ...] = ()
    task_handle_identities: tuple[str, ...] = ()
    installed_setup: InstalledWave3SetupEvidence | None = None
    cancel_order_isolation_verified = False
    application_reopened = False
    writable_persistence_verified = False
    background_continuation_verified = False
    focus_restoration_verified = False
    system_health_context_verified = False
    system_health_identity_graph: tuple[str, ...] = ()
    system_health_accessibility_verified = False
    queued_state_observed = False
    running_state_observed = False
    partial_state_observed = False
    controlled_failure_observed = False
    safe_failure_reason_verified = False
    retry_idempotency_verified = False
    duplicate_work_count = -1
    terminal_completion_observed = False
    if wave2_mode:
        input_fixture: Any = fixture
        (
            running_task,
            accepted_command_kinds,
            installed_setup,
        ) = _start_installed_wave2_commands(
            app=app,
            host=host,
            root=root,
            context=context,
            application=input_fixture.application,
            expect_controlled_failure=issue_118_certification,
        )
        diagnostic_task_identity = running_task.task_id.value
        if issue_118_certification:
            controlled_failure_observed = bool(
                any(
                    node.lifecycle.value == "failed"
                    for node in running_task.handoff.campaign_nodes
                )
            )
            if not controlled_failure_observed:
                raise RuntimeError(
                    "Issue #118 certification did not observe the controlled "
                    "Campaign failure"
                )
            (
                running_task,
                safe_failure_reason_verified,
                retry_idempotency_verified,
                duplicate_work_count,
            ) = _retry_installed_controlled_failure(
                app=app,
                host=host,
                root=root,
                context=context,
                task=running_task,
                capture_accessibility=capture_accessibility,
            )
            queued_state_observed = retry_idempotency_verified
            running_state_observed = bool(
                running_task.lifecycle.value == "running"
            )
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

        for route in ACTIVE_JOURNEY_ROUTES:
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
            capture_manual_trading_audit(
                route=route,
                stage="running",
            )

        preterminal_generation = bridge.connection_generation
        bridge.mark_disconnected()
        for route in ACTIVE_JOURNEY_ROUTES:
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
        partial_state_observed = bool(
            root.property("screenState") == "partial"
            or root.property("evidenceScreenState") == "partial"
            or host._run_monitoring.property("freshness")
            in {"last_reliable", "disconnected"}
            or host._evidence_and_findings.property("freshness")
            in {"last_reliable", "disconnected"}
        )
        if not partial_state_observed:
            raise RuntimeError(
                "Installed disconnect did not expose a partial/last-reliable state"
            )
        capture_accessibility("partial")
        capture_accessibility("disconnected")

        preterminal_connection = bridge.mark_reconnected()
        app.processEvents()
        capture_accessibility("stale")
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

        route_before_reopen = str(root.property("activeRoute"))

        fixture = (
            _reopen_active_installed_wave2_fixture_after_frontend_quiescence(
                close_mount=close_initial_mount,
                stop_event_bridge=bridge.stop,
                close_fixture=partial(
                    _close_release_fixture,
                    input_fixture,
                    defer_native_teardown=defer_native_teardown,
                ),
                reopen_fixture=partial(
                    reopen_active_wave2_release_input_fixture,
                    bundle_root=persistence_root,
                    diagnostic_task_id=diagnostic_task_identity,
                    campaign_id=campaign_id,
                    ptrade_host=certification_ptrade_host,
                ),
                cleanup_errors=cleanup_errors,
            )
        )
        cleanup.callback(
            _record_cleanup,
            cleanup_errors,
            "reopened active installed Wave 2 fixture",
            partial(
                _close_release_fixture,
                fixture,
                defer_native_teardown=defer_native_teardown,
            ),
        )
        lifecycle_checks.append(_closed_check(fixture))
        input_fixture = fixture
        _assert_running_wave2_public_state(
            application=input_fixture.application,
            diagnostic_task_id=diagnostic_task_identity,
            campaign_id=campaign_id,
            task_handle_identities=task_handle_identities,
        )
        application_reopened = True
        _advance_installed_wave2_campaign_after_mount_quiescence(
            application=input_fixture.application,
            campaign_id=campaign_id,
            close_mount=close_initial_mount,
            stop_event_bridge=bridge.stop,
            cleanup_errors=cleanup_errors,
        )
        with _serialized_application_access(input_fixture.application):
            completed_backend_task = (
                input_fixture.application.get_diagnostic_task(
                    diagnostic_task_identity
                )
            )
        completed_backend_handoff = (
            None
            if completed_backend_task is None
            else completed_backend_task.campaign_handoff
        )
        completed_backend_handles = (
            ()
            if completed_backend_task is None
            else tuple(
                handle.task_handle_id
                for handle in completed_backend_task.task_handles
            )
        )
        if (
            completed_backend_task is None
            or completed_backend_handoff is None
            or completed_backend_handles != task_handle_identities
            or completed_backend_handoff.campaign_id != campaign_id
            or completed_backend_handoff.evidence_package_id is None
            or completed_backend_handoff.reproduction_manifest_id is None
        ):
            raise RuntimeError(
                "Installed background continuation did not preserve the "
                "Diagnostic Task, TaskHandles, Campaign, evidence, and "
                "Reproduction Manifest identities"
            )
        evidence_package_id = (
            completed_backend_handoff.evidence_package_id
        )
        manifest_id = (
            completed_backend_handoff.reproduction_manifest_id
        )
        background_continuation_verified = True
        terminal_completion_observed = True

        _close_release_fixture(
            input_fixture,
            defer_native_teardown=defer_native_teardown,
        )
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
            partial(
                _close_release_fixture,
                fixture,
                defer_native_teardown=defer_native_teardown,
            ),
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
        bridge.start()
        read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
            fixture.application,
            fixture.engine,
        )
        diagnostic_tasks_application = (
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                fixture.application,
                setup_selection_provider=setup_coordinator.current,
            )
        )
        strategy_library_application = (
            LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
                fixture.application
            )
        )
        scenario_lab_application = (
            LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
                fixture.application
            )
        )
        system_health_application = (
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                fixture.application
            )
        )
        context, window, host = _create_production_window(
            event_bridge=bridge,
            strategy_diagnostics_application=fixture.application,
            strategy_diagnostics_read_model=read_model,
            strategy_diagnostics_tasks_application=(
                diagnostic_tasks_application
            ),
            strategy_diagnostics_library_application=(
                strategy_library_application
            ),
            strategy_diagnostics_scenario_lab_application=(
                scenario_lab_application
            ),
            strategy_diagnostics_system_health_application=(
                system_health_application
            ),
            diagnostic_setup_selection_coordinator=setup_coordinator,
            settings_path=report_dir / "frontend-v2-settings.json",
        )
        close_initial_mount = register_mount(
            context=context,
            window=window,
            host=host,
        )
        window.setObjectName("frontendV2PackageTerminalRemountWindow")
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        root = host.rootObject()
        if root is None:
            raise RuntimeError(
                "Terminal remounted Journey Workspace is unavailable"
            )
        _settle_until(
            app,
            lambda: bool(
                root.property("activeRoute") == route_before_reopen
                and _route_focus_is_visible(root, route_before_reopen)
            ),
            "terminal route and focus restoration",
        )
        focus_restoration_verified = True
        accessibility_preferences.append(
            _accessibility_preferences_verified(root)
        )

        (
            completed_task,
            cancel_order_isolation_verified,
            selected_manifest_id,
        ) = _complete_installed_wave2_campaign(
            app=app,
            host=host,
            context=context,
            application=fixture.application,
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
        if selected_manifest_id != fixture.selected_manifest.manifest_id:
            raise RuntimeError(
                "Installed QML projection selected a different "
                "Reproduction Manifest after Application reopen"
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
        if installed_setup is None:
            raise RuntimeError(
                "Installed Wave 3 setup evidence is unavailable after reopen"
            )
        try:
            terminal_setup_index = (
                installed_setup.approved_recipe_identities.index(recipe_id)
            )
        except ValueError as error:
            raise RuntimeError(
                "Terminal Recipe identity was not created after installation: "
                f"{recipe_id}"
            ) from error
        terminal_setup_case = (
            installed_setup.materialized_scenario_identities[
                terminal_setup_index
            ]
        )
        terminal_setup_path = installed_setup.materialized_path_identities[
            terminal_setup_index
        ]
        terminal_nodes = tuple(
            node
            for node in completed_task.handoff.campaign_nodes
            if node.lifecycle.value == "completed"
            and any(
                run.reproduction_manifest_id is not None
                and run.reproduction_manifest_id.value == manifest_id
                for attempt in node.attempts
                for run in attempt.runs
            )
        )
        if len(terminal_nodes) != 1:
            raise RuntimeError(
                "Terminal Reproduction Manifest did not bind exactly one "
                "Formal Campaign node"
            )
        terminal_node = terminal_nodes[0]
        terminal_campaign_case_identity = (
            terminal_node.campaign_case_id.value
        )
        terminal_selected_campaign_case_identity = (
            terminal_node.selected_campaign_case_id.value
        )
        terminal_node_market_scenario_identity = (
            terminal_node.market_scenario_id.value
        )
        terminal_campaign_node_lifecycle = terminal_node.lifecycle.value
        terminal_case_manifest_binding_verified = bool(
            terminal_campaign_node_lifecycle == "completed"
            and
            terminal_campaign_case_identity == case_id
            and terminal_selected_campaign_case_identity
            == terminal_setup_case
            and terminal_node_market_scenario_identity
            == terminal_setup_path
        )
        if not terminal_case_manifest_binding_verified:
            raise RuntimeError(
                "Terminal execution Case/Manifest did not preserve its "
                "selected Campaign Case and Reference Market Path binding: "
                f"execution_case={terminal_campaign_case_identity!r}; "
                f"manifest_case={case_id!r}; "
                "selected_campaign_case="
                f"{terminal_selected_campaign_case_identity!r}; "
                f"setup_case={terminal_setup_case!r}; "
                f"node_path={terminal_node_market_scenario_identity!r}; "
                f"setup_path={terminal_setup_path!r}"
            )
        with _serialized_application_access(fixture.application):
            reopened_drafts = (
                fixture.application.scenario_recipe_draft_revisions()
            )
            reopened_validations = (
                fixture.application.scenario_recipe_validation_history()
            )
            reopened_approvals = (
                fixture.application.scenario_recipe_approval_history()
            )
            reopened_materialization_tasks = (
                fixture.application.scenario_materialization_task_handles()
            )
            reopened_recipe_ids = {
                item.version_id
                for item in fixture.application.list_approved_scenario_recipes()
            }
            reopened_path_ids = {
                item.artifact_hash
                for item in fixture.application.list_materialized_market_paths()
            }
            reopened_campaign_cases = (
                fixture.application.list_available_diagnostic_campaign_cases()
            )
            reopened_campaign_case_ids = {
                item.case_id for item in reopened_campaign_cases
            }
            reopened_formal_sets = (
                fixture.application.scenario_lab_formal_scenario_sets()
            )
            reopened_scenario_selections = (
                fixture.application.scenario_lab_selection_contexts()
            )
            reopened_task = fixture.application.get_diagnostic_task(
                diagnostic_task_identity
            )
        reopened_binding = (
            None
            if reopened_task is None
            else reopened_task.setup_dependency_binding
        )
        reopened_installed_setup_ledger = {
            "recipe_drafts": tuple(
                sorted(item.draft.draft_id for item in reopened_drafts)
            ),
            "recipe_validations": tuple(
                sorted(item.validation_id for item in reopened_validations)
            ),
            "approved_recipes": tuple(sorted(reopened_recipe_ids)),
            "materialization_task_handles": tuple(
                sorted(
                    item.task_handle_id
                    for item in reopened_materialization_tasks
                )
            ),
            "materialized_paths": tuple(sorted(reopened_path_ids)),
            "materialized_scenarios": tuple(
                sorted(reopened_campaign_case_ids)
            ),
            "draft_validation_approval_bindings": tuple(
                sorted(
                    "|".join(
                        (
                            item.draft.draft.draft_id,
                            ""
                            if item.validation is None
                            else item.validation.validation_id,
                            item.version.version_id,
                        )
                    )
                    for item in reopened_approvals
                )
            ),
            "materialization_bindings": tuple(
                sorted(
                    "|".join(
                        (
                            item.target_identity,
                            item.task_handle_id,
                            item.result_identity or "",
                        )
                    )
                    for item in reopened_materialization_tasks
                )
            ),
            "campaign_case_bindings": tuple(
                sorted(
                    "|".join(
                        (
                            item.recipe_version_id,
                            item.materialization_hash,
                            item.case_id,
                        )
                    )
                    for item in reopened_campaign_cases
                )
            ),
            "formal_scenario_sets": tuple(
                sorted(item.scenario_set_id for item in reopened_formal_sets)
            ),
            "scenario_selection_contexts": tuple(
                sorted(
                    item.selection_context_id
                    for item in reopened_scenario_selections
                )
            ),
            "scenario_selection_set_bindings": tuple(
                sorted(
                    f"{item.selection_context_id}|{item.scenario_set_id}"
                    for item in reopened_scenario_selections
                )
            ),
            "strategy_selection_contexts": (
                ()
                if reopened_binding is None
                else (reopened_binding.strategy_selection_context_id,)
            ),
            "setup_selection_contexts": (
                ()
                if reopened_binding is None
                else (reopened_binding.source_identity,)
            ),
            "task_scenario_selection_contexts": (
                ()
                if reopened_binding is None
                else (reopened_binding.scenario_selection_context_id,)
            ),
        }
        expected_reopened_setup_ledger = {
            "recipe_drafts": tuple(
                sorted(installed_setup.recipe_draft_identities)
            ),
            "recipe_validations": tuple(
                sorted(installed_setup.recipe_validation_identities)
            ),
            "approved_recipes": tuple(
                sorted(installed_setup.approved_recipe_identities)
            ),
            "materialization_task_handles": tuple(
                sorted(
                    installed_setup.materialization_task_handle_identities
                )
            ),
            "materialized_paths": tuple(
                sorted(installed_setup.materialized_path_identities)
            ),
            "materialized_scenarios": tuple(
                sorted(installed_setup.materialized_scenario_identities)
            ),
            "draft_validation_approval_bindings": tuple(
                sorted(
                    "|".join(values)
                    for values in zip(
                        installed_setup.recipe_draft_identities,
                        installed_setup.recipe_validation_identities,
                        installed_setup.approved_recipe_identities,
                        strict=True,
                    )
                )
            ),
            "materialization_bindings": tuple(
                sorted(
                    "|".join(values)
                    for values in zip(
                        installed_setup.approved_recipe_identities,
                        installed_setup.materialization_task_handle_identities,
                        installed_setup.materialized_path_identities,
                        strict=True,
                    )
                )
            ),
            "campaign_case_bindings": tuple(
                sorted(
                    "|".join(values)
                    for values in zip(
                        installed_setup.approved_recipe_identities,
                        installed_setup.materialized_path_identities,
                        installed_setup.materialized_scenario_identities,
                        strict=True,
                    )
                )
            ),
            "formal_scenario_sets": (
                installed_setup.formal_scenario_set_identity,
            ),
            "scenario_selection_contexts": (
                installed_setup.scenario_selection_context_identity,
            ),
            "scenario_selection_set_bindings": (
                installed_setup.scenario_selection_context_identity
                + "|"
                + installed_setup.formal_scenario_set_identity,
            ),
            "strategy_selection_contexts": (
                installed_setup.strategy_selection_context_identity,
            ),
            "setup_selection_contexts": (
                installed_setup.setup_selection_context_identity,
            ),
            "task_scenario_selection_contexts": (
                installed_setup.scenario_selection_context_identity,
            ),
        }
        installed_setup_ledger_reopened = (
            reopened_installed_setup_ledger
            == expected_reopened_setup_ledger
        )
        if (
            not installed_setup_ledger_reopened
            or terminal_setup_path not in fixture.raw_artifact_hashes
            or not set(installed_setup.materialized_path_identities).issubset(
                fixture.raw_artifact_hashes
            )
        ):
            raise RuntimeError(
                "Installed-created Recipe/path/case identities did not "
                "survive terminal Application reopen; "
                f"selected_recipe={recipe_id!r}; "
                f"selected_case={case_id!r}; "
                f"setup_case={terminal_setup_case!r}; "
                f"setup_path={terminal_setup_path!r}; "
                f"expected_ledger={expected_reopened_setup_ledger!r}; "
                f"reopened_ledger={reopened_installed_setup_ledger!r}"
            )
        installed_setup = replace(
            installed_setup,
            recipe_draft_identity=(
                installed_setup.recipe_draft_identities[
                    terminal_setup_index
                ]
            ),
            recipe_validation_identity=(
                installed_setup.recipe_validation_identities[
                    terminal_setup_index
                ]
            ),
            approved_recipe_identity=recipe_id,
            materialization_task_handle_identity=(
                installed_setup.materialization_task_handle_identities[
                    terminal_setup_index
                ]
            ),
            materialized_path_identity=terminal_setup_path,
            materialized_scenario_identity=terminal_setup_case,
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

    def prime_evidence_route() -> None:
        """Complete the current mount's first authoritative Evidence read."""
        _navigate_route(
            app=app,
            host=host,
            root=root,
            route="evidence_and_findings",
        )
        keyboard_routes.add("evidence_and_findings")
        evidence_adapter = host._evidence_and_findings
        if evidence_adapter is None:
            raise RuntimeError("Evidence & Findings Adapter is unavailable")
        _settle_until(
            app,
            lambda: (
                root.property("activeRoute") == "evidence_and_findings"
                and root.property("evidenceScreenState") == "ready"
                and evidence_adapter.property("freshness") == "fresh"
            ),
            "initial authoritative Evidence & Findings route",
        )

    # The route-scoped Evidence subscription is deactivated while the initial
    # workspace route is active.  Prime each mount through production QML so
    # launch and remount retain the strict ready/fresh evidence requirement.
    prime_evidence_route()

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

    # Leave the route-scoped Evidence subscription before publishing the
    # current-generation invalidation.  Publishing while Evidence is active
    # races its queued Qt delivery against the subsequent route change and can
    # expose either stale or fresh at the Run checkpoint.
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="run_monitoring",
    )

    def reconnect_route_is_stale() -> bool:
        snapshot = host.accessibility_snapshot()
        return bool(
            root.property("activeRoute") == "run_monitoring"
            and snapshot.run_freshness == "stale"
            and snapshot.evidence_freshness == "stale"
        )

    _settle_until(
        app,
        reconnect_route_is_stale,
        "reconnected Run route before current-generation invalidation",
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
            ("reconnected_terminal_run", "fresh", "stale"),
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

    if not wave2_mode:
        route_before_reopen = str(root.property("activeRoute"))
        _quiesce_installed_wave2_mount(
            close_mount=close_initial_mount,
            cleanup_errors=cleanup_errors,
            operation="sealed V1 remount",
        )
        context, window, host = _create_production_window(
            event_bridge=bridge,
            strategy_diagnostics_application=fixture.application,
            strategy_diagnostics_read_model=read_model,
            strategy_diagnostics_tasks_application=(
                diagnostic_tasks_application
            ),
            strategy_diagnostics_library_application=(
                strategy_library_application
            ),
            strategy_diagnostics_scenario_lab_application=(
                scenario_lab_application
            ),
            strategy_diagnostics_system_health_application=(
                system_health_application
            ),
            diagnostic_setup_selection_coordinator=setup_coordinator,
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
        _settle_until(
            app,
            lambda: bool(
                root.property("activeRoute") == route_before_reopen
                and _route_focus_is_visible(root, route_before_reopen)
            ),
            "sealed V1 route and focus restoration",
        )
        focus_restoration_verified = True
        accessibility_preferences.append(
            _accessibility_preferences_verified(root)
        )

    prime_evidence_route()
    observe(*EXPECTED_JOURNEY[8])
    observe(*EXPECTED_JOURNEY[9])
    capture_accessibility("completed")

    if wave2_mode and issue_118_certification:
        for route in ACTIVE_JOURNEY_ROUTES:
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
                f"reopened terminal safety audit {route} route",
            )
            capture_manual_trading_audit(
                route=route,
                stage="reopened_terminal",
            )

    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="system_health",
    )
    keyboard_routes.add("system_health")
    system_health_adapter = host._system_health
    if system_health_adapter is None:
        raise RuntimeError("System Health Adapter is unavailable")
    expected_health_resolution = (
        "completed" if wave2_mode else "no_current_task"
    )
    try:
        _settle_until(
            app,
            lambda: bool(
                root.property("activeRoute") == "system_health"
                and system_health_adapter.property("phase") != "loading"
                and system_health_adapter.property(
                    "diagnosticContextResolution"
                )
                == expected_health_resolution
                and (
                    not wave2_mode
                    or system_health_adapter.property(
                        "diagnosticContextTerminal"
                    )
                )
            ),
            "installed System Health diagnostic context",
            timeout_seconds=10.0,
        )
    except RuntimeError as error:
        raise RuntimeError(
            f"{error}; observed route={root.property('activeRoute')!r}, "
            f"phase={system_health_adapter.property('phase')!r}, "
            "resolution="
            f"{system_health_adapter.property('diagnosticContextResolution')!r}, "
            "terminal="
            f"{system_health_adapter.property('diagnosticContextTerminal')!r}, "
            "identity="
            f"{system_health_adapter.property('diagnosticIdentityText')!r}"
        ) from error
    system_health_identity_graph = (
        ()
        if not wave2_mode
        else (
            diagnostic_task_identity,
            campaign_id,
            run_id,
            evidence_package_id,
            manifest_id,
        )
    )
    system_health_identity_text = str(
        system_health_adapter.property("diagnosticIdentityText")
    )
    system_health_context_verified = bool(
        system_health_adapter.property("diagnosticContextResolution")
        == expected_health_resolution
        and (
            not wave2_mode
            or all(
                identity in system_health_identity_text
                for identity in system_health_identity_graph
            )
        )
    )
    system_health_accessible_text = _accessible_announcement(
        root,
        "diagnosticContextAccessibleStatus",
    )
    system_health_accessibility_verified = bool(
        expected_health_resolution.replace("_", " ")
        in system_health_accessible_text.casefold()
        and (
            not wave2_mode
            or all(
                identity in system_health_accessible_text
                for identity in system_health_identity_graph
            )
        )
    )
    if not system_health_context_verified:
        raise RuntimeError(
            "System Health did not preserve the installed "
            "Task/Run/Evidence/Manifest context"
        )
    if not system_health_accessibility_verified:
        raise RuntimeError(
            "System Health diagnostic context is not accessible"
        )
    accessibility_announcements.append(system_health_accessible_text)

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
    accessibility_failures = (
        validate_installed_accessibility_checkpoints(
            accessibility_checkpoints,
            require_installed_window_scale=installed_package_certification,
        )
        if wave2_mode and issue_118_certification
        else ()
    )
    if accessibility_failures:
        raise RuntimeError(
            "Installed accessibility gate failed: "
            + "; ".join(accessibility_failures)
            + "; redacted checkpoint summary: "
            + json.dumps(
                summarize_installed_accessibility_checkpoints(
                    accessibility_checkpoints
                ),
                sort_keys=True,
            )
        )
    manual_trading_failures = (
        validate_no_manual_trading_route_audits(
            manual_trading_route_audits
        )
        if wave2_mode and issue_118_certification
        else ()
    )
    if manual_trading_failures:
        raise RuntimeError(
            "Installed no-manual-trading gate failed: "
            + "; ".join(manual_trading_failures)
        )
    manual_action_count = sum(
        int(audit["forbidden_action_count"])
        for audit in manual_trading_route_audits
    )
    read_only_context_visible = _read_only_context_visible(host)

    result = PackageSmokeResult(
        schema_version=4,
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
        keyboard_navigation_verified=(
            keyboard_routes == set(ACTIVE_JOURNEY_ROUTES)
        ),
        accessibility_preferences_verified=bool(
            accessibility_preferences
            and all(accessibility_preferences)
        ),
        accessibility_announcements=tuple(
            accessibility_announcements
        ),
        accessibility_checkpoints=tuple(accessibility_checkpoints),
        installed_accessibility_verified=bool(
            installed_package_certification and not accessibility_failures
        ),
        no_color_only_meaning_verified=bool(accessibility_checkpoints)
        and all(
            checkpoint.get("non_color_cue_verified") is True
            and bool(checkpoint.get("non_color_cues"))
            for checkpoint in accessibility_checkpoints
        ),
        chart_narrative_table_revision_verified=bool(
            accessibility_checkpoints
            and accessibility_checkpoints[-1][
                "chart_narrative_table_revision"
            ]["same_revision"]
        ),
        manual_trading_route_audits=tuple(
            manual_trading_route_audits
        ),
        certification_scope=certification_scope.value,
        old_generation_rejected=old_generation_rejected,
        authoritative_reconnect_verified=(
            authoritative_reconnect_verified
        ),
        routes_rendered=ACTIVE_JOURNEY_ROUTES,
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
            "authoritative_writable_wave3_inputs"
            if wave2_mode
            else "sealed_completed_v1"
        ),
        strategy_selection_created_after_install=(
            installed_setup is not None
        ),
        recipe_draft_created_after_install=(installed_setup is not None),
        recipe_validation_created_after_install=(
            installed_setup is not None
        ),
        recipe_approval_created_after_install=(installed_setup is not None),
        reference_path_materialized_after_install=(
            installed_setup is not None
        ),
        scenario_set_created_after_install=(installed_setup is not None),
        scenario_selection_created_after_install=(
            installed_setup is not None
        ),
        strategy_selection_context_identity=(
            ""
            if installed_setup is None
            else installed_setup.strategy_selection_context_identity
        ),
        recipe_draft_identity=(
            ""
            if installed_setup is None
            else installed_setup.recipe_draft_identity
        ),
        recipe_validation_identity=(
            ""
            if installed_setup is None
            else installed_setup.recipe_validation_identity
        ),
        materialization_task_handle_identity=(
            ""
            if installed_setup is None
            else installed_setup.materialization_task_handle_identity
        ),
        materialized_path_identity=(
            ""
            if installed_setup is None
            else installed_setup.materialized_path_identity
        ),
        materialized_scenario_identity=(
            ""
            if installed_setup is None
            else installed_setup.materialized_scenario_identity
        ),
        terminal_campaign_case_identity=(
            terminal_campaign_case_identity
        ),
        terminal_selected_campaign_case_identity=(
            terminal_selected_campaign_case_identity
        ),
        terminal_node_market_scenario_identity=(
            terminal_node_market_scenario_identity
        ),
        terminal_campaign_node_lifecycle=(
            terminal_campaign_node_lifecycle
        ),
        terminal_case_manifest_binding_verified=(
            terminal_case_manifest_binding_verified
        ),
        installed_setup_ledger_reopened=(
            installed_setup_ledger_reopened
        ),
        reopened_installed_setup_ledger=(
            reopened_installed_setup_ledger
        ),
        formal_scenario_set_identity=(
            ""
            if installed_setup is None
            else installed_setup.formal_scenario_set_identity
        ),
        scenario_selection_context_identity=(
            ""
            if installed_setup is None
            else installed_setup.scenario_selection_context_identity
        ),
        setup_selection_context_identity=(
            ""
            if installed_setup is None
            else installed_setup.setup_selection_context_identity
        ),
        installed_setup_command_kinds=(
            ()
            if installed_setup is None
            else installed_setup.installed_setup_command_kinds
        ),
        installed_recipe_draft_identities=(
            ()
            if installed_setup is None
            else installed_setup.recipe_draft_identities
        ),
        installed_recipe_validation_identities=(
            ()
            if installed_setup is None
            else installed_setup.recipe_validation_identities
        ),
        installed_approved_recipe_identities=(
            ()
            if installed_setup is None
            else installed_setup.approved_recipe_identities
        ),
        installed_materialization_task_handle_identities=(
            ()
            if installed_setup is None
            else installed_setup.materialization_task_handle_identities
        ),
        installed_materialized_path_identities=(
            ()
            if installed_setup is None
            else installed_setup.materialized_path_identities
        ),
        installed_materialized_scenario_identities=(
            ()
            if installed_setup is None
            else installed_setup.materialized_scenario_identities
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
        system_health_context_verified=system_health_context_verified,
        system_health_identity_graph=system_health_identity_graph,
        system_health_accessibility_verified=(
            system_health_accessibility_verified
        ),
        focus_restoration_verified=focus_restoration_verified,
        queued_state_observed=queued_state_observed,
        running_state_observed=running_state_observed,
        partial_state_observed=partial_state_observed,
        controlled_failure_observed=controlled_failure_observed,
        safe_failure_reason_verified=safe_failure_reason_verified,
        retry_idempotency_verified=retry_idempotency_verified,
        duplicate_work_count=duplicate_work_count,
        terminal_completion_observed=terminal_completion_observed,
    )
    _record_cleanup(
        cleanup_errors,
        "EventBridge pre-fixture quiescence",
        bridge.stop,
    )
    try:
        app.processEvents()
    except BaseException as error:
        cleanup_errors.append(
            "Qt event drain after EventBridge stop failed: "
            f"{type(error).__name__}"
        )
    for close_mount in reversed(tuple(mount_closers)):
        close_mount()
    schedule_retired_mount_releases()
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
    # Hide and drain first so Qt Quick has stopped rendering. Quiesce every QML
    # Adapter without synchronously unloading the compiled native object graph,
    # close the window, and only then close the typed Features. The smoke
    # journey retains Python references for its final lifecycle audit; native
    # object reclamation is deferred to the owning process-exit boundary.
    strategy_library_feature = getattr(
        context,
        "strategy_library_feature",
        None,
    )
    scenario_lab_feature = getattr(
        context,
        "scenario_lab_feature",
        None,
    )
    system_health_feature = getattr(
        context,
        "system_health_feature",
        None,
    )
    close_actions = [
        ("MainWindow hide", window.hide),
        ("Qt event drain before QML teardown", app.processEvents),
        (
            "QML Adapter",
            lambda: host.close_adapter(unload_qml=False),
        ),
        ("Qt event drain after QML teardown", app.processEvents),
        ("MainWindow", window.close),
        ("Qt event drain after MainWindow close", app.processEvents),
    ]
    if strategy_library_feature is not None:
        close_actions.append(
            (
                "Strategy Library Feature",
                strategy_library_feature.close,
            )
        )
    if scenario_lab_feature is not None:
        close_actions.append(
            (
                "Scenario Lab Feature",
                scenario_lab_feature.close,
            )
        )
    close_actions.extend(
        [
            (
                "Diagnostic Tasks Feature",
                context.diagnostic_tasks_feature.close,
            ),
            ("Run Monitoring Feature", context.run_monitoring_feature.close),
            (
                "Evidence and Findings Feature",
                context.evidence_and_findings_feature.close,
            ),
            (
                "System Health Feature",
                lambda: _close_system_health_feature_for_release(
                    system_health_feature
                ),
            ),
            ("Qt event drain after Feature teardown", app.processEvents),
        ]
    )
    for label, action in close_actions:
        try:
            action()
        except BaseException as error:
            observed_errors.append(
                f"{label} cleanup failed: {type(error).__name__}"
            )
    if errors is None and observed_errors:
        raise RuntimeError("; ".join(observed_errors))


def _close_system_health_feature_for_release(feature: Any) -> None:
    if feature is None:
        return
    close_and_wait = getattr(feature, "close_and_wait", None)
    if callable(close_and_wait):
        stopped = bool(close_and_wait(timeout_seconds=5.0))
    else:
        feature.close()
        stopped = True
    if not stopped:
        raise RuntimeError("System Health release worker did not stop")


def _schedule_closed_mount_release(
    *,
    app: Any,
    window: Any,
    errors: list[str] | None = None,
) -> None:
    observed_errors = errors if errors is not None else []
    # Queue ownership release, but do not force DeferredDelete delivery here.
    # Nuitka/PySide6 can corrupt the native heap when a compiled QML graph is
    # synchronously deleted mid-runtime. Source smoke completes Qt static
    # teardown through QApplication.shutdown(). Compiled smoke separately
    # verifies mount, Feature, bridge, and fixture quiescence, then leaves final
    # native-object reclamation to its immediate OS-level process exit.
    try:
        window.deleteLater()
    except BaseException as error:
        observed_errors.append(
            "MainWindow deferred delete cleanup failed: "
            f"{type(error).__name__}"
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


def _cleanup_temporary_persistence_root(
    path: Path,
    *,
    remove_tree: Callable[[Path], Any] = shutil.rmtree,
    collect_cycles: Callable[[], Any] = gc.collect,
    pause: Callable[[float], Any] = sleep,
    max_attempts: int = 20,
) -> None:
    """Remove a closed SQLite fixture without replacing a primary failure."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        if not path.exists():
            return
        collect_cycles()
        try:
            remove_tree(path)
        except OSError:
            if attempt + 1 < max_attempts:
                pause(min(0.05 * (attempt + 1), 0.25))
            continue
        if not path.exists():
            return
    raise RuntimeError("Temporary persistence root remained in use")


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
        and getattr(
            getattr(context, "strategy_library_feature", None),
            "_closed",
            False,
        )
        and getattr(
            getattr(context, "scenario_lab_feature", None),
            "_closed",
            False,
        )
        and _owned_executor_is_stopped(
            getattr(context, "scenario_lab_feature", None)
        )
        and getattr(context.diagnostic_tasks_feature, "_closed", False)
        and getattr(context.run_monitoring_feature, "_closed", False)
        and _owned_executor_is_stopped(context.run_monitoring_feature)
        and getattr(
            context.evidence_and_findings_feature,
            "_closed",
            False,
        )
        and _owned_executor_is_stopped(
            context.evidence_and_findings_feature
        )
        and _system_health_release_is_stopped(
            getattr(context, "system_health_feature", None)
        )
        and not window.isVisible()
    )


def _owned_executor_is_stopped(feature: Any) -> bool:
    if not getattr(feature, "_owns_executor", False):
        return True
    executor = getattr(feature, "_executor", None)
    if executor is None:
        return False
    return all(
        not thread.is_alive()
        for thread in tuple(getattr(executor, "_threads", ()))
    )


def _system_health_release_is_stopped(feature: Any) -> bool:
    if feature is None:
        return True
    return bool(getattr(feature, "release_stopped", False))


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
    return len(_unapproved_interactive_actions(root))


def _unapproved_interactive_actions(
    root: Any,
) -> tuple[tuple[str, str, str], ...]:
    from PySide6.QtCore import QObject

    findings: list[tuple[str, str, str]] = []
    for item in (root, *root.findChildren(QObject)):
        meta = item.metaObject()
        class_name_getter = getattr(meta, "className", None)
        class_name = (
            str(class_name_getter())
            if callable(class_name_getter)
            else type(item).__name__
        )
        object_name = str(item.property("objectName") or "")
        if object_name in _PACKAGED_NON_ACTION_FOCUS_OBJECT_NAMES:
            continue
        if (
            not object_name
            and (
                class_name.startswith("QQuickTextField")
                or class_name.startswith("TextField_QMLTYPE")
            )
            and _has_qml_parent_object_name(
                item,
                _PACKAGED_NON_ACTION_FOCUS_PARENT_OBJECT_NAMES,
            )
        ):
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
                findings.append(
                    (
                        class_name,
                        object_name or _qml_parent_object_path(item),
                        "missing accessible name",
                    )
                )
            continue
        if not _APPROVED_INTERACTIVE_NAMES.fullmatch(name):
            findings.append((class_name, object_name, name))
    return tuple(findings)


def _qml_parent_object_path(item: Any) -> str:
    names: list[str] = []
    parent = item.parent()
    while parent is not None:
        name = str(parent.property("objectName") or "")
        if name:
            names.append(name)
        parent = parent.parent()
    return "/".join(names)


def _has_qml_parent_object_name(
    item: Any,
    approved_names: frozenset[str],
) -> bool:
    parent = item.parent()
    while parent is not None:
        if str(parent.property("objectName") or "") in approved_names:
            return True
        parent = parent.parent()
    return False


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
    app.aboutToQuit.connect(context.strategy_library_feature.close)
    app.aboutToQuit.connect(context.scenario_lab_feature.close)
    app.aboutToQuit.connect(context.diagnostic_tasks_feature.close)
    app.aboutToQuit.connect(context.run_monitoring_feature.close)
    app.aboutToQuit.connect(context.evidence_and_findings_feature.close)
    app.aboutToQuit.connect(context.system_health_feature.close)
    app.aboutToQuit.connect(stop_frontend_bridge)
    window.show()
    return int(app.exec())


def _installed_formal_v1_fixture_archive_path() -> Path:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
    )

    return (
        Path(sys.argv[0]).resolve().parent
        / str(FORMAL_V1_RELEASE_FIXTURE_ARCHIVE)
    )


def _installed_wave3_input_fixture_archive_path() -> Path:
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    return (
        Path(sys.argv[0]).resolve().parent
        / str(WAVE3_RELEASE_INPUT_FIXTURE_ARCHIVE)
    )


def _write_certification_report(
    report_path: Path,
    payload: dict[str, Any],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_installed_performance_report(
    *,
    report_path: Path,
    renderer_lane: RendererLane,
    duration_seconds: float,
    source_commit: str,
    fixture_archive_path: Path,
) -> int:
    from stock_sim.release.frontend_v2_performance import (
        REFERENCE_FIXTURE,
    )
    from stock_sim.release.frontend_v2_performance_runtime import (
        run_performance_lane,
    )

    if duration_seconds < REFERENCE_FIXTURE.duration_seconds:
        raise RuntimeError(
            "An installed certifying performance lane must run continuously "
            f"for at least {REFERENCE_FIXTURE.duration_seconds} seconds"
        )
    if not fixture_archive_path.is_file():
        raise RuntimeError(
            "The packaged real V1 performance fixture archive is unavailable"
        )
    report = run_performance_lane(
        lane=renderer_lane.value,
        duration_seconds=duration_seconds,
        source_commit=source_commit,
        smoke=False,
        process_started_ns=perf_counter_ns(),
        fixture_archive_path=fixture_archive_path,
    )
    _write_certification_report(report_path, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


def _wave3_bookmark_payload() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "diagnostic_tasks",
            "diagnostic_task_id": "diagnostic-task-wave3-installed",
            "scenario_focus_target": "market_scenario",
            "scenario_focus_identity": "market-scenario-wave3-installed",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _file_inventory(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def _run_installed_migration_report(
    *,
    report_path: Path,
    migration_kind: str,
    work_root: Path,
    source_commit: str,
    fixture_archive_path: Path,
) -> int:
    from app.journey_recovery import restore_journey_workspace_bookmark
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        create_file_backed_wave2_release_input_fixture,
        extract_sealed_wave2_release_input_fixture_archive,
        open_sealed_wave2_release_input_fixture,
        reopen_file_backed_wave2_release_input_fixture,
    )
    from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION

    if work_root.exists() and any(work_root.iterdir()):
        raise RuntimeError("The installed migration work root must be empty")
    work_root.mkdir(parents=True, exist_ok=True)
    first_identities: tuple[str, ...]
    second_identities: tuple[str, ...]
    reopen_verified = False
    initial_inventory: tuple[str, ...]
    final_inventory: tuple[str, ...]
    clean_exit = False
    schema_migration_verified = False
    source_schema_revision = ""
    initial_applied_revisions: tuple[str, ...] = ()
    first_reopen_applied_revisions: tuple[str, ...] = ()
    second_reopen_applied_revisions: tuple[str, ...] = ()
    if migration_kind == "fresh":
        fresh_root = work_root / "fresh-install"
        database_path = fresh_root / "strategy-diagnostics-v1.sqlite3"
        artifact_root = fresh_root / "artifacts"
        first = create_file_backed_wave2_release_input_fixture(
            database_path=database_path,
            artifact_root=artifact_root,
        )
        try:
            first_identities = first.authoritative_input_identities
            initial_migration = first.initialization_migration
            first_reopen_migration = first.reopen_migration
        finally:
            first.close()
        first_closed = first.closed
        initial_inventory = _file_inventory(fresh_root)
        second = reopen_file_backed_wave2_release_input_fixture(
            database_path=database_path,
            artifact_root=artifact_root,
        )
        try:
            second_identities = second.authoritative_input_identities
            second_reopen_migration = second.reopen_migration
        finally:
            second.close()
        reopen_verified = first_closed and second.closed
        final_inventory = _file_inventory(fresh_root)
        clean_exit = reopen_verified
        if initial_migration is not None:
            source_schema_revision = initial_migration.current_revision
            initial_applied_revisions = initial_migration.applied_revisions
        first_reopen_applied_revisions = (
            first_reopen_migration.applied_revisions
        )
        second_reopen_applied_revisions = (
            second_reopen_migration.applied_revisions
        )
        schema_migration_verified = bool(
            initial_migration is not None
            and initial_migration.current_revision == DIAGNOSTIC_SCHEMA_REVISION
            and initial_applied_revisions
            and initial_applied_revisions[-1] == DIAGNOSTIC_SCHEMA_REVISION
            and first_reopen_migration.current_revision
            == DIAGNOSTIC_SCHEMA_REVISION
            and not first_reopen_applied_revisions
            and second_reopen_migration.current_revision
            == DIAGNOSTIC_SCHEMA_REVISION
            and not second_reopen_applied_revisions
        )
    elif migration_kind == "copied-wave3":
        copied_root = work_root / "copied-wave3"
        extract_sealed_wave2_release_input_fixture_archive(
            archive_path=fixture_archive_path,
            bundle_root=copied_root,
        )
        initial_inventory = _file_inventory(copied_root)
        first = open_sealed_wave2_release_input_fixture(
            bundle_root=copied_root,
            expected_source_commit=source_commit,
        )
        try:
            first_identities = first.authoritative_input_identities
            first_reopen_migration = first.reopen_migration
        finally:
            first.close()
        second = open_sealed_wave2_release_input_fixture(
            bundle_root=copied_root,
            expected_source_commit=source_commit,
        )
        try:
            second_identities = second.authoritative_input_identities
            second_reopen_migration = second.reopen_migration
        finally:
            second.close()
        reopen_verified = first.closed and second.closed
        final_inventory = _file_inventory(copied_root)
        clean_exit = reopen_verified
        source_schema_revision = first_reopen_migration.current_revision
        first_reopen_applied_revisions = (
            first_reopen_migration.applied_revisions
        )
        second_reopen_applied_revisions = (
            second_reopen_migration.applied_revisions
        )
        schema_migration_verified = bool(
            first_reopen_migration.current_revision
            == DIAGNOSTIC_SCHEMA_REVISION
            and second_reopen_migration.current_revision
            == DIAGNOSTIC_SCHEMA_REVISION
            and not first_reopen_applied_revisions
            and not second_reopen_applied_revisions
        )
    else:
        raise RuntimeError("Unsupported installed migration kind")

    first_bookmark = restore_journey_workspace_bookmark(
        _wave3_bookmark_payload()
    )
    second_bookmark = restore_journey_workspace_bookmark(
        first_bookmark.canonical_payload
    )
    identity_retention_verified = bool(
        first_identities
        and first_identities == second_identities
    )
    bookmark_migration_verified = bool(
        first_bookmark.migrated
        and not second_bookmark.migrated
        and first_bookmark.bookmark == second_bookmark.bookmark
        and first_bookmark.canonical_payload
        == second_bookmark.canonical_payload
    )
    non_destructive = set(initial_inventory).issubset(final_inventory)
    passed = bool(
        schema_migration_verified
        and identity_retention_verified
        and bookmark_migration_verified
        and reopen_verified
        and clean_exit
        and non_destructive
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": migration_kind,
        "source_commit": source_commit,
        "passed": passed,
        "schema_revision": DIAGNOSTIC_SCHEMA_REVISION,
        "schema_migration_verified": schema_migration_verified,
        "source_schema_revision": source_schema_revision,
        "target_schema_revision": DIAGNOSTIC_SCHEMA_REVISION,
        "initial_applied_revisions": list(initial_applied_revisions),
        "first_reopen_applied_revisions": list(
            first_reopen_applied_revisions
        ),
        "second_reopen_applied_revisions": list(
            second_reopen_applied_revisions
        ),
        "bookmark_migration_verified": bookmark_migration_verified,
        "deterministic": identity_retention_verified,
        "idempotent": bool(
            schema_migration_verified
            and not second_reopen_applied_revisions
            and reopen_verified
            and not second_bookmark.migrated
        ),
        "identity_retention_verified": identity_retention_verified,
        "reopen_verified": reopen_verified,
        "destructive_migration": not non_destructive,
        "authoritative_input_identities": list(first_identities),
        "initial_file_inventory": list(initial_inventory),
        "final_file_inventory": list(final_inventory),
        "bookmark_route": first_bookmark.bookmark.last_route.value,
        "bookmark_task_identity": (
            None
            if first_bookmark.bookmark.diagnostic_task_id is None
            else first_bookmark.bookmark.diagnostic_task_id.value
        ),
        "clean_exit": clean_exit,
        "errors": [] if passed else ["Installed migration probe failed"],
    }
    _write_certification_report(report_path, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 1


def _run_installed_recovery_report(
    *,
    report_path: Path,
    source_commit: str,
    bundle_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
    diagnostic_task_id: str,
) -> int:
    from stock_sim.release.wave4_rollback_probe import (
        run_candidate_authoritative_recovery_probe,
    )

    probe = run_candidate_authoritative_recovery_probe(
        bundle_root=bundle_root,
        campaign_id=campaign_id,
        evidence_package_id=evidence_package_id,
        selected_manifest_id=selected_manifest_id,
        diagnostic_task_id=diagnostic_task_id,
    )
    payload = {
        "schema_version": 1,
        "source_commit": source_commit,
        **asdict(probe),
    }
    _write_certification_report(report_path, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if probe.clean_exit else 1


def _run_installed_observation_readiness_report(
    *,
    report_path: Path,
    source_commit: str,
) -> int:
    from stock_sim.release.wave4_legacy_inventory import (
        build_legacy_route_inventory,
    )
    from stock_sim.release.wave4_observation_ledger import (
        DAILY_LEDGER_JSON_SCHEMA_PATH,
        DAILY_LEDGER_SCHEMA_VERSION,
        EXPECTED_CHECKPOINT_IDS,
        METRIC_SET_ID,
        REQUIRED_FEATURE_ROUTES,
    )

    captured_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    inventory = build_legacy_route_inventory(
        source_commit=source_commit,
        captured_at=captured_at,
    )
    schema_available = DAILY_LEDGER_JSON_SCHEMA_PATH.is_file()
    configuration_available = bool(
        schema_available
        and DAILY_LEDGER_SCHEMA_VERSION
        and METRIC_SET_ID
        and EXPECTED_CHECKPOINT_IDS
        and REQUIRED_FEATURE_ROUTES == ACTIVE_JOURNEY_ROUTES
    )
    legacy_route_count = inventory.get("legacy_route_count")
    inventory_available = bool(
        isinstance(legacy_route_count, int)
        and not isinstance(legacy_route_count, bool)
        and legacy_route_count > 0
        and inventory.get("widgets_shell_status") == "retained"
        and inventory.get("deletion_authorized") is False
    )
    passed = inventory_available and configuration_available
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source_commit": source_commit,
        "passed": passed,
        "legacy_inventory_available": inventory_available,
        "legacy_route_count": legacy_route_count,
        "legacy_inventory": inventory,
        "observation_ledger_configuration_available": configuration_available,
        "observation_ledger_schema_version": DAILY_LEDGER_SCHEMA_VERSION,
        "observation_metric_set_id": METRIC_SET_ID,
        "required_feature_routes": list(REQUIRED_FEATURE_ROUTES),
        "expected_checkpoint_ids": list(EXPECTED_CHECKPOINT_IDS),
        "observation_window_started": False,
        "destructive_migration": False,
        "errors": [] if passed else ["Observation-ledger readiness is incomplete"],
    }
    _write_certification_report(report_path, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 1


def _installed_recipe_family_is_complete(result: PackageSmokeResult) -> bool:
    collections = (
        result.installed_recipe_draft_identities,
        result.installed_recipe_validation_identities,
        result.installed_approved_recipe_identities,
        result.installed_materialization_task_handle_identities,
        result.installed_materialized_path_identities,
        result.installed_materialized_scenario_identities,
    )
    if any(
        len(values) != 14
        or len(set(values)) != 14
        or any(not value.strip() for value in values)
        for values in collections
    ):
        return False
    try:
        selected_index = result.installed_approved_recipe_identities.index(
            result.approved_recipe_identity
        )
    except ValueError:
        return False
    return (
        result.recipe_draft_identity
        == result.installed_recipe_draft_identities[selected_index]
        and result.recipe_validation_identity
        == result.installed_recipe_validation_identities[selected_index]
        and result.materialization_task_handle_identity
        == result.installed_materialization_task_handle_identities[
            selected_index
        ]
        and result.materialized_path_identity
        == result.installed_materialized_path_identities[selected_index]
        and result.materialized_scenario_identity
        == result.installed_materialized_scenario_identities[selected_index]
    )


def _expected_reopened_setup_ledger(
    result: PackageSmokeResult,
) -> dict[str, tuple[str, ...]]:
    identity_families = (
        result.installed_recipe_draft_identities,
        result.installed_recipe_validation_identities,
        result.installed_approved_recipe_identities,
        result.installed_materialization_task_handle_identities,
        result.installed_materialized_path_identities,
        result.installed_materialized_scenario_identities,
    )
    if any(len(values) != 14 for values in identity_families):
        return {}
    return {
        "recipe_drafts": tuple(
            sorted(result.installed_recipe_draft_identities)
        ),
        "recipe_validations": tuple(
            sorted(result.installed_recipe_validation_identities)
        ),
        "approved_recipes": tuple(
            sorted(result.installed_approved_recipe_identities)
        ),
        "materialization_task_handles": tuple(
            sorted(result.installed_materialization_task_handle_identities)
        ),
        "materialized_paths": tuple(
            sorted(result.installed_materialized_path_identities)
        ),
        "materialized_scenarios": tuple(
            sorted(result.installed_materialized_scenario_identities)
        ),
        "draft_validation_approval_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(
                    result.installed_recipe_draft_identities,
                    result.installed_recipe_validation_identities,
                    result.installed_approved_recipe_identities,
                    strict=True,
                )
            )
        ),
        "materialization_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(
                    result.installed_approved_recipe_identities,
                    result.installed_materialization_task_handle_identities,
                    result.installed_materialized_path_identities,
                    strict=True,
                )
            )
        ),
        "campaign_case_bindings": tuple(
            sorted(
                "|".join(values)
                for values in zip(
                    result.installed_approved_recipe_identities,
                    result.installed_materialized_path_identities,
                    result.installed_materialized_scenario_identities,
                    strict=True,
                )
            )
        ),
        "formal_scenario_sets": (result.formal_scenario_set_identity,),
        "scenario_selection_contexts": (
            result.scenario_selection_context_identity,
        ),
        "scenario_selection_set_bindings": (
            result.scenario_selection_context_identity
            + "|"
            + result.formal_scenario_set_identity,
        ),
        "strategy_selection_contexts": (
            result.strategy_selection_context_identity,
        ),
        "setup_selection_contexts": (
            result.setup_selection_context_identity,
        ),
        "task_scenario_selection_contexts": (
            result.scenario_selection_context_identity,
        ),
    }


def _compiled_smoke_failures(
    result: PackageSmokeResult,
    *,
    shutdown_errors: Sequence[str],
    certification_scope: CertificationScope = CertificationScope.INSTALLED,
) -> tuple[str, ...]:
    failures = [*shutdown_errors, *result.errors]
    checks = (
        (
            result.certification_scope == certification_scope.value,
            "installed Journey certification scope did not match",
        ),
        (result.clean_exit, "installed Journey did not exit cleanly"),
        (
            result.manual_trading_action_count == 0,
            "installed Journey exposed a manual-trading action",
        ),
        (
            result.read_only_context_visible,
            "installed Journey lost its read-only context",
        ),
        (
            result.fixture_kind == "authoritative_writable_wave3_inputs",
            "installed Journey did not use authoritative Wave 3 inputs",
        ),
        (
            result.strategy_selection_created_after_install,
            "formal Strategy selection was not created after install",
        ),
        (
            result.recipe_draft_created_after_install,
            "Recipe Draft was not created after install",
        ),
        (
            result.recipe_validation_created_after_install,
            "Recipe validation was not created after install",
        ),
        (
            result.recipe_approval_created_after_install,
            "Recipe approval was not created after install",
        ),
        (
            result.reference_path_materialized_after_install,
            "Reference Market Path was not materialized after install",
        ),
        (
            result.scenario_set_created_after_install,
            "Formal Scenario Set was not created after install",
        ),
        (
            result.scenario_selection_created_after_install,
            "Formal Scenario selection was not created after install",
        ),
        (
            result.installed_setup_command_kinds
            == WAVE3_ACCEPTED_SETUP_COMMAND_KINDS,
            "installed setup command kinds are incomplete",
        ),
        (
            _installed_recipe_family_is_complete(result),
            "installed 14-case Recipe family is incomplete or misbound",
        ),
        (
            result.terminal_case_manifest_binding_verified
            and result.terminal_campaign_case_identity
            == result.case_identity
            and result.terminal_selected_campaign_case_identity
            == result.materialized_scenario_identity
            and result.terminal_node_market_scenario_identity
            == result.materialized_path_identity
            and result.terminal_campaign_node_lifecycle == "completed",
            "terminal Manifest execution Case is not bound to the selected "
            "installed Campaign Case",
        ),
        (
            result.installed_setup_ledger_reopened
            and result.reopened_installed_setup_ledger
            == _expected_reopened_setup_ledger(result),
            "installed setup ledger was not authoritatively re-read after "
            "Application reopen",
        ),
        (
            all(
                value.strip()
                for value in (
                    result.strategy_selection_context_identity,
                    result.recipe_draft_identity,
                    result.recipe_validation_identity,
                    result.approved_recipe_identity,
                    result.materialization_task_handle_identity,
                    result.materialized_path_identity,
                    result.materialized_scenario_identity,
                    result.formal_scenario_set_identity,
                    result.scenario_selection_context_identity,
                    result.setup_selection_context_identity,
                )
            ),
            "installed setup identity evidence is incomplete",
        ),
        (
            result.task_created_after_install,
            "Diagnostic Task was not created after install",
        ),
        (
            result.campaign_created_after_install,
            "Formal Diagnostic Campaign was not created after install",
        ),
        (
            bool(result.diagnostic_task_identity.strip()),
            "Diagnostic Task identity is unavailable",
        ),
        (
            result.accepted_command_kinds == WAVE2_ACCEPTED_COMMAND_KINDS,
            "Diagnostic Task command kinds are incomplete",
        ),
        (
            len(result.task_handle_identities) >= 3
            and all(
                identity.strip()
                for identity in result.task_handle_identities
            )
            and len(set(result.task_handle_identities))
            == len(result.task_handle_identities),
            "Diagnostic TaskHandle identities are incomplete or invalid",
        ),
        (
            result.writable_persistence_verified,
            "writable persistence was not verified",
        ),
        (result.application_reopened, "Application reopen was not verified"),
        (
            result.background_continuation_verified,
            "background Campaign continuation was not verified",
        ),
        (
            result.task_cancel_order_isolation_verified,
            "Diagnostic Task cancel/order isolation was not verified",
        ),
        (result.queued_state_observed, "queued task state was not observed"),
        (result.running_state_observed, "running task state was not observed"),
        (result.partial_state_observed, "partial task state was not observed"),
        (
            result.controlled_failure_observed,
            "controlled task failure was not observed",
        ),
        (
            result.safe_failure_reason_verified,
            "safe redacted task failure reason was not verified",
        ),
        (
            result.retry_idempotency_verified
            and result.duplicate_work_count == 0,
            "DiagnosticTasksFeature retry was not idempotent",
        ),
        (
            result.terminal_completion_observed,
            "terminal task completion was not observed",
        ),
        (
            result.routes_rendered == ACTIVE_JOURNEY_ROUTES
            and result.keyboard_navigation_verified,
            "installed Journey did not complete all six keyboard routes",
        ),
        (
            result.system_health_context_verified
            and result.system_health_accessibility_verified
            and bool(result.system_health_identity_graph),
            "System Health did not preserve the exact installed context",
        ),
        (
            result.focus_restoration_verified,
            "installed route focus was not restored after reopen",
        ),
        (
            (
                certification_scope is CertificationScope.PACKAGE_ASSEMBLY
                or result.installed_accessibility_verified
            )
            and result.no_color_only_meaning_verified
            and result.chart_narrative_table_revision_verified
            and len(result.accessibility_checkpoints) >= 8,
            "installed accessibility checkpoints are incomplete",
        ),
    )
    failures.extend(message for passed, message in checks if not passed)
    return tuple(failures)


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = tuple(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "--renderer-lane",
        choices=tuple(lane.value for lane in RendererLane),
        default=RendererLane.HARDWARE.value,
    )
    parser.add_argument("--smoke-report-dir", type=Path)
    parser.add_argument("--package-assembly-smoke-report-dir", type=Path)
    parser.add_argument("--performance-report", type=Path)
    parser.add_argument(
        "--performance-duration-seconds",
        type=float,
        default=60.0,
    )
    parser.add_argument("--migration-report", type=Path)
    parser.add_argument(
        "--migration-kind",
        choices=("fresh", "copied-wave3"),
    )
    parser.add_argument("--migration-work-root", type=Path)
    parser.add_argument("--recovery-report", type=Path)
    parser.add_argument("--observation-readiness-report", type=Path)
    parser.add_argument("--supported-data-copy", type=Path)
    parser.add_argument("--campaign-id")
    parser.add_argument("--evidence-package-id")
    parser.add_argument("--selected-manifest-id")
    parser.add_argument("--diagnostic-task-id")
    parser.add_argument("--fixture-archive", type=Path)
    parser.add_argument("--source-commit", default="unbound")
    parser.add_argument("--no-images", action="store_true")
    arguments = parser.parse_args(raw_arguments)
    report_modes = tuple(
        value
        for value in (
            arguments.smoke_report_dir,
            arguments.package_assembly_smoke_report_dir,
            arguments.performance_report,
            arguments.migration_report,
            arguments.recovery_report,
            arguments.observation_readiness_report,
        )
        if value is not None
    )
    if len(report_modes) > 1:
        parser.error("installed certification report modes are mutually exclusive")
    renderer_lane = RendererLane(arguments.renderer_lane)
    configure_renderer_environment(renderer_lane)
    if arguments.performance_report is not None:
        fixture_archive_path = arguments.fixture_archive
        if fixture_archive_path is None and "__compiled__" in globals():
            fixture_archive_path = _installed_formal_v1_fixture_archive_path()
        if fixture_archive_path is None:
            parser.error("--fixture-archive is required outside the package")
        return _run_installed_performance_report(
            report_path=arguments.performance_report,
            renderer_lane=renderer_lane,
            duration_seconds=arguments.performance_duration_seconds,
            source_commit=arguments.source_commit,
            fixture_archive_path=fixture_archive_path,
        )
    if arguments.migration_report is not None:
        fixture_archive_path = arguments.fixture_archive
        if fixture_archive_path is None and "__compiled__" in globals():
            fixture_archive_path = _installed_wave3_input_fixture_archive_path()
        if arguments.migration_kind is None:
            parser.error("--migration-kind is required with --migration-report")
        if arguments.migration_work_root is None:
            parser.error(
                "--migration-work-root is required with --migration-report"
            )
        if fixture_archive_path is None:
            parser.error("--fixture-archive is required outside the package")
        return _run_installed_migration_report(
            report_path=arguments.migration_report,
            migration_kind=arguments.migration_kind,
            work_root=arguments.migration_work_root,
            source_commit=arguments.source_commit,
            fixture_archive_path=fixture_archive_path,
        )
    if arguments.recovery_report is not None:
        recovery_values = (
            arguments.supported_data_copy,
            arguments.campaign_id,
            arguments.evidence_package_id,
            arguments.selected_manifest_id,
            arguments.diagnostic_task_id,
        )
        if any(value is None for value in recovery_values):
            parser.error(
                "supported data-copy and durable identity arguments are "
                "required with --recovery-report"
            )
        return _run_installed_recovery_report(
            report_path=arguments.recovery_report,
            source_commit=arguments.source_commit,
            bundle_root=arguments.supported_data_copy,
            campaign_id=arguments.campaign_id,
            evidence_package_id=arguments.evidence_package_id,
            selected_manifest_id=arguments.selected_manifest_id,
            diagnostic_task_id=arguments.diagnostic_task_id,
        )
    if arguments.observation_readiness_report is not None:
        return _run_installed_observation_readiness_report(
            report_path=arguments.observation_readiness_report,
            source_commit=arguments.source_commit,
        )
    smoke_report_dir = (
        arguments.package_assembly_smoke_report_dir
        if arguments.package_assembly_smoke_report_dir is not None
        else arguments.smoke_report_dir
    )
    if smoke_report_dir is not None:
        compiled_package = "__compiled__" in globals()
        certification_scope = (
            CertificationScope.PACKAGE_ASSEMBLY
            if arguments.package_assembly_smoke_report_dir is not None
            else (
                CertificationScope.INSTALLED
                if compiled_package
                else CertificationScope.SOURCE_VALIDATION
            )
        )
        if (
            certification_scope is CertificationScope.PACKAGE_ASSEMBLY
            and not compiled_package
        ):
            parser.error(
                "--package-assembly-smoke-report-dir requires the compiled "
                "package"
            )
        fixture_archive_path = arguments.fixture_archive
        if fixture_archive_path is None and compiled_package:
            fixture_archive_path = _installed_wave3_input_fixture_archive_path()
        from PySide6.QtWidgets import QApplication

        owns_application = QApplication.instance() is None
        shutdown_errors: list[str] = []
        try:
            result = run_smoke_journey(
                report_dir=smoke_report_dir,
                renderer_lane=renderer_lane,
                source_commit=arguments.source_commit,
                capture_images=not arguments.no_images,
                fixture_archive_path=fixture_archive_path,
                defer_native_teardown=compiled_package,
                certification_scope=certification_scope,
            )
        finally:
            if owns_application:
                _shutdown_smoke_application(
                    shutdown_errors,
                    run_qt_teardown=not compiled_package,
                )
        failures = (
            _compiled_smoke_failures(
                result,
                shutdown_errors=shutdown_errors,
                certification_scope=certification_scope,
            )
            if compiled_package
            else tuple((*shutdown_errors, *result.errors))
        )
        if failures:
            print(
                "Installed smoke rejected: " + "; ".join(failures),
                file=sys.stderr,
            )
            return 1
        return 0
    return _run_interactive()


def _run_process_entry(
    *,
    compiled: bool,
    arguments: Sequence[str],
    run: Callable[[], int] = main,
    terminate: Callable[[int], None] = _terminate_compiled_smoke_process,
    cyclic_gc_enabled: Callable[[], bool] = gc.isenabled,
    suspend_cyclic_gc: Callable[[], None] = gc.disable,
    resume_cyclic_gc: Callable[[], None] = gc.enable,
) -> None:
    compiled_certification = bool(
        compiled
        and any(
            argument == report_argument
            or argument.startswith(report_argument + "=")
            for argument in arguments
            for report_argument in (
                "--smoke-report-dir",
                "--package-assembly-smoke-report-dir",
                "--performance-report",
                "--migration-report",
                "--recovery-report",
                "--observation-readiness-report",
            )
        )
    )
    if not compiled_certification:
        raise SystemExit(run())

    cyclic_gc_was_suspended = cyclic_gc_enabled()
    if cyclic_gc_was_suspended:
        suspend_cyclic_gc()

    completed_normally = False
    try:
        exit_code = int(run())
        completed_normally = True
    except SystemExit as error:
        if error.code is None:
            exit_code = 0
        elif isinstance(error.code, int):
            exit_code = error.code
        else:
            exit_code = 1
            try:
                print(
                    "Installed certification rejected invalid arguments.",
                    file=sys.stderr,
                )
            except BaseException:
                pass
    except BaseException:
        exit_code = 1
        try:
            print(
                "Installed certification failed at a redacted process boundary.",
                file=sys.stderr,
            )
        except BaseException:
            pass

    if completed_normally and exit_code == 0:
        terminate(0)
        if cyclic_gc_was_suspended:
            resume_cyclic_gc()
        raise RuntimeError(
            "OS-level process termination unexpectedly returned"
        )

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except BaseException:
            exit_code = 1
    terminate(exit_code)
    if cyclic_gc_was_suspended:
        resume_cyclic_gc()
    raise RuntimeError("OS-level process termination unexpectedly returned")


if __name__ == "__main__":
    _run_process_entry(
        compiled="__compiled__" in globals(),
        arguments=tuple(sys.argv[1:]),
    )
