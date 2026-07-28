"""Installed-package black-box entry point for the Frontend V2 release gate."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from time import monotonic, sleep
from typing import Any


PRODUCTION_PATH = (
    "DiagnosticsApplication",
    "FileBackedV1Persistence",
    "LiveStrategyDiagnosticsV1ApplicationAdapter",
    "EventBridge",
    "LiveRunMonitoringAdapter",
    "LiveEvidenceAndFindingsAdapter",
    "JourneyWorkspaceHost",
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
    r"Open Run Monitoring|"
    r"Open Evidence and Findings|"
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
) -> tuple[Any, Any, Any]:
    from app.app_context import build_app_context
    from app.ui.main_window import MainWindow

    context = build_app_context(
        settings_path=str(settings_path),
        run_monitoring_mode="live",
        event_bridge=event_bridge,
        runtime_gateway=runtime_gateway,
        strategy_diagnostics_read_model=strategy_diagnostics_read_model,
    )
    window = None
    try:
        window = MainWindow(
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


def _visible_and_accessible_text(root: Any) -> str:
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QAccessible

    rendered: list[str] = []
    for item in (root, *root.findChildren(QObject)):
        meta = item.metaObject()
        visible = (
            bool(item.property("visible"))
            if meta.indexOfProperty("visible") >= 0
            else True
        )
        if (
            visible
            and meta.indexOfProperty("text") >= 0
            and item.property("text")
        ):
            rendered.append(str(item.property("text")))
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is None or not interface.isValid():
            continue
        for kind in (
            QAccessible.Text.Name,
            QAccessible.Text.Description,
        ):
            value = interface.text(kind)
            if value:
                rendered.append(value)
    return "\n".join(rendered)


def _focus_accessible_name_with_keyboard(
    *,
    app: Any,
    host: Any,
    accessible_name: str,
) -> Any:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible

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
        interface = QAccessible.queryAccessibleInterface(item)
        if (
            interface is not None
            and interface.isValid()
            and interface.text(QAccessible.Text.Name).casefold()
            == accessible_name.casefold()
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
    from PySide6.QtGui import QAccessible

    quick_window = host.quickWindow()
    if quick_window is None:
        raise RuntimeError("Journey Workspace Quick Window is unavailable")
    rendered: list[str] = []
    for _ in range(steps):
        item = quick_window.activeFocusItem()
        if item is not None:
            interface = QAccessible.queryAccessibleInterface(item)
            if interface is not None and interface.isValid():
                rendered.extend(
                    (
                        interface.text(QAccessible.Text.Name),
                        interface.text(QAccessible.Text.Description),
                    )
                )
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
    from PySide6.QtGui import QAccessible
    _navigate_route(
        app=app,
        host=host,
        root=root,
        route="evidence_and_findings",
    )
    rendered = [_visible_and_accessible_text(root)]
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
        candidate_interface = QAccessible.queryAccessibleInterface(candidate)
        if candidate_interface is None or not candidate_interface.isValid():
            raise RuntimeError(
                "Evidence candidate lacks a valid accessible interface"
            )
        candidate = _focus_accessible_name_with_keyboard(
            app=app,
            host=host,
            accessible_name=candidate_interface.text(
                QAccessible.Text.Name
            ),
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
            tab = _focus_accessible_name_with_keyboard(
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
) -> tuple[str, ...]:
    run_state = context.run_monitoring_feature.snapshot(
        context.run_monitoring_context
    )
    evidence_state = context.evidence_and_findings_feature.snapshot(
        context.evidence_and_findings_context
    )
    feature_text = "\n".join(
        _typed_string_values((run_state, evidence_state))
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
    from PySide6.QtGui import QAccessible

    item = root.findChild(QObject, object_name)
    if item is None:
        raise RuntimeError(
            f"Accessible status object is unavailable: {object_name}"
        )
    interface = QAccessible.queryAccessibleInterface(item)
    if interface is None or not interface.isValid():
        raise RuntimeError(
            f"Accessible status interface is unavailable: {object_name}"
        )
    return " ".join(
        (
            interface.text(QAccessible.Text.Name),
            interface.text(QAccessible.Text.Description),
        )
    ).strip()


def run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str = "development-smoke",
    capture_images: bool = True,
) -> PackageSmokeResult:
    cleanup_errors: list[str] = []
    lifecycle_checks: list[Callable[[], bool]] = []
    with ExitStack() as cleanup:
        result = _run_smoke_journey(
            report_dir=report_dir,
            renderer_lane=renderer_lane,
            source_commit=source_commit,
            capture_images=capture_images,
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


def _run_smoke_journey(
    *,
    report_dir: Path,
    renderer_lane: RendererLane,
    source_commit: str,
    capture_images: bool,
    cleanup: ExitStack,
    cleanup_errors: list[str],
    lifecycle_checks: list[Callable[[], bool]],
) -> PackageSmokeResult:
    from PySide6.QtWidgets import QApplication

    from app.event_bridge import EventBridge
    from app.features import (
        ACTIVE_FEATURE_INTERFACES,
        LiveStrategyDiagnosticsV1ApplicationAdapter,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        create_file_backed_formal_v1_release_fixture,
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    persistence_root = report_dir / "v1-persistence"
    fixture = create_file_backed_formal_v1_release_fixture(
        database_path=persistence_root / "strategy-diagnostics-v1.sqlite3",
        artifact_root=persistence_root / "artifacts",
    )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "Strategy Diagnostics V1 fixture",
        fixture.close,
    )
    lifecycle_checks.append(lambda fixture=fixture: fixture.closed)
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
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        fixture.application,
        fixture.engine,
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
    expected_identity_graph = fixture.expected_identity_graph

    app = QApplication.instance() or QApplication([])
    bridge = EventBridge(subscribe_backend=False)
    previous_environment = _configure_smoke_route_identity(
        campaign_id=campaign_id,
        run_id=run_id,
        strategy_id=strategy_id,
        case_id=case_id,
        recipe_id=recipe_id,
        evidence_package_id=evidence_package_id,
        manifest_id=manifest_id,
    )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "release environment",
        lambda: _restore_environment(previous_environment),
    )
    lifecycle_checks.append(
        lambda previous=previous_environment: all(
            (
                os.environ.get(name) == value
                if value is not None
                else name not in os.environ
            )
            for name, value in previous.items()
        )
    )
    cleanup.callback(
        _record_cleanup,
        cleanup_errors,
        "EventBridge",
        bridge.stop,
    )
    bridge.start()
    lifecycle_checks.append(
        lambda bridge=bridge: bool(
            not bridge._running
            and (
                bridge._th is None
                or not bridge._th.is_alive()
            )
        )
    )
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
                context=context,
                window=window,
                host=host,
                errors=cleanup_errors,
            )
            state["closed"] = True
            app.processEvents()

        cleanup.callback(close_mount)
        lifecycle_checks.append(
            lambda state=state, context=context, window=window, host=host: bool(
                state["closed"]
                and _mount_is_closed(context, window, host)
            )
        )
        return close_mount

    context, window, host = _create_production_window(
        event_bridge=bridge,
        strategy_diagnostics_read_model=read_model,
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
                f"{stage}: QML/QAccessible identity graph is missing "
                f"{missing}"
            )

    observe(*EXPECTED_JOURNEY[0])
    observe(*EXPECTED_JOURNEY[1])
    feature_identity_graph = _feature_identity_graph(
        context=context,
        expected=expected_identity_graph,
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

    context, window, host = _create_production_window(
        event_bridge=bridge,
        strategy_diagnostics_read_model=read_model,
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
        keyboard_navigation_verified=keyboard_routes == {
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
        routes_rendered=("run_monitoring", "evidence_and_findings"),
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
    )
    return result


def _close_mount(
    *,
    context: Any,
    window: Any,
    host: Any,
    errors: list[str] | None = None,
) -> None:
    observed_errors = errors if errors is not None else []
    for label, action in (
        ("QML Adapter", host.close_adapter),
        ("MainWindow", window.close),
        ("Run Monitoring Feature", context.run_monitoring_feature.close),
        (
            "Evidence and Findings Feature",
            context.evidence_and_findings_feature.close,
        ),
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


def _mount_is_closed(
    context: Any,
    window: Any,
    host: Any,
) -> bool:
    return bool(
        getattr(host, "_workspace_closed", False)
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
    from PySide6.QtGui import QAccessible

    count = 0
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
    app.aboutToQuit.connect(context.run_monitoring_feature.close)
    app.aboutToQuit.connect(context.evidence_and_findings_feature.close)
    app.aboutToQuit.connect(stop_frontend_bridge)
    window.show()
    return int(app.exec())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--renderer-lane",
        choices=tuple(lane.value for lane in RendererLane),
        default=RendererLane.HARDWARE.value,
    )
    parser.add_argument("--smoke-report-dir", type=Path)
    parser.add_argument("--source-commit", default="unbound")
    parser.add_argument("--no-images", action="store_true")
    arguments = parser.parse_args(argv)
    renderer_lane = RendererLane(arguments.renderer_lane)
    configure_renderer_environment(renderer_lane)
    if arguments.smoke_report_dir is not None:
        result = run_smoke_journey(
            report_dir=arguments.smoke_report_dir,
            renderer_lane=renderer_lane,
            source_commit=arguments.source_commit,
            capture_images=not arguments.no_images,
        )
        return (
            0
            if (
                not result.errors
                and result.clean_exit
                and result.manual_trading_action_count == 0
                and result.read_only_context_visible
            )
            else 1
        )
    return _run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
