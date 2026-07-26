"""Live Run Monitoring Adapter over existing runtime Implementations."""

from __future__ import annotations

from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable, TypeVar

from app.event_bridge import EventBridge
from app.runtime_gateway import RuntimeGateway

from .run_monitoring import (
    AlertSeverity,
    CancelDiagnosticTask,
    Completeness,
    DiagnosticCommandRejectionReason,
    DiagnosticTaskCapabilities,
    DiagnosticTaskCommandResult,
    DiagnosticTaskId,
    ExecutionAssumption,
    Freshness,
    MarketScenarioId,
    PauseDiagnosticTask,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResumeDiagnosticTask,
    RunAlert,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringObserver,
    RunMonitoringPresentationState,
    RunMonitoringSource,
    RunMonitoringViewState,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    TaskHandle,
    TaskHandleId,
    TaskPhase,
    TerminalOutcome,
    ViewPhase,
    WallTime,
    _diagnostic_task_transition,
)
from .versioning import (
    RUN_MONITORING_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _LiveSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
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


class LiveRunMonitoringAdapter:
    """Typed, batched live seam for an already-existing Strategy Run."""

    def __init__(
        self,
        *,
        runtime_gateway: RuntimeGateway,
        event_bridge: EventBridge,
        diagnostic_tasks: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        executor: Executor | None = None,
    ) -> None:
        self._runtime_gateway = runtime_gateway
        self._event_bridge = event_bridge
        self._diagnostic_tasks = diagnostic_tasks
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="run-monitoring-diagnostic-task",
        )
        self._owns_executor = executor is None
        self._states: dict[RunMonitoringContext, RunMonitoringViewState] = {}
        self._subscriptions: dict[
            int,
            tuple[RunMonitoringContext, RunMonitoringObserver, _LiveSubscription],
        ] = {}
        self._task_handles: dict[DiagnosticTaskId, TaskHandle] = {}
        self._next_subscription_id = 1
        self._next_task_id = 1
        self._closed = False
        self._lock = RLock()
        self._dispose_batch_subscription = event_bridge.subscribe_batches(
            self._on_snapshot_batch
        )

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return RUN_MONITORING_INTERFACE_VERSION

    def snapshot(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        with self._lock:
            self._ensure_open()
            current = self._states.get(context)
        if current is not None:
            aged = self._age_state(current)
            if aged is not current:
                return self._store_and_notify(context, aged)
            return current
        initial = self._read_state(context, revision=1)
        with self._lock:
            self._ensure_open()
            return self._states.setdefault(context, initial)

    def subscribe(
        self,
        context: RunMonitoringContext,
        observer: RunMonitoringObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _LiveSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
        observer(state)
        return subscription

    def pause_diagnostic_task(
        self,
        command: PauseDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="pause",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def resume_diagnostic_task(
        self,
        command: ResumeDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="resume",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def cancel_diagnostic_task(
        self,
        command: CancelDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="cancel",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                item[2] for item in self._subscriptions.values()
            )
            self._subscriptions.clear()
            dispose_batch = self._dispose_batch_subscription
            self._dispose_batch_subscription = lambda: None
        dispose_batch()
        for subscription in subscriptions:
            subscription.mark_disposed()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _on_snapshot_batch(
        self,
        batch: tuple[dict[str, Any], ...],
    ) -> None:
        batch_run_ids = {
            str(item.get("run_id") or "").strip()
            for item in batch
            if str(item.get("run_id") or "").strip()
        }
        with self._lock:
            if self._closed:
                return
            contexts = tuple(self._states)
        for context in contexts:
            selection = context.selection
            if (
                selection is not None
                and selection.run_id is not None
                and batch_run_ids
                and selection.run_id.value not in batch_run_ids
            ):
                continue
            if selection is None or selection.run_id is None:
                continue
            self._executor.submit(self._refresh_context, context)

    def _refresh_context(self, context: RunMonitoringContext) -> None:
        with self._lock:
            if self._closed:
                return
            previous = self._states.get(context)
        if previous is None:
            return
        state = self._read_state(context, revision=previous.revision + 1)
        if state.last_reliable_data is None and previous.last_reliable_data is not None:
            age = max(
                state.observed_at
                - previous.last_reliable_data.wall_time.observed_at,
                timedelta(0),
            )
            state = replace(
                state,
                freshness=Freshness.STALE,
                age=age,
                phase=ViewPhase.DEGRADED,
                presentation=previous.presentation,
                last_reliable_data=previous.last_reliable_data,
                error=state.error
                or StructuredFeatureError(
                    code="run_monitoring_source_unavailable",
                    message=(
                        "The selected run is temporarily unavailable; "
                        "showing the last reliable state."
                    ),
                    retryable=True,
                ),
                completeness=previous.completeness,
            )
        self._store_and_notify(context, state)

    def _read_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
    ) -> RunMonitoringViewState:
        observed_at = _aware(self._clock())
        if (
            context.selection is None
            or context.selection.run_id is None
        ):
            return self._empty_state(
                context,
                revision=revision,
                observed_at=observed_at,
            )
        try:
            record = self._runtime_gateway.get_run_monitoring_snapshot(
                context.selection.run_id.value
            )
        except Exception as error:
            return self._failed_state(
                context,
                revision=revision,
                observed_at=observed_at,
                error=error,
            )
        if record is None:
            return self._empty_state(
                context,
                revision=revision,
                observed_at=observed_at,
            )
        try:
            data = self._map_record(
                context,
                record,
                observed_at=observed_at,
            )
        except Exception as error:
            return self._failed_state(
                context,
                revision=revision,
                observed_at=observed_at,
                error=error,
            )
        terminal = data.terminal_outcome is not None
        failed = data.lifecycle is RunLifecyclePhase.FAILED
        age = max(
            observed_at - data.wall_time.observed_at,
            timedelta(0),
        )
        stale = age > self._freshness_threshold
        if stale:
            data = replace(
                data,
                capabilities=DiagnosticTaskCapabilities(
                    False,
                    False,
                    False,
                ),
            )
        completeness = _data_completeness(data)
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.STALE if stale else Freshness.FRESH,
            age=age,
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=(
                ViewPhase.FAILED
                if failed
                else ViewPhase.DEGRADED
                if stale
                else ViewPhase.READY
            ),
            presentation=(
                RunMonitoringPresentationState.TERMINAL
                if terminal
                else RunMonitoringPresentationState.ACTIVE
            ),
            last_reliable_data=data,
            error=(
                StructuredFeatureError(
                    code="diagnostic_run_failed",
                    message=next(
                        (
                            alert.message
                            for alert in data.alerts
                            if alert.severity is AlertSeverity.ERROR
                        ),
                        "The diagnostic run failed.",
                    ),
                    retryable=False,
                )
                if failed
                else StructuredFeatureError(
                    code="run_monitoring_source_stale",
                    message=(
                        "Run Monitoring data is older than its "
                        "freshness threshold."
                    ),
                    retryable=True,
                )
                if stale
                else None
            ),
            completeness=completeness,
        )

    def _map_record(
        self,
        context: RunMonitoringContext,
        record: dict[str, Any],
        *,
        observed_at: datetime,
    ) -> RunMonitoringData:
        selection = context.selection
        assert selection is not None
        assert selection.run_id is not None
        task_value = _optional_text(record.get("task_id"))
        task_id = (
            DiagnosticTaskId(task_value)
            if task_value is not None
            else None
        )
        runtime_lifecycle = _lifecycle(record.get("status"))
        controller_status = (
            self._diagnostic_task_status(task_id)
            if task_id is not None
            else None
        )
        lifecycle = (
            _lifecycle(controller_status)
            if controller_status is not None
            and runtime_lifecycle
            not in {
                RunLifecyclePhase.COMPLETED,
                RunLifecyclePhase.FAILED,
                RunLifecyclePhase.CANCELED,
            }
            else runtime_lifecycle
        )
        started_at = _optional_aware(record.get("started_at"))
        wall_observed_at = _optional_aware(record.get("updated_at")) or observed_at
        elapsed = (
            max(wall_observed_at - started_at, timedelta(0))
            if started_at is not None
            else timedelta(0)
        )
        simulation_instant = (
            _optional_aware(record.get("last_sim_dt"))
            or datetime(1, 1, 1, tzinfo=timezone.utc)
        )
        requested = _string_mapping(record.get("requested_execution"))
        effective = _string_mapping(record.get("effective_execution"))
        overrides = _string_mapping(record.get("execution_override_reasons"))
        assumption_names = tuple(sorted(set(requested) | set(effective)))
        assumptions = tuple(
            ExecutionAssumption(
                name=name,
                requested_value=requested.get(
                    name,
                    effective.get(name, "unavailable"),
                ),
                effective_value=effective.get(
                    name,
                    requested.get(name, "unavailable"),
                ),
                override_reason=overrides.get(name),
            )
            for name in assumption_names
        )
        alerts = tuple(
            RunAlert(
                code=_nonempty(item.get("code"), "runtime_alert"),
                severity=_alert_severity(item.get("severity")),
                message=_nonempty(
                    item.get("message"),
                    "Runtime alert details are unavailable.",
                ),
            )
            for item in _mapping_sequence(record.get("alerts"))
        )
        completed = max(int(record.get("completed_nodes") or 0), 0)
        total = max(int(record.get("total_nodes") or 1), 1)
        completed = min(completed, total)
        active_task = (
            self._task_handles.get(task_id)
            if task_id is not None
            else None
        )
        capabilities = (
            self._capabilities(task_id, lifecycle)
            if task_id is not None
            else DiagnosticTaskCapabilities(False, False, False)
        )
        if (
            active_task is not None
            and active_task.phase in {TaskPhase.QUEUED, TaskPhase.RUNNING}
        ):
            capabilities = DiagnosticTaskCapabilities(False, False, False)
        return RunMonitoringData(
            selection=selection,
            strategy_id=_optional_identity(
                record.get("strategy_id"),
                StrategyUnderTestId,
            ),
            market_scenario_id=_optional_identity(
                record.get("scenario_name"),
                MarketScenarioId,
            ),
            scenario_set_id=_optional_identity(
                record.get("scenario_set_id"),
                ScenarioSetId,
            ),
            reproduction_manifest_id=_optional_identity(
                record.get("reproduction_manifest_id"),
                ReproductionManifestId,
            ),
            task_id=task_id,
            lifecycle=lifecycle,
            terminal_outcome=_terminal_outcome(lifecycle),
            progress=RunProgress(
                current_node_id=_nonempty(
                    record.get("current_node_id"),
                    f"RUN-{lifecycle.value.upper()}",
                ),
                current_node_label=_nonempty(
                    record.get("current_node_label"),
                    lifecycle.value.replace("_", " ").title(),
                ),
                completed=completed,
                total=total,
            ),
            simulation_time=SimulationTime(
                sim_day=max(int(record.get("last_sim_day") or 0), 0),
                instant=simulation_instant,
            ),
            wall_time=WallTime(
                started_at=started_at,
                observed_at=wall_observed_at,
                elapsed=elapsed,
            ),
            execution_assumptions=assumptions,
            alerts=alerts,
            context=ReadOnlyDiagnosticContext(
                market=_string_tuple(record.get("market_context")),
                account=_string_tuple(record.get("account_context")),
                positions=_string_tuple(record.get("position_context")),
                orders=_string_tuple(record.get("order_context")),
                fills=_string_tuple(record.get("fill_context")),
            ),
            capabilities=capabilities,
            active_task=active_task,
        )

    def _apply_command(
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
                return _rejected(
                    DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
                    "The diagnostic task is unavailable.",
                )
            context, state = match
            aged_state = self._age_state(state)
            if aged_state is not state:
                self._states[context] = aged_state
                state = aged_state
            data = state.last_reliable_data
            assert data is not None
            if state.revision != expected_revision:
                return _rejected(
                    DiagnosticCommandRejectionReason.STALE_EXPECTED_REVISION,
                    "The diagnostic task changed; refresh and try again.",
                )
            if state.freshness in {
                Freshness.DISCONNECTED,
                Freshness.STALE,
            }:
                return _rejected(
                    DiagnosticCommandRejectionReason.DISCONNECTED_SOURCE,
                    "The diagnostic source is disconnected.",
                )
            if (
                data.active_task is not None
                and data.active_task.phase
                in {TaskPhase.QUEUED, TaskPhase.RUNNING}
            ):
                return _rejected(
                    DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
                    "A diagnostic task operation is already in progress.",
                )
            transition = _diagnostic_task_transition(action)
            if not transition.is_allowed(data.capabilities):
                return _rejected(
                    transition.rejection_reason,
                    f"The diagnostic task cannot {action} in its current phase.",
                )
            task = TaskHandle(
                identity=TaskHandleId(
                    f"LIVE-TASK-{self._next_task_id:04d}"
                ),
                target_id=target_id,
                phase=TaskPhase.QUEUED,
                progress=0.0,
                result=None,
                error=None,
                cancelable=False,
            )
            self._next_task_id += 1
            self._task_handles[target_id] = task
            queued_state = replace(
                state,
                revision=state.revision + 1,
                observed_at=_aware(self._clock()),
                last_reliable_data=replace(
                    data,
                    capabilities=DiagnosticTaskCapabilities(
                        False,
                        False,
                        False,
                    ),
                    active_task=task,
                ),
            )
            self._states[context] = queued_state
            observers = self._observers_for(context)
        for observer in observers:
            observer(queued_state)

        future = self._executor.submit(
            self._invoke_diagnostic_task,
            action,
            target_id,
        )
        def _complete(completed: Future[Any]) -> None:
            self._complete_command(
                context=context,
                action=action,
                target_id=target_id,
                task=task,
                future=completed,
            )

        future.add_done_callback(_complete)
        return DiagnosticTaskCommandResult(
            accepted=True,
            message=f"Diagnostic task {action} accepted.",
            rejection_reason=None,
            task=task,
        )

    def _invoke_diagnostic_task(
        self,
        action: str,
        target_id: DiagnosticTaskId,
    ) -> Any:
        controller = self._diagnostic_tasks
        if controller is None:
            raise RuntimeError("Diagnostic task capability is unavailable")
        transition = _diagnostic_task_transition(action)
        method = getattr(controller, transition.controller_method, None)
        if not callable(method):
            raise RuntimeError("Diagnostic task capability is unavailable")
        return method(target_id.value)

    def _complete_command(
        self,
        *,
        context: RunMonitoringContext,
        action: str,
        target_id: DiagnosticTaskId,
        task: TaskHandle,
        future: Future[Any],
    ) -> None:
        try:
            future.result()
        except Exception:
            task = replace(
                task,
                phase=TaskPhase.FAILED,
                progress=1.0,
                error=StructuredFeatureError(
                    code=f"diagnostic_task_{action}_failed",
                    message="The diagnostic task action failed.",
                    retryable=False,
                ),
            )
            lifecycle = None
        else:
            transition = _diagnostic_task_transition(action)
            task = replace(
                task,
                phase=TaskPhase.COMPLETED,
                progress=1.0,
                result=transition.result,
            )
            lifecycle = transition.lifecycle
        with self._lock:
            if self._closed:
                return
            state = self._states.get(context)
            if state is None or state.last_reliable_data is None:
                return
            tracked = self._task_handles.get(target_id)
            if tracked is None or tracked.identity != task.identity:
                return
            self._task_handles[target_id] = task
            data = state.last_reliable_data
            updated_data = replace(
                data,
                lifecycle=lifecycle or data.lifecycle,
                terminal_outcome=(
                    _terminal_outcome(lifecycle)
                    if lifecycle is not None
                    else data.terminal_outcome
                ),
                capabilities=self._capabilities(
                    target_id,
                    lifecycle or data.lifecycle,
                ),
                active_task=task,
            )
            updated_state = replace(
                state,
                revision=state.revision + 1,
                observed_at=_aware(self._clock()),
                phase=(
                    ViewPhase.DEGRADED
                    if task.phase is TaskPhase.FAILED
                    else ViewPhase.READY
                ),
                presentation=(
                    RunMonitoringPresentationState.TERMINAL
                    if updated_data.terminal_outcome is not None
                    else RunMonitoringPresentationState.ACTIVE
                ),
                last_reliable_data=updated_data,
                error=task.error,
            )
            self._states[context] = updated_state
            observers = self._observers_for(context)
        for observer in observers:
            observer(updated_state)

    def _diagnostic_task_status(
        self,
        task_id: DiagnosticTaskId,
    ) -> str | None:
        controller = self._diagnostic_tasks
        reader = getattr(controller, "get_arena", None)
        if not callable(reader):
            return None
        try:
            state = reader(task_id.value)
        except Exception:
            return None
        if not isinstance(state, dict):
            return None
        value = str(state.get("status") or "").strip()
        return value or None

    def _capabilities(
        self,
        task_id: DiagnosticTaskId,
        lifecycle: RunLifecyclePhase,
    ) -> DiagnosticTaskCapabilities:
        status = self._diagnostic_task_status(task_id)
        if status is None:
            return DiagnosticTaskCapabilities(False, False, False)
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

    def _empty_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.FRESH,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.READY,
            presentation=RunMonitoringPresentationState.EMPTY,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.EMPTY,
        )

    def _failed_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
        error: Exception,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.DISCONNECTED,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.FAILED,
            presentation=RunMonitoringPresentationState.DISCONNECTED,
            last_reliable_data=None,
            error=StructuredFeatureError(
                code="run_monitoring_query_failed",
                message=(
                    "Run Monitoring data is temporarily unavailable."
                ),
                retryable=True,
            ),
            completeness=Completeness.UNKNOWN,
        )

    def _age_state(
        self,
        state: RunMonitoringViewState,
    ) -> RunMonitoringViewState:
        data = state.last_reliable_data
        if (
            data is None
            or data.terminal_outcome is not None
            or state.freshness is Freshness.DISCONNECTED
        ):
            return state
        observed_at = _aware(self._clock())
        age = max(
            observed_at - data.wall_time.observed_at,
            timedelta(0),
        )
        source_failed = (
            state.freshness is Freshness.STALE
            and state.error is not None
            and state.error.code != "run_monitoring_source_stale"
        )
        if source_failed:
            if observed_at == state.observed_at and age == state.age:
                return state
            return replace(
                state,
                revision=state.revision + 1,
                observed_at=observed_at,
                age=age,
            )
        stale = age > self._freshness_threshold
        freshness = Freshness.STALE if stale else Freshness.FRESH
        if (
            observed_at == state.observed_at
            and age == state.age
            and freshness is state.freshness
        ):
            return state
        return replace(
            state,
            revision=state.revision + 1,
            observed_at=observed_at,
            freshness=freshness,
            age=age,
            phase=ViewPhase.DEGRADED if stale else ViewPhase.READY,
            last_reliable_data=data,
            error=(
                StructuredFeatureError(
                    code="run_monitoring_source_stale",
                    message=(
                        "Run Monitoring data is older than its "
                        "freshness threshold."
                    ),
                    retryable=True,
                )
                if stale
                else None
            ),
        )

    def _store_and_notify(
        self,
        context: RunMonitoringContext,
        state: RunMonitoringViewState,
    ) -> RunMonitoringViewState:
        with self._lock:
            if self._closed:
                return self._states.get(context, state)
            previous = self._states.get(context)
            if previous is not None and state.revision <= previous.revision:
                return previous
            self._states[context] = state
            observers = self._observers_for(context)
        for observer in observers:
            observer(state)
        return state

    def _observers_for(
        self,
        context: RunMonitoringContext,
    ) -> tuple[RunMonitoringObserver, ...]:
        return tuple(
            observer
            for subscribed_context, observer, _ in self._subscriptions.values()
            if subscribed_context == context
        )

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Run Monitoring Adapter is closed")

    @staticmethod
    def _source() -> RunMonitoringSource:
        return RunMonitoringSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="frontend-v2-live-runtime",
        )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _optional_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return _aware(parsed)
    return None


