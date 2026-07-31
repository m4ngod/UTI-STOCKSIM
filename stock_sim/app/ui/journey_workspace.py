"""Internal Qt Adapter and host for the centralized QML Journey Workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from math import ceil
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from uuid import uuid4

from PySide6.QtCore import (
    Property,
    QObject,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from app.features import (
    ApproveDiagnosticTaskConfiguration,
    CampaignNodeTarget,
    CancelDiagnosticTarget,
    CancelDiagnosticTask,
    CandidateEvidence,
    CreateDiagnosticTask,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCampaignNodeHandoff,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandResult,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    DiagnosticTasksViewState,
    DiagnosticTaskTarget,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsSubscription,
    EvidenceAndFindingsViewState,
    EvidenceCoverage,
    EvidenceDimension,
    FormalDiagnosticCampaignTarget,
    PauseDiagnosticTarget,
    PauseDiagnosticTask,
    ResumeDiagnosticTarget,
    ResumeDiagnosticTask,
    ReviseDiagnosticTaskConfiguration,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringSelection,
    RunMonitoringViewState,
    StartFormalDiagnosticCampaign,
    Subscription,
    ValidateDiagnosticTaskConfiguration,
)

from .accessibility import (
    AccessibilityPreferences,
    AccessibilitySettingsQtAdapter,
    detect_accessibility_preferences,
)
from .evidence_chart import (
    EvidenceChartFrameGate,
    EvidenceChartFrameGateResult,
    EvidenceChartPresentation,
    EvidenceChartRenderFrame,
    EvidenceChartSamplingPolicy,
    EvidenceChartViewport,
    advance_evidence_chart_presentation_revision,
    build_evidence_chart_presentation,
)

_QML_ROOT = Path(__file__).resolve().parent / "qml"
_MOUNT_GENERATIONS = count(1)
_MOUNT_GENERATION_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class ViewMountGenerationId:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("View mount generation must be positive")


def _next_mount_generation() -> ViewMountGenerationId:
    with _MOUNT_GENERATION_LOCK:
        return ViewMountGenerationId(next(_MOUNT_GENERATIONS))


class DiagnosticTasksQtAdapter(QObject):
    """Qt-only projection of the typed Diagnostic Tasks Feature Interface."""

    stateChanged = Signal()
    deliveryRequested = Signal(int, object)
    campaignHandoffReady = Signal(object)

    def __init__(
        self,
        feature: DiagnosticTasksFeature,
        *,
        context: DiagnosticTasksContext | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or DiagnosticTasksContext.workspace()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._last_emitted_monitoring_selection: tuple[str, str] | None = None
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: DiagnosticTasksViewState) -> None:
        if not self._closed:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: DiagnosticTasksViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        self._state = state
        self.stateChanged.emit()
        self._emit_monitoring_handoff_if_ready()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        error = self._state.error
        details = (
            f"{self.freshness} · {self.presentationState} · "
            f"{self._state.completeness.value}"
        )
        return details if error is None else f"{details} · {error.message}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def stateTitle(self) -> str:  # noqa: N802
        return {
            "loading": "Loading authoritative inputs",
            "empty": "No authoritative inputs are registered",
            "ready": "Authoritative inputs are ready",
            "degraded": "Showing last reliable authoritative inputs",
            "failed": "Authoritative input read failed",
            "input_unavailable": "Required authoritative inputs are unavailable",
        }[self.presentationState]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceText(self) -> str:  # noqa: N802
        return (
            f"{self._state.source.identity} · "
            f"g{self._state.source.generation.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def strategyCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.strategies:
            return "No authoritative Strategy Under Test is available."
        return "\n".join(
            (
                f"{item.strategy_id.value}@{item.strategy_version} · "
                f"{'required fixed input' if item.required else 'optional input'} · "
                f"compatibility {item.compatibility_surface_version} "
                f"{item.compatibility_manifest_hash} · "
                f"module {item.strategy_module} · "
                f"guardrail {item.guardrail_profile_id.value}@"
                f"{item.guardrail_profile_version} · thresholds "
                + ", ".join(
                    f"{threshold.metric_name} {threshold.operator} {threshold.value}"
                    for threshold in item.guardrail_thresholds
                )
            )
            for item in inventory.strategies
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def recipeCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.approved_recipes:
            return "No approved Scenario Recipe version is available."
        return "\n".join(
            (
                f"{item.recipe_id} · {item.recipe_version_id.value} · "
                f"{item.content_hash} · schema {item.schema_version} · "
                f"catalog {item.transformation_catalog_version}"
            )
            for item in inventory.approved_recipes
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioCatalogText(self) -> str:  # noqa: N802
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.market_scenarios:
            return "No materialized Market Scenario is available."
        return "\n".join(
            (
                f"{item.market_scenario_id.value} · {item.layer.value} · "
                f"case {item.campaign_case_id.value} · "
                f"source {item.historical_segment_id.value} "
                f"{item.historical_segment_content_hash} · "
                f"snapshot {item.source_snapshot_id.value} · "
                f"seed {item.materialization_seed} · "
                f"materializer {item.materialization_provenance.expander_version} "
                f"{item.materialization_provenance.source_resolution}->"
                f"{item.materialization_provenance.runtime_resolution} · "
                f"numeric tolerance "
                f"{item.materialization_provenance.numeric_tolerance} · "
                f"normalization "
                f"{item.materialization_provenance.normalization_provenance} · "
                f"reconstructed "
                f"{str(item.materialization_provenance.reconstructed).lower()} · "
                f"transformations {item.transformation_catalog_version}/"
                + (
                    ", ".join(
                        f"{transformation.transformation_id} "
                        f"[{transformation.family}]@"
                        f"{transformation.implementation_version} "
                        + (
                            "("
                            + ", ".join(
                                f"{parameter.name}={parameter.value}"
                                for parameter in transformation.parameters
                            )
                            + ")"
                            if transformation.parameters
                            else "(no parameters)"
                        )
                        for transformation in item.applied_transformations
                    )
                    or "baseline (no applied transformations)"
                )
                + " · "
                f"market rules {item.market_rule_profile_version} · "
                f"comparison {item.comparison_requirement} · "
                "execution policy "
                + ", ".join(
                    f"{value.name}={value.value}@{value.version} "
                    f"from {value.source}"
                    for value in item.execution_policy_values
                )
            )
            for item in inventory.market_scenarios
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproductionManifestStatus(self) -> str:  # noqa: N802
        return str(self._state.reproduction_manifest_availability.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def blockingReasonsText(self) -> str:  # noqa: N802
        if not self._state.blocking_reasons:
            return "No blocking reason."
        return "\n".join(
            f"{reason.code.value}: {reason.message}"
            for reason in self._state.blocking_reasons
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCreate(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_create)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canRevise(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_revise)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canValidate(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_validate)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canApprove(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_approve)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canStartCampaign(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_start_campaign)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_pause)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_resume)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelTask(self) -> bool:  # noqa: N802
        return bool(self._state.capabilities.can_cancel)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            is DiagnosticTaskLifecycle.RUNNING
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            is DiagnosticTaskLifecycle.PAUSED
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelCampaign(self) -> bool:  # noqa: N802
        task = self._state.task
        return bool(
            task is not None
            and task.handoff.campaign_id is not None
            and task.handoff.campaign_lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
            }
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPauseCampaignNode(self) -> bool:  # noqa: N802
        task = self._state.task
        node = self._actionable_campaign_node()
        return bool(
            task is not None
            and task.lifecycle is DiagnosticTaskLifecycle.RUNNING
            and node is not None
            and node.lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
            }
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResumeCampaignNode(self) -> bool:  # noqa: N802
        task = self._state.task
        node = self._actionable_campaign_node()
        return bool(
            task is not None
            and task.lifecycle is DiagnosticTaskLifecycle.RUNNING
            and node is not None
            and node.lifecycle is DiagnosticTaskLifecycle.PAUSED
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancelCampaignNode(self) -> bool:  # noqa: N802
        node = self._actionable_campaign_node()
        return bool(
            node is not None
            and node.lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
            }
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def taskStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None:
            return "No durable Diagnostic Task has been created."
        return (
            f"{task.task_id.value} · r{task.revision} · "
            f"{task.lifecycle.value} · configuration "
            f"{task.configuration.content_identity.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def taskHandleText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or not task.task_handles:
            return "No persistent TaskHandle is available."
        return "\n".join(
            (
                f"{handle.identity.value} · {handle.phase.value} · "
                f"{handle.progress:.0%} · "
                f"{handle.result or 'pending'} · "
                f"cancelable {str(handle.cancelable).lower()}"
            )
            for handle in task.task_handles
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def createStatusText(self) -> str:  # noqa: N802
        return getattr(
            self,
            "_create_status",
            "Create is ready when all displayed authoritative inputs are ready.",
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def validationStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None:
            return "No Diagnostic Task revision is available for validation."
        validation = task.validation
        if validation.validation_id is None:
            return f"Task r{task.revision} has not been validated."
        findings = (
            "no findings"
            if not validation.findings
            else "; ".join(
                f"{item.severity.value} {item.code.value}: "
                f"{item.safe_explanation}"
                for item in validation.findings
            )
        )
        return (
            f"{validation.state.value} · validation "
            f"{validation.validation_id.value}@"
            f"{validation.validation_revision} · task "
            f"r{validation.validated_revision} · {findings}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def approvalStatusText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or task.approval is None:
            return "No exact-revision approval is active."
        approval = task.approval
        return (
            f"{approval.approval_id.value} · task "
            f"r{approval.approved_revision} · validation "
            f"{approval.validation_id.value}@"
            f"{approval.validation_revision} · actor "
            f"{approval.actor_identity.value} · "
            f"{approval.approved_at.isoformat()}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignHandoffText(self) -> str:  # noqa: N802
        context = self.monitoring_context()
        if context is None or context.selection is None:
            return "No Formal Diagnostic Campaign has been handed off."
        selection = context.selection
        return (
            f"Campaign {selection.campaign_id.value} · "
            f"Run {selection.run_id.value if selection.run_id is not None else 'pending'}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignLifecycleText(self) -> str:  # noqa: N802
        task = self._state.task
        if task is None or task.handoff.campaign_id is None:
            return "No Formal Diagnostic Campaign lifecycle is available."
        lifecycle = task.handoff.campaign_lifecycle
        revision = task.handoff.campaign_revision
        return (
            f"{task.handoff.campaign_id.value} · "
            f"r{revision if revision is not None else 'unknown'} · "
            f"{lifecycle.value if lifecycle is not None else 'unknown'}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignNodeLifecycleText(self) -> str:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None:
            return "No actionable Campaign node is available."
        return (
            f"{node.campaign_node_id.value} · r{node.revision} · "
            f"{node.lifecycle.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def commandStatusText(self) -> str:  # noqa: N802
        return getattr(
            self,
            "_command_status",
            "Correction, validation, and exact-revision approval are ready "
            "when their typed capabilities are available.",
        )

    @Slot()
    def createTask(self) -> None:  # noqa: N802
        configuration = self._configuration_from_inventory(
            include_all_cases=False
        )
        if configuration is None or not self.canCreate:
            self._create_status = (
                "Diagnostic Task creation requires all authoritative inputs."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        result = self._feature.create_diagnostic_task(
            CreateDiagnosticTask(
                command_id=DiagnosticCommandId(
                    f"create-diagnostic-task-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"diagnostic-task-create-{command_identity}"
                ),
                configuration=configuration,
            )
        )
        self._create_status = result.message
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def reviseTask(self) -> None:  # noqa: N802
        task = self._state.task
        configuration = self._configuration_from_inventory(
            include_all_cases=True
        )
        if task is None or configuration is None or not self.canRevise:
            self._command_status = (
                "Configuration correction is unavailable for this task state."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        result = self._feature.revise_configuration(
            ReviseDiagnosticTaskConfiguration(
                command_id=DiagnosticCommandId(
                    f"revise-diagnostic-task-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"diagnostic-task-revise-{command_identity}"
                ),
                task_id=task.task_id,
                expected_revision=task.revision,
                configuration=configuration,
            )
        )
        self._command_status = result.message
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def validateTask(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canValidate:
            self._command_status = (
                "Validation is unavailable for this task state."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        result = self._feature.validate_configuration(
            ValidateDiagnosticTaskConfiguration(
                command_id=DiagnosticCommandId(
                    f"validate-diagnostic-task-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"diagnostic-task-validate-{command_identity}"
                ),
                task_id=task.task_id,
                expected_revision=task.revision,
            )
        )
        self._command_status = result.message
        self.refresh()
        self.stateChanged.emit()

    @Slot(str)
    def approveTask(self, actor_identity: str) -> None:  # noqa: N802
        task = self._state.task
        actor = actor_identity.strip()
        if task is None or not self.canApprove or not actor:
            self._command_status = (
                "Approval requires a valid exact revision and an actor identity."
            )
            self.stateChanged.emit()
            return
        validation = task.validation
        if (
            validation.validation_id is None
            or validation.validation_revision is None
            or validation.validated_revision is None
            or validation.configuration_content_identity is None
        ):
            self._command_status = (
                "Approval requires a valid exact revision."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        result = self._feature.approve_configuration(
            ApproveDiagnosticTaskConfiguration(
                command_id=DiagnosticCommandId(
                    f"approve-diagnostic-task-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"diagnostic-task-approve-{command_identity}"
                ),
                task_id=task.task_id,
                expected_revision=task.revision,
                validation_id=validation.validation_id,
                validation_revision=validation.validation_revision,
                validated_revision=validation.validated_revision,
                configuration_content_id=(
                    validation.configuration_content_identity
                ),
                actor_id=DiagnosticActorId(actor),
            )
        )
        self._command_status = result.message
        self.refresh()
        self.stateChanged.emit()

    @Slot()
    def startCampaign(self) -> None:  # noqa: N802
        task = self._state.task
        approval = None if task is None else task.approval
        if (
            task is None
            or approval is None
            or not self.canStartCampaign
            or approval.approved_revision != task.revision
        ):
            self._command_status = (
                "Campaign start requires the exact approved task revision."
            )
            self.stateChanged.emit()
            return
        command_identity = uuid4().hex
        result = self._feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId(
                    f"start-diagnostic-campaign-{command_identity}"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    f"diagnostic-campaign-start-{command_identity}"
                ),
                task_id=task.task_id,
                expected_revision=task.revision,
                approved_revision=approval.approved_revision,
            )
        )
        self._command_status = result.message
        self.refresh()
        self.stateChanged.emit()
        self._emit_monitoring_handoff_if_ready()

    @Slot()
    def pauseDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canPauseTask:
            self._lifecycle_unavailable("Task pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-pause-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def resumeDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canResumeTask:
            self._lifecycle_unavailable("Task resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-resume-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def cancelDiagnosticTaskTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if task is None or not self.canCancelTask:
            self._lifecycle_unavailable("Task cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-diagnostic-task-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-task-cancel-{command_identity}"
                    ),
                    target=DiagnosticTaskTarget(task.task_id),
                    expected_revision=task.revision,
                )
            )
        )

    @Slot()
    def pauseFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canPauseCampaign
        ):
            self._lifecycle_unavailable("Campaign pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-pause-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def resumeFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canResumeCampaign
        ):
            self._lifecycle_unavailable("Campaign resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-resume-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def cancelFormalDiagnosticCampaignTarget(self) -> None:  # noqa: N802
        task = self._state.task
        if (
            task is None
            or task.handoff.campaign_id is None
            or task.handoff.campaign_revision is None
            or not self.canCancelCampaign
        ):
            self._lifecycle_unavailable("Campaign cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-diagnostic-campaign-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"diagnostic-campaign-cancel-{command_identity}"
                    ),
                    target=FormalDiagnosticCampaignTarget(
                        task.handoff.campaign_id
                    ),
                    expected_revision=task.handoff.campaign_revision,
                )
            )
        )

    @Slot()
    def pauseCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canPauseCampaignNode:
            self._lifecycle_unavailable("Campaign node pause")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.pause_diagnostic_target(
                PauseDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"pause-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-pause-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    @Slot()
    def resumeCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canResumeCampaignNode:
            self._lifecycle_unavailable("Campaign node resume")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.resume_diagnostic_target(
                ResumeDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"resume-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-resume-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    @Slot()
    def cancelCampaignNodeTarget(self) -> None:  # noqa: N802
        node = self._actionable_campaign_node()
        if node is None or not self.canCancelCampaignNode:
            self._lifecycle_unavailable("Campaign node cancel")
            return
        command_identity = uuid4().hex
        self._complete_lifecycle_command(
            self._feature.cancel_diagnostic_target(
                CancelDiagnosticTarget(
                    command_id=DiagnosticCommandId(
                        f"cancel-campaign-node-{command_identity}"
                    ),
                    idempotency_key=DiagnosticCommandIdempotencyKey(
                        f"campaign-node-cancel-{command_identity}"
                    ),
                    target=CampaignNodeTarget(node.campaign_node_id),
                    expected_revision=node.revision,
                )
            )
        )

    def _complete_lifecycle_command(
        self,
        result: DiagnosticTasksCommandResult,
    ) -> None:
        self._command_status = result.message
        self.refresh()
        self.stateChanged.emit()

    def _lifecycle_unavailable(self, operation: str) -> None:
        self._command_status = (
            f"{operation} is unavailable for the authoritative lifecycle."
        )
        self.stateChanged.emit()

    def _actionable_campaign_node(
        self,
    ) -> DiagnosticCampaignNodeHandoff | None:
        task = self._state.task
        if task is None:
            return None
        terminal = {
            DiagnosticTaskLifecycle.CANCELED,
            DiagnosticTaskLifecycle.COMPLETED,
            DiagnosticTaskLifecycle.FAILED,
        }
        return next(
            (
                node
                for node in task.handoff.campaign_nodes
                if node.lifecycle not in terminal
            ),
            next(iter(task.handoff.campaign_nodes), None),
        )

    def monitoring_context(self) -> RunMonitoringContext | None:
        task = self._state.task
        if task is None:
            return None
        handoff = task.handoff
        if handoff.campaign_id is None:
            return None
        for node in handoff.campaign_nodes:
            for attempt in node.attempts:
                for run in attempt.runs:
                    return RunMonitoringContext.for_run(
                        RunMonitoringSelection(
                            campaign_id=handoff.campaign_id,
                            run_id=run.run_id,
                        )
                    )
        return None

    def _emit_monitoring_handoff_if_ready(self) -> None:
        context = self.monitoring_context()
        if context is None or context.selection is None:
            return
        selection = context.selection
        if selection.run_id is None:
            return
        identity = (selection.campaign_id.value, selection.run_id.value)
        if identity == self._last_emitted_monitoring_selection:
            return
        self._last_emitted_monitoring_selection = identity
        self.campaignHandoffReady.emit(context)

    def _configuration_from_inventory(
        self,
        *,
        include_all_cases: bool,
    ) -> DiagnosticTaskConfiguration | None:
        inventory = self._state.last_reliable_inventory
        if inventory is None or not inventory.market_scenarios:
            return None
        recipe_by_id = {
            item.recipe_version_id: item
            for item in inventory.approved_recipes
        }
        baseline_case_id = next(
            (
                item.campaign_case_id
                for item in inventory.market_scenarios
                if item.layer is DiagnosticCampaignLayer.BASELINE
            ),
            None,
        )
        if baseline_case_id is None:
            return None
        selected_scenarios = tuple(
            item
            for item in inventory.market_scenarios
            if include_all_cases
            or item.layer is DiagnosticCampaignLayer.BASELINE
        )
        return DiagnosticTaskConfiguration.create(
            strategy_selections=tuple(
                DiagnosticStrategySelection(
                    strategy_id=item.strategy_id,
                    strategy_version=item.strategy_version,
                    compatibility_manifest_hash=(
                        item.compatibility_manifest_hash
                    ),
                    guardrail_profile_id=item.guardrail_profile_id,
                    guardrail_profile_version=item.guardrail_profile_version,
                )
                for item in inventory.strategies
            ),
            campaign_case_selections=tuple(
                DiagnosticCampaignCaseSelection(
                    layer=item.layer,
                    recipe_version_id=item.recipe_version_id,
                    recipe_content_hash=recipe_by_id[
                        item.recipe_version_id
                    ].content_hash,
                    market_scenario_id=item.market_scenario_id,
                    campaign_case_id=item.campaign_case_id,
                    comparison_role=(
                        DiagnosticComparisonRole.CONTROL
                        if item.layer is DiagnosticCampaignLayer.BASELINE
                        else DiagnosticComparisonRole.COMPARE_TO_BASELINE
                    ),
                    baseline_campaign_case_id=(
                        None
                        if item.layer is DiagnosticCampaignLayer.BASELINE
                        else baseline_case_id
                    ),
                    execution_policy_values=item.execution_policy_values,
                )
                for item in selected_scenarios
            ),
        )

    @Slot()
    def refresh(self) -> None:
        self._accept_state(
            self._mount_generation.value,
            self._feature.snapshot(self._context),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


class RunMonitoringQtAdapter(QObject):
    """Qt-only projection of the external typed Run Monitoring Interface."""

    stateChanged = Signal()
    commandChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or RunMonitoringContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: RunMonitoringViewState) -> None:
        if self._closed:
            return
        self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: RunMonitoringViewState,
    ) -> None:
        if (
            self._closed
            or mount_generation != self._mount_generation.value
        ):
            return
        if state.context != self._context:
            return
        if state.revision <= self._state.revision:
            return
        self._state = state
        self.stateChanged.emit()

    def select_context(self, context: RunMonitoringContext) -> None:
        if self._closed:
            return
        if context == self._context:
            return
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        self._mount_generation = _next_mount_generation()
        self._context = context
        self._state = self._feature.snapshot(context)
        self._subscription = self._feature.subscribe(
            context,
            self._queue_state,
        )
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def ageText(self) -> str:  # noqa: N802 - QML property convention
        return f"{self._state.age.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshnessThresholdText(self) -> str:  # noqa: N802
        return f"{self._state.freshness_threshold.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        details = (
            f"{self.freshness} · {self.phase} · {self.completeness}"
        )
        error = self._state.error
        if error is not None:
            return f"{details} · {error.code} · {error.message}"
        return details

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802 - QML property convention
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def observedAtText(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.observed_at.isoformat())

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceIdentity(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.source.identity)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceGenerationText(self) -> str:  # noqa: N802
        return f"g{self._state.source.generation.value}"

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def mountGeneration(self) -> int:  # noqa: N802
        return self._mount_generation.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def mountGenerationText(self) -> str:  # noqa: N802
        return f"m{self._mount_generation.value}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        return "" if selection is None else selection.campaign_id.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def runIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        if selection is None or selection.run_id is None:
            return ""
        return str(selection.run_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def strategyIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.strategy_id is None:
            return "Unavailable"
        return str(data.strategy_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.market_scenario_id is None:
            return "Unavailable"
        return str(data.market_scenario_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def scenarioSetIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.scenario_set_id is None:
            return "Unavailable"
        return str(data.scenario_set_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproductionManifestIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.reproduction_manifest_id is None:
            return "Unavailable"
        return str(data.reproduction_manifest_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def lifecycle(self) -> str:
        data = self._state.last_reliable_data
        return "" if data is None else data.lifecycle.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def terminalOutcome(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.terminal_outcome is None:
            return ""
        return str(data.terminal_outcome.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def currentNodeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"{data.progress.current_node_id} · "
            f"{data.progress.current_node_label}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def progressText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return f"{data.progress.completed} / {data.progress.total}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def simulationTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"Day {data.simulation_time.sim_day} · "
            f"{data.simulation_time.instant.isoformat()}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def wallTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        seconds = int(data.wall_time.elapsed.total_seconds())
        return f"{data.wall_time.observed_at.isoformat()} · elapsed {seconds}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def executionAssumptionsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            (
                f"{item.name}: requested {item.requested_value}; "
                f"effective {item.effective_value}"
                + (
                    f"; override {item.override_reason}"
                    if item.override_reason
                    else ""
                )
            )
            for item in data.execution_assumptions
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def alertsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            f"{item.severity.value.upper()} · {item.message}"
            for item in data.alerts
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def diagnosticContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.context
        return "\n".join(
            (
                f"Market · {', '.join(context.market) or 'none'}",
                f"Account · {', '.join(context.account) or 'none'}",
                f"Positions · {', '.join(context.positions) or 'none'}",
                f"Orders · {', '.join(context.orders) or 'none'}",
                f"Fills · {', '.join(context.fills) or 'none'}",
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPause(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_pause
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResume(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_resume
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancel(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_cancel
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def activeTaskText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.active_task is None:
            return ""
        task = data.active_task
        details = [
            task.identity.value,
            task.phase.value,
            f"{round(task.progress * 100)}%",
            "cancelable" if task.cancelable else "not cancelable",
        ]
        if task.result:
            details.append(task.result)
        if task.error is not None:
            details.extend((task.error.code, task.error.message))
        return " · ".join(details)

    @Property(str, notify=commandChanged)  # type: ignore[arg-type]
    def commandMessage(self) -> str:  # noqa: N802
        return getattr(self, "_command_message", "")

    @Slot()
    def refresh(self) -> None:
        self._accept_state(
            self._mount_generation.value,
            self._feature.snapshot(self._context),
        )

    @Slot()
    def pauseDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.pause_diagnostic_task(
            PauseDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def resumeDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.resume_diagnostic_task(
            ResumeDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def cancelDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.cancel_diagnostic_task(
            CancelDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    def _set_command_message(self, message: str) -> None:
        if getattr(self, "_command_message", "") == message:
            return
        self._command_message = message
        self.commandChanged.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


class EvidenceAndFindingsQtAdapter(QObject):
    """Qt projection plus local-only research exploration state."""

    stateChanged = Signal()
    localStateChanged = Signal()
    chartPresentationChanged = Signal()
    chartGeometryChanged = Signal()
    chartInteractionChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: EvidenceAndFindingsFeature,
        *,
        context: EvidenceAndFindingsContext | None = None,
        chart_clock: Callable[[], int] = monotonic_ns,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or EvidenceAndFindingsContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._closed = False
        self._selected_candidate = ""
        self._selected_finding = ""
        self._evidence_filter = "all"
        self._sort_order = "dimension"
        self._active_tab = "findings"
        self._viewport_intent = "overview"
        self._selected_point_source_index: int | None = None
        self._selected_overlay = ""
        self._selected_breakpoint = ""
        self._chart_clock = chart_clock
        self._chart_frame_gate = EvidenceChartFrameGate(
            max_frames_per_second=20
        )
        self._pending_chart_presentations: list[
            EvidenceChartPresentation
        ] = []
        self._chart_interaction_enabled = True
        self._chart_timer = QTimer(self)
        self._chart_timer.setSingleShot(True)
        self._chart_timer.timeout.connect(self.flush_chart_frames)
        self._repair_local_selection()
        self._chart_presentation = self._build_chart_presentation()
        self._chart_frame_sequence = 1
        initial_gate = self._chart_frame_gate.offer(
            self._chart_presentation.frame,
            now_ns=self._chart_clock(),
        )
        if not initial_gate.committed:
            raise RuntimeError(
                "Initial Evidence chart presentation was not committed"
            )
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: EvidenceAndFindingsSubscription | None = (
            feature.subscribe(
                self._context,
                self._queue_state,
            )
        )

    def _queue_state(self, state: EvidenceAndFindingsViewState) -> None:
        if not self._closed:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: EvidenceAndFindingsViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        previous_state = self._state
        self._state = state
        self._repair_local_selection()
        if (
            state.context == previous_state.context
            and state.source == previous_state.source
            and state.last_reliable_data is previous_state.last_reliable_data
        ):
            presentation = advance_evidence_chart_presentation_revision(
                self._chart_presentation,
                state,
            )
        else:
            presentation = self._build_chart_presentation()
        self._offer_chart_presentation(
            presentation,
            local=False,
        )
        self.stateChanged.emit()
        self.localStateChanged.emit()

    def _repair_local_selection(self) -> None:
        data = self._state.last_reliable_data
        candidates = () if data is None else data.candidates
        candidate_ids = {item.identity.value for item in candidates}
        if self._selected_candidate not in candidate_ids:
            self._selected_candidate = (
                candidates[0].identity.value if candidates else ""
            )
        candidate = self._candidate()
        findings = () if candidate is None else candidate.findings
        finding_ids = {item.identity.value for item in findings}
        if self._selected_finding not in finding_ids:
            self._selected_finding = (
                findings[0].identity.value if findings else ""
            )
        chart = None if candidate is None else candidate.chart
        overlay_ids = (
            set() if chart is None else {item.identity for item in chart.overlays}
        )
        if self._selected_overlay not in overlay_ids:
            self._selected_overlay = (
                chart.overlays[0].identity
                if chart is not None and chart.overlays
                else ""
            )
        breakpoints = tuple(
            breakpoint
            for finding in findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        breakpoint_ids = {item.identity.value for item in breakpoints}
        if self._selected_breakpoint not in breakpoint_ids:
            self._selected_breakpoint = (
                breakpoints[0].identity.value if breakpoints else ""
            )
        if chart is None:
            self._selected_point_source_index = None

    def _candidate(self) -> CandidateEvidence | None:
        data = self._state.last_reliable_data
        if data is None:
            return None
        return next(
            (
                item
                for item in data.candidates
                if item.identity.value == self._selected_candidate
            ),
            None,
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceText(self) -> str:  # noqa: N802
        return (
            f"{self._state.source.identity} · "
            f"g{self._state.source.generation.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        error = self._state.error
        details = (
            f"{self.freshness} · {self.phase} · {self.completeness}"
        )
        if error is not None:
            return f"{details} · {error.message}"
        return details

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def pinnedIdentitiesText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        selection = (
            data.selection
            if data is not None
            else self._state.context.selection
        )
        if selection is None:
            return "No Formal Diagnostic Campaign or Strategy Run selected."
        lines = [
                f"Campaign · {selection.campaign_id.value}",
                f"Run · {selection.run_id.value}",
                (
                    "Strategy Under Test · "
                    f"{_optional_identity(selection.strategy_id)}"
                ),
                (
                    "Market Scenario · "
                    f"{_optional_identity(selection.market_scenario_id)}"
                ),
                (
                    "Approved Scenario Recipe · "
                    f"{_optional_identity(selection.approved_recipe_id)}"
                ),
                (
                    "Reproduction Manifest · "
                    f"{_optional_identity(selection.reproduction_manifest_id)}"
                ),
        ]
        if data is not None:
            lines.append(
                "Diagnostic Evidence Package · "
                f"{data.evidence_package_id.value}"
            )
        return "\n".join(lines)

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def hasReliableData(self) -> bool:  # noqa: N802
        return self._state.last_reliable_data is not None

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def candidateIdentities(self) -> list[str]:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return []
        return [item.identity.value for item in data.candidates]

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def findingIdentities(self) -> list[str]:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return []
        return [item.identity.value for item in candidate.findings]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def candidateSummaryText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return "No candidate evidence is available."
        return "  ·  ".join(
            f"{item.identity.value} — {item.label}" for item in data.candidates
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def curveCatalogText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        curves = (
            ()
            if data is None
            else tuple(
                curve
                for candidate in data.candidates
                for curve in candidate.curves
            )
        )
        if not curves:
            return (
                "No sealed sensitivity curves are available; typed textual "
                "evidence remains authoritative."
            )
        lines = []
        for curve in curves:
            axis = (
                (
                    f"{curve.axis.parameter_name} "
                    f"({curve.axis.value_type}, {curve.axis.order})"
                )
                if curve.axis is not None
                else "categorical"
            )
            points = ", ".join(
                (
                    f"case {point.case_id.value} / run {point.run_id.value} / "
                    f"metric {point.evidence_id.value} / manifest "
                    f"{point.reproduction_manifest_id.value} / artifact "
                    f"{point.run_artifact_hash} / parameters "
                    f"{', '.join(f'{name}={value}' for name, value in point.parameters)} "
                    f"/ value {point.value} {curve.unit}"
                )
                for point in curve.points
            )
            lines.append(

                    f"{curve.identity} · transformation "
                    f"{curve.transformation_family} / {curve.transformation_id} · "
                    f"strategy {curve.strategy_id.value}@{curve.strategy_version} · "
                    f"metric {curve.metric_name} / unit {curve.unit} · "
                    f"axis {axis} · {points}"

            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedCandidateIdentity(self) -> str:  # noqa: N802
        return self._selected_candidate

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedFindingIdentity(self) -> str:  # noqa: N802
        return self._selected_finding

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def evidenceFilter(self) -> str:  # noqa: N802
        return self._evidence_filter

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def sortOrder(self) -> str:  # noqa: N802
        return self._sort_order

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def activeTab(self) -> str:  # noqa: N802
        return self._active_tab

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def viewportIntent(self) -> str:  # noqa: N802
        return self._viewport_intent

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevision(self) -> int:  # noqa: N802
        return self._chart_presentation.frame.revision

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevisionText(self) -> str:  # noqa: N802
        return f"r{self.chartAcceptedRevision}"

    @Property(str, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSourceIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.source_identity

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSourcePointCount(self) -> int:  # noqa: N802
        return self._chart_presentation.source_point_count

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartVisiblePointCount(self) -> int:  # noqa: N802
        sample = self._chart_presentation.sample
        return 0 if sample is None else len(sample.points)

    @Property(int, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayCount(self) -> int:  # noqa: N802
        return len(self._chart_presentation.overlay_identities)

    @Property(str, notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartSamplingPolicy(self) -> str:  # noqa: N802
        sample = self._chart_presentation.sample
        return (
            EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1.value
            if sample is None
            else sample.key.policy.value
        )

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartNarrativeText(self) -> str:  # noqa: N802
        return self._chart_presentation.narrative_text

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartTableText(self) -> str:  # noqa: N802
        return self._chart_presentation.table_text

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAccessibleText(self) -> str:  # noqa: N802
        return self._chart_presentation.accessible_text

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.overlay_identities)

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartOverlayModels(self) -> list[dict[str, object]]:  # noqa: N802
        frame = self._chart_presentation.frame
        return [
            {
                "identity": item.identity,
                "axis": item.axis.value,
                "position": item.normalized_coordinate,
                "selected": (
                    item.identity == frame.selected_overlay_identity
                ),
            }
            for item in frame.overlays
        ]

    @Property("QVariantList", notify=chartGeometryChanged)  # type: ignore[arg-type]
    def chartNormalizedPoints(self) -> list[QPointF]:  # noqa: N802
        sample = self._chart_presentation.sample
        if sample is None:
            return []
        return [
            QPointF(item.normalized_x, item.normalized_y)
            for item in sample.points
        ]

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartFrameSequence(self) -> int:  # noqa: N802
        return self._chart_frame_sequence

    @Property(bool, notify=chartInteractionChanged)  # type: ignore[arg-type]
    def chartInteractionEnabled(self) -> bool:  # noqa: N802
        return self._chart_interaction_enabled

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartBreakpointIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.breakpoint_identities)

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartOverlayIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_overlay_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartFindingIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_finding_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartBreakpointIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_breakpoint_identity

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointIndex(self) -> int:  # noqa: N802
        selected = self._chart_presentation.selected_point_source_index
        return -1 if selected is None else selected

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointX(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[0]

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointY(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[1]

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def coverageText(self) -> str:  # noqa: N802
        return (
            "Baseline  ·  Isolated sensitivity  ·  Compound scenario  ·  "
            "Quick Experiment — exploratory only; does not satisfy formal coverage."
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def comparisonText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        data = self._state.last_reliable_data
        if data is None:
            return ""
        records = {
            item.identity: item
            for package_candidate in data.candidates
            for item in package_candidate.evidence
        }
        lines = [f"TYPED COMPARISONS · {candidate.identity.value}"]
        for comparison in candidate.comparisons:
            reference = records[comparison.reference_evidence_id]
            observed = records[comparison.observed_evidence_id]
            lines.extend(
                (
                    f"{comparison.identity.value} · {comparison.label}",
                    (
                        f"Reference {reference.identity.value} · "
                        f"{reference.value} {reference.unit} · "
                        f"Observed {observed.identity.value} · "
                        f"{observed.value} {observed.unit}"
                    ),
                )
            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def breakpointsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        breakpoints = tuple(
            breakpoint
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        return "\n".join(
            (
                f"Sensitivity Breakpoint · {item.identity.value} · "
                f"{item.assumption_name} {item.threshold} · {item.outcome} · "
                f"evidence {', '.join(ref.value for ref in item.evidence_ids)}"
            )
            for item in breakpoints
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def assumptionsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        return "\n".join(
            (
                f"{item.name} · requested {item.requested_value} · "
                f"effective {item.effective_value}"
                + (
                    f" · override {item.override_reason}"
                    if item.override_reason
                    else " · no override"
                )
            )
            for item in candidate.execution_assumptions
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def provenanceText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        provenance = candidate.provenance
        dependencies = ", ".join(
            f"{item.name} {item.version} {item.artifact_hash}"
            for item in provenance.dependencies
        )
        return "\n".join(
            (
                f"Artifact hashes · {', '.join(provenance.artifact_hashes)}",
                (
                    "Source runs · "
                    f"{', '.join(item.value for item in provenance.source_run_ids)}"
                ),
                f"Runner · {provenance.runner_version}",
                f"Build · {provenance.build_version}",
                f"Dependencies · {dependencies}",
            )
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def readOnlyContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.read_only_context
        orders = ", ".join(
            f"{item.identity} {item.status} ({item.diagnostic_note})"
            for item in context.orders
        )
        fills = ", ".join(
            (
                f"{item.identity} from {item.order_identity} · "
                f"{item.quantity} @ {item.price}"
            )
            for item in context.fills
        )
        return "\n".join(
            (
                "Orders and fills are read-only evidence traces.",
                f"Market · {', '.join(context.market)}",
                f"Account · {', '.join(context.account)}",
                f"Positions · {', '.join(context.positions)}",
                f"Orders · {orders}",
                f"Fills · {fills}",
            )
        )

    @Slot(str)
    def selectCandidate(self, identity: str) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or identity not in {
            item.identity.value for item in data.candidates
        }:
            return
        if identity == self._selected_candidate:
            return
        self._selected_candidate = identity
        self._selected_finding = ""
        self._repair_local_selection()
        self._publish_local_change()

    @Slot(str)
    def selectFinding(self, identity: str) -> None:  # noqa: N802
        candidate = self._candidate()
        if candidate is None or identity not in {
            item.identity.value for item in candidate.findings
        }:
            return
        if identity != self._selected_finding:
            self._selected_finding = identity
            self._publish_local_change()

    @Slot(float)
    def selectChartPointAtRatio(self, ratio: float) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points:
            return
        bounded = max(0.0, min(float(ratio), 1.0))
        sample_index = round(bounded * (len(sample.points) - 1))
        source_index = sample.points[sample_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(int)
    def stepChartPoint(self, direction: int) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points or direction == 0:
            return
        current_index = next(
            (
                index
                for index, point in enumerate(sample.points)
                if point.source_index == self._selected_point_source_index
            ),
            len(sample.points) - 1,
        )
        target_index = max(
            0,
            min(
                current_index + (1 if direction > 0 else -1),
                len(sample.points) - 1,
            ),
        )
        source_index = sample.points[target_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(str)
    def selectChartOverlay(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.overlay_identities
            or identity == self._selected_overlay
        ):
            return
        self._selected_overlay = identity
        self._publish_local_change()

    @Slot(str)
    def selectChartBreakpoint(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.breakpoint_identities
            or identity == self._selected_breakpoint
        ):
            return
        self._selected_breakpoint = identity
        self._publish_local_change()

    @Slot(str)
    def setEvidenceFilter(self, value: str) -> None:  # noqa: N802
        allowed = {"all"} | {item.value for item in EvidenceCoverage} | {
            item.value for item in EvidenceDimension
        }
        self._set_local("_evidence_filter", value, allowed)

    @Slot(str)
    def setSortOrder(self, value: str) -> None:  # noqa: N802
        self._set_local("_sort_order", value, {"dimension", "coverage"})

    @Slot(str)
    def setActiveTab(self, value: str) -> None:  # noqa: N802
        if (
            value
            not in {"findings", "assumptions", "provenance", "context"}
            or value == self._active_tab
        ):
            return
        self._active_tab = value
        self.localStateChanged.emit()

    @Slot(str)
    def setViewportIntent(self, value: str) -> None:  # noqa: N802
        self._set_local(
            "_viewport_intent",
            value,
            {"overview", "baseline", "sensitivity", "compound_stress"},
        )

    def _set_local(
        self,
        attribute: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if value not in allowed or getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._publish_local_change()

    def _publish_local_change(self) -> None:
        self._offer_chart_presentation(
            self._build_chart_presentation(),
            local=True,
        )
        self.localStateChanged.emit()

    def _build_chart_presentation(self) -> EvidenceChartPresentation:
        return build_evidence_chart_presentation(
            self._state,
            self._candidate(),
            selected_finding_identity=self._selected_finding,
            viewport=_chart_viewport(self._viewport_intent),
            selected_point_source_index=self._selected_point_source_index,
            selected_overlay_identity=self._selected_overlay,
            selected_breakpoint_identity=self._selected_breakpoint,
            evidence_filter=self._evidence_filter,
            sort_order=self._sort_order,
        )

    def _offer_chart_presentation(
        self,
        presentation: EvidenceChartPresentation,
        *,
        local: bool,
    ) -> None:
        self._selected_point_source_index = (
            presentation.selected_point_source_index
        )
        self._selected_overlay = presentation.selected_overlay_identity
        self._selected_breakpoint = presentation.selected_breakpoint_identity
        self._pending_chart_presentations.append(presentation)
        now_ns = self._chart_clock()
        result = (
            self._chart_frame_gate.offer_local(
                presentation.frame,
                now_ns=now_ns,
            )
            if local
            else self._chart_frame_gate.offer_metadata(
                presentation.frame,
                now_ns=now_ns,
            )
            if (
                not self._pending_chart_presentations[:-1]
                and self._same_chart_paint_work(
                    self._chart_presentation,
                    presentation,
                )
            )
            else self._chart_frame_gate.offer(
                presentation.frame,
                now_ns=now_ns,
            )
        )
        if not result.accepted:
            self._pending_chart_presentations.pop()
        self._apply_chart_gate_result(result)

    def flush_chart_frames(self) -> None:
        self._apply_chart_gate_result(
            self._chart_frame_gate.flush(now_ns=self._chart_clock())
        )

    def _apply_chart_gate_result(
        self,
        result: EvidenceChartFrameGateResult,
    ) -> None:
        for frame in result.committed:
            presentation_index = self._matching_chart_presentation_index(
                frame
            )
            if presentation_index is None:
                continue
            presentation = self._pending_chart_presentations[
                presentation_index
            ]
            del self._pending_chart_presentations[: presentation_index + 1]
            previous = self._chart_presentation
            geometry_changed = (
                previous.source_identity != presentation.source_identity
                or previous.source_point_count
                != presentation.source_point_count
                or previous.frame.points != presentation.frame.points
                or previous.frame.overlays != presentation.frame.overlays
                or previous.selected_overlay_identity
                != presentation.selected_overlay_identity
            )
            self._chart_presentation = presentation
            self._chart_frame_sequence += 1
            if geometry_changed:
                self.chartGeometryChanged.emit()
            self.chartPresentationChanged.emit()
        due_in_ns = result.due_in_ns
        if due_in_ns is None:
            self._chart_timer.stop()
        else:
            self._chart_timer.start(max(1, ceil(due_in_ns / 1_000_000)))
        self._sync_chart_interaction_enabled()

    @staticmethod
    def _same_chart_paint_work(
        current: EvidenceChartPresentation,
        candidate: EvidenceChartPresentation,
    ) -> bool:
        return bool(
            current.source_identity == candidate.source_identity
            and current.source_point_count == candidate.source_point_count
            and current.frame.points == candidate.frame.points
            and current.frame.overlays == candidate.frame.overlays
            and current.frame.selected_point
            == candidate.frame.selected_point
            and current.frame.selected_overlay_identity
            == candidate.frame.selected_overlay_identity
            and current.frame.selected_finding_identity
            == candidate.frame.selected_finding_identity
            and current.frame.selected_breakpoint_identity
            == candidate.frame.selected_breakpoint_identity
        )

    def _sync_chart_interaction_enabled(self) -> None:
        enabled = not self._pending_chart_presentations
        if enabled == self._chart_interaction_enabled:
            return
        self._chart_interaction_enabled = enabled
        self.chartInteractionChanged.emit()

    def _matching_chart_presentation_index(
        self,
        frame: EvidenceChartRenderFrame,
    ) -> int | None:
        for index in range(
            len(self._pending_chart_presentations) - 1,
            -1,
            -1,
        ):
            candidate = self._pending_chart_presentations[index].frame
            if (
                candidate.revision == frame.revision
                and candidate.points is frame.points
                and candidate.overlays is frame.overlays
                and candidate.selected_point
                == frame.selected_point
                and candidate.selected_overlay_identity
                == frame.selected_overlay_identity
                and candidate.selected_finding_identity
                == frame.selected_finding_identity
                and candidate.selected_breakpoint_identity
                == frame.selected_breakpoint_identity
            ):
                return index
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._chart_timer.stop()
        self._pending_chart_presentations.clear()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


def _title(value: EvidenceCoverage | EvidenceDimension) -> str:
    if value is EvidenceCoverage.QUICK_EXPERIMENT:
        return "Quick Experiment"
    return str(value.value).replace("_", " ").capitalize()


def _optional_identity(value: object | None) -> str:
    if value is None:
        return "Unavailable"
    return str(getattr(value, "value", "Unavailable"))


def _chart_viewport(intent: str) -> EvidenceChartViewport:
    viewports = {
        "overview": EvidenceChartViewport(0.0, 1.0),
        "baseline": EvidenceChartViewport(0.0, 0.25),
        "sensitivity": EvidenceChartViewport(0.25, 0.7),
        "compound_stress": EvidenceChartViewport(0.7, 1.0),
    }
    return viewports.get(intent, viewports["overview"])


class JourneyWorkspaceHost(QQuickWidget):
    """Exactly one route-level QML host mounted by the Widgets MainWindow."""

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        diagnostic_tasks_feature: DiagnosticTasksFeature | None = None,
        diagnostic_tasks_context: DiagnosticTasksContext | None = None,
        evidence_feature: EvidenceAndFindingsFeature | None = None,
        evidence_context: EvidenceAndFindingsContext | None = None,
        accessibility_preferences: AccessibilityPreferences | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("journeyWorkspaceHost")
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._workspace_closed = False
        self._accessibility_settings = AccessibilitySettingsQtAdapter(
            accessibility_preferences or detect_accessibility_preferences(),
            parent=self,
        )
        self.rootContext().setContextProperty(
            "accessibilitySettings",
            self._accessibility_settings,
        )
        self._diagnostic_tasks = (
            DiagnosticTasksQtAdapter(
                diagnostic_tasks_feature,
                context=diagnostic_tasks_context,
                parent=self,
            )
            if diagnostic_tasks_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "diagnosticTasks",
            self._diagnostic_tasks,
        )
        self._run_monitoring = RunMonitoringQtAdapter(
            feature,
            context=context,
            parent=self,
        )
        if self._diagnostic_tasks is not None:
            self._diagnostic_tasks.campaignHandoffReady.connect(
                self._open_run_monitoring_handoff
            )
        self.rootContext().setContextProperty(
            "runMonitoring",
            self._run_monitoring,
        )
        self._evidence_and_findings = (
            EvidenceAndFindingsQtAdapter(
                evidence_feature,
                context=evidence_context,
                parent=self,
            )
            if evidence_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "evidenceAndFindings",
            self._evidence_and_findings,
        )
        self.setSource(QUrl.fromLocalFile(str(_QML_ROOT / "JourneyWorkspace.qml")))
        if self.status() == QQuickWidget.Status.Error:
            details = "; ".join(error.toString() for error in self.errors())
            raise RuntimeError(f"Failed to load Journey Workspace QML: {details}")
        if self._diagnostic_tasks is not None:
            monitoring_context = self._diagnostic_tasks.monitoring_context()
            if monitoring_context is not None:
                self._open_run_monitoring_handoff(monitoring_context)

    @Slot(object)
    def _open_run_monitoring_handoff(
        self,
        context: RunMonitoringContext,
    ) -> None:
        if self._workspace_closed or not isinstance(context, RunMonitoringContext):
            return
        self._run_monitoring.select_context(context)
        root = self.rootObject()
        if root is not None:
            root.setProperty("activeRoute", "run_monitoring")

    def close_adapter(self) -> None:
        if self._workspace_closed:
            return
        self._workspace_closed = True
        if self._diagnostic_tasks is not None:
            self._diagnostic_tasks.close()
        self._run_monitoring.close()
        if self._evidence_and_findings is not None:
            self._evidence_and_findings.close()
        self.setSource(QUrl())


__all__ = [
    "DiagnosticTasksQtAdapter",
    "EvidenceAndFindingsQtAdapter",
    "JourneyWorkspaceHost",
    "RunMonitoringQtAdapter",
]
