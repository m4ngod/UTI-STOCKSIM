"""Live and deterministic fake Adapters for Scenario Lab 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from threading import RLock

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
)

from .diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    CampaignCaseId,
    HistoricalMarketSegmentId,
    SourceSnapshotId,
)
from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
)
from .scenario_lab import (
    ScenarioLabBlockingCode,
    ScenarioLabBlockingReason,
    ScenarioLabCapabilities,
    ScenarioLabContext,
    ScenarioLabObserver,
    ScenarioLabPresentationState,
    ScenarioLabSource,
    ScenarioLabViewState,
)
from .scenario_lab_application import (
    AppliedTransformationProjection,
    ApproveScenarioRecipeCommand,
    ApproveScenarioRecipeResult,
    ComposeFormalScenarioSetCommand,
    ComposeFormalScenarioSetResult,
    CreateScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftResult,
    HistoricalSegmentEntry,
    HistoricalSegmentProvenance,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    MaterializeApprovedScenarioRecipeCommand,
    MaterializeApprovedScenarioRecipeResult,
    MarketScenarioComparisonRole,
    MarketScenarioEntry,
    MarketScenarioLayer,
    ReferenceMarketPathEntry,
    ReferenceMarketPathId,
    ReferencePathPreview,
    ReferencePathPreviewNode,
    RequestedExecutionAssumptionsProjection,
    ScenarioCompatibilityState,
    ScenarioExecutionResolutionState,
    ScenarioLabApplicationAvailability,
    ScenarioLabApplicationInventoryResult,
    ScenarioLabApplicationVersion,
    ScenarioLabAdmissionState,
    ScenarioLabCommandMetadata,
    ScenarioLabCommandReceipt,
    ScenarioLabCommandDisposition,
    ScenarioLabIntegrityState,
    ScenarioLabInventory,
    ScenarioLabQualityState,
    ScenarioLabTaskOperation,
    ScenarioLabUnavailabilityCode,
    ScenarioLabUnavailabilityReason,
    ScenarioReproducibilityState,
    ResolveScenarioExecutionAssumptionsCommand,
    ResolveScenarioExecutionAssumptionsResult,
    RetryScenarioMaterializationCommand,
    RetryScenarioMaterializationResult,
    ReviseScenarioRecipeDraftCommand,
    ReviseScenarioRecipeDraftResult,
    SelectFormalScenarioSetCommand,
    SelectFormalScenarioSetResult,
    StrategyDiagnosticsV1ScenarioLabApplication,
    TransformationCatalogEntryProjection,
    TransformationCatalogProjection,
    TransformationParameterProjection,
    ValidateScenarioRecipeDraftCommand,
    ValidateScenarioRecipeDraftResult,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .versioning import SCENARIO_LAB_INTERFACE_VERSION, FeatureInterfaceVersion


class _ScenarioLabSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._last_revision = 0
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
        observer: ScenarioLabObserver,
        state: ScenarioLabViewState,
    ) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._last_revision:
                return
            self._last_revision = state.revision
        try:
            observer(state)
        except Exception:  # noqa: BLE001 - observer failures stay isolated.
            return


class _ScenarioLabAdapter:
    def __init__(
        self,
        *,
        application: StrategyDiagnosticsV1ScenarioLabApplication,
        source_kind: SourceKind,
        source_identity: str,
        event_bridge: EventBridge | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        self._application = application
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._states: dict[ScenarioLabContext, ScenarioLabViewState] = {}
        self._current_context: ScenarioLabContext | None = None
        self._last_reliable_inventory: ScenarioLabInventory | None = None
        self._last_reliable_availability: (
            ScenarioLabApplicationAvailability | None
        ) = None
        self._last_reliable_at: datetime | None = None
        self._source_token: SourceRevisionToken | None = None
        self._subscriptions: dict[
            int,
            tuple[
                ScenarioLabContext,
                ScenarioLabObserver,
                _ScenarioLabSubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._revision = 0
        connection = event_bridge.connection_state if event_bridge else None
        self._bridge_generation = 1 if connection is None else connection.generation.value
        self._generation = SourceGenerationId(self._bridge_generation)
        self._connection_sequence = 1 if connection is None else connection.sequence.value
        self._connection_phase = (
            EventBridgeConnectionPhase.CONNECTED
            if connection is None
            else connection.phase
        )
        self._closed = False
        self._lock = RLock()
        self._dispose_connection_subscription = (
            event_bridge.subscribe_connection_state(
                self._on_connection_state,
                replay_current=True,
            )
            if event_bridge is not None
            else lambda: None
        )
        self._dispose_batch_subscription = (
            event_bridge.subscribe_batches(self._on_snapshot_batch)
            if event_bridge is not None
            else lambda: None
        )

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return SCENARIO_LAB_INTERFACE_VERSION

    def snapshot(
        self,
        context: ScenarioLabContext,
        *,
        _track_current: bool = True,
    ) -> ScenarioLabViewState:
        with self._lock:
            self._ensure_open()
            if _track_current:
                self._current_context = context
                self._prune_inactive_states()
            previous = self._states.get(context)
            generation = self._generation
            sequence = self._connection_sequence
            if previous is None and self._last_reliable_inventory is None:
                state = self._loading_state(context)
                if self._connection_phase is EventBridgeConnectionPhase.DISCONNECTED:
                    state = self._connection_state(
                        state,
                        EventBridgeConnectionPhase.DISCONNECTED,
                    )
                self._states[context] = state
                return state
            if self._connection_phase is EventBridgeConnectionPhase.DISCONNECTED:
                if previous is not None:
                    return previous
                assert self._last_reliable_inventory is not None
                state = self._state_from_inventory(
                    context,
                    self._last_reliable_inventory,
                    self._source_token,
                    self._last_reliable_availability
                    or _availability(self._last_reliable_inventory),
                )
                state = self._connection_state(
                    state,
                    EventBridgeConnectionPhase.DISCONNECTED,
                )
                self._states[context] = state
                return state
            if previous is None and self._last_reliable_inventory is not None:
                state = self._state_from_inventory(
                    context,
                    self._last_reliable_inventory,
                    self._source_token,
                    _availability(self._last_reliable_inventory),
                )
                self._states[context] = state
                return state
        assert previous is not None
        result = self._application.read_inventory()
        now = _aware(self._clock())
        with self._lock:
            if self._closed:
                return previous
            if (
                generation != self._generation
                or sequence != self._connection_sequence
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return self._states.get(context, previous)
            latest = self._states.get(context, previous)
            if latest is not previous:
                return latest
            if result.error is not None or result.inventory is None:
                state = self._failure_state(context, previous, result, now)
            elif (
                previous.freshness is Freshness.FRESH
                and result.source_token == previous.source_revision
                and previous.source.generation == self._generation
            ):
                return previous
            else:
                self._last_reliable_inventory = result.inventory
                self._last_reliable_availability = result.availability
                self._last_reliable_at = now
                self._source_token = result.source_token
                state = self._state_from_inventory(
                    context,
                    result.inventory,
                    result.source_token,
                    result.availability,
                    observed_at=now,
                )
            self._states[context] = state
            observers = self._observers_for(context)
        self._deliver(observers, state)
        return state

    def subscribe(
        self,
        context: ScenarioLabContext,
        observer: ScenarioLabObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _ScenarioLabSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
        subscription.deliver(observer, state)
        return subscription

    def create_recipe_draft(
        self, command: CreateScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        )
        return (
            CreateScenarioRecipeDraftResult(receipt=blocked)
            if blocked is not None
            else self._application.create_recipe_draft(command)
        )

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT
        )
        return (
            ReviseScenarioRecipeDraftResult(receipt=blocked)
            if blocked is not None
            else self._application.revise_recipe_draft(command)
        )

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT
        )
        return (
            ValidateScenarioRecipeDraftResult(receipt=blocked)
            if blocked is not None
            else self._application.validate_recipe_draft(command)
        )

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.APPROVE_RECIPE
        )
        return (
            ApproveScenarioRecipeResult(receipt=blocked)
            if blocked is not None
            else self._application.approve_recipe(command)
        )

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
        )
        return (
            MaterializeApprovedScenarioRecipeResult(receipt=blocked)
            if blocked is not None
            else self._application.materialize_reference_path(command)
        )

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.RETRY_MATERIALIZATION
        )
        return (
            RetryScenarioMaterializationResult(receipt=blocked)
            if blocked is not None
            else self._application.retry_materialization(command)
        )

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET
        )
        return (
            ComposeFormalScenarioSetResult(receipt=blocked)
            if blocked is not None
            else self._application.compose_scenario_set(command)
        )

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult:
        blocked = self._disconnected_receipt(
            command.metadata,
            ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS,
        )
        return (
            ResolveScenarioExecutionAssumptionsResult(receipt=blocked)
            if blocked is not None
            else self._application.resolve_execution_assumptions(command)
        )

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult:
        blocked = self._disconnected_receipt(
            command.metadata,
            ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET,
        )
        return (
            SelectFormalScenarioSetResult(receipt=blocked)
            if blocked is not None
            else self._application.select_formal_scenario_set(command)
        )

    def _disconnected_receipt(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt | None:
        with self._lock:
            self._ensure_open()
            if self._connection_phase is not EventBridgeConnectionPhase.CONNECTED:
                return ScenarioLabCommandReceipt(
                    metadata=metadata,
                    operation=operation,
                    disposition=ScenarioLabCommandDisposition.UNAVAILABLE,
                    message="Scenario Lab mutations are unavailable while disconnected.",
                    authoritative_revision=None,
                    task_handle=None,
                )
        return None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(item[2] for item in self._subscriptions.values())
            self._subscriptions.clear()
            dispose_connection = self._dispose_connection_subscription
            dispose_batch = self._dispose_batch_subscription
            self._dispose_connection_subscription = lambda: None
            self._dispose_batch_subscription = lambda: None
        dispose_connection()
        dispose_batch()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _loading_state(self, context: ScenarioLabContext) -> ScenarioLabViewState:
        now = _aware(self._clock())
        return ScenarioLabViewState(
            interface_version=SCENARIO_LAB_INTERFACE_VERSION,
            revision=self._next_revision(),
            observed_at=now,
            last_reliable_at=None,
            freshness=Freshness.AWAITING_FIRST_STATE,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            source_revision=None,
            context=context,
            phase=ViewPhase.LOADING,
            presentation=ScenarioLabPresentationState.LOADING,
            completeness=Completeness.UNKNOWN,
            historical_segments=(),
            reference_paths=(),
            market_scenarios=(),
            transformation_catalog=None,
            last_reliable_inventory=None,
            capabilities=ScenarioLabCapabilities.read_only(),
            blocking_reasons=_future_blocking_reasons(),
            focus_restoration_identity=None,
            error=None,
        )

    def _state_from_inventory(
        self,
        context: ScenarioLabContext,
        inventory: ScenarioLabInventory,
        source_token: SourceRevisionToken | None,
        availability: ScenarioLabApplicationAvailability,
        *,
        observed_at: datetime | None = None,
    ) -> ScenarioLabViewState:
        now = observed_at or _aware(self._clock())
        segments, paths, scenarios, catalog = _filtered_inventory(inventory, context)
        partial = availability is ScenarioLabApplicationAvailability.PARTIAL
        empty = not segments and not paths and not scenarios
        focus = context.focus_identity if _contains_identity(
            context.focus_identity,
            segments,
            paths,
            scenarios,
        ) else None
        return ScenarioLabViewState(
            interface_version=SCENARIO_LAB_INTERFACE_VERSION,
            revision=self._next_revision(),
            observed_at=now,
            last_reliable_at=self._last_reliable_at or now,
            freshness=Freshness.FRESH,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            source_revision=source_token,
            context=context,
            phase=ViewPhase.DEGRADED if partial else ViewPhase.READY,
            presentation=(
                ScenarioLabPresentationState.PARTIAL
                if partial
                else ScenarioLabPresentationState.EMPTY
                if empty
                else ScenarioLabPresentationState.READY
            ),
            completeness=(
                Completeness.PARTIAL
                if partial
                else Completeness.EMPTY
                if empty
                else Completeness.COMPLETE
            ),
            historical_segments=segments,
            reference_paths=paths,
            market_scenarios=scenarios,
            transformation_catalog=catalog,
            last_reliable_inventory=inventory,
            capabilities=ScenarioLabCapabilities.read_only(),
            blocking_reasons=(
                *((
                    ScenarioLabBlockingReason(
                        code=ScenarioLabBlockingCode.INVENTORY_PARTIAL,
                        message="Some immutable Scenario Lab facts failed closed.",
                        dependent_operations=("materialize_reference_path", "compose_scenario_set"),
                    ),
                ) if partial else ()),
                *_future_blocking_reasons(),
            ),
            focus_restoration_identity=focus,
            error=None,
        )

    def _failure_state(
        self,
        context: ScenarioLabContext,
        previous: ScenarioLabViewState,
        result: ScenarioLabApplicationInventoryResult,
        now: datetime,
    ) -> ScenarioLabViewState:
        error = result.error
        structured = StructuredFeatureError(
            code="scenario_lab_inventory_read_failed" if error is None else error.code.value,
            message=(
                "The authoritative Scenario Lab inventory could not be read."
                if error is None
                else error.message
            ),
            retryable=False if error is None else error.retryable,
        )
        inventory = self._last_reliable_inventory
        if inventory is None:
            segments: tuple[HistoricalSegmentEntry, ...] = ()
            paths: tuple[ReferenceMarketPathEntry, ...] = ()
            scenarios: tuple[MarketScenarioEntry, ...] = ()
            presentation = ScenarioLabPresentationState.FAILED
            completeness = Completeness.UNKNOWN
            phase = ViewPhase.FAILED
            freshness = Freshness.AWAITING_FIRST_STATE
            catalog = None
        else:
            segments, paths, scenarios, catalog = _filtered_inventory(
                inventory,
                context,
            )
            presentation = ScenarioLabPresentationState.STALE
            completeness = previous.completeness
            phase = ViewPhase.DEGRADED
            freshness = Freshness.STALE
        return replace(
            previous,
            revision=self._next_revision(),
            observed_at=now,
            last_reliable_at=self._last_reliable_at,
            freshness=freshness,
            age=timedelta(0) if self._last_reliable_at is None else now - self._last_reliable_at,
            phase=phase,
            presentation=presentation,
            completeness=completeness,
            historical_segments=segments,
            reference_paths=paths,
            market_scenarios=scenarios,
            transformation_catalog=catalog,
            last_reliable_inventory=inventory,
            blocking_reasons=(
                ScenarioLabBlockingReason(
                    code=ScenarioLabBlockingCode.INVENTORY_READ_FAILED,
                    message=structured.message,
                    dependent_operations=("snapshot",),
                ),
                *_future_blocking_reasons(),
            ),
            error=structured,
        )

    def _connection_state(
        self,
        previous: ScenarioLabViewState,
        phase: EventBridgeConnectionPhase,
    ) -> ScenarioLabViewState:
        now = _aware(self._clock())
        disconnected = phase is EventBridgeConnectionPhase.DISCONNECTED
        has_reliable = self._last_reliable_inventory is not None
        code = (
            ScenarioLabBlockingCode.SOURCE_DISCONNECTED
            if disconnected
            else ScenarioLabBlockingCode.SOURCE_RECONNECTING
        )
        message = (
            "Scenario Lab is disconnected; retained data may be stale."
            if disconnected
            else "Scenario Lab is reconnecting and rereading authority."
        )
        return replace(
            previous,
            revision=self._next_revision(),
            observed_at=now,
            freshness=Freshness.DISCONNECTED if disconnected else Freshness.STALE,
            age=timedelta(0) if self._last_reliable_at is None else now - self._last_reliable_at,
            source=self._source(),
            phase=ViewPhase.DEGRADED if has_reliable else ViewPhase.FAILED,
            presentation=(
                ScenarioLabPresentationState.DISCONNECTED
                if disconnected
                else ScenarioLabPresentationState.STALE
            ),
            blocking_reasons=(
                ScenarioLabBlockingReason(
                    code=code,
                    message=message,
                    dependent_operations=("create_recipe_draft", "materialize_reference_path"),
                ),
                *_future_blocking_reasons(),
            ),
            error=StructuredFeatureError(
                code=code.value,
                message=message,
                retryable=True,
            ),
        )

    def _on_connection_state(self, connection: EventBridgeConnectionState) -> None:
        with self._lock:
            if self._closed or connection.sequence.value <= self._connection_sequence:
                return
            if connection.generation.value != self._bridge_generation:
                self._generation = SourceGenerationId(self._generation.value + 1)
            self._bridge_generation = connection.generation.value
            self._connection_sequence = connection.sequence.value
            self._connection_phase = connection.phase
            contexts = self._contexts_to_refresh()
        for context in contexts:
            self._publish_connection_state(context, connection.phase)
        if connection.phase is EventBridgeConnectionPhase.CONNECTED:
            for context in contexts:
                self.snapshot(context, _track_current=False)

    def _publish_connection_state(
        self,
        context: ScenarioLabContext,
        phase: EventBridgeConnectionPhase,
    ) -> None:
        with self._lock:
            previous = self._states.get(context)
            if self._closed or previous is None:
                return
            state = self._connection_state(previous, phase)
            self._states[context] = state
            observers = self._observers_for(context)
        self._deliver(observers, state)

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
        if not any(
            _is_scenario_lab_invalidation(item) for item in batch.snapshots
        ):
            return
        with self._lock:
            if (
                self._closed
                or batch.generation.value != self._bridge_generation
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return
            contexts = self._contexts_to_refresh()
        for context in contexts:
            self.snapshot(context, _track_current=False)

    def _source(self) -> ScenarioLabSource:
        return ScenarioLabSource(
            kind=self._source_kind,
            identity=self._source_identity,
            generation=self._generation,
        )

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision

    def _observers_for(
        self,
        context: ScenarioLabContext,
    ) -> tuple[tuple[ScenarioLabObserver, _ScenarioLabSubscription], ...]:
        return tuple(
            (observer, subscription)
            for subscribed_context, observer, subscription in self._subscriptions.values()
            if subscribed_context == context
        )

    @staticmethod
    def _deliver(
        observers: tuple[tuple[ScenarioLabObserver, _ScenarioLabSubscription], ...],
        state: ScenarioLabViewState,
    ) -> None:
        for observer, subscription in observers:
            subscription.deliver(observer, state)

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            removed = self._subscriptions.pop(subscription_id, None)
            if removed is None:
                return
            context = removed[0]
            if (
                context != self._current_context
                and not any(item[0] == context for item in self._subscriptions.values())
            ):
                self._states.pop(context, None)

    def _contexts_to_refresh(self) -> tuple[ScenarioLabContext, ...]:
        contexts = [item[0] for item in self._subscriptions.values()]
        if self._current_context is not None:
            contexts.append(self._current_context)
        return tuple(dict.fromkeys(contexts))

    def _prune_inactive_states(self) -> None:
        subscribed = {item[0] for item in self._subscriptions.values()}
        for cached_context in tuple(self._states):
            if cached_context != self._current_context and cached_context not in subscribed:
                self._states.pop(cached_context, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Scenario Lab Adapter is closed")


class LiveScenarioLabAdapter(_ScenarioLabAdapter):
    def __init__(
        self,
        *,
        application: StrategyDiagnosticsV1ScenarioLabApplication,
        event_bridge: EventBridge | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        super().__init__(
            application=application,
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="strategy-diagnostics-v1-scenario-lab",
            event_bridge=event_bridge,
            clock=clock,
            freshness_threshold=freshness_threshold,
        )


class _DeterministicFakeScenarioLabApplication:
    def __init__(
        self,
        inventory: ScenarioLabInventory,
        *,
        clock: Callable[[], datetime],
        scripted_results: tuple[ScenarioLabApplicationInventoryResult, ...],
    ) -> None:
        self._clock = clock
        self._scripted_results = list(scripted_results)
        self._result = ScenarioLabApplicationInventoryResult(
            availability=_availability(inventory),
            inventory=inventory,
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(inventory).encode("utf-8")).hexdigest()
            ),
            observed_at=_aware(clock()),
            error=None,
        )

    @property
    def interface_version(self) -> ScenarioLabApplicationVersion:
        from .scenario_lab_application import SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

        return SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult:
        if self._scripted_results:
            self._result = self._scripted_results.pop(0)
        return replace(self._result, observed_at=_aware(self._clock()))

    @staticmethod
    def _receipt(
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt:
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.UNAVAILABLE,
            message="This Scenario Lab capability is not yet available.",
            authoritative_revision=None,
            task_handle=None,
        )

    def create_recipe_draft(
        self, command: CreateScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult:
        return CreateScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT)
        )

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        return ReviseScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT)
        )

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        return ValidateScenarioRecipeDraftResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT)
        )

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        return ApproveScenarioRecipeResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.APPROVE_RECIPE)
        )

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        return MaterializeApprovedScenarioRecipeResult(
            self._receipt(
                command.metadata, ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
            )
        )

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        return RetryScenarioMaterializationResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.RETRY_MATERIALIZATION)
        )

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult:
        return ComposeFormalScenarioSetResult(
            self._receipt(command.metadata, ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET)
        )

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult:
        return ResolveScenarioExecutionAssumptionsResult(
            self._receipt(
                command.metadata,
                ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS,
            )
        )

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult:
        return SelectFormalScenarioSetResult(
            self._receipt(
                command.metadata,
                ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET,
            )
        )


class DeterministicFakeScenarioLabAdapter(_ScenarioLabAdapter):
    def __init__(
        self,
        *,
        inventory: ScenarioLabInventory | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        scripted_results: tuple[ScenarioLabApplicationInventoryResult, ...] = (),
    ) -> None:
        resolved_clock = clock or (lambda: datetime.now(timezone.utc))
        application = _DeterministicFakeScenarioLabApplication(
            inventory or _default_inventory(),
            clock=resolved_clock,
            scripted_results=scripted_results,
        )
        self._fake_bridge = EventBridge(subscribe_backend=False)
        super().__init__(
            application=application,
            source_kind=SourceKind.DETERMINISTIC_FAKE,
            source_identity="deterministic-fake-scenario-lab",
            event_bridge=self._fake_bridge,
            clock=resolved_clock,
            freshness_threshold=freshness_threshold,
        )

    def advance_to_disconnected(self) -> None:
        self._fake_bridge.mark_disconnected()

    def advance_to_reconnected(self) -> None:
        self._fake_bridge.mark_reconnected()

    def deliver_invalidation(self, *, generation: int) -> None:
        self._fake_bridge.on_snapshot(
            {"kind": "scenario-lab"},
            generation=generation,
        )
        self._fake_bridge.flush(force=True)

    def close(self) -> None:
        super().close()
        self._fake_bridge.stop()


def _future_blocking_reasons() -> tuple[ScenarioLabBlockingReason, ...]:
    return (
        ScenarioLabBlockingReason(
            ScenarioLabBlockingCode.RECIPE_DRAFT_NOT_YET_AVAILABLE,
            "Recipe Draft creation and validation are owned by Issue #80.",
            ("create_recipe_draft", "revise_recipe_draft", "validate_recipe_draft"),
        ),
        ScenarioLabBlockingReason(
            ScenarioLabBlockingCode.RECIPE_APPROVAL_NOT_YET_AVAILABLE,
            "Recipe approval is owned by Issue #81.",
            ("approve_recipe",),
        ),
        ScenarioLabBlockingReason(
            ScenarioLabBlockingCode.MATERIALIZATION_NOT_YET_AVAILABLE,
            "Reference Path materialization is owned by Issue #82.",
            ("materialize_reference_path", "retry_materialization"),
        ),
        ScenarioLabBlockingReason(
            ScenarioLabBlockingCode.SCENARIO_COMPOSITION_NOT_YET_AVAILABLE,
            "Formal Scenario composition is owned by Issue #83.",
            ("compose_scenario_set", "resolve_execution_assumptions", "select_formal_scenario_set"),
        ),
    )


def _filtered_inventory(
    inventory: ScenarioLabInventory,
    context: ScenarioLabContext,
) -> tuple[
    tuple[HistoricalSegmentEntry, ...],
    tuple[ReferenceMarketPathEntry, ...],
    tuple[MarketScenarioEntry, ...],
    TransformationCatalogProjection,
]:
    needle = context.search_text.casefold()
    market_segments = tuple(
        item
        for item in inventory.historical_segments
        if (not context.markets or item.market in context.markets)
        and (
            not context.sources
            or item.source_snapshot_id.value in context.sources
        )
    )
    market_segment_ids = {item.segment_id for item in market_segments}
    segments = tuple(
        item
        for item in market_segments
        if (
            not needle
            or needle in " ".join(
                (
                    item.segment_id.value,
                    item.label,
                    item.market,
                    item.provenance.provider,
                    item.provenance.dataset,
                    *item.recommendation_tags,
                )
            ).casefold()
        )
    )
    eligible_paths = tuple(
        item
        for item in inventory.reference_paths
        if (not context.markets or item.segment_id in market_segment_ids)
        and (
            not context.sources
            or item.source_snapshot_id.value in context.sources
        )
        and (context.reconstructed is None or item.reconstructed is context.reconstructed)
        and (
            not context.transformation_families
            or any(
                transformation.family in context.transformation_families
                for transformation in item.transformations
            )
        )
        and (
            not context.compatibilities
            or item.compatibility.value in context.compatibilities
        )
        and (
            not context.reproducibilities
            or item.reproducibility.value in context.reproducibilities
        )
    )
    paths = tuple(
        item
        for item in eligible_paths
        if (
            not needle
            or needle in " ".join(
                (
                    item.path_id.value,
                    item.segment_id.value,
                    item.expander_version,
                    item.normalization_provenance,
                    item.market_rule_profile_version,
                    *(value.transformation_id for value in item.transformations),
                )
            ).casefold()
        )
    )
    market_path_ids = {
        item.path_id
        for item in inventory.reference_paths
        if not context.markets or item.segment_id in market_segment_ids
        if not context.sources or item.source_snapshot_id.value in context.sources
    }
    scenarios = tuple(
        item
        for item in inventory.market_scenarios
        if (not context.layers or item.layer.value in context.layers)
        and (not context.markets or item.path_id in market_path_ids)
        and (
            not context.sources
            or item.source_snapshot_id.value in context.sources
        )
        and (
            not context.recipe_versions
            or item.recipe_version_id.value in context.recipe_versions
        )
        and (
            not context.transformation_families
            or any(
                transformation.family in context.transformation_families
                for transformation in item.transformations
            )
        )
        and (
            not context.compatibilities
            or item.compatibility.value in context.compatibilities
        )
        and (
            not context.reproducibilities
            or item.reproducibility.value in context.reproducibilities
        )
        and (
            not needle
            or needle in " ".join(
                (
                    item.scenario_id.value,
                    item.path_id.value,
                    item.recipe_version_id.value,
                    item.layer.value,
                    *(value.transformation_id for value in item.transformations),
                )
            ).casefold()
        )
    )
    catalog = replace(
        inventory.transformation_catalog,
        entries=tuple(
            item
            for item in inventory.transformation_catalog.entries
            if (
                not context.transformation_families
                or item.family in context.transformation_families
            )
            and (
                not needle
                or needle in " ".join(
                    (
                        item.transformation_id,
                        item.family,
                        item.implementation_version,
                    )
                ).casefold()
            )
        ),
    )
    return segments, paths, scenarios, catalog


def _contains_identity(
    identity: str | None,
    segments: tuple[HistoricalSegmentEntry, ...],
    paths: tuple[ReferenceMarketPathEntry, ...],
    scenarios: tuple[MarketScenarioEntry, ...],
) -> bool:
    if identity is None:
        return False
    return identity in {
        *(item.segment_id.value for item in segments),
        *(item.path_id.value for item in paths),
        *(item.scenario_id.value for item in scenarios),
    }


def _availability(
    inventory: ScenarioLabInventory,
) -> ScenarioLabApplicationAvailability:
    if any(
        item.integrity is not ScenarioLabIntegrityState.VERIFIED
        for item in inventory.reference_paths
    ):
        return ScenarioLabApplicationAvailability.PARTIAL
    if inventory.historical_segments or inventory.reference_paths or inventory.market_scenarios:
        return ScenarioLabApplicationAvailability.READY
    return ScenarioLabApplicationAvailability.EMPTY


def _is_scenario_lab_invalidation(snapshot: dict[str, object]) -> bool:
    kind = str(snapshot.get("kind") or "").strip().casefold()
    return kind in {
        "campaign-case",
        "historical-segment",
        "market-rule-profile",
        "reference-market-path",
        "scenario-lab",
        "scenario-recipe",
        "scenario-transformation-catalog",
    }


def _default_inventory() -> ScenarioLabInventory:
    observed_at = datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc)
    local_time = datetime(2026, 1, 2, 9, 30)
    segment_id = HistoricalMarketSegmentId("segment-cn-a-2026-01")
    source_id = SourceSnapshotId("snapshot-cn-a-2026-01")
    path_id = ReferenceMarketPathId("f" * 64)
    scenario_id = CampaignCaseId("campaign-case-" + "a" * 24)
    catalog = TransformationCatalogProjection(
        catalog_version="scenario-transformation-catalog.v1",
        entries=(
            TransformationCatalogEntryProjection(
                transformation_id="volatility-scaling.v1",
                family="volatility",
                implementation_version="volatility-scaling.v1",
                parameters=(
                    TransformationParameterProjection(
                        name="multiplier",
                        value_type="decimal",
                        required=True,
                        minimum="0.5",
                        maximum="2",
                        choices=(),
                    ),
                ),
                compatibility_rules=("a-share-cash-equity.v1", "one-transform-per-family"),
                causality_constraints=("point-in-time-inputs-only",),
            ),
        ),
    )
    segment = HistoricalSegmentEntry(
        segment_id=segment_id,
        content_hash="1" * 64,
        source_snapshot_id=source_id,
        source_snapshot_content_hash="0" * 64,
        provenance=HistoricalSegmentProvenance(
            provider="deterministic-fixture",
            dataset="cn-a-five-minute",
            version="2026-01",
            observed_at=observed_at,
        ),
        market="cn-a",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 30),
        label="CN A admitted January segment",
        eligible_instrument_count=2,
        trading_day_count=20,
        bar_count=960,
        admission_state=ScenarioLabAdmissionState.ADMITTED,
        quality_state=ScenarioLabQualityState.PASSED,
        recommendation_tags=("representative",),
        unavailability_reasons=(),
    )
    preview_node = ReferencePathPreviewNode(
        instrument="000001.SZ",
        simulation_time=local_time,
        open="10",
        high="10.1",
        low="9.9",
        close="10.05",
        volume=1000,
        amount="10050",
        reconstructed=True,
    )
    path = ReferenceMarketPathEntry(
        path_id=path_id,
        segment_id=segment_id,
        segment_content_hash=segment.content_hash,
        source_snapshot_id=source_id,
        seed=7,
        expander_version="deterministic-5m-to-30s.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        reconstructed=True,
        reconstruction_notice=(
            "Reconstructed 30-second path from admitted 5-minute bars; not recorded microstructure."
        ),
        numeric_tolerance="1e-9",
        normalization_provenance="canonical-unadjusted-source",
        market_rule_profile_version="a-share-market-rules.v1",
        transformation_catalog_version=catalog.catalog_version,
        transformations=(),
        start_time=local_time,
        end_time=local_time,
        integrity=ScenarioLabIntegrityState.VERIFIED,
        compatibility=ScenarioCompatibilityState.COMPATIBLE,
        reproducibility=ScenarioReproducibilityState.REPRODUCIBLE,
        preview=ReferencePathPreview(
            at_time=local_time,
            eligible_universe=(preview_node.instrument,),
            nodes=(preview_node,),
            node_count=1,
            bounded_node_limit=24,
        ),
        unavailability_reasons=(),
    )
    scenario = MarketScenarioEntry(
        scenario_id=scenario_id,
        layer=MarketScenarioLayer.BASELINE,
        comparison_role=MarketScenarioComparisonRole.CONTROL,
        baseline_scenario_id=None,
        recipe_version_id=ApprovedScenarioRecipeVersionId("recipe-version-baseline-v1"),
        recipe_content_hash="2" * 64,
        path_id=path_id,
        segment_id=segment_id,
        segment_content_hash=segment.content_hash,
        source_snapshot_id=source_id,
        seed=7,
        transformation_catalog_version=catalog.catalog_version,
        transformations=(),
        market_rule_profile_version="a-share-market-rules.v1",
        decision_cadence_minutes=5,
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="3",
            slippage_bps="5",
            max_fill_fraction="1",
            latency_nodes=1,
            allow_partial_fills=True,
        ),
        compatibility=ScenarioCompatibilityState.COMPATIBLE,
        reproducibility=ScenarioReproducibilityState.REPRODUCIBLE,
        execution_resolution=ScenarioExecutionResolutionState.NOT_YET_RESOLVED,
        unavailability_reasons=(
            ScenarioLabUnavailabilityReason(
                code=ScenarioLabUnavailabilityCode.EXECUTION_ASSUMPTIONS_UNRESOLVED,
                summary="Effective execution assumptions are resolved by Issue #83.",
                corrective_guidance=(
                    "Resolve the selected Strategy Under Test and Scenario Set "
                    "assumptions before Diagnostic Task handoff."
                ),
            ),
        ),
    )
    return ScenarioLabInventory(
        historical_segments=(segment,),
        reference_paths=(path,),
        market_scenarios=(scenario,),
        transformation_catalog=catalog,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


__all__ = [
    "DeterministicFakeScenarioLabAdapter",
    "LiveScenarioLabAdapter",
    "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
]