def _nonempty(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


IdentityT = TypeVar("IdentityT")


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_identity(
    value: Any,
    factory: Callable[[str], IdentityT],
) -> IdentityT | None:
    text = _optional_text(value)
    return factory(text) if text is not None else None


def _data_completeness(data: RunMonitoringData) -> Completeness:
    required_identities = (
        data.strategy_id,
        data.market_scenario_id,
        data.scenario_set_id,
        data.reproduction_manifest_id,
        data.task_id,
    )
    return (
        Completeness.COMPLETE
        if all(identity is not None for identity in required_identities)
        else Completeness.PARTIAL
    )


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(
        text
        for item in value
        if (text := str(item or "").strip())
    )


def _mapping_sequence(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _lifecycle(value: Any) -> RunLifecyclePhase:
    normalized = str(value or "").strip().lower()
    aliases = {
        "created": RunLifecyclePhase.QUEUED,
        "ready": RunLifecyclePhase.QUEUED,
        "starting": RunLifecyclePhase.QUEUED,
        "recovered": RunLifecyclePhase.RUNNING,
        "running": RunLifecyclePhase.RUNNING,
        "paused": RunLifecyclePhase.PAUSED,
        "completed": RunLifecyclePhase.COMPLETED,
        "stopped": RunLifecyclePhase.COMPLETED,
        "failed": RunLifecyclePhase.FAILED,
        "canceled": RunLifecyclePhase.CANCELED,
        "cancelled": RunLifecyclePhase.CANCELED,
    }
    return aliases.get(normalized, RunLifecyclePhase.QUEUED)


def _terminal_outcome(
    lifecycle: RunLifecyclePhase | None,
) -> TerminalOutcome | None:
    if lifecycle is None:
        return None
    return {
        RunLifecyclePhase.COMPLETED: TerminalOutcome.COMPLETED,
        RunLifecyclePhase.FAILED: TerminalOutcome.FAILED,
        RunLifecyclePhase.CANCELED: TerminalOutcome.CANCELED,
    }.get(lifecycle)


def _alert_severity(value: Any) -> AlertSeverity:
    try:
        return AlertSeverity(str(value or "").strip().lower())
    except ValueError:
        return AlertSeverity.INFO


def _rejected(
    reason: DiagnosticCommandRejectionReason,
    message: str,
) -> DiagnosticTaskCommandResult:
    return DiagnosticTaskCommandResult(
        accepted=False,
        message=message,
        rejection_reason=reason,
        task=None,
    )


__all__ = ["LiveRunMonitoringAdapter"]
