"""Installed QML accessibility evidence captured from Qt's public API."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuick import QQuickItem


ORDERED_ACCESSIBILITY_CHECKPOINTS = (
    "loading",
    "empty",
    "failed",
    "recovering",
    "partial",
    "disconnected",
    "stale",
    "completed",
)
REQUIRED_ACCESSIBILITY_STATES = ORDERED_ACCESSIBILITY_CHECKPOINTS
ACCESSIBILITY_CHECKPOINT_BINDINGS = {
    "loading": ("runMonitoringRouteNavigation", "loading"),
    "empty": ("diagnosticTasksRouteNavigation", "empty"),
    "failed": ("failedCampaignNodeAttemptHistory", "failed"),
    "recovering": ("diagnosticTaskRecoveryProgressStatus", "recover"),
    "partial": ("systemHealthAccessibleStatus", "partial"),
    "disconnected": ("systemHealthAccessibleStatus", "disconnected"),
    "stale": ("systemHealthAccessibleStatus", "stale"),
    "completed": ("runMonitoringRouteNavigation", "terminal"),
}

_STATE_TERMS = {
    "loading": ("loading", "waiting"),
    "empty": ("empty", "no current", "unavailable"),
    "stale": ("stale", "refresh"),
    "disconnected": ("disconnected", "last reliable"),
    "partial": ("partial", "last reliable"),
    "failed": ("failed", "failure", "error"),
    "recovering": ("recover", "retry", "queued"),
    "completed": ("completed", "complete", "terminal", "sealed"),
}

_SAFE_SEMANTIC_TERMS = tuple(
    sorted(
        {
            term
            for terms in _STATE_TERMS.values()
            for term in terms
        }
        | {"progress", "error", "health", "fresh", "recover", "recovery"}
    )
)

_STATE_FLAGS = (
    "active",
    "busy",
    "checked",
    "disabled",
    "editable",
    "expandable",
    "expanded",
    "focusable",
    "focused",
    "invisible",
    "modal",
    "multiLine",
    "offscreen",
    "pressed",
    "readOnly",
    "selectable",
    "selected",
)

_CONTRAST_PAIRS = (
    ("textPrimary", "background", 4.5),
    ("textPrimary", "surface", 4.5),
    ("textMuted", "surface", 4.5),
    ("textQuiet", "surface", 4.5),
    ("accent", "background", 3.0),
    ("focus", "background", 3.0),
    ("border", "background", 3.0),
)

_CHECKPOINT_MARKER_OBJECT_NAME = "installedAccessibilityCheckpointMarker"


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


def _accessible_nodes(root: QObject) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in (root, *root.findChildren(QObject)):
        if item.objectName() == _CHECKPOINT_MARKER_OBJECT_NAME:
            continue
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is None or not interface.isValid():
            continue
        name = interface.text(QAccessible.Text.Name).strip()
        description = interface.text(QAccessible.Text.Description).strip()
        if not name and not description:
            continue
        state = interface.state()
        if state.invisible or state.offscreen:
            continue
        semantic_text = f"{name} {description}".casefold()
        nodes.append(
            {
                "object_name": _safe_object_name(item.objectName()),
                "role": interface.role().name,
                "name_present": bool(name),
                "description_present": bool(description),
                "semantic_terms": [
                    term
                    for term in _SAFE_SEMANTIC_TERMS
                    if term in semantic_text
                ],
                "visible": True,
                "states": [
                    flag
                    for flag in _STATE_FLAGS
                    if bool(getattr(state, flag, False))
                ],
            }
        )
    return nodes


def _quick_item_is_actually_rendered(
    item: QQuickItem,
    *,
    root: QQuickItem,
) -> bool:
    if (
        not item.isVisible()
        or item.opacity() <= 0.0
        or item.width() <= 0.0
        or item.height() <= 0.0
    ):
        return False
    item_rect = item.boundingRect()
    try:
        if not item.mapRectToItem(root, item_rect).intersects(root.boundingRect()):
            return False
        ancestor = item.parentItem()
        while ancestor is not None:
            if not ancestor.isVisible() or ancestor.opacity() <= 0.0:
                return False
            if ancestor.clip() and not item.mapRectToItem(
                ancestor,
                item_rect,
            ).intersects(ancestor.boundingRect()):
                return False
            ancestor = ancestor.parentItem()
    except RuntimeError:
        return False
    return True


def _rendered_owner_object_names(item: QQuickItem) -> tuple[str, ...] | None:
    owners: list[str] = []
    current: QQuickItem | None = item
    while current is not None:
        object_name = current.objectName()
        if object_name == _CHECKPOINT_MARKER_OBJECT_NAME:
            return None
        if object_name:
            owners.append(_safe_object_name(object_name))
        current = current.parentItem()
    return tuple(owners)


def _rendered_text_nodes(root: QObject) -> list[dict[str, Any]]:
    if not isinstance(root, QQuickItem):
        return []
    rendered: list[dict[str, Any]] = []
    for item in (root, *root.findChildren(QQuickItem)):
        owner_object_names = _rendered_owner_object_names(item)
        if owner_object_names is None:
            continue
        meta = item.metaObject()
        if meta.indexOfProperty("text") < 0:
            continue
        text = str(item.property("text") or "").strip()
        if not text or not _quick_item_is_actually_rendered(item, root=root):
            continue
        folded = text.casefold()
        rendered.append(
            {
                "object_name": _safe_object_name(item.objectName()),
                "item_type": str(meta.className()),
                "visible": True,
                "positive_area": True,
                "owner_object_names": list(owner_object_names),
                "semantic_terms": [
                    term for term in _SAFE_SEMANTIC_TERMS if term in folded
                ],
            }
        )
    return rendered


def _non_color_cue_evidence(
    nodes: Sequence[Mapping[str, Any]],
    *,
    checkpoint: str,
    status_object_name: str,
    status_semantic_term: str,
) -> list[dict[str, str]]:
    expected_terms = _STATE_TERMS.get(checkpoint, ())
    cues: list[dict[str, str]] = []
    for node in nodes:
        if node.get("visible") is not True:
            continue
        if status_object_name not in node.get("owner_object_names", ()):
            continue
        semantic_terms = {
            str(term).casefold()
            for term in node.get("semantic_terms", [])
        }
        matched = (
            status_semantic_term
            if status_semantic_term in expected_terms
            and status_semantic_term in semantic_terms
            else None
        )
        if matched is None:
            continue
        cues.append(
            {
                "cue_kind": "rendered_qquick_text",
                "item_type": str(node.get("item_type", "")),
                "matched_term": matched,
                "status_object_name": status_object_name,
            }
        )
    return cues


def _linear_channel(value: int) -> float:
    normalized = value / 255.0
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def _luminance(color: QColor) -> float:
    red, green, blue, _alpha = color.getRgb()
    return (
        0.2126 * _linear_channel(red)
        + 0.7152 * _linear_channel(green)
        + 0.0722 * _linear_channel(blue)
    )


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    lighter = max(_luminance(foreground), _luminance(background))
    darker = min(_luminance(foreground), _luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _contrast_evidence(tokens: QObject) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for foreground_name, background_name, minimum in _CONTRAST_PAIRS:
        foreground = QColor(tokens.property(foreground_name))
        background = QColor(tokens.property(background_name))
        ratio = _contrast_ratio(foreground, background)
        evidence.append(
            {
                "foreground_token": foreground_name,
                "foreground": foreground.name(),
                "background_token": background_name,
                "background": background.name(),
                "ratio": round(ratio, 4),
                "required_ratio": minimum,
                "passed": ratio >= minimum,
            }
        )
    return evidence


def _chart_revision_evidence(root: QObject) -> dict[str, Any]:
    chart = root.findChild(QObject, "productionEvidenceChart")
    table = root.findChild(QObject, "evidenceChartAccessibleTable")
    narrative = root.findChild(QObject, "evidenceChartAccessibleNarrative")
    if chart is None or table is None or narrative is None:
        return {
            "available": False,
            "same_revision": False,
            "accepted_revision": -1,
        }
    revision = int(chart.property("acceptedRevision"))
    marker = f"Accepted evidence revision · r{revision}"
    chart_interface = QAccessible.queryAccessibleInterface(chart)
    chart_text = "" if chart_interface is None else " ".join(
        (
            chart_interface.text(QAccessible.Text.Name),
            chart_interface.text(QAccessible.Text.Description),
        )
    )
    table_text = str(table.property("text") or "")
    narrative_text = str(narrative.property("text") or "")
    return {
        "available": True,
        "same_revision": bool(
            revision >= 1
            and marker in chart_text
            and marker in table_text
            and marker in narrative_text
        ),
        "accepted_revision": revision,
        "revision_marker": marker,
        "chart": marker in chart_text,
        "table": marker in table_text,
        "narrative": marker in narrative_text,
    }


def capture_installed_accessibility_checkpoint(
    root: QObject,
    *,
    checkpoint: str,
    sequence: int,
    snapshot_identity: str,
    route: str,
    run_revision: str,
    evidence_revision: str,
    status_object_name: str,
    status_semantic_term: str,
) -> dict[str, Any]:
    """Capture the rendered QAccessible graph and effective preferences."""

    tokens = root.findChild(QObject, "designTokens")
    if tokens is None:
        raise RuntimeError("Installed accessibility design tokens are unavailable")
    nodes = _accessible_nodes(root)
    rendered_text_nodes = _rendered_text_nodes(root)
    contrast = _contrast_evidence(tokens)
    non_color_cues = _non_color_cue_evidence(
        rendered_text_nodes,
        checkpoint=checkpoint,
        status_object_name=status_object_name,
        status_semantic_term=status_semantic_term,
    )
    return {
        "checkpoint": checkpoint,
        "sequence": sequence,
        "snapshot_identity": snapshot_identity,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "route": route,
        "run_revision": run_revision,
        "evidence_revision": evidence_revision,
        "status_object_name": status_object_name,
        "status_semantic_term": status_semantic_term,
        "active_route": str(root.property("activeRoute") or ""),
        "run_state": str(root.property("screenState") or ""),
        "evidence_state": str(root.property("evidenceScreenState") or ""),
        "text_scale_percent": int(round(float(tokens.property("textScale")) * 100)),
        "high_contrast": bool(tokens.property("highContrast")),
        "reduced_motion": bool(tokens.property("reducedMotion")),
        "motion_duration_ms": int(tokens.property("durationForMotion")),
        "nodes": nodes,
        "rendered_text_nodes": rendered_text_nodes,
        "non_color_cues": non_color_cues,
        "non_color_cue_verified": bool(non_color_cues),
        "contrast": contrast,
        "wcag_2_2_aa_contrast_verified": bool(contrast)
        and all(item["passed"] for item in contrast),
        "chart_narrative_table_revision": _chart_revision_evidence(root),
    }


def validate_installed_accessibility_checkpoints(
    checkpoints: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return fail-closed reasons for incomplete installed accessibility."""

    failures: list[str] = []
    if not checkpoints:
        return ("No installed QAccessible checkpoints were captured",)
    labels = {str(item.get("checkpoint", "")) for item in checkpoints}
    missing_states = set(REQUIRED_ACCESSIBILITY_STATES) - labels
    if missing_states:
        failures.append(
            "Missing installed accessibility states: "
            + ", ".join(sorted(missing_states))
        )
    ordered_labels = tuple(
        str(item.get("checkpoint", "")) for item in checkpoints
    )
    if ordered_labels != ORDERED_ACCESSIBILITY_CHECKPOINTS:
        failures.append(
            "Installed accessibility checkpoint order did not match the "
            "production lifecycle"
        )
    expected_sequences = tuple(
        range(1, len(ORDERED_ACCESSIBILITY_CHECKPOINTS) + 1)
    )
    observed_sequences = tuple(
        item.get("sequence") for item in checkpoints
    )
    if observed_sequences != expected_sequences:
        failures.append(
            "Installed accessibility checkpoint sequence was not monotonic"
        )
    snapshot_identities = tuple(
        str(item.get("snapshot_identity", "")) for item in checkpoints
    )
    if (
        any(not identity for identity in snapshot_identities)
        or len(set(snapshot_identities)) != len(snapshot_identities)
        or any(
            not item.get("captured_at_utc")
            or not item.get("route")
            or not re.fullmatch(r"r\d+", str(item.get("run_revision", "")))
            or not re.fullmatch(
                r"r\d+",
                str(item.get("evidence_revision", "")),
            )
            for item in checkpoints
        )
    ):
        failures.append(
            "Installed accessibility checkpoint identity/revision was invalid"
        )
    captured_times: list[datetime] = []
    for item in checkpoints:
        try:
            captured_at = datetime.fromisoformat(
                str(item.get("captured_at_utc", ""))
            )
        except (TypeError, ValueError):
            captured_times = []
            break
        if captured_at.tzinfo is None:
            captured_times = []
            break
        captured_times.append(captured_at)
    if len(captured_times) != len(ORDERED_ACCESSIBILITY_CHECKPOINTS) or any(
        later <= earlier
        for earlier, later in zip(captured_times, captured_times[1:])
    ):
        failures.append(
            "Installed accessibility checkpoint timestamps were not monotonic"
        )
    for item in checkpoints:
        label = str(item.get("checkpoint", ""))
        expected_terms = _STATE_TERMS.get(label)
        if expected_terms is None:
            continue
        expected_binding = ACCESSIBILITY_CHECKPOINT_BINDINGS.get(label)
        if expected_binding is None or (
            item.get("status_object_name"),
            item.get("status_semantic_term"),
        ) != expected_binding:
            failures.append(
                f"Installed {label} checkpoint status binding was invalid"
            )
            continue
        visible_terms = {
            str(term).casefold()
            for node in item.get("nodes", [])
            if isinstance(node, Mapping)
            and node.get("visible") is True
            and node.get("object_name") == expected_binding[0]
            for term in node.get("semantic_terms", [])
        }
        if expected_binding[1] not in visible_terms:
            failures.append(
                f"Installed {label} checkpoint target did not expose its state"
            )
    def has_rendered_non_color_cue(item: Mapping[str, Any]) -> bool:
        expected_terms = set(
            _STATE_TERMS.get(str(item.get("checkpoint", "")), ())
        )
        rendered_terms = {
            str(term).casefold()
            for node in item.get("rendered_text_nodes", ())
            if isinstance(node, Mapping) and node.get("visible") is True
            and item.get("status_object_name")
            in node.get("owner_object_names", ())
            for term in node.get("semantic_terms", ())
        }
        return bool(
            item.get("non_color_cue_verified") is True
            and rendered_terms
            and any(
                isinstance(cue, Mapping)
                and cue.get("cue_kind") == "rendered_qquick_text"
                and cue.get("status_object_name")
                == item.get("status_object_name")
                and str(cue.get("matched_term", "")).casefold()
                in expected_terms
                and str(cue.get("matched_term", "")).casefold()
                in rendered_terms
                for cue in item.get("non_color_cues", ())
            )
        )

    if any(not has_rendered_non_color_cue(item) for item in checkpoints):
        failures.append(
            "Installed accessibility states relied on color-only meaning"
        )
    if any(item.get("text_scale_percent") != 200 for item in checkpoints):
        failures.append("Installed accessibility text scale was not 200 percent")
    if any(item.get("high_contrast") is not True for item in checkpoints):
        failures.append("Installed high-contrast preference was not effective")
    if any(item.get("reduced_motion") is not True for item in checkpoints):
        failures.append("Installed reduced-motion preference was not effective")
    if any(item.get("motion_duration_ms") != 0 for item in checkpoints):
        failures.append("Installed motion duration was not reduced to zero")
    if any(
        item.get("wcag_2_2_aa_contrast_verified") is not True
        for item in checkpoints
    ):
        failures.append("Installed WCAG 2.2 AA contrast calculation failed")
    all_nodes = [
        node
        for checkpoint in checkpoints
        for node in checkpoint.get("nodes", [])
        if isinstance(node, Mapping) and node.get("visible") is True
    ]
    if not all_nodes or any(not node.get("role") for node in all_nodes):
        failures.append("Installed accessible roles were not available")
    if any(
        not (node.get("name_present") or node.get("description_present"))
        for node in all_nodes
    ):
        failures.append("Installed accessible names/descriptions were incomplete")
    normalized_terms = {
        str(term).casefold()
        for node in all_nodes
        for term in node.get("semantic_terms", [])
    }
    for term in ("progress", "error", "health", "fresh", "recover"):
        if term not in normalized_terms:
            failures.append(f"Installed accessible semantics omitted {term}")
    completed = next(
        (
            item
            for item in checkpoints
            if item.get("checkpoint") == "completed"
        ),
        None,
    )
    if not isinstance(completed, Mapping) or (
        completed.get("chart_narrative_table_revision", {}).get(
            "same_revision"
        )
        is not True
    ):
        failures.append(
            "Installed chart, narrative, and table did not share a revision"
        )
    return tuple(failures)


