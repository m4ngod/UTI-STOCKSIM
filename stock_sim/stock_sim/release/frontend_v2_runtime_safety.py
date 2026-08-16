"""Installed QML object-tree no-manual-trading capability audit."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QMetaMethod, QObject
from PySide6.QtGui import QAccessible


REQUIRED_RUNTIME_SAFETY_ROUTES = (
    "strategy_library",
    "scenario_lab",
    "diagnostic_tasks",
    "run_monitoring",
    "evidence_and_findings",
    "system_health",
)

REQUIRED_RUNTIME_SAFETY_STAGES = (
    "running",
    "reopened_terminal",
)

REQUIRED_RUNTIME_SAFETY_COVERAGE = (
    "qml_object_tree",
    "accessible_interface",
    "action_interface",
    "selection_interface",
    "value_interface",
    "shortcut_properties",
    "qt_signal_surface",
    "command_binding_properties",
    "context_menu_roles",
    "hidden_automation_peers",
)

_FORBIDDEN_MANUAL_TRADING = re.compile(
    r"(?:"
    r"\b(?:buy|sell)\b|"
    r"\bmanual[ _-]*(?:order|trading)\b|"
    r"\b(?:submit|place|cancel|replace|bulk)[ _-]*order\b|"
    r"\border[ _-]*(?:entry|submit|place|cancel|replace|bulk)\b|"
    r"\bbroker[ _-]*(?:connection|connect)?\b|"
    r"\breal[ _-]*money\b"
    r")",
    re.IGNORECASE,
)

_INTERACTIVE_ROLES = frozenset(
    {
        "Button",
        "ButtonDropDown",
        "ButtonDropGrid",
        "ButtonMenu",
        "CheckBox",
        "ComboBox",
        "Dial",
        "EditableText",
        "Link",
        "ListItem",
        "MenuItem",
        "PageTab",
        "RadioButton",
        "Slider",
        "SpinBox",
        "TreeItem",
    }
)

_CONTEXT_MENU_ROLES = frozenset(
    {
        "ButtonMenu",
        "ButtonDropDown",
        "ButtonDropGrid",
        "MenuBar",
        "MenuItem",
        "PopupMenu",
    }
)

_TRIGGER_SIGNAL_NAMES = frozenset(
    {
        "accepted",
        "activated",
        "clicked",
        "doubleClicked",
        "invoked",
        "linkActivated",
        "pressed",
        "released",
        "triggered",
        "toggled",
    }
)

_SHORTCUT_PROPERTIES = (
    "shortcut",
    "keySequence",
    "standardKey",
)

_COMMAND_BINDING_PROPERTIES = (
    "action",
    "command",
    "commandName",
    "targetAction",
)

_CONTEXT_MENU_PROPERTIES = (
    "contextMenu",
    "menu",
)

_CLASSIFICATION_PROPERTIES = tuple(
    dict.fromkeys(
        (
            *_SHORTCUT_PROPERTIES,
            *_COMMAND_BINDING_PROPERTIES,
            *_CONTEXT_MENU_PROPERTIES,
            "accessibleName",
            "accessibleDescription",
            "text",
            "title",
            "toolTip",
        )
    )
)

_UNREADABLE_BOUND_PROPERTY = object()


def classify_manual_trading_surface(
    *,
    accessible_text: str,
    object_name: str,
    role: str,
    action_patterns: Sequence[str],
    trigger_sources: Sequence[str],
    focusable: bool,
) -> str:
    """Classify a surface without treating static diagnostic text as an action."""

    searchable = f"{object_name} {accessible_text}"
    forbidden_terms = _FORBIDDEN_MANUAL_TRADING.search(searchable) is not None
    actionable = bool(
        action_patterns
        or trigger_sources
        or focusable
        or role in _INTERACTIVE_ROLES
    )
    if forbidden_terms and actionable:
        return "forbidden_manual_trading"
    if forbidden_terms:
        return "static_read_only_diagnostic"
    if actionable:
        return "diagnostic_interactive"
    return "diagnostic_read_only"


def _safe_object_name(value: str) -> str:
    stripped = value.strip()
    if (
        stripped
        and len(stripped) <= 160
        and re.fullmatch(r"[A-Za-z0-9_.:-]+", stripped)
    ):
        return stripped
    if not stripped:
        return "unnamed"
    digest = hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:12]
    return f"redacted:{digest}"


def _meta_property(item: QObject, name: str) -> tuple[bool, Any]:
    meta = item.metaObject()
    if meta.indexOfProperty(name) < 0:
        return False, None
    try:
        return True, item.property(name)
    except RuntimeError:
        # Some Qt Quick pointer properties (notably QQuickAction*) do not have
        # a Python converter.  Presence is security-relevant, so retain it as
        # a bound value instead of silently dropping the command surface.
        return True, _UNREADABLE_BOUND_PROPERTY


def _meta_signal_names(
    item: QObject,
    *,
    connected_only: bool = False,
) -> tuple[str, ...]:
    meta = item.metaObject()
    names: set[str] = set()
    for index in range(meta.methodCount()):
        method = meta.method(index)
        if method.methodType() != QMetaMethod.MethodType.Signal:
            continue
        name = bytes(method.name()).decode("ascii", errors="ignore")
        if name in _TRIGGER_SIGNAL_NAMES:
            if connected_only and not item.isSignalConnected(method):
                continue
            names.add(name)
    return tuple(sorted(names))


def _meta_classification_text(item: QObject) -> str:
    values: list[str] = []
    for name in _CLASSIFICATION_PROPERTIES:
        available, value = _meta_property(item, name)
        if not available or value in (None, "", 0, False):
            continue
        if value is _UNREADABLE_BOUND_PROPERTY:
            continue
        if isinstance(value, QObject):
            value = value.objectName()
        elif not isinstance(value, (str, int, float, bytes)):
            converter = getattr(value, "toString", None)
            if not callable(converter):
                continue
            try:
                value = converter()
            except RuntimeError:
                continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        text = str(value).strip()
        if text:
            values.append(text)
    return " ".join(values)


def _accessible_action_patterns(interface: Any) -> tuple[str, ...]:
    patterns: set[str] = set()
    action_interface = interface.actionInterface()
    if action_interface is not None:
        for action_name in action_interface.actionNames():
            folded = str(action_name).casefold()
            if "press" in folded:
                patterns.add("Invoke")
            elif "toggle" in folded:
                patterns.add("Toggle")
            elif "showmenu" in folded or "show menu" in folded:
                patterns.add("ExpandCollapse")
            elif any(
                token in folded
                for token in ("increase", "decrease", "scroll", "page")
            ):
                patterns.add("Value")
            elif "focus" not in folded:
                patterns.add("Action")
    if interface.selectionInterface() is not None:
        patterns.add("Selection")
    if (
        interface.valueInterface() is not None
        or interface.editableTextInterface() is not None
    ):
        patterns.add("Value")
    return tuple(sorted(patterns))


def _trigger_sources(
    item: QObject,
    *,
    role: str,
    action_patterns: Sequence[str],
) -> tuple[str, ...]:
    sources: set[str] = set()
    for name in _SHORTCUT_PROPERTIES:
        available, value = _meta_property(item, name)
        if available and value not in (None, "", 0, False):
            sources.add(f"shortcut:{name}")
    for name in _COMMAND_BINDING_PROPERTIES:
        available, value = _meta_property(item, name)
        if available and value not in (None, "", 0, False):
            sources.add(f"command-binding:{name}")
    if role in _CONTEXT_MENU_ROLES:
        sources.add(f"context-menu:{role}")
    for name in _CONTEXT_MENU_PROPERTIES:
        available, value = _meta_property(item, name)
        if available and value not in (None, "", 0, False):
            sources.add(f"context-menu:{name}")
    sources.update(
        f"signal:{name}"
        for name in _meta_signal_names(item, connected_only=True)
    )
    return tuple(sorted(sources))


def _safe_surface_evidence(
    *,
    item: QObject,
    role: str,
    classification: str,
    action_patterns: Sequence[str],
    trigger_sources: Sequence[str],
    enabled: bool,
    visible: bool,
    focusable: bool,
) -> dict[str, Any]:
    return {
        "object_name": _safe_object_name(item.objectName()),
        "role": role,
        "accessible_name_classification": classification,
        "action_patterns": list(action_patterns),
        "trigger_sources": list(trigger_sources),
        "enabled": enabled,
        "visible": visible,
        "focusable": focusable,
    }


def capture_no_manual_trading_route_audit(
    root: QObject,
    *,
    route: str,
    stage: str,
) -> dict[str, Any]:
    """Audit one active route, including hidden and disabled automation peers."""

    objects = (root, *root.findChildren(QObject))
    accessible_count = 0
    interactive_count = 0
    hidden_count = 0
    disabled_count = 0
    shortcut_count = 0
    context_menu_count = 0
    command_binding_count = 0
    signal_surface_count = 0
    declared_signal_surface_count = 0
    observed_patterns: set[str] = set()
    forbidden: list[dict[str, Any]] = []
    static_diagnostics: list[dict[str, Any]] = []
    for item in objects:
        interface = QAccessible.queryAccessibleInterface(item)
        interface_valid = interface is not None and interface.isValid()
        if interface_valid:
            accessible_count += 1
            role = interface.role().name
            state = interface.state()
        else:
            role = str(item.metaObject().className())
            state = None
        enabled_property, enabled_value = _meta_property(item, "enabled")
        visible_property, visible_value = _meta_property(item, "visible")
        enabled = bool(
            (state is None or not state.disabled)
            and (not enabled_property or enabled_value is not False)
        )
        visible = bool(
            (state is None or not state.invisible)
            and (not visible_property or visible_value is not False)
        )
        focusable_property, focusable_value = _meta_property(
            item,
            "activeFocusOnTab",
        )
        focusable = bool(
            (state is not None and state.focusable)
            or (focusable_property and focusable_value is True)
        )
        if not visible:
            hidden_count += 1
        if not enabled:
            disabled_count += 1
        action_patterns = (
            _accessible_action_patterns(interface) if interface_valid else ()
        )
        trigger_sources = _trigger_sources(
            item,
            role=role,
            action_patterns=action_patterns,
        )
        declared_signal_surface_count += int(bool(_meta_signal_names(item)))
        observed_patterns.update(action_patterns)
        shortcut_count += int(
            any(source.startswith("shortcut:") for source in trigger_sources)
        )
        context_menu_count += int(
            any(
                source.startswith("context-menu:")
                for source in trigger_sources
            )
        )
        command_binding_count += int(
            any(
                source.startswith("command-binding:")
                for source in trigger_sources
            )
        )
        signal_surface_count += int(
            any(source.startswith("signal:") for source in trigger_sources)
        )
        if action_patterns or trigger_sources or focusable or role in _INTERACTIVE_ROLES:
            interactive_count += 1
        accessible_text = _meta_classification_text(item)
        if interface_valid:
            accessible_text = " ".join(
                (
                    interface.text(QAccessible.Text.Name),
                    interface.text(QAccessible.Text.Description),
                    accessible_text,
                )
            ).strip()
        classification = classify_manual_trading_surface(
            accessible_text=accessible_text,
            object_name=item.objectName(),
            role=role,
            action_patterns=action_patterns,
            trigger_sources=trigger_sources,
            focusable=focusable,
        )
        if classification not in {
            "forbidden_manual_trading",
            "static_read_only_diagnostic",
        }:
            continue
        evidence = _safe_surface_evidence(
            item=item,
            role=role,
            classification=classification,
            action_patterns=action_patterns,
            trigger_sources=trigger_sources,
            enabled=enabled,
            visible=visible,
            focusable=focusable,
        )
        if classification == "forbidden_manual_trading":
            forbidden.append(evidence)
        else:
            static_diagnostics.append(evidence)
    return {
        "route": route,
        "stage": stage,
        "coverage": list(REQUIRED_RUNTIME_SAFETY_COVERAGE),
        "object_count": len(objects),
        "accessible_object_count": accessible_count,
        "interactive_object_count": interactive_count,
        "hidden_object_count": hidden_count,
        "disabled_object_count": disabled_count,
        "shortcut_surface_count": shortcut_count,
        "context_menu_surface_count": context_menu_count,
        "command_binding_surface_count": command_binding_count,
        "signal_surface_count": signal_surface_count,
        "declared_signal_surface_count": declared_signal_surface_count,
        "action_patterns_observed": sorted(observed_patterns),
        "forbidden_action_count": len(forbidden),
        "forbidden_actions": forbidden,
        "static_read_only_diagnostics": static_diagnostics,
    }


def validate_no_manual_trading_route_audits(
    audits: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Fail closed unless every route and audit surface is present and safe."""

    failures: list[str] = []
    route_stage_values = tuple(
        (
            str(audit.get("stage", "")),
            str(audit.get("route", "")),
        )
        for audit in audits
    )
    required_route_stages = {
        (stage, route)
        for stage in REQUIRED_RUNTIME_SAFETY_STAGES
        for route in REQUIRED_RUNTIME_SAFETY_ROUTES
    }
    if set(route_stage_values) != required_route_stages:
        failures.append(
            "Installed no-manual-trading audit missed a route or lifecycle stage"
        )
    if len(route_stage_values) != len(set(route_stage_values)):
        failures.append(
            "Installed no-manual-trading route stages were duplicated"
        )
    for audit in audits:
        route = str(audit.get("route", ""))
        if set(audit.get("coverage") or ()) != set(
            REQUIRED_RUNTIME_SAFETY_COVERAGE
        ):
            failures.append(f"Installed {route} safety coverage is incomplete")
        if int(audit.get("object_count", 0)) <= 0:
            failures.append(f"Installed {route} object tree was not scanned")
        if int(audit.get("accessible_object_count", 0)) <= 0:
            failures.append(
                f"Installed {route} accessibility tree was not scanned"
            )
        forbidden = audit.get("forbidden_actions")
        forbidden_count = int(audit.get("forbidden_action_count", -1))
        if (
            not isinstance(forbidden, list)
            or forbidden_count != len(forbidden)
            or forbidden_count != 0
        ):
            failures.append(
                f"Installed {route} exposed a manual-trading capability"
            )
    return tuple(dict.fromkeys(failures))


__all__ = [
    "REQUIRED_RUNTIME_SAFETY_COVERAGE",
    "REQUIRED_RUNTIME_SAFETY_ROUTES",
    "REQUIRED_RUNTIME_SAFETY_STAGES",
    "capture_no_manual_trading_route_audit",
    "classify_manual_trading_surface",
    "validate_no_manual_trading_route_audits",
]
