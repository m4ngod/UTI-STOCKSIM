"""Read-only exact identity resolver for the System Health diagnostic context."""

from __future__ import annotations

from typing import TypeVar

from .diagnostic_tasks_application import (
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationEvidenceHandoffState,
    DiagnosticTasksApplicationTask,
    DiagnosticTasksApplicationTaskResult,
    DiagnosticTasksApplicationTaskLifecycle,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
)
from .strategy_diagnostics_v1_read_model import (
    ApplicationReadAvailability,
    ApplicationReadErrorCode,
    ApplicationReadResult,
    StrategyDiagnosticsV1ApplicationReadModel,
    V1JourneySelector,
)


_ApplicationReadT = TypeVar("_ApplicationReadT")
from .system_health import (
    SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION,
    SystemHealthContext,
    SystemHealthContextResolution,
    SystemHealthDiagnosticContext,
    SystemHealthDiagnosticContextState,
)


class LiveSystemHealthDiagnosticContextReader:
    """Resolve one requested graph through existing public Application seams."""

    def __init__(
        self,
        *,
        diagnostic_tasks_application: StrategyDiagnosticsV1DiagnosticTasksApplication,
        application_read_model: StrategyDiagnosticsV1ApplicationReadModel,
    ) -> None:
        self._diagnostic_tasks = diagnostic_tasks_application
        self._read_model = application_read_model

    def __call__(
        self,
        context: SystemHealthContext,
    ) -> SystemHealthDiagnosticContextState:
        requested = context.diagnostic
        if context.version != SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION:
            return _state(
                resolution=SystemHealthContextResolution.INCOMPATIBLE,
                requested=requested,
                explanation="The System Health context version is incompatible.",
            )
        if requested is None:
            return _state(
                resolution=SystemHealthContextResolution.NO_CURRENT_TASK,
                requested=None,
                explanation="No current Diagnostic Task is selected.",
            )
        if requested.version != SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION:
            return _state(
                resolution=SystemHealthContextResolution.INCOMPATIBLE,
                requested=requested,
                explanation="The diagnostic context version is incompatible.",
            )
        try:
            result = self._diagnostic_tasks.read_diagnostic_task(requested.task_id)
        except (OSError, RuntimeError, TypeError, ValueError):
            return _unavailable(requested)
        if result.availability is DiagnosticTasksApplicationAvailability.EMPTY:
            return _state(
                resolution=SystemHealthContextResolution.MISSING,
                requested=requested,
                source_revision=_source_revision(result),
                explanation="The requested Diagnostic Task identity is missing.",
            )
        if (
            result.availability is not DiagnosticTasksApplicationAvailability.READY
            or result.task is None
        ):
            return _unavailable(requested, source_revision=_source_revision(result))

        task = result.task
        identity_resolution = _resolve_task_graph(requested, task)
        if identity_resolution is not None:
            resolution, explanation = identity_resolution
            return _state(
                resolution=resolution,
                requested=requested,
                task=task,
                source_revision=_source_revision(result),
                explanation=explanation,
            )
        lifecycle_resolution = _resolve_lifecycle(task)
        if (
            lifecycle_resolution is not None
            and lifecycle_resolution[0] is SystemHealthContextResolution.FAILED
        ):
            resolution, explanation = lifecycle_resolution
            return _state(
                resolution=resolution,
                requested=requested,
                task=task,
                source_revision=_source_revision(result),
                explanation=explanation,
            )
        artifact_resolution = _resolve_artifact_graph(requested, task)
        if artifact_resolution is not None:
            resolution, explanation = artifact_resolution
            return _state(
                resolution=resolution,
                requested=requested,
                task=task,
                source_revision=_source_revision(result),
                explanation=explanation,
            )
        evidence_resolution = self._resolve_evidence_identity(requested)
        if evidence_resolution is not None:
            resolution, explanation = evidence_resolution
            if (
                lifecycle_resolution is not None
                and lifecycle_resolution[0]
                is SystemHealthContextResolution.COMPLETED
                and resolution is SystemHealthContextResolution.UNAVAILABLE
            ):
                resolution, explanation = lifecycle_resolution
            return _state(
                resolution=resolution,
                requested=requested,
                task=task,
                source_revision=_source_revision(result),
                explanation=explanation,
            )
        if lifecycle_resolution is not None:
            resolution, explanation = lifecycle_resolution
            return _state(
                resolution=resolution,
                requested=requested,
                task=task,
                source_revision=_source_revision(result),
                explanation=explanation,
            )
        return _state(
            resolution=SystemHealthContextResolution.EXACT_MATCH,
            requested=requested,
            task=task,
            source_revision=_source_revision(result),
            explanation="The exact typed diagnostic identity graph is current.",
        )

    def _resolve_evidence_identity(
        self,
        requested: SystemHealthDiagnosticContext,
    ) -> tuple[SystemHealthContextResolution, str] | None:
        if requested.finding_id is None and requested.sensitivity_breakpoint_id is None:
            return None
        if (
            requested.campaign_id is None
            or requested.run_id is None
            or requested.evidence_package_id is None
        ):
            return (
                SystemHealthContextResolution.MISSING,
                "The requested evidence identity graph is incomplete.",
            )
        selector = V1JourneySelector(
            campaign_id=requested.campaign_id,
            run_id=requested.run_id,
            evidence_package_id=requested.evidence_package_id,
            manifest_id=requested.reproduction_manifest_id,
        )
        try:
            resolved = self._read_model.resolve_journey(selector)
        except (OSError, RuntimeError, TypeError, ValueError):
            return (
                SystemHealthContextResolution.UNAVAILABLE,
                "The exact diagnostic evidence graph could not be read safely.",
            )
        if resolved.availability is not ApplicationReadAvailability.READY:
            return _application_read_resolution(resolved)
        if resolved.value is None:
            return (
                SystemHealthContextResolution.UNAVAILABLE,
                "The exact diagnostic evidence graph could not be read safely.",
            )
        try:
            evidence_result = self._read_model.read_evidence(resolved.value)
        except (OSError, RuntimeError, TypeError, ValueError):
            return (
                SystemHealthContextResolution.UNAVAILABLE,
                "The exact Diagnostic Evidence could not be read safely.",
            )
        if evidence_result.availability is not ApplicationReadAvailability.READY:
            return _application_read_resolution(evidence_result)
        evidence = evidence_result.value
        if evidence is None or evidence.evidence_package_id != requested.evidence_package_id:
            return (
                SystemHealthContextResolution.MISSING,
                "The requested Diagnostic Evidence identity is missing.",
            )
        finding = next(
            (
                finding
                for candidate in evidence.candidates
                for finding in candidate.findings
                if finding.identity == requested.finding_id
            ),
            None,
        )
        if requested.finding_id is not None and finding is None:
            return (
                SystemHealthContextResolution.MISSING,
                "The requested Diagnostic Finding identity is missing.",
            )
        if requested.sensitivity_breakpoint_id is not None:
            breakpoint_found = finding is not None and any(
                item.identity == requested.sensitivity_breakpoint_id
                for item in finding.sensitivity_breakpoints
            )
            if not breakpoint_found:
                return (
                    SystemHealthContextResolution.MISSING,
                    "The requested Sensitivity Breakpoint identity is missing.",
                )
        return None


