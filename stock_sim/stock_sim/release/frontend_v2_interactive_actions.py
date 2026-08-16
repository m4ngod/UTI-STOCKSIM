"""Approved interactive names for the installed Frontend V2 safety audit."""

from __future__ import annotations

import re

from app.features.diagnostic_tasks import DiagnosticTasksPresentationState
from app.features.run_monitoring import RunMonitoringPresentationState


def _enum_alternation(values: tuple[str, ...]) -> str:
    return "|".join(re.escape(value) for value in values)


DIAGNOSTIC_TASKS_ROUTE_PRESENTATIONS = tuple(
    presentation.value for presentation in DiagnosticTasksPresentationState
) + ("unavailable",)
RUN_MONITORING_ROUTE_PRESENTATIONS = tuple(
    presentation.value for presentation in RunMonitoringPresentationState
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
    r"Approve exact Recipe validation .+|"
    r"Materialize exact Approved Recipe .+|"
    r"Compose visible Campaign Cases into a Scenario Set|"
    r"Resolve requested and effective execution assumptions|"
    r"Select immutable Formal Scenario Set context|"
    r"Open Diagnostic Tasks, inventory (?:"
    + _enum_alternation(DIAGNOSTIC_TASKS_ROUTE_PRESENTATIONS)
    + r")|"
    r"Open Run Monitoring, current state (?:"
    + _enum_alternation(RUN_MONITORING_ROUTE_PRESENTATIONS)
    + r")|"
    r"Open Evidence and Findings|"
    r"Open System Health|"
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
    r"Search authoritative Strategy inventory|"
    r"Filter Strategy availability|"
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


__all__ = [
    "APPROVED_INTERACTIVE_NAMES",
    "DIAGNOSTIC_TASKS_ROUTE_PRESENTATIONS",
    "RUN_MONITORING_ROUTE_PRESENTATIONS",
]
