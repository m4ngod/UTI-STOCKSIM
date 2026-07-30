"""Run Monitoring Feature Interface types and deterministic fake Adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Callable, Protocol, runtime_checkable

from .versioning import (
    RUN_MONITORING_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class Freshness(str, Enum):
    AWAITING_FIRST_STATE = "awaiting_first_state"
    FRESH = "fresh"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class ViewPhase(str, Enum):
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


class Completeness(str, Enum):
    UNKNOWN = "unknown"
    EMPTY = "empty"
    PARTIAL = "partial"
    COMPLETE = "complete"


class RunMonitoringPresentationState(str, Enum):
    LOADING = "loading"
    EMPTY = "empty"
    ACTIVE = "active"
    TERMINAL = "terminal"
    DISCONNECTED = "disconnected"


class SourceKind(str, Enum):
    DETERMINISTIC_FAKE = "deterministic_fake"
    LIVE_RUNTIME = "live_runtime"


@dataclass(frozen=True, slots=True)
class SourceGenerationId:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("Source generation must be a positive integer")


class RunLifecyclePhase(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TerminalOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskPhase(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class DiagnosticCommandRejectionReason(str, Enum):
    INVALID_LIFECYCLE_PHASE = "invalid_lifecycle_phase"
    STALE_EXPECTED_REVISION = "stale_expected_revision"
    DISCONNECTED_SOURCE = "disconnected_source"
    NON_CANCELABLE_TASK = "non_cancelable_task"
    UNAVAILABLE_CAPABILITY = "unavailable_capability"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class FormalDiagnosticCampaignId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Formal Diagnostic Campaign identity cannot be empty")


@dataclass(frozen=True, slots=True)
class StrategyRunId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Strategy Run identity cannot be empty")


def _require_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} identity cannot be empty")


@dataclass(frozen=True, slots=True)
class StrategyUnderTestId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Strategy Under Test")


@dataclass(frozen=True, slots=True)
class MarketScenarioId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Market Scenario")


@dataclass(frozen=True, slots=True)
class ScenarioSetId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario-set")


@dataclass(frozen=True, slots=True)
class ReproductionManifestId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Reproduction Manifest")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic task")


@dataclass(frozen=True, slots=True)
class TaskHandleId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Task handle")


@dataclass(frozen=True, slots=True)
class RunMonitoringSelection:
    campaign_id: FormalDiagnosticCampaignId
    run_id: StrategyRunId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, FormalDiagnosticCampaignId):
            raise TypeError("campaign_id must be a FormalDiagnosticCampaignId")
        if self.run_id is not None and not isinstance(self.run_id, StrategyRunId):
            raise TypeError("run_id must be a StrategyRunId")


@dataclass(frozen=True, slots=True)
class RunMonitoringContext:
    selection: RunMonitoringSelection | None

    @classmethod
    def no_selection(cls) -> "RunMonitoringContext":
        return cls(selection=None)

    @classmethod
    def for_run(
        cls,
        selection: RunMonitoringSelection,
    ) -> "RunMonitoringContext":
        if selection.run_id is None:
            raise ValueError("A Strategy Run identity is required")
        return cls(selection=selection)

    @classmethod
    def for_campaign(
        cls,
        campaign_id: FormalDiagnosticCampaignId,
    ) -> "RunMonitoringContext":
        return cls(selection=RunMonitoringSelection(campaign_id=campaign_id))


@dataclass(frozen=True, slots=True)
class RunMonitoringSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class StructuredFeatureError:
    code: str
    message: str
    retryable: bool
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunProgress:
    current_node_id: str
    current_node_label: str
    completed: int
    total: int

    def __post_init__(self) -> None:
        _require_identity(self.current_node_id, "Current node")
        if not self.current_node_label.strip():
            raise ValueError("Current node label cannot be empty")
        if self.completed < 0 or self.total < 1 or self.completed > self.total:
            raise ValueError("Run progress must satisfy 0 <= completed <= total")


@dataclass(frozen=True, slots=True)
class SimulationTime:
    sim_day: int
    instant: datetime

    def __post_init__(self) -> None:
        if self.sim_day < 0:
            raise ValueError("Simulation day cannot be negative")
        if self.instant.tzinfo is None:
            raise ValueError("Simulation Time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class WallTime:
    started_at: datetime | None
    observed_at: datetime
    elapsed: timedelta

    def __post_init__(self) -> None:
        if self.started_at is not None and self.started_at.tzinfo is None:
            raise ValueError("Wall Time start must be timezone-aware")
        if self.observed_at.tzinfo is None:
            raise ValueError("Wall Time observation must be timezone-aware")
        if self.elapsed < timedelta(0):
            raise ValueError("Wall Time elapsed cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionAssumption:
    name: str
    requested_value: str
    effective_value: str
    override_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Execution assumption name cannot be empty")
        if not self.requested_value.strip() or not self.effective_value.strip():
            raise ValueError("Execution assumption values cannot be empty")


@dataclass(frozen=True, slots=True)
class RunAlert:
    code: str
    severity: AlertSeverity
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("Run alert code and message cannot be empty")


@dataclass(frozen=True, slots=True)
class ReadOnlyDiagnosticContext:
    market: tuple[str, ...] = ()
    account: tuple[str, ...] = ()
    positions: tuple[str, ...] = ()
    orders: tuple[str, ...] = ()
    fills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCapabilities:
    can_pause: bool
    can_resume: bool
    can_cancel: bool


@dataclass(frozen=True, slots=True)
class _DiagnosticTaskTransition:
    capability_name: str
    controller_method: str
    lifecycle: RunLifecyclePhase
    result: str
    rejection_reason: DiagnosticCommandRejectionReason

    def is_allowed(self, capabilities: DiagnosticTaskCapabilities) -> bool:
        return bool(getattr(capabilities, self.capability_name))


_DIAGNOSTIC_TASK_TRANSITIONS = {
    "pause": _DiagnosticTaskTransition(
        capability_name="can_pause",
        controller_method="pause_arena",
        lifecycle=RunLifecyclePhase.PAUSED,
        result="diagnostic_task_paused",
        rejection_reason=(
            DiagnosticCommandRejectionReason.INVALID_LIFECYCLE_PHASE
        ),
    ),
    "resume": _DiagnosticTaskTransition(
        capability_name="can_resume",
        controller_method="resume_arena",
        lifecycle=RunLifecyclePhase.RUNNING,
        result="diagnostic_task_resumed",
        rejection_reason=(
            DiagnosticCommandRejectionReason.INVALID_LIFECYCLE_PHASE
        ),
    ),
    "cancel": _DiagnosticTaskTransition(
        capability_name="can_cancel",
        controller_method="cancel_diagnostic_task",
        lifecycle=RunLifecyclePhase.CANCELED,
        result="diagnostic_task_canceled",
        rejection_reason=(
            DiagnosticCommandRejectionReason.NON_CANCELABLE_TASK
        ),
    ),
}


def _diagnostic_task_transition(action: str) -> _DiagnosticTaskTransition:
    return _DIAGNOSTIC_TASK_TRANSITIONS[action]


@dataclass(frozen=True, slots=True)
class TaskHandle:
    identity: TaskHandleId
    target_id: DiagnosticTaskId
    phase: TaskPhase
    progress: float
    result: str | None
    error: StructuredFeatureError | None
    cancelable: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("Task progress must be between zero and one")


@dataclass(frozen=True, slots=True)
class RunMonitoringData:
    selection: RunMonitoringSelection
    strategy_id: StrategyUnderTestId | None
    market_scenario_id: MarketScenarioId | None
    scenario_set_id: ScenarioSetId | None
    reproduction_manifest_id: ReproductionManifestId | None
    task_id: DiagnosticTaskId | None
    lifecycle: RunLifecyclePhase
    terminal_outcome: TerminalOutcome | None
    progress: RunProgress
    simulation_time: SimulationTime
    wall_time: WallTime
    execution_assumptions: tuple[ExecutionAssumption, ...]
    alerts: tuple[RunAlert, ...]
    context: ReadOnlyDiagnosticContext
    capabilities: DiagnosticTaskCapabilities
    active_task: TaskHandle | None = None


@dataclass(frozen=True, slots=True)
class PauseDiagnosticTask:
    target_id: DiagnosticTaskId
    expected_revision: int

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be positive")


@dataclass(frozen=True, slots=True)
class ResumeDiagnosticTask:
    target_id: DiagnosticTaskId
    expected_revision: int

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be positive")


@dataclass(frozen=True, slots=True)
class CancelDiagnosticTask:
    target_id: DiagnosticTaskId
    expected_revision: int

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be positive")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCommandResult:
    accepted: bool
    message: str
    rejection_reason: DiagnosticCommandRejectionReason | None
    task: TaskHandle | None


@dataclass(frozen=True, slots=True)
class RunMonitoringViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: RunMonitoringSource
    context: RunMonitoringContext
    phase: ViewPhase
    presentation: RunMonitoringPresentationState
    last_reliable_data: RunMonitoringData | None
    error: StructuredFeatureError | None
    completeness: Completeness


RunMonitoringObserver = Callable[[RunMonitoringViewState], None]


@runtime_checkable
class Subscription(Protocol):
    @property
    def disposed(self) -> bool: ...

    def dispose(self) -> None: ...


@runtime_checkable
class RunMonitoringFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(self, context: RunMonitoringContext) -> RunMonitoringViewState: ...

    def subscribe(
        self,
        context: RunMonitoringContext,
        observer: RunMonitoringObserver,
    ) -> Subscription: ...

    def pause_diagnostic_task(
        self,
        command: PauseDiagnosticTask,
    ) -> DiagnosticTaskCommandResult: ...

    def resume_diagnostic_task(
        self,
        command: ResumeDiagnosticTask,
    ) -> DiagnosticTaskCommandResult: ...

    def cancel_diagnostic_task(
        self,
        command: CancelDiagnosticTask,
    ) -> DiagnosticTaskCommandResult: ...

    def close(self) -> None: ...


def _default_fake_time() -> datetime:
    return datetime(2030, 1, 1, tzinfo=timezone.utc)


class _RevisionGuardedSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._last_delivered_revision = 0
        self._lock = RLock()

    @property
    def disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
        self._dispose()

    def mark_disposed(self) -> None:
        with self._lock:
            self._disposed = True

    def deliver(
        self,
        observer: RunMonitoringObserver,
        state: RunMonitoringViewState,
    ) -> None:
        with self._lock:
            if (
                self._disposed
                or state.revision <= self._last_delivered_revision
            ):
                return
            self._last_delivered_revision = state.revision
            observer(state)


class DeterministicFakeRunMonitoringAdapter:
    """Deterministic fake for the external Run Monitoring Seam."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _default_fake_time,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        self._clock = clock
        self._freshness_threshold = freshness_threshold
        self._states: dict[RunMonitoringContext, RunMonitoringViewState] = {}
        self._subscriptions: dict[
            int,
            tuple[
                RunMonitoringContext,
                RunMonitoringObserver,
                _RevisionGuardedSubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._next_task_id = 1
        self._source_generation = SourceGenerationId(1)
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return RUN_MONITORING_INTERFACE_VERSION

    def snapshot(self, context: RunMonitoringContext) -> RunMonitoringViewState:
        with self._lock:
            self._ensure_open()
            state = self._states.get(context)
            if state is None:
                state = self._loading_state(context)
                self._states[context] = state
            return state

    def subscribe(
        self,
        context: RunMonitoringContext,
        observer: RunMonitoringObserver,
    ) -> Subscription:
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _RevisionGuardedSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
            state = self._states.get(context)
            if state is None:
                state = self._loading_state(context)
                self._states[context] = state
        subscription.deliver(observer, state)
        return subscription

    def advance_to_running(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        selection = context.selection
        if selection is None or selection.run_id is None:
            raise ValueError("A selected run is required for a running state")
        observed_at = self._clock()
        data = RunMonitoringData(
            selection=selection,
            strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
            scenario_set_id=ScenarioSetId("SCENARIO-SET-001"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
            task_id=DiagnosticTaskId(f"TASK-{selection.run_id.value}"),
            lifecycle=RunLifecyclePhase.RUNNING,
            terminal_outcome=None,
            progress=RunProgress(
                current_node_id="NODE-03",
                current_node_label="Isolated sensitivity",
                completed=2,
                total=10,
            ),
            simulation_time=SimulationTime(
                sim_day=3,
                instant=datetime(2029, 1, 3, 10, 30, tzinfo=timezone.utc),
            ),
            wall_time=WallTime(
                started_at=observed_at - timedelta(minutes=10),
                observed_at=observed_at,
                elapsed=timedelta(minutes=10),
            ),
            execution_assumptions=(
                ExecutionAssumption(
                    name="fee_model",
                    requested_value="standard",
                    effective_value="stress-1.6x",
                    override_reason="Scenario override",
                ),
                ExecutionAssumption(
                    name="latency_ms",
                    requested_value="10",
                    effective_value="10",
                ),
            ),
            alerts=(
                RunAlert(
                    code="spread_widening",
                    severity=AlertSeverity.WARNING,
                    message="Spread widening is affecting fills.",
                ),
            ),
            context=ReadOnlyDiagnosticContext(
                market=("600519.SH",),
                account=("MODEL-B17",),
                positions=("600519.SH +100",),
                orders=("ORD-001 filled",),
                fills=("FILL-001 100 @ 1500.00",),
            ),
            capabilities=DiagnosticTaskCapabilities(
                can_pause=True,
                can_resume=False,
                can_cancel=True,
            ),
        )
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=RunMonitoringPresentationState.ACTIVE,
            completeness=Completeness.COMPLETE,
            error=None,
            data=data,
            observed_at=observed_at,
        )

    def advance_to_empty(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        selection = context.selection
        if selection is not None and selection.run_id is not None:
            raise ValueError("A selected run cannot advance to empty")
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=RunMonitoringPresentationState.EMPTY,
            completeness=Completeness.EMPTY,
            error=None,
            data=None,
        )

    def advance_to_disconnected(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        current = self.snapshot(context)
        has_reliable_data = current.last_reliable_data is not None
        return self._transition_state(
            context,
            freshness=Freshness.DISCONNECTED,
            phase=(
                ViewPhase.DEGRADED
                if has_reliable_data
                else ViewPhase.FAILED
            ),
            presentation=RunMonitoringPresentationState.DISCONNECTED,
            completeness=Completeness.UNKNOWN,
            error=StructuredFeatureError(
                code="run_monitoring_source_disconnected",
                message="Runtime data is unavailable.",
                retryable=True,
            ),
            data=None,
        )

    def advance_to_stale(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        return self._transition_state(
            context,
            freshness=Freshness.STALE,
            phase=ViewPhase.DEGRADED,
            presentation=RunMonitoringPresentationState.ACTIVE,
            completeness=Completeness.COMPLETE,
            error=StructuredFeatureError(
                code="run_monitoring_source_stale",
                message=(
                    "Run Monitoring data is older than its "
                    "freshness threshold."
                ),
                retryable=True,
            ),
            data=None,
            age=self._freshness_threshold + timedelta(seconds=1),
        )

    def advance_to_partial(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            raise ValueError("A reliable run is required for partial state")
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.DEGRADED,
            presentation=current.presentation,
            completeness=Completeness.PARTIAL,
            error=StructuredFeatureError(
                code="run_monitoring_partial",
                message="Some Run Monitoring identity data is unavailable.",
                retryable=True,
            ),
            data=data,
        )

    def advance_to_reconnected(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            selection = context.selection
            if selection is not None and selection.run_id is not None:
                raise ValueError("A reliable run is required for reconnect")
            self._source_generation = SourceGenerationId(
                self._source_generation.value + 1
            )
            return self._transition_state(
                context,
                freshness=Freshness.FRESH,
                phase=ViewPhase.READY,
                presentation=RunMonitoringPresentationState.EMPTY,
                completeness=Completeness.EMPTY,
                error=None,
                data=None,
            )
        self._source_generation = SourceGenerationId(
            self._source_generation.value + 1
        )
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=(
                RunMonitoringPresentationState.TERMINAL
                if data.terminal_outcome is not None
                else RunMonitoringPresentationState.ACTIVE
            ),
            completeness=Completeness.COMPLETE,
            error=None,
            data=data,
        )

    def advance_to_failed(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            raise ValueError("A reliable run is required for failed state")
        failed_data = replace(
            data,
            lifecycle=RunLifecyclePhase.FAILED,
            terminal_outcome=TerminalOutcome.FAILED,
            capabilities=DiagnosticTaskCapabilities(False, False, False),
        )
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.FAILED,
            presentation=RunMonitoringPresentationState.TERMINAL,
            completeness=current.completeness,
            error=StructuredFeatureError(
                code="diagnostic_run_failed",
                message="The diagnostic run failed.",
                retryable=False,
            ),
            data=failed_data,
        )

    def advance_to_completed(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            raise ValueError("A reliable run is required for completed state")
        completed_data = replace(
            data,
            lifecycle=RunLifecyclePhase.COMPLETED,
            terminal_outcome=TerminalOutcome.COMPLETED,
            capabilities=DiagnosticTaskCapabilities(False, False, False),
        )
        return self._transition_state(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=RunMonitoringPresentationState.TERMINAL,
            completeness=current.completeness,
            error=None,
            data=completed_data,
        )

    def pause_diagnostic_task(
        self,
        command: PauseDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_diagnostic_command(
            action="pause",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def resume_diagnostic_task(
        self,
        command: ResumeDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_diagnostic_command(
            action="resume",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def cancel_diagnostic_task(
        self,
        command: CancelDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_diagnostic_command(
            action="cancel",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def _transition_state(
        self,
        context: RunMonitoringContext,
        *,
        freshness: Freshness,
        phase: ViewPhase,
        presentation: RunMonitoringPresentationState,
        completeness: Completeness,
        error: StructuredFeatureError | None,
        data: RunMonitoringData | None,
        observed_at: datetime | None = None,
        age: timedelta = timedelta(0),
    ) -> RunMonitoringViewState:
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context)
            if previous is None:
                previous = self._loading_state(context)
            previous_data = previous.last_reliable_data
            if (
                previous_data is not None
                and previous_data.terminal_outcome is not None
                and data is not None
                and data != previous_data
            ):
                data = previous_data
                phase = ViewPhase.FAILED
                presentation = RunMonitoringPresentationState.TERMINAL
                completeness = previous.completeness
                error = StructuredFeatureError(
                    code="strategy_diagnostics_integrity_failed",
                    message=(
                        "The terminal Strategy Run conflicts with its last "
                        "verified artifact."
                    ),
                    retryable=False,
                )
            state = RunMonitoringViewState(
                interface_version=self.interface_version,
                revision=previous.revision + 1,
                observed_at=observed_at or self._clock(),
                freshness=freshness,
                age=age,
                freshness_threshold=self._freshness_threshold,
                source=self._source(),
                context=context,
                phase=phase,
                presentation=presentation,
                last_reliable_data=(
                    data if data is not None else previous.last_reliable_data
                ),
                error=error,
                completeness=completeness,
            )
            self._states[context] = state
            deliveries = tuple(
                (observer, subscription)
                for subscribed_context, observer, subscription
                in self._subscriptions.values()
                if subscribed_context == context
            )
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def _apply_diagnostic_command(
        self,
        *,
        action: str,
        target_id: DiagnosticTaskId,
        expected_revision: int,
    ) -> DiagnosticTaskCommandResult:
        with self._lock:
            self._ensure_open()
            match = next(
                (
                    (context, state)
                    for context, state in self._states.items()
                    if state.last_reliable_data is not None
                    and state.last_reliable_data.task_id == target_id
                ),
                None,
            )
            if match is None:
                return _rejected_command(
                    DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
                    "The diagnostic task is unavailable.",
                )
            context, state = match
            data = state.last_reliable_data
            assert data is not None
            if state.revision != expected_revision:
                return _rejected_command(
                    DiagnosticCommandRejectionReason.STALE_EXPECTED_REVISION,
                    "The diagnostic task changed; refresh and try again.",
                )
            if state.freshness is Freshness.DISCONNECTED:
                return _rejected_command(
                    DiagnosticCommandRejectionReason.DISCONNECTED_SOURCE,
                    "The diagnostic source is disconnected.",
                )
            transition = _diagnostic_task_transition(action)
            if not transition.is_allowed(data.capabilities):
                return _rejected_command(
                    transition.rejection_reason,
                    f"The diagnostic task cannot {action} in its current phase.",
                )
            task_number = self._next_task_id
            self._next_task_id += 1
            task = TaskHandle(
                identity=TaskHandleId(f"FAKE-TASK-{task_number:04d}"),
                target_id=target_id,
                phase=TaskPhase.COMPLETED,
                progress=1.0,
                result=transition.result,
                error=None,
                cancelable=False,
            )
            lifecycle = transition.lifecycle
            terminal_outcome = (
                TerminalOutcome.CANCELED if action == "cancel" else None
            )
            capabilities = _capabilities_for_lifecycle(lifecycle)
            updated_data = replace(
                data,
                lifecycle=lifecycle,
                terminal_outcome=terminal_outcome,
                capabilities=capabilities,
                active_task=task,
            )
            updated_state = replace(
                state,
                revision=state.revision + 1,
                observed_at=self._clock(),
                freshness=Freshness.FRESH,
                age=timedelta(0),
                phase=ViewPhase.READY,
                presentation=(
                    RunMonitoringPresentationState.TERMINAL
                    if terminal_outcome is not None
                    else RunMonitoringPresentationState.ACTIVE
                ),
                last_reliable_data=updated_data,
                error=None,
                completeness=Completeness.COMPLETE,
            )
            self._states[context] = updated_state
            deliveries = tuple(
                (observer, subscription)
                for subscribed_context, observer, subscription
                in self._subscriptions.values()
                if subscribed_context == context
            )
        for observer, subscription in deliveries:
            subscription.deliver(observer, updated_state)
        return DiagnosticTaskCommandResult(
            accepted=True,
            message=f"Diagnostic task {action} accepted.",
            rejection_reason=None,
            task=task,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                subscription for _, _, subscription in self._subscriptions.values()
            )
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _loading_state(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=1,
            observed_at=self._clock(),
            freshness=Freshness.AWAITING_FIRST_STATE,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.LOADING,
            presentation=RunMonitoringPresentationState.LOADING,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.UNKNOWN,
        )

    def _source(self) -> RunMonitoringSource:
        return RunMonitoringSource(
            kind=SourceKind.DETERMINISTIC_FAKE,
            identity="frontend-v2-run-monitoring-fake",
            generation=self._source_generation,
        )

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Run Monitoring Adapter is closed")


def _capabilities_for_lifecycle(
    lifecycle: RunLifecyclePhase,
) -> DiagnosticTaskCapabilities:
    return DiagnosticTaskCapabilities(
        can_pause=lifecycle is RunLifecyclePhase.RUNNING,
        can_resume=lifecycle is RunLifecyclePhase.PAUSED,
        can_cancel=lifecycle
        in {
            RunLifecyclePhase.QUEUED,
            RunLifecyclePhase.RUNNING,
            RunLifecyclePhase.PAUSED,
        },
    )


def _rejected_command(
    reason: DiagnosticCommandRejectionReason,
    message: str,
) -> DiagnosticTaskCommandResult:
    return DiagnosticTaskCommandResult(
        accepted=False,
        message=message,
        rejection_reason=reason,
        task=None,
    )


__all__ = [
    "AlertSeverity",
    "CancelDiagnosticTask",
    "Completeness",
    "DeterministicFakeRunMonitoringAdapter",
    "DiagnosticCommandRejectionReason",
    "DiagnosticTaskCapabilities",
    "DiagnosticTaskCommandResult",
    "DiagnosticTaskId",
    "ExecutionAssumption",
    "FormalDiagnosticCampaignId",
    "Freshness",
    "MarketScenarioId",
    "PauseDiagnosticTask",
    "ReadOnlyDiagnosticContext",
    "ReproductionManifestId",
    "ResumeDiagnosticTask",
    "RunMonitoringContext",
    "RunMonitoringData",
    "RunMonitoringFeature",
    "RunMonitoringObserver",
    "RunMonitoringPresentationState",
    "RunMonitoringSelection",
    "RunMonitoringSource",
    "RunMonitoringViewState",
    "RunAlert",
    "RunLifecyclePhase",
    "RunProgress",
    "ScenarioSetId",
    "SimulationTime",
    "SourceKind",
    "SourceGenerationId",
    "StrategyUnderTestId",
    "StrategyRunId",
    "StructuredFeatureError",
    "Subscription",
    "TaskHandle",
    "TaskHandleId",
    "TaskPhase",
    "TerminalOutcome",
    "ViewPhase",
    "WallTime",
]