def _resolve_task_graph(
    requested: SystemHealthDiagnosticContext,
    task: DiagnosticTasksApplicationTask,
) -> tuple[SystemHealthContextResolution, str] | None:
    if task.task_id != requested.task_id:
        return (
            SystemHealthContextResolution.MISSING,
            "The requested Diagnostic Task identity is missing.",
        )
    if task.revision != requested.task_revision:
        return (
            (
                SystemHealthContextResolution.SUPERSEDED
                if task.revision > requested.task_revision
                else SystemHealthContextResolution.MISSING
            ),
            "The requested Diagnostic Task revision is not current.",
        )
    if task.configuration.content_identity != requested.configuration_content_id:
        return (
            SystemHealthContextResolution.SUPERSEDED,
            "The requested Diagnostic Task configuration is superseded.",
        )
    actual_recipe_versions = tuple(
        item.recipe_version_id for item in task.configuration.campaign_case_selections
    )
    if (
        requested.approved_recipe_version_ids
        and requested.approved_recipe_version_ids != actual_recipe_versions
    ):
        return (
            SystemHealthContextResolution.SUPERSEDED,
            "The requested Approved Scenario Recipe versions are superseded.",
        )
    if requested.task_handle_id is not None and all(
        item.identity != requested.task_handle_id for item in task.task_handles
    ):
        return (
            SystemHealthContextResolution.MISSING,
            "The requested TaskHandle identity is missing.",
        )

    handoff = task.campaign_handoff
    if requested.campaign_id is None:
        return None
    if handoff is None:
        return (
            SystemHealthContextResolution.MISSING,
            "The requested Formal Diagnostic Campaign identity is missing.",
        )
    if handoff.campaign_id != requested.campaign_id:
        return (
            SystemHealthContextResolution.SUPERSEDED,
            "The requested Formal Diagnostic Campaign identity is superseded.",
        )
    if handoff.campaign_revision != requested.campaign_revision:
        return (
            (
                SystemHealthContextResolution.SUPERSEDED
                if handoff.campaign_revision > (requested.campaign_revision or 0)
                else SystemHealthContextResolution.MISSING
            ),
            "The requested Formal Diagnostic Campaign revision is not current.",
        )
    runs = tuple(
        run
        for node in handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    selected_run = next((run for run in runs if run.run_id == requested.run_id), None)
    if requested.run_id is not None and selected_run is None:
        return (
            SystemHealthContextResolution.MISSING,
            "The requested Strategy Run identity is missing.",
        )
    return None


def _resolve_artifact_graph(
    requested: SystemHealthDiagnosticContext,
    task: DiagnosticTasksApplicationTask,
) -> tuple[SystemHealthContextResolution, str] | None:
    handoff = task.campaign_handoff
    if handoff is None:
        return None
    selected_run = next(
        (
            run
            for node in handoff.campaign_nodes
            for attempt in node.attempts
            for run in attempt.runs
            if run.run_id == requested.run_id
        ),
        None,
    )
    if requested.evidence_package_id is not None:
        if handoff.evidence_package_id is None:
            return (
                SystemHealthContextResolution.MISSING,
                "The requested Diagnostic Evidence identity is missing.",
            )
        if handoff.evidence_package_id != requested.evidence_package_id:
            return (
                SystemHealthContextResolution.SUPERSEDED,
                "The requested Diagnostic Evidence identity is superseded.",
            )
    if requested.reproduction_manifest_id is not None:
        current_manifest = (
            None if selected_run is None else selected_run.reproduction_manifest_id
        ) or handoff.reproduction_manifest_id
        if current_manifest is None:
            return (
                SystemHealthContextResolution.MISSING,
                "The requested Reproduction Manifest identity is missing.",
            )
        if current_manifest != requested.reproduction_manifest_id:
            return (
                SystemHealthContextResolution.SUPERSEDED,
                "The requested Reproduction Manifest identity is superseded.",
            )
    return None


def _resolve_lifecycle(
    task: DiagnosticTasksApplicationTask,
) -> tuple[SystemHealthContextResolution, str] | None:
    handoff = task.campaign_handoff
    failed = task.lifecycle is DiagnosticTasksApplicationTaskLifecycle.FAILED
    if handoff is not None:
        failed = failed or handoff.campaign_lifecycle is (
            DiagnosticTasksApplicationTaskLifecycle.FAILED
        )
        failed = failed or handoff.evidence_state is (
            DiagnosticTasksApplicationEvidenceHandoffState.FAILED
        )
        failed = failed or any(
            node.lifecycle is DiagnosticTasksApplicationTaskLifecycle.FAILED
            or any(
                attempt.lifecycle is DiagnosticTasksApplicationTaskLifecycle.FAILED
                or attempt.failure is not None
                for attempt in node.attempts
                if node.active_attempt_id is None
                or attempt.attempt_id == node.active_attempt_id
            )
            for node in handoff.campaign_nodes
        )
    if failed:
        return (
            SystemHealthContextResolution.FAILED,
            "The selected diagnostic has failed.",
        )
    if task.lifecycle is DiagnosticTasksApplicationTaskLifecycle.COMPLETED:
        return (
            SystemHealthContextResolution.COMPLETED,
            "The selected Diagnostic Task is complete.",
        )
    return None


def _application_read_resolution(
    result: ApplicationReadResult[_ApplicationReadT],
) -> tuple[SystemHealthContextResolution, str]:
    error_code = None if result.error is None else result.error.code
    if error_code is ApplicationReadErrorCode.CONTRACT_INCOMPATIBLE:
        return (
            SystemHealthContextResolution.INCOMPATIBLE,
            "The requested diagnostic evidence contract is incompatible.",
        )
    if result.availability is ApplicationReadAvailability.NOT_FOUND:
        return (
            SystemHealthContextResolution.MISSING,
            "The requested diagnostic evidence identity is missing.",
        )
    if result.availability in {
        ApplicationReadAvailability.PENDING,
        ApplicationReadAvailability.PARTIAL,
    }:
        return (
            SystemHealthContextResolution.UNAVAILABLE,
            "The exact diagnostic evidence graph is not yet complete.",
        )
    return (
        SystemHealthContextResolution.UNAVAILABLE,
        "The exact diagnostic evidence graph could not be read safely.",
    )


def _source_revision(result: DiagnosticTasksApplicationTaskResult) -> str | None:
    return None if result.source_token is None else result.source_token.value


def _unavailable(
    requested: SystemHealthDiagnosticContext,
    *,
    source_revision: str | None = None,
) -> SystemHealthDiagnosticContextState:
    return _state(
        resolution=SystemHealthContextResolution.UNAVAILABLE,
        requested=requested,
        source_revision=source_revision,
        explanation="The exact typed diagnostic context could not be read safely.",
    )


def _state(
    *,
    resolution: SystemHealthContextResolution,
    requested: SystemHealthDiagnosticContext | None,
    task: DiagnosticTasksApplicationTask | None = None,
    source_revision: str | None = None,
    explanation: str,
) -> SystemHealthDiagnosticContextState:
    handoff = None if task is None else task.campaign_handoff
    return SystemHealthDiagnosticContextState(
        resolution=resolution,
        requested=requested,
        observed_task_revision=None if task is None else task.revision,
        observed_campaign_revision=(
            None if handoff is None else handoff.campaign_revision
        ),
        terminal=resolution
        in {
            SystemHealthContextResolution.FAILED,
            SystemHealthContextResolution.COMPLETED,
        },
        source_revision=source_revision,
        explanation=explanation,
    )


__all__ = ["LiveSystemHealthDiagnosticContextReader"]
