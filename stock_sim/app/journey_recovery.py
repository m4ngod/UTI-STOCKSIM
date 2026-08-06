"""Typed presentation bookmark for reopening the six-Feature Journey Workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from app.features.run_monitoring import DiagnosticTaskId
from app.features.scenario_lab import ScenarioLabFocusTarget


_SCHEMA_VERSION = "1.0"
_BOOKMARK_KEYS = frozenset(
    {
        "schema_version",
        "last_route",
        "diagnostic_task_id",
        "scenario_focus_target",
        "scenario_focus_identity",
    }
)


class JourneyWorkspaceRoute(str, Enum):
    STRATEGY_LIBRARY = "strategy_library"
    SCENARIO_LAB = "scenario_lab"
    DIAGNOSTIC_TASKS = "diagnostic_tasks"
    RUN_MONITORING = "run_monitoring"
    EVIDENCE_AND_FINDINGS = "evidence_and_findings"
    SYSTEM_HEALTH = "system_health"


@dataclass(frozen=True, slots=True)
class JourneyWorkspaceBookmark:
    """Identity-only recovery hints; durable domain state remains authoritative."""

    last_route: JourneyWorkspaceRoute = JourneyWorkspaceRoute.STRATEGY_LIBRARY
    diagnostic_task_id: DiagnosticTaskId | None = None
    scenario_focus_target: ScenarioLabFocusTarget = ScenarioLabFocusTarget.SEARCH
    scenario_focus_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.last_route, JourneyWorkspaceRoute):
            raise TypeError("last_route must be a JourneyWorkspaceRoute")
        if self.diagnostic_task_id is not None and not isinstance(
            self.diagnostic_task_id,
            DiagnosticTaskId,
        ):
            raise TypeError("diagnostic_task_id must be a DiagnosticTaskId")
        if not isinstance(self.scenario_focus_target, ScenarioLabFocusTarget):
            raise TypeError(
                "scenario_focus_target must be a ScenarioLabFocusTarget"
            )
        identity = self.scenario_focus_identity
        if identity is not None and (
            not isinstance(identity, str)
            or not identity.strip()
            or identity != identity.strip()
        ):
            raise ValueError("scenario focus identity must be exact and non-empty")
        if self.scenario_focus_target is ScenarioLabFocusTarget.SEARCH:
            if identity is not None:
                raise ValueError("search focus cannot carry an identity")
        elif identity is None:
            raise ValueError("detail focus requires an identity")


def encode_journey_workspace_bookmark(
    bookmark: JourneyWorkspaceBookmark,
) -> str:
    if not isinstance(bookmark, JourneyWorkspaceBookmark):
        raise TypeError("bookmark must be a JourneyWorkspaceBookmark")
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "last_route": bookmark.last_route.value,
            "diagnostic_task_id": (
                None
                if bookmark.diagnostic_task_id is None
                else bookmark.diagnostic_task_id.value
            ),
            "scenario_focus_target": bookmark.scenario_focus_target.value,
            "scenario_focus_identity": bookmark.scenario_focus_identity,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_journey_workspace_bookmark(
    payload: str,
) -> JourneyWorkspaceBookmark | None:
    if not isinstance(payload, str) or not payload or len(payload) > 8_192:
        return None
    try:
        raw = json.loads(payload)
        if not isinstance(raw, dict) or frozenset(raw) != _BOOKMARK_KEYS:
            return None
        if raw["schema_version"] != _SCHEMA_VERSION:
            return None
        last_route = raw["last_route"]
        task_identity = raw["diagnostic_task_id"]
        focus_target = raw["scenario_focus_target"]
        focus_identity = raw["scenario_focus_identity"]
        if not isinstance(last_route, str) or not isinstance(focus_target, str):
            return None
        if task_identity is not None and not isinstance(task_identity, str):
            return None
        if focus_identity is not None and not isinstance(focus_identity, str):
            return None
        return JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute(last_route),
            diagnostic_task_id=(
                None
                if task_identity is None
                else DiagnosticTaskId(task_identity)
            ),
            scenario_focus_target=ScenarioLabFocusTarget(focus_target),
            scenario_focus_identity=focus_identity,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


__all__ = [
    "JourneyWorkspaceBookmark",
    "JourneyWorkspaceRoute",
    "decode_journey_workspace_bookmark",
    "encode_journey_workspace_bookmark",
]
