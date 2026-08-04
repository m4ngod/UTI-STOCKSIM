"""Shared naming and version convention for Frontend V2 Feature Interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeatureModuleName(str, Enum):
    """The six Feature Modules approved for the Frontend V2 journey."""

    STRATEGY_LIBRARY = "StrategyLibraryFeature"
    SCENARIO_LAB = "ScenarioLabFeature"
    DIAGNOSTIC_TASKS = "DiagnosticTasksFeature"
    RUN_MONITORING = "RunMonitoringFeature"
    EVIDENCE_AND_FINDINGS = "EvidenceAndFindingsFeature"
    SYSTEM_HEALTH = "SystemHealthFeature"


@dataclass(frozen=True, slots=True)
class FeatureInterfaceVersion:
    """Major/minor version shared by every Feature Interface."""

    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True, slots=True)
class FeatureInterfaceDescriptor:
    """Identifies one callable Feature Interface and its contract version."""

    name: FeatureModuleName
    version: FeatureInterfaceVersion


RUN_MONITORING_INTERFACE_VERSION = FeatureInterfaceVersion(major=1, minor=2)
EVIDENCE_AND_FINDINGS_INTERFACE_VERSION = FeatureInterfaceVersion(
    major=1,
    minor=1,
)
DIAGNOSTIC_TASKS_INTERFACE_VERSION = FeatureInterfaceVersion(major=1, minor=0)
STRATEGY_LIBRARY_INTERFACE_VERSION = FeatureInterfaceVersion(major=1, minor=0)
SCENARIO_LAB_INTERFACE_VERSION = FeatureInterfaceVersion(major=1, minor=0)

ACTIVE_FEATURE_INTERFACES = (
    FeatureInterfaceDescriptor(
        name=FeatureModuleName.STRATEGY_LIBRARY,
        version=STRATEGY_LIBRARY_INTERFACE_VERSION,
    ),
    FeatureInterfaceDescriptor(
        name=FeatureModuleName.SCENARIO_LAB,
        version=SCENARIO_LAB_INTERFACE_VERSION,
    ),
    FeatureInterfaceDescriptor(
        name=FeatureModuleName.DIAGNOSTIC_TASKS,
        version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    ),
    FeatureInterfaceDescriptor(
        name=FeatureModuleName.RUN_MONITORING,
        version=RUN_MONITORING_INTERFACE_VERSION,
    ),
    FeatureInterfaceDescriptor(
        name=FeatureModuleName.EVIDENCE_AND_FINDINGS,
        version=EVIDENCE_AND_FINDINGS_INTERFACE_VERSION,
    ),
)


__all__ = [
    "ACTIVE_FEATURE_INTERFACES",
    "DIAGNOSTIC_TASKS_INTERFACE_VERSION",
    "EVIDENCE_AND_FINDINGS_INTERFACE_VERSION",
    "RUN_MONITORING_INTERFACE_VERSION",
    "SCENARIO_LAB_INTERFACE_VERSION",
    "STRATEGY_LIBRARY_INTERFACE_VERSION",
    "FeatureInterfaceDescriptor",
    "FeatureInterfaceVersion",
    "FeatureModuleName",
]