def summarize_installed_accessibility_checkpoints(
    checkpoints: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return a redacted checkpoint summary without raw UIA/QML text."""

    summaries: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        nodes = tuple(
            node
            for node in checkpoint.get("nodes", [])
            if isinstance(node, Mapping) and node.get("visible") is True
        )
        summaries.append(
            {
                "checkpoint": str(checkpoint.get("checkpoint", "")),
                "status_object_name": str(
                    checkpoint.get("status_object_name", "")
                ),
                "status_semantic_term": str(
                    checkpoint.get("status_semantic_term", "")
                ),
                "visible_node_count": len(nodes),
                "visible_roles": sorted(
                    {
                        str(node.get("role", ""))
                        for node in nodes
                        if node.get("role")
                    }
                ),
                "visible_object_names": sorted(
                    {
                        str(node.get("object_name", ""))
                        for node in nodes
                        if node.get("object_name")
                    }
                ),
                "visible_semantic_terms": sorted(
                    {
                        str(term)
                        for node in nodes
                        for term in node.get("semantic_terms", [])
                    }
                ),
                "non_color_cue_terms": sorted(
                    {
                        str(cue.get("matched_term", ""))
                        for cue in checkpoint.get("non_color_cues", [])
                        if isinstance(cue, Mapping) and cue.get("matched_term")
                    }
                ),
            }
        )
    return tuple(summaries)


__all__ = [
    "ACCESSIBILITY_CHECKPOINT_BINDINGS",
    "REQUIRED_ACCESSIBILITY_STATES",
    "ORDERED_ACCESSIBILITY_CHECKPOINTS",
    "capture_installed_accessibility_checkpoint",
    "summarize_installed_accessibility_checkpoints",
    "validate_installed_accessibility_checkpoints",
]
