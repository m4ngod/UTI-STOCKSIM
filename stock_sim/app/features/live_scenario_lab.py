"""Live and deterministic fake Adapters for Scenario Lab 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from time import sleep

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
    ScenarioSetId,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    TaskHandleId,
    TaskPhase,
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
    ApprovedScenarioRecipeVersionProjection,
    ApproveScenarioRecipeCommand,
    ApproveScenarioRecipeResult,
    ComposeFormalScenarioSetCommand,
    ComposeFormalScenarioSetResult,
    CreateAiAssistedScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftResult,
    HistoricalSegmentEntry,
    HistoricalSegmentProvenance,
    FormalScenarioComparisonProjection,
    FormalScenarioSetEligibility,
    FormalScenarioSetProjection,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    MaterializeApprovedScenarioRecipeCommand,
    MaterializeApprovedScenarioRecipeResult,
    MarketScenarioComparisonRole,
    MarketScenarioEntry,
    MarketScenarioLayer,
    MarketScenarioTransformationProjection,
    ReferenceMarketPathEntry,
    ReferenceMarketPathId,
    ReferencePathPreview,
    ReferencePathPreviewNode,
    RequestedExecutionAssumptionsProjection,
    ScenarioCompatibilityState,
    ScenarioExecutionResolutionState,
    ScenarioExecutionConditionProjection,
    ScenarioExecutionAssumptionTarget,
    ScenarioExecutionResolutionId,
    ScenarioExecutionResolutionProjection,
    ScenarioExecutionTargetProjection,
    ScenarioLabApplicationAvailability,
    ScenarioLabApplicationError,
    ScenarioLabApplicationErrorCode,
    ScenarioLabApplicationInventoryResult,
    ScenarioLabApplicationVersion,
    ScenarioLabAdmissionState,
    ScenarioLabActorId,
    ScenarioLabCommandMetadata,
    ScenarioLabCommandReceipt,
    ScenarioLabCommandResult,
    ScenarioLabCommandDisposition,
    ScenarioLabIntegrityState,
    ScenarioLabInventory,
    ScenarioLabQualityState,
    ScenarioLabTaskHandle,
    ScenarioLabTaskIdentity,
    ScenarioLabTaskIdentityKind,
    ScenarioLabTaskOperation,
    ScenarioLabUnavailabilityCode,
    ScenarioLabUnavailabilityReason,
    ScenarioSelectionContextId,
    ScenarioSelectionCaseBindingProjection,
    ScenarioSelectionContextProjection,
    ScenarioSelectionContextStatus,
    ScenarioSelectionStrategyBindingProjection,
    ScenarioReproducibilityState,
    ScenarioMaterializationAttemptId,
    ScenarioRecipeAuthoringMode,
    ScenarioRecipeApprovalAuthorityState,
    ScenarioRecipeApprovalId,
    ScenarioRecipeApprovalProjection,
    ScenarioRecipeDraftProjection,
    ScenarioRecipeAuthoringCapabilitiesProjection,
    ScenarioRecipeCompatibilityObservation,
    ScenarioRecipeCompatibilityState,
    ScenarioRecipeDataPolicy,
    ScenarioRecipeDraftId,
    ScenarioRecipeDraftPayload,
    ScenarioRecipeValidationDependenciesProjection,
    ScenarioRecipeValidationFindingProjection,
    ScenarioRecipeValidationId,
    ScenarioRecipeValidationProjection,
    ScenarioRecipeValidationSeverity,
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
    canonical_scenario_lab_command_content_identity,
)


_DEFAULT_FORMAL_STRATEGY_IDS = (
    StrategyUnderTestId("quentx-live-minute-scenario-native"),
    StrategyUnderTestId("quentx-5.2.3-scenario-native"),
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken


_FAKE_MATERIALIZATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="fake-scenario-materialization",
)


def _schedule_fake_materialization(callback: Callable[[], None]) -> None:
    _FAKE_MATERIALIZATION_EXECUTOR.submit(callback)
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
        executor: Executor | None = None,
    ) -> None:
        self._application = application
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._owns_executor = executor is None
        self._executor_thread_prefix = (
            f"scenario-lab-{id(self):x}" if self._owns_executor else None
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=(
                self._executor_thread_prefix or "scenario-lab-external"
            ),
        )
        self._materialization_refresh_scheduled = False
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
        if blocked is not None:
            return CreateScenarioRecipeDraftResult(receipt=blocked)
        result = self._application.create_recipe_draft(command)
        self._refresh_after_authoring(result.receipt)
        return result

    def author_recipe_with_ai(
        self, command: CreateAiAssistedScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        )
        if blocked is not None:
            return CreateScenarioRecipeDraftResult(receipt=blocked)
        result = self._application.author_recipe_with_ai(command)
        self._refresh_after_authoring(result.receipt)
        return result

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT
        )
        if blocked is not None:
            return ReviseScenarioRecipeDraftResult(receipt=blocked)
        result = self._application.revise_recipe_draft(command)
        self._refresh_after_authoring(result.receipt)
        return result

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT
        )
        if blocked is not None:
            return ValidateScenarioRecipeDraftResult(receipt=blocked)
        result = self._application.validate_recipe_draft(command)
        self._refresh_after_authoring(result.receipt)
        return result

    def _refresh_after_authoring(
        self,
        receipt: ScenarioLabCommandReceipt,
    ) -> None:
        if receipt.disposition is not ScenarioLabCommandDisposition.ACCEPTED:
            return
        with self._lock:
            contexts = self._contexts_to_refresh()
        for context in contexts:
            self.snapshot(context, _track_current=False)
        handle = receipt.task_handle
        if handle is not None and not handle.terminal:
            self._schedule_materialization_refresh()

    def _schedule_materialization_refresh(self) -> None:
        with self._lock:
            if self._closed or self._materialization_refresh_scheduled:
                return
            self._materialization_refresh_scheduled = True
        try:
            self._executor.submit(self._drain_materialization_refreshes)
        except RuntimeError:
            with self._lock:
                self._materialization_refresh_scheduled = False

    def _drain_materialization_refreshes(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    self._materialization_refresh_scheduled = False
                    return
                if (
                    self._connection_phase
                    is not EventBridgeConnectionPhase.CONNECTED
                ):
                    self._materialization_refresh_scheduled = False
                    return
                contexts = self._contexts_to_refresh()
            for context in contexts:
                self.snapshot(context, _track_current=False)
            with self._lock:
                active = any(
                    not handle.terminal
                    for state in self._states.values()
                    for handle in state.task_handles
                )
                if not active:
                    self._materialization_refresh_scheduled = False
                    return
            sleep(0.02)

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.APPROVE_RECIPE
        )
        result = (
            ApproveScenarioRecipeResult(receipt=blocked)
            if blocked is not None
            else self._application.approve_recipe(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        with self._lock:
            return self._materialize_reference_path(command)

    def _materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
        )
        result = (
            MaterializeApprovedScenarioRecipeResult(receipt=blocked)
            if blocked is not None
            else self._application.materialize_reference_path(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        with self._lock:
            return self._retry_materialization(command)

    def _retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.RETRY_MATERIALIZATION
        )
        result = (
            RetryScenarioMaterializationResult(receipt=blocked)
            if blocked is not None
            else self._application.retry_materialization(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult:
        blocked = self._disconnected_receipt(
            command.metadata, ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET
        )
        result = (
            ComposeFormalScenarioSetResult(receipt=blocked)
            if blocked is not None
            else self._application.compose_scenario_set(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult:
        blocked = self._disconnected_receipt(
            command.metadata,
            ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS,
        )
        result = (
            ResolveScenarioExecutionAssumptionsResult(receipt=blocked)
            if blocked is not None
            else self._application.resolve_execution_assumptions(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult:
        blocked = self._disconnected_receipt(
            command.metadata,
            ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET,
        )
        result = (
            SelectFormalScenarioSetResult(receipt=blocked)
            if blocked is not None
            else self._application.select_formal_scenario_set(command)
        )
        self._refresh_after_authoring(result.receipt)
        return result

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
            if metadata.expected_source_generation != self._generation:
                return ScenarioLabCommandReceipt(
                    metadata=metadata,
                    operation=operation,
                    disposition=ScenarioLabCommandDisposition.CONFLICT,
                    message=(
                        "The expected Scenario Lab source generation is stale; "
                        "old-generation commands are quarantined."
                    ),
                    authoritative_revision=self._source_token,
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
            self._materialization_refresh_scheduled = False
        dispose_connection()
        dispose_batch()
        for subscription in subscriptions:
            subscription.mark_disposed()
        if self._owns_executor:
            self._executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

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
            recipe_drafts=(),
            recipe_validations=(),
            approved_recipe_versions=(),
            task_handles=(),
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
        (
            segments,
            paths,
            scenarios,
            catalog,
            drafts,
            validations,
            approved_versions,
            task_handles,
        ) = _filtered_inventory(inventory, context)
        partial = availability is ScenarioLabApplicationAvailability.PARTIAL
        empty = (
            not segments
            and not paths
            and not scenarios
            and not drafts
            and not approved_versions
        )
        focus = context.focus_identity if _contains_identity(
            context.focus_identity,
            segments,
            paths,
            scenarios,
            drafts,
            validations,
            approved_versions,
            task_handles,
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
            recipe_drafts=drafts,
            recipe_validations=validations,
            approved_recipe_versions=approved_versions,
            task_handles=task_handles,
            last_reliable_inventory=inventory,
            capabilities=_authoring_capabilities(inventory),
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
            scenario_sets=inventory.scenario_sets,
            execution_resolutions=inventory.execution_resolutions,
            selection_contexts=inventory.selection_contexts,
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
            drafts: tuple[ScenarioRecipeDraftProjection, ...] = ()
            validations: tuple[ScenarioRecipeValidationProjection, ...] = ()
            approved_versions: tuple[
                ApprovedScenarioRecipeVersionProjection, ...
            ] = ()
            task_handles: tuple[ScenarioLabTaskHandle, ...] = ()
        else:
            (
                segments,
                paths,
                scenarios,
                catalog,
                drafts,
                validations,
                approved_versions,
                task_handles,
            ) = _filtered_inventory(inventory, context)
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
            recipe_drafts=drafts,
            recipe_validations=validations,
            approved_recipe_versions=approved_versions,
            task_handles=task_handles,
            scenario_sets=(
                () if inventory is None else inventory.scenario_sets
            ),
            execution_resolutions=(
                () if inventory is None else inventory.execution_resolutions
            ),
            selection_contexts=(
                () if inventory is None else inventory.selection_contexts
            ),
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
                    dependent_operations=(
                        "create_recipe_draft",
                        "revise_recipe_draft",
                        "validate_recipe_draft",
                        "materialize_reference_path",
                    ),
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
            with self._lock:
                has_active_materialization = any(
                    not handle.terminal
                    for state in self._states.values()
                    for handle in state.task_handles
                )
            if has_active_materialization:
                self._schedule_materialization_refresh()

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
        executor: Executor | None = None,
    ) -> None:
        super().__init__(
            application=application,
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="strategy-diagnostics-v1-scenario-lab",
            event_bridge=event_bridge,
            clock=clock,
            freshness_threshold=freshness_threshold,
            executor=executor,
        )


class _DeterministicFakeScenarioLabApplication:
    def __init__(
        self,
        inventory: ScenarioLabInventory,
        *,
        clock: Callable[[], datetime],
        scripted_results: tuple[ScenarioLabApplicationInventoryResult, ...],
        materialization_scheduler: Callable[[Callable[[], None]], None],
        formal_strategy_ids: tuple[StrategyUnderTestId, ...],
    ) -> None:
        self._clock = clock
        self._materialization_scheduler = materialization_scheduler
        self._lock = RLock()
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
        self._commands: dict[
            str,
            tuple[
                str,
                ScenarioLabTaskOperation,
                ScenarioLabCommandResult,
            ],
        ] = {}
        self._command_identities: dict[str, str] = {}
        self._ai_audits: dict[
            str,
            tuple[ScenarioRecipeDraftPayload, ScenarioLabActorId],
        ] = {}
        self._materialization_failures_remaining = 0
        self._materialization_integrity_failures_remaining = 0
        self._formal_strategy_ids = frozenset(formal_strategy_ids)

    def fail_next_materialization(self) -> None:
        """Inject one deterministic retryable materialization failure."""

        with self._lock:
            self._materialization_failures_remaining += 1

    def fail_next_materialization_integrity(self) -> None:
        """Inject one deterministic terminal artifact integrity failure."""

        with self._lock:
            self._materialization_integrity_failures_remaining += 1

    @property
    def interface_version(self) -> ScenarioLabApplicationVersion:
        from .scenario_lab_application import SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

        return SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult:
        with self._lock:
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
        operation = ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return CreateScenarioRecipeDraftResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return CreateScenarioRecipeDraftResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, CreateScenarioRecipeDraftResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return CreateScenarioRecipeDraftResult(receipt=source_conflict)
        if command.authoring_mode is ScenarioRecipeAuthoringMode.AI_ASSISTED:
            audit = self._ai_audits.get(command.assistant_attempt_id or "")
            if audit != (command.payload, command.author_id):
                return CreateScenarioRecipeDraftResult(
                    receipt=self._rejected_receipt(
                        command.metadata,
                        operation,
                        (
                            "The typed Draft does not match the audited AI "
                            "result and author identity."
                        ),
                    )
                )
        digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        draft = ScenarioRecipeDraftProjection(
            draft_id=ScenarioRecipeDraftId("recipe_draft_" + digest[:24]),
            recipe_id="recipe_" + digest[24:48],
            revision=1,
            payload=command.payload,
            payload_hash=_fake_payload_hash(command.payload),
            author_id=command.author_id,
            created_at=_aware(self._clock()),
            predecessor_draft_id=None,
            based_on_recipe_version_id=None,
            authoring_mode=command.authoring_mode,
            assistant_attempt_id=command.assistant_attempt_id,
        )
        result = CreateScenarioRecipeDraftResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            payload_hash=draft.payload_hash,
            draft=draft,
        )
        self._remember(command.metadata, operation, result)
        inventory = self._inventory()
        self._set_inventory(
            replace(inventory, recipe_drafts=(*inventory.recipe_drafts, draft))
        )
        return result

    def author_recipe_with_ai(
        self, command: CreateAiAssistedScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return CreateScenarioRecipeDraftResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return CreateScenarioRecipeDraftResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, CreateScenarioRecipeDraftResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return CreateScenarioRecipeDraftResult(receipt=source_conflict)
        inventory = self._inventory()
        capabilities = inventory.authoring_capabilities
        if not capabilities.ai_authoring_available:
            return CreateScenarioRecipeDraftResult(
                receipt=self._receipt(command.metadata, operation)
            )
        segment = next(
            (
                item
                for item in inventory.historical_segments
                if item.admission_state is ScenarioLabAdmissionState.ADMITTED
                and item.quality_state is ScenarioLabQualityState.PASSED
            ),
            None,
        )
        if segment is None:
            return CreateScenarioRecipeDraftResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "No admitted Historical Market Segment is available.",
                )
            )
        digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        payload = ScenarioRecipeDraftPayload(
            name=command.intent[:120],
            historical_segment_id=segment.segment_id,
            transformations=(),
            requested_execution_assumptions=(
                RequestedExecutionAssumptionsProjection(
                    commission_bps="3",
                    slippage_bps="0",
                    max_fill_fraction="1",
                    latency_nodes=0,
                    allow_partial_fills=True,
                )
            ),
            decision_cadence_minutes=30,
            materialization_seed=80,
            data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
            market_rule_profile_version="a-share-cash-equity.v1",
        )
        draft = ScenarioRecipeDraftProjection(
            draft_id=ScenarioRecipeDraftId("recipe_draft_" + digest[:24]),
            recipe_id="recipe_" + digest[24:48],
            revision=1,
            payload=payload,
            payload_hash=_fake_payload_hash(payload),
            author_id=command.author_id,
            created_at=_aware(self._clock()),
            predecessor_draft_id=None,
            based_on_recipe_version_id=None,
            authoring_mode=ScenarioRecipeAuthoringMode.AI_ASSISTED,
            assistant_attempt_id="fake_ai_recipe_attempt_" + digest[:24],
        )
        if draft.assistant_attempt_id is None:  # pragma: no cover - fixed above.
            raise RuntimeError("Fake AI Draft requires an attempt identity")
        self._ai_audits[draft.assistant_attempt_id] = (
            draft.payload,
            draft.author_id,
        )
        result = CreateScenarioRecipeDraftResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            payload_hash=draft.payload_hash,
            draft=draft,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(inventory, recipe_drafts=(*inventory.recipe_drafts, draft))
        )
        return result

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ReviseScenarioRecipeDraftResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return ReviseScenarioRecipeDraftResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, ReviseScenarioRecipeDraftResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return ReviseScenarioRecipeDraftResult(receipt=source_conflict)
        inventory = self._inventory()
        predecessor = next(
            (
                item
                for item in inventory.recipe_drafts
                if item.draft_id == command.predecessor_draft_id
            ),
            None,
        )
        if predecessor is None:
            return ReviseScenarioRecipeDraftResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The predecessor Scenario Recipe Draft is unavailable.",
                )
            )
        current_revision = max(
            item.revision
            for item in inventory.recipe_drafts
            if item.recipe_id == predecessor.recipe_id
        )
        if (
            predecessor.revision != current_revision
            or command.expected_draft_revision != current_revision
        ):
            return ReviseScenarioRecipeDraftResult(
                receipt=self._conflict_receipt(
                    command.metadata,
                    operation,
                    "The expected Scenario Recipe Draft revision is stale.",
                ),
                authoritative_draft_revision=current_revision,
            )
        if command.based_on_recipe_version_id is not None:
            based_on_version = next(
                (
                    item
                    for item in inventory.approved_recipe_versions
                    if item.recipe_version_id
                    == command.based_on_recipe_version_id
                ),
                None,
            )
            if (
                based_on_version is None
                or based_on_version.recipe_id != predecessor.recipe_id
                or (
                    based_on_version.approval.draft_id
                    != predecessor.draft_id
                    and predecessor.based_on_recipe_version_id
                    != based_on_version.recipe_version_id
                )
            ):
                return ReviseScenarioRecipeDraftResult(
                    receipt=self._rejected_receipt(
                        command.metadata,
                        operation,
                        (
                            "The based-on Approved Recipe Version must exist and "
                            "belong to the exact predecessor Recipe Draft."
                        ),
                    ),
                    authoritative_draft_revision=current_revision,
                )
        digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        draft = ScenarioRecipeDraftProjection(
            draft_id=ScenarioRecipeDraftId("recipe_draft_" + digest[:24]),
            recipe_id=predecessor.recipe_id,
            revision=current_revision + 1,
            payload=command.payload,
            payload_hash=_fake_payload_hash(command.payload),
            author_id=command.author_id,
            created_at=_aware(self._clock()),
            predecessor_draft_id=predecessor.draft_id,
            based_on_recipe_version_id=(
                command.based_on_recipe_version_id
                or predecessor.based_on_recipe_version_id
            ),
            authoring_mode=ScenarioRecipeAuthoringMode.MANUAL,
            assistant_attempt_id=None,
        )
        result = ReviseScenarioRecipeDraftResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            payload_hash=draft.payload_hash,
            draft=draft,
            authoritative_draft_revision=draft.revision,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(inventory, recipe_drafts=(*inventory.recipe_drafts, draft))
        )
        return result

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ValidateScenarioRecipeDraftResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return ValidateScenarioRecipeDraftResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, ValidateScenarioRecipeDraftResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return ValidateScenarioRecipeDraftResult(receipt=source_conflict)
        inventory = self._inventory()
        draft = next(
            (
                item
                for item in inventory.recipe_drafts
                if item.draft_id == command.draft_id
            ),
            None,
        )
        if draft is None:
            return ValidateScenarioRecipeDraftResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The Scenario Recipe Draft is unavailable.",
                )
            )
        current_revision = max(
            item.revision
            for item in inventory.recipe_drafts
            if item.recipe_id == draft.recipe_id
        )
        if (
            draft.revision != current_revision
            or draft.revision != command.expected_draft_revision
            or draft.payload_hash != command.expected_payload_hash
        ):
            return ValidateScenarioRecipeDraftResult(
                receipt=self._conflict_receipt(
                    command.metadata,
                    operation,
                    "The expected Scenario Recipe Draft facts are stale.",
                ),
                authoritative_draft_revision=current_revision,
            )
        segment = next(
            (
                item
                for item in inventory.historical_segments
                if item.segment_id == draft.payload.historical_segment_id
            ),
            None,
        )
        if segment is None:
            return ValidateScenarioRecipeDraftResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The exact Historical Market Segment dependency is not admitted and cannot be bound for validation.",
                ),
                authoritative_draft_revision=current_revision,
            )
        findings = _fake_recipe_validation_findings(
            draft,
            inventory.transformation_catalog,
        )
        dependencies = _fake_recipe_validation_dependencies(
            draft,
            inventory,
            findings,
        )
        if dependencies is None:
            raise RuntimeError(
                "Deterministic fake admitted dependency disappeared during validation"
            )
        valid = not findings
        digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        validation = ScenarioRecipeValidationProjection(
            validation_id=ScenarioRecipeValidationId(
                "recipe_validation_" + digest[:24]
            ),
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            payload_hash=draft.payload_hash,
            is_valid=valid,
            findings=findings,
            dependencies=dependencies,
            recipe_content_hash=(
                hashlib.sha256(repr(draft.payload).encode("utf-8")).hexdigest()
                if valid
                else None
            ),
            validated_at=_aware(self._clock()),
        )
        result = ValidateScenarioRecipeDraftResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            validation_id=validation.validation_id,
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            validation=validation,
            authoritative_draft_revision=draft.revision,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                recipe_validations=(
                    *inventory.recipe_validations,
                    validation,
                ),
            )
        )
        return result

    def _content_identity_rejection(
        self,
        command: (
            CreateAiAssistedScenarioRecipeDraftCommand
            | CreateScenarioRecipeDraftCommand
            | ReviseScenarioRecipeDraftCommand
            | ValidateScenarioRecipeDraftCommand
            | ApproveScenarioRecipeCommand
            | MaterializeApprovedScenarioRecipeCommand
            | RetryScenarioMaterializationCommand
            | ComposeFormalScenarioSetCommand
            | ResolveScenarioExecutionAssumptionsCommand
            | SelectFormalScenarioSetCommand
        ),
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt | None:
        if (
            canonical_scenario_lab_command_content_identity(command)
            == command.metadata.canonical_content_identity
        ):
            return None
        return self._rejected_receipt(
            command.metadata,
            operation,
            (
                "The canonical command content identity does not match the "
                "typed Scenario Lab command body."
            ),
        )

    def _inventory(self) -> ScenarioLabInventory:
        if self._result.inventory is None:
            raise RuntimeError("Deterministic Scenario Lab inventory is unavailable")
        return self._result.inventory

    def _set_inventory(self, inventory: ScenarioLabInventory) -> None:
        inventory = replace(
            inventory,
            approved_recipe_versions=tuple(
                _reconcile_fake_recipe_approval(item, inventory)
                for item in inventory.approved_recipe_versions
            ),
        )
        inventory = replace(
            inventory,
            selection_contexts=_reconcile_fake_selection_contexts(
                inventory,
                formal_strategy_ids=self._formal_strategy_ids,
            ),
        )
        self._result = ScenarioLabApplicationInventoryResult(
            availability=_availability(inventory),
            inventory=inventory,
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(inventory).encode("utf-8")).hexdigest()
            ),
            observed_at=_aware(self._clock()),
            error=None,
        )

    def _replay(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> tuple[ScenarioLabCommandResult | None, ScenarioLabCommandReceipt | None]:
        existing = self._commands.get(metadata.idempotency_identity.value)
        if existing is None:
            claimed_idempotency = self._command_identities.get(
                metadata.command_id.value
            )
            if claimed_idempotency is None:
                return None, None
            return None, self._conflict_receipt(
                metadata,
                operation,
                (
                    "The command identity is already bound to a different "
                    "idempotency identity."
                ),
            )
        content_identity, existing_operation, result = existing
        if (
            content_identity != metadata.canonical_content_identity.value
            or existing_operation is not operation
        ):
            return None, self._conflict_receipt(
                metadata,
                operation,
                "The idempotency identity is already bound to different canonical content.",
            )
        return result, None

    def _remember(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
        result: ScenarioLabCommandResult,
    ) -> None:
        self._commands[metadata.idempotency_identity.value] = (
            metadata.canonical_content_identity.value,
            operation,
            result,
        )
        self._command_identities[
            metadata.command_id.value
        ] = metadata.idempotency_identity.value

    def _source_conflict(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt | None:
        if metadata.expected_source_revision == self._result.source_token:
            return None
        return self._conflict_receipt(
            metadata,
            operation,
            "The expected Scenario Lab source revision is stale.",
        )

    def _accepted_receipt(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt:
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.ACCEPTED,
            message="Scenario Lab command completed.",
            authoritative_revision=metadata.expected_source_revision,
            task_handle=None,
        )

    def _conflict_receipt(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
        message: str,
    ) -> ScenarioLabCommandReceipt:
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.CONFLICT,
            message=message,
            authoritative_revision=self._result.source_token,
            task_handle=None,
        )

    def _rejected_receipt(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
        message: str,
    ) -> ScenarioLabCommandReceipt:
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.REJECTED,
            message=message,
            authoritative_revision=self._result.source_token,
            task_handle=None,
        )

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        operation = ScenarioLabTaskOperation.APPROVE_RECIPE
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ApproveScenarioRecipeResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return ApproveScenarioRecipeResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, ApproveScenarioRecipeResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            if replay.approved_version is None:
                return replay
            current_version = next(
                (
                    item
                    for item in self._inventory().approved_recipe_versions
                    if item.recipe_version_id
                    == replay.approved_version.recipe_version_id
                ),
                None,
            )
            return (
                replay
                if current_version is None
                else replace(replay, approved_version=current_version)
            )
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return ApproveScenarioRecipeResult(receipt=source_conflict)
        inventory = self._inventory()
        draft = next(
            (
                item
                for item in inventory.recipe_drafts
                if item.draft_id == command.draft_id
            ),
            None,
        )
        if draft is None:
            return ApproveScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The Scenario Recipe Draft is unavailable.",
                )
            )
        current_revision = max(
            item.revision
            for item in inventory.recipe_drafts
            if item.recipe_id == draft.recipe_id
        )
        if (
            draft.revision != current_revision
            or draft.revision != command.expected_draft_revision
            or draft.payload_hash != command.expected_payload_hash
        ):
            return ApproveScenarioRecipeResult(
                receipt=self._conflict_receipt(
                    command.metadata,
                    operation,
                    "The expected Scenario Recipe Draft facts are stale.",
                ),
                authoritative_draft_revision=current_revision,
            )
        validation = next(
            (
                item
                for item in inventory.recipe_validations
                if item.validation_id == command.validation_id
            ),
            None,
        )
        if (
            validation is None
            or not validation.is_valid
            or validation.draft_id != draft.draft_id
            or validation.draft_revision != draft.revision
            or validation.payload_hash != draft.payload_hash
            or validation.recipe_content_hash is None
        ):
            return ApproveScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "Approval requires the exact successful validation for "
                        "the current immutable Draft revision and payload hash."
                    ),
                ),
                authoritative_draft_revision=current_revision,
            )
        if any(
            item.approval.draft_id == draft.draft_id
            for item in inventory.approved_recipe_versions
        ):
            return ApproveScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The Scenario Recipe Draft already has an immutable approval.",
                ),
                authoritative_draft_revision=current_revision,
            )
        current_dependencies = _fake_recipe_validation_dependencies(
            draft,
            inventory,
            _fake_recipe_validation_findings(
                draft,
                inventory.transformation_catalog,
            ),
        )
        if current_dependencies != validation.dependencies:
            return ApproveScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "The exact validation dependencies changed; reread and "
                        "revalidate before approval."
                    ),
                ),
                authoritative_draft_revision=current_revision,
            )
        digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        version_number = 1 + max(
            (
                item.version_number
                for item in inventory.approved_recipe_versions
                if item.recipe_id == draft.recipe_id
            ),
            default=0,
        )
        version = ApprovedScenarioRecipeVersionProjection(
            recipe_version_id=ApprovedScenarioRecipeVersionId(
                "recipe_version_" + digest
            ),
            recipe_id=draft.recipe_id,
            version_number=version_number,
            content_hash=validation.recipe_content_hash,
            payload=draft.payload,
            author_id=draft.author_id,
            approval=ScenarioRecipeApprovalProjection(
                approval_id=ScenarioRecipeApprovalId(
                    "recipe_approval_" + digest
                ),
                draft_id=draft.draft_id,
                draft_revision=draft.revision,
                payload_hash=draft.payload_hash,
                validation_id=validation.validation_id,
                recipe_content_hash=validation.recipe_content_hash,
                actor_id=command.actor_id,
                approved_at=_aware(self._clock()),
                dependencies=validation.dependencies,
            ),
            based_on_recipe_version_id=draft.based_on_recipe_version_id,
            authority_state=ScenarioRecipeApprovalAuthorityState.CURRENT,
            authority_reasons=(),
            can_materialize=True,
        )
        result = ApproveScenarioRecipeResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            recipe_version_id=version.recipe_version_id,
            recipe_content_hash=version.content_hash,
            approved_version=version,
            authoritative_draft_revision=draft.revision,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                approved_recipe_versions=(
                    *inventory.approved_recipe_versions,
                    version,
                ),
            )
        )
        return result

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        with self._lock:
            return self._materialize_reference_path_locked(command)

    def _materialize_reference_path_locked(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        operation = ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return MaterializeApprovedScenarioRecipeResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return MaterializeApprovedScenarioRecipeResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, MaterializeApprovedScenarioRecipeResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return MaterializeApprovedScenarioRecipeResult(
                receipt=source_conflict
            )
        inventory = self._inventory()
        version = next(
            (
                item
                for item in inventory.approved_recipe_versions
                if item.recipe_version_id == command.recipe_version_id
            ),
            None,
        )
        if version is None or not version.can_materialize:
            return MaterializeApprovedScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "Materialization requires an exact current compatible "
                        "Approved Scenario Recipe dependency binding."
                    ),
                )
            )
        if version.content_hash != command.expected_recipe_content_hash:
            return MaterializeApprovedScenarioRecipeResult(
                receipt=self._conflict_receipt(
                    command.metadata,
                    operation,
                    "The expected Approved Scenario Recipe content hash is stale.",
                )
            )
        dependencies = version.approval.dependencies
        if dependencies is None:
            return MaterializeApprovedScenarioRecipeResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "The exact approval dependency binding is unavailable.",
                )
            )
        command_digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        attempt_id = ScenarioMaterializationAttemptId(
            "scenario_materialization_attempt_" + command_digest
        )
        task_handle_id = TaskHandleId("scenario_task_handle_" + command_digest)
        outcome = self._claim_fake_materialization_outcome()
        handle = self._queued_materialization_handle(
            version=version,
            operation=operation,
            attempt_id=attempt_id,
            task_handle_id=task_handle_id,
            predecessor_task_handle_id=None,
        )
        result = MaterializeApprovedScenarioRecipeResult(
            receipt=replace(
                self._accepted_receipt(command.metadata, operation),
                message="Scenario materialization was durably accepted and queued.",
                task_handle=handle,
            ),
            attempt_id=attempt_id,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                task_handles=(*inventory.task_handles, handle),
            )
        )
        self._schedule_fake_materialization(
            metadata=command.metadata,
            operation=operation,
            version_id=version.recipe_version_id,
            attempt_id=attempt_id,
            task_handle_id=task_handle_id,
            predecessor_task_handle_id=None,
            outcome=outcome,
        )
        return result

    def _claim_fake_materialization_outcome(self) -> str:
        if self._materialization_integrity_failures_remaining:
            self._materialization_integrity_failures_remaining -= 1
            return "integrity_failure"
        if self._materialization_failures_remaining:
            self._materialization_failures_remaining -= 1
            return "retryable_failure"
        return "completed"

    def _queued_materialization_handle(
        self,
        *,
        version: ApprovedScenarioRecipeVersionProjection,
        operation: ScenarioLabTaskOperation,
        attempt_id: ScenarioMaterializationAttemptId,
        task_handle_id: TaskHandleId,
        predecessor_task_handle_id: TaskHandleId | None,
    ) -> ScenarioLabTaskHandle:
        return ScenarioLabTaskHandle(
            identity=task_handle_id,
            attempt_identity=attempt_id,
            operation=operation,
            target_identity=ScenarioLabTaskIdentity(
                kind=ScenarioLabTaskIdentityKind.APPROVED_RECIPE_VERSION,
                value=version.recipe_version_id.value,
            ),
            phase=TaskPhase.QUEUED,
            progress=0.0,
            result_identity=None,
            error=None,
            cancelable=False,
            retryable=False,
            terminal=False,
            predecessor_task_handle_id=predecessor_task_handle_id,
        )

    def _schedule_fake_materialization(
        self,
        *,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
        version_id: ApprovedScenarioRecipeVersionId,
        attempt_id: ScenarioMaterializationAttemptId,
        task_handle_id: TaskHandleId,
        predecessor_task_handle_id: TaskHandleId | None,
        outcome: str,
    ) -> None:
        self._materialization_scheduler(
            lambda: self._complete_fake_materialization(
                metadata=metadata,
                operation=operation,
                version_id=version_id,
                attempt_id=attempt_id,
                task_handle_id=task_handle_id,
                predecessor_task_handle_id=predecessor_task_handle_id,
                outcome=outcome,
            )
        )

    def _complete_fake_materialization(
        self,
        *,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
        version_id: ApprovedScenarioRecipeVersionId,
        attempt_id: ScenarioMaterializationAttemptId,
        task_handle_id: TaskHandleId,
        predecessor_task_handle_id: TaskHandleId | None,
        outcome: str,
    ) -> None:
        with self._lock:
            inventory = self._inventory()
            version = next(
                item
                for item in inventory.approved_recipe_versions
                if item.recipe_version_id == version_id
            )
            current = next(
                item
                for item in inventory.task_handles
                if item.identity == task_handle_id
            )
            running = replace(
                current,
                phase=TaskPhase.RUNNING,
                progress=0.25,
            )
            self._set_inventory(
                replace(
                    inventory,
                    task_handles=tuple(
                        running if item.identity == task_handle_id else item
                        for item in inventory.task_handles
                    ),
                )
            )
            if outcome != "completed":
                integrity_failure = outcome == "integrity_failure"
                terminal = self._failed_materialization_handle(
                    version=version,
                    operation=operation,
                    attempt_id=attempt_id,
                    task_handle_id=task_handle_id,
                    predecessor_task_handle_id=predecessor_task_handle_id,
                    error_code=(
                        ScenarioLabApplicationErrorCode.PATH_INTEGRITY_FAILED
                        if integrity_failure
                        else ScenarioLabApplicationErrorCode.MATERIALIZATION_FAILED
                    ),
                    error_message=(
                        "Deterministic artifact identity collision fixture."
                        if integrity_failure
                        else "Deterministic materializer failure fixture."
                    ),
                    retryable=not integrity_failure,
                )
                terminal_result: ScenarioLabCommandResult = (
                    MaterializeApprovedScenarioRecipeResult(
                        receipt=replace(
                            self._accepted_receipt(metadata, operation),
                            message="Reference Market Path materialization failed.",
                            task_handle=terminal,
                        ),
                        attempt_id=attempt_id,
                    )
                    if operation
                    is ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
                    else RetryScenarioMaterializationResult(
                        receipt=replace(
                            self._accepted_receipt(metadata, operation),
                            message="Reference Market Path materialization failed.",
                            task_handle=terminal,
                        ),
                        attempt_id=attempt_id,
                    )
                )
                current_inventory = self._inventory()
                self._set_inventory(
                    replace(
                        current_inventory,
                        task_handles=tuple(
                            terminal if item.identity == task_handle_id else item
                            for item in current_inventory.task_handles
                        ),
                    )
                )
                self._remember(metadata, operation, terminal_result)
                return
            current_inventory = self._inventory()
            path, scenario, terminal = self._completed_materialization(
                inventory=current_inventory,
                version=version,
                operation=operation,
                attempt_id=attempt_id,
                task_handle_id=task_handle_id,
                predecessor_task_handle_id=predecessor_task_handle_id,
            )
            terminal_result = (
                MaterializeApprovedScenarioRecipeResult(
                    receipt=replace(
                        self._accepted_receipt(metadata, operation),
                        message="Reference Market Path materialization completed.",
                        task_handle=terminal,
                    ),
                    path_id=path.path_id,
                    attempt_id=attempt_id,
                )
                if operation
                is ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH
                else RetryScenarioMaterializationResult(
                    receipt=replace(
                        self._accepted_receipt(metadata, operation),
                        message="Reference Market Path materialization completed.",
                        task_handle=terminal,
                    ),
                    path_id=path.path_id,
                    attempt_id=attempt_id,
                )
            )
            self._set_inventory(
                replace(
                    current_inventory,
                    reference_paths=(
                        current_inventory.reference_paths
                        if path.path_id
                        in {item.path_id for item in current_inventory.reference_paths}
                        else (*current_inventory.reference_paths, path)
                    ),
                    market_scenarios=(
                        current_inventory.market_scenarios
                        if path.path_id
                        in {item.path_id for item in current_inventory.market_scenarios}
                        else (*current_inventory.market_scenarios, scenario)
                    ),
                    task_handles=tuple(
                        terminal if item.identity == task_handle_id else item
                        for item in current_inventory.task_handles
                    ),
                )
            )
            self._remember(metadata, operation, terminal_result)

    def _failed_materialization_handle(
        self,
        *,
        version: ApprovedScenarioRecipeVersionProjection,
        operation: ScenarioLabTaskOperation,
        attempt_id: ScenarioMaterializationAttemptId,
        task_handle_id: TaskHandleId,
        predecessor_task_handle_id: TaskHandleId | None,
        error_code: ScenarioLabApplicationErrorCode,
        error_message: str,
        retryable: bool,
    ) -> ScenarioLabTaskHandle:
        return ScenarioLabTaskHandle(
            identity=task_handle_id,
            attempt_identity=attempt_id,
            operation=operation,
            target_identity=ScenarioLabTaskIdentity(
                kind=ScenarioLabTaskIdentityKind.APPROVED_RECIPE_VERSION,
                value=version.recipe_version_id.value,
            ),
            phase=TaskPhase.FAILED,
            progress=1.0,
            result_identity=None,
            error=ScenarioLabApplicationError(
                code=error_code,
                message=error_message,
                retryable=retryable,
            ),
            cancelable=False,
            retryable=retryable,
            terminal=True,
            predecessor_task_handle_id=predecessor_task_handle_id,
        )

    def _completed_materialization(
        self,
        *,
        inventory: ScenarioLabInventory,
        version: ApprovedScenarioRecipeVersionProjection,
        operation: ScenarioLabTaskOperation,
        attempt_id: ScenarioMaterializationAttemptId,
        task_handle_id: TaskHandleId,
        predecessor_task_handle_id: TaskHandleId | None,
    ) -> tuple[
        ReferenceMarketPathEntry,
        MarketScenarioEntry,
        ScenarioLabTaskHandle,
    ]:
        dependencies = version.approval.dependencies
        if dependencies is None:
            raise RuntimeError("Exact approved Recipe dependency binding disappeared")
        digest = hashlib.sha256(
            ("reference-path|" + version.content_hash).encode("utf-8")
        ).hexdigest()
        path_id = ReferenceMarketPathId(digest)
        handle = ScenarioLabTaskHandle(
            identity=task_handle_id,
            attempt_identity=attempt_id,
            operation=operation,
            target_identity=ScenarioLabTaskIdentity(
                kind=ScenarioLabTaskIdentityKind.APPROVED_RECIPE_VERSION,
                value=version.recipe_version_id.value,
            ),
            phase=TaskPhase.COMPLETED,
            progress=1.0,
            result_identity=ScenarioLabTaskIdentity(
                kind=ScenarioLabTaskIdentityKind.REFERENCE_MARKET_PATH,
                value=path_id.value,
            ),
            error=None,
            cancelable=False,
            retryable=False,
            terminal=True,
            predecessor_task_handle_id=predecessor_task_handle_id,
        )
        catalog = {
            item.transformation_id: item
            for item in inventory.transformation_catalog.entries
        }
        applied = tuple(
            AppliedTransformationProjection(
                transformation_id=item.transformation_id,
                family=catalog[item.transformation_id].family,
                catalog_version=inventory.transformation_catalog.catalog_version,
                implementation_version=(
                    catalog[item.transformation_id].implementation_version
                ),
                parameters=tuple(
                    (parameter.name, str(parameter.value))
                    for parameter in item.parameters
                ),
            )
            for item in version.payload.transformations
        )
        path = replace(
            inventory.reference_paths[0],
            path_id=path_id,
            segment_id=dependencies.historical_segment_id,
            segment_content_hash=dependencies.historical_segment_content_hash,
            source_snapshot_id=dependencies.source_snapshot_id,
            seed=version.payload.materialization_seed,
            market_rule_profile_version=(
                dependencies.market_rule_profile_version
            ),
            transformation_catalog_version=(
                dependencies.transformation_catalog_version
            ),
            transformations=applied,
        )
        scenario_transformations = tuple(
            MarketScenarioTransformationProjection(
                transformation_id=item.transformation_id,
                family=item.family,
                implementation_version=item.implementation_version,
                parameters=item.parameters,
            )
            for item in applied
        )
        transformation_count = len(scenario_transformations)
        scenario = replace(
            inventory.market_scenarios[0],
            scenario_id=CampaignCaseId("campaign-case-" + digest[:24]),
            layer=(
                MarketScenarioLayer.BASELINE
                if transformation_count == 0
                else MarketScenarioLayer.ISOLATED_SENSITIVITY
                if transformation_count == 1
                else MarketScenarioLayer.COMPOUND
            ),
            comparison_role=(
                MarketScenarioComparisonRole.CONTROL
                if transformation_count == 0
                else MarketScenarioComparisonRole.COMPARE_TO_BASELINE
            ),
            baseline_scenario_id=(
                None
                if transformation_count == 0
                else inventory.market_scenarios[0].scenario_id
            ),
            recipe_version_id=version.recipe_version_id,
            recipe_content_hash=version.content_hash,
            path_id=path_id,
            segment_id=dependencies.historical_segment_id,
            segment_content_hash=dependencies.historical_segment_content_hash,
            source_snapshot_id=dependencies.source_snapshot_id,
            seed=version.payload.materialization_seed,
            transformation_catalog_version=(
                dependencies.transformation_catalog_version
            ),
            transformations=scenario_transformations,
            market_rule_profile_version=(
                dependencies.market_rule_profile_version
            ),
            decision_cadence_minutes=version.payload.decision_cadence_minutes,
            requested_execution_assumptions=(
                version.payload.requested_execution_assumptions
            ),
        )
        return path, scenario, handle

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        with self._lock:
            return self._retry_materialization_locked(command)

    def _retry_materialization_locked(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        operation = ScenarioLabTaskOperation.RETRY_MATERIALIZATION
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return RetryScenarioMaterializationResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return RetryScenarioMaterializationResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, RetryScenarioMaterializationResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return RetryScenarioMaterializationResult(receipt=source_conflict)
        inventory = self._inventory()
        predecessor = next(
            (
                item
                for item in inventory.task_handles
                if item.identity == command.predecessor_task_handle_id
                and item.attempt_identity == command.predecessor_attempt_id
            ),
            None,
        )
        if (
            predecessor is None
            or predecessor.phase is not TaskPhase.FAILED
            or not predecessor.retryable
            or predecessor.target_identity.kind
            is not ScenarioLabTaskIdentityKind.APPROVED_RECIPE_VERSION
        ):
            return RetryScenarioMaterializationResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "Retry requires one exact retryable failed materialization "
                        "attempt and TaskHandle."
                    ),
                )
            )
        version = next(
            (
                item
                for item in inventory.approved_recipe_versions
                if item.recipe_version_id.value
                == predecessor.target_identity.value
            ),
            None,
        )
        if version is None or not version.can_materialize:
            return RetryScenarioMaterializationResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "The Approved Scenario Recipe dependencies are no longer "
                        "eligible for retry."
                    ),
                )
            )
        command_digest = hashlib.sha256(
            command.metadata.command_id.value.encode("utf-8")
        ).hexdigest()
        attempt_id = ScenarioMaterializationAttemptId(
            "scenario_materialization_attempt_" + command_digest
        )
        task_handle_id = TaskHandleId("scenario_task_handle_" + command_digest)
        outcome = self._claim_fake_materialization_outcome()
        handle = self._queued_materialization_handle(
            version=version,
            operation=operation,
            attempt_id=attempt_id,
            task_handle_id=task_handle_id,
            predecessor_task_handle_id=predecessor.identity,
        )
        result = RetryScenarioMaterializationResult(
            receipt=replace(
                self._accepted_receipt(command.metadata, operation),
                message="Scenario materialization retry was accepted and queued.",
                task_handle=handle,
            ),
            attempt_id=attempt_id,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                task_handles=(*inventory.task_handles, handle),
            )
        )
        self._schedule_fake_materialization(
            metadata=command.metadata,
            operation=operation,
            version_id=version.recipe_version_id,
            attempt_id=attempt_id,
            task_handle_id=task_handle_id,
            predecessor_task_handle_id=predecessor.identity,
            outcome=outcome,
        )
        return result

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult:
        operation = ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ComposeFormalScenarioSetResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return ComposeFormalScenarioSetResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, ComposeFormalScenarioSetResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return ComposeFormalScenarioSetResult(receipt=source_conflict)
        inventory = self._inventory()
        indexed = {item.scenario_id: item for item in inventory.market_scenarios}
        selected_ids = (
            command.baseline_case_id,
            *command.isolated_case_ids,
            *command.compound_case_ids,
        )
        if any(identity not in indexed for identity in selected_ids):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "A selected Campaign Case is no longer authoritative.",
                )
            )
        baseline = indexed[command.baseline_case_id]
        isolated = tuple(indexed[item] for item in command.isolated_case_ids)
        compounds = tuple(indexed[item] for item in command.compound_case_ids)
        if baseline.layer is not MarketScenarioLayer.BASELINE:
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Baseline Scenario Set requires one untransformed case.",
                )
            )
        if any(item.layer is not MarketScenarioLayer.ISOLATED_SENSITIVITY for item in isolated):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Isolated Sensitivity cases require one transformation family.",
                )
            )
        if any(item.layer is not MarketScenarioLayer.COMPOUND for item in compounds):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Compound Scenario Set requires multiple transformation families.",
                )
            )
        comparable_fields = (
            "segment_id",
            "segment_content_hash",
            "source_snapshot_id",
            "seed",
            "transformation_catalog_version",
            "market_rule_profile_version",
            "decision_cadence_minutes",
            "requested_execution_assumptions",
        )
        cases = (baseline, *isolated, *compounds)
        paths = {item.path_id: item for item in inventory.reference_paths}
        if any(item.path_id not in paths for item in cases):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "A selected Reference Market Path is no longer authoritative.",
                )
            )
        comparable_path_fields = (
            "expander_version",
            "source_resolution",
            "runtime_resolution",
            "numeric_tolerance",
            "normalization_provenance",
        )
        if any(
            getattr(item, field) != getattr(baseline, field)
            for item in cases[1:]
            for field in comparable_fields
        ) or any(
            getattr(paths[item.path_id], field)
            != getattr(paths[baseline.path_id], field)
            for item in cases[1:]
            for field in comparable_path_fields
        ):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Formal Scenario Set requires comparable pinned inputs.",
                )
            )
        families = (
            "trend-regime",
            "volatility",
            "shock-recovery",
            "market-structure",
            "liquidity",
            "execution-stress",
        )
        selected_families = {
            item.transformations[0].family for item in isolated
        }
        if selected_families - set(families):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Isolated Sensitivity case uses an unsupported family.",
                )
            )
        comparable_authority = tuple(
            item
            for item in inventory.market_scenarios
            if item.path_id in paths
            and all(
                getattr(item, field) == getattr(baseline, field)
                for field in comparable_fields
            )
            and all(
                getattr(paths[item.path_id], field)
                == getattr(paths[baseline.path_id], field)
                for field in comparable_path_fields
            )
        )
        authoritative_isolated = tuple(
            item
            for item in comparable_authority
            if item.layer is MarketScenarioLayer.ISOLATED_SENSITIVITY
        )
        authoritative_compounds = tuple(
            item
            for item in comparable_authority
            if item.layer is MarketScenarioLayer.COMPOUND
        )
        if any(
            item.transformations[0].family not in families
            for item in authoritative_isolated
        ):
            return ComposeFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Authoritative Isolated Sensitivity family is unsupported.",
                )
            )
        isolated_by_family = {
            family: tuple(
                item
                for item in isolated
                if item.transformations[0].family == family
            )
            for family in families
        }
        selected_isolated_slots = tuple(
            _fake_isolated_scenario_slot(item) for item in isolated
        )
        authoritative_isolated_slots = {
            _fake_isolated_scenario_slot(item)
            for item in authoritative_isolated
        }
        complete_isolated = all(
            2 <= len(items) <= 12
            and len({item.transformations[0].parameters for item in items})
            == len(items)
            and len(
                {
                    (
                        item.transformations[0].transformation_id,
                        item.transformations[0].implementation_version,
                    )
                    for item in items
                }
            )
            == 1
            for items in isolated_by_family.values()
        ) and (
            len(selected_isolated_slots) == len(set(selected_isolated_slots))
            and set(selected_isolated_slots)
            == authoritative_isolated_slots
        )
        selected_compound_slots = tuple(
            _fake_compound_scenario_slot(item) for item in compounds
        )
        authoritative_compound_slots = {
            _fake_compound_scenario_slot(item)
            for item in authoritative_compounds
        }
        complete_compounds = (
            bool(compounds)
            and len(selected_compound_slots)
            == len(set(selected_compound_slots))
            and set(selected_compound_slots)
            == authoritative_compound_slots
        )
        missing = (
            *(("complete isolated sensitivity sweep",) if not complete_isolated else ()),
            *(("declared compound scenario set",) if not complete_compounds else ()),
        )
        eligibility = (
            FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE
            if not missing
            else FormalScenarioSetEligibility.QUICK_EXPERIMENT_ONLY
        )
        comparisons = tuple(
            FormalScenarioComparisonProjection(
                kind="isolated-vs-baseline",
                subject_case_id=item.scenario_id,
                control_case_ids=(baseline.scenario_id,),
            )
            for item in isolated
        ) + tuple(
            FormalScenarioComparisonProjection(
                kind="compound-vs-baseline-and-isolated",
                subject_case_id=item.scenario_id,
                control_case_ids=(
                    baseline.scenario_id,
                    *(
                        candidate.scenario_id
                        for candidate in isolated
                        if candidate.transformations[0].family
                        in {value.family for value in item.transformations}
                    ),
                ),
            )
            for item in compounds
        )
        identity = ScenarioSetId(
            "formal-scenario-set-"
            + hashlib.sha256(
                repr((selected_ids, eligibility, comparisons)).encode("utf-8")
            ).hexdigest()[:24]
        )
        scenario_set = FormalScenarioSetProjection(
            scenario_set_id=identity,
            projection_revision=len(inventory.scenario_sets) + 1,
            eligibility=eligibility,
            baseline_case_id=baseline.scenario_id,
            isolated_case_ids=command.isolated_case_ids,
            compound_case_ids=command.compound_case_ids,
            case_ids=selected_ids,
            comparison_relationships=comparisons,
            missing_requirements=missing,
            formal_handoff_eligible=(
                eligibility
                is FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE
            ),
        )
        result = ComposeFormalScenarioSetResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            scenario_set_id=identity,
            scenario_set=scenario_set,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                scenario_sets=(*inventory.scenario_sets, scenario_set),
            )
        )
        return result

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult:
        operation = ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ResolveScenarioExecutionAssumptionsResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return ResolveScenarioExecutionAssumptionsResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, ResolveScenarioExecutionAssumptionsResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return ResolveScenarioExecutionAssumptionsResult(receipt=source_conflict)
        inventory = self._inventory()
        scenario_set = next(
            (
                item
                for item in reversed(inventory.scenario_sets)
                if command.scenario_set_id is not None
                and item.scenario_set_id == command.scenario_set_id
            ),
            None,
        )
        if scenario_set is None:
            return ResolveScenarioExecutionAssumptionsResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Execution resolution requires one authoritative Scenario Set.",
                )
            )
        if len(command.targets) != len(set(command.targets)):
            return ResolveScenarioExecutionAssumptionsResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Execution assumption targets must be unique.",
                )
            )
        strategy_ids = {item.strategy_id for item in command.targets}
        if strategy_ids - self._formal_strategy_ids:
            return ResolveScenarioExecutionAssumptionsResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    (
                        "Execution assumption target is not an exact formal "
                        "Strategy/Case binding."
                    ),
                )
            )
        cases = {item.scenario_id: item for item in inventory.market_scenarios}
        resolved_targets = tuple(
            _fake_execution_target(item, cases[item.campaign_case_id])
            for item in command.targets
            if item.campaign_case_id in scenario_set.case_ids
            and item.campaign_case_id in cases
        )
        if len(resolved_targets) != len(command.targets):
            return ResolveScenarioExecutionAssumptionsResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Execution target is outside the exact Scenario Set.",
                )
            )
        expected = {
            (strategy_id, case_id)
            for strategy_id in self._formal_strategy_ids
            for case_id in scenario_set.case_ids
        }
        provided = {
            (item.strategy_id, item.campaign_case_id)
            for item in command.targets
        }
        eligible = (
            scenario_set.formal_handoff_eligible
            and strategy_ids == self._formal_strategy_ids
            and provided == expected
            and all(
                item.state is ScenarioExecutionResolutionState.RESOLVED
                for item in resolved_targets
            )
        )
        identity = ScenarioExecutionResolutionId(
            "scenario-execution-resolution-"
            + hashlib.sha256(
                repr(
                    (
                        scenario_set.scenario_set_id,
                        scenario_set.projection_revision,
                        resolved_targets,
                    )
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        resolution = ScenarioExecutionResolutionProjection(
            resolution_id=identity,
            projection_revision=len(inventory.execution_resolutions) + 1,
            scenario_set_id=scenario_set.scenario_set_id,
            scenario_set_projection_revision=(
                scenario_set.projection_revision
            ),
            targets=resolved_targets,
            formal_handoff_eligible=eligible,
        )
        result = ResolveScenarioExecutionAssumptionsResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            resolution_id=identity,
            resolution=resolution,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                execution_resolutions=(
                    *inventory.execution_resolutions,
                    resolution,
                ),
            )
        )
        return result

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult:
        operation = ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return SelectFormalScenarioSetResult(receipt=rejection)
        replay, conflict = self._replay(command.metadata, operation)
        if conflict is not None:
            return SelectFormalScenarioSetResult(receipt=conflict)
        if replay is not None:
            if not isinstance(replay, SelectFormalScenarioSetResult):
                raise TypeError("Scenario Lab fake replay operation mismatch")
            return replay
        source_conflict = self._source_conflict(command.metadata, operation)
        if source_conflict is not None:
            return SelectFormalScenarioSetResult(receipt=source_conflict)
        inventory = self._inventory()
        scenario_set = next(
            (
                item
                for item in reversed(inventory.scenario_sets)
                if item.scenario_set_id == command.scenario_set_id
            ),
            None,
        )
        resolution = next(
            (
                item
                for item in reversed(inventory.execution_resolutions)
                if command.execution_resolution_id is not None
                and item.resolution_id == command.execution_resolution_id
            ),
            None,
        )
        if (
            scenario_set is None
            or resolution is None
            or not scenario_set.formal_handoff_eligible
            or not resolution.formal_handoff_eligible
            or resolution.scenario_set_id != scenario_set.scenario_set_id
            or resolution.scenario_set_projection_revision
            != scenario_set.projection_revision
            or command.case_ids != scenario_set.case_ids
        ):
            return SelectFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Quick, incomplete, or stale Scenario Sets cannot be selected for formal handoff.",
                )
            )
        selection_revision = len(inventory.selection_contexts) + 1
        scenarios = {
            item.scenario_id: item for item in inventory.market_scenarios
        }
        paths = {item.path_id: item for item in inventory.reference_paths}
        if any(
            case_id not in scenarios
            or scenarios[case_id].path_id not in paths
            for case_id in command.case_ids
        ):
            return SelectFormalScenarioSetResult(
                receipt=self._rejected_receipt(
                    command.metadata,
                    operation,
                    "Formal selection dependencies are no longer authoritative.",
                )
            )
        case_bindings = tuple(
            _fake_selection_case_binding(
                scenarios[case_id],
                paths[scenarios[case_id].path_id],
            )
            for case_id in command.case_ids
        )
        strategies: dict[
            StrategyUnderTestId,
            ScenarioSelectionStrategyBindingProjection,
        ] = {}
        for target in resolution.targets:
            binding = ScenarioSelectionStrategyBindingProjection(
                strategy_id=target.strategy_id,
                strategy_version=target.strategy_version,
                compatibility_manifest_hash=(
                    target.compatibility_manifest_hash
                ),
                guardrail_profile_id=target.guardrail_profile_id,
                guardrail_profile_version=(
                    target.guardrail_profile_version
                ),
                execution_policy_version=target.execution_policy_version,
            )
            predecessor = strategies.setdefault(target.strategy_id, binding)
            if predecessor != binding:
                return SelectFormalScenarioSetResult(
                    receipt=self._rejected_receipt(
                        command.metadata,
                        operation,
                        "Execution resolution Strategy bindings conflict.",
                    )
                )
        strategy_bindings = tuple(
            strategies[identity]
            for identity in sorted(strategies, key=lambda item: item.value)
        )
        identity = ScenarioSelectionContextId(
            "scenario-selection-context-"
            + hashlib.sha256(
                repr(
                    (
                        scenario_set.scenario_set_id,
                        scenario_set.projection_revision,
                        resolution.resolution_id,
                        resolution.projection_revision,
                        command.case_ids,
                        case_bindings,
                        strategy_bindings,
                        command.originating_view_revision,
                        selection_revision,
                    )
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        selection = ScenarioSelectionContextProjection(
            selection_context_id=identity,
            scenario_set_id=scenario_set.scenario_set_id,
            scenario_set_projection_revision=(
                scenario_set.projection_revision
            ),
            case_ids=command.case_ids,
            case_bindings=case_bindings,
            strategy_bindings=strategy_bindings,
            execution_resolution_id=resolution.resolution_id,
            execution_resolution_projection_revision=(
                resolution.projection_revision
            ),
            status=ScenarioSelectionContextStatus.CURRENT,
            selection_revision=selection_revision,
            originating_view_revision=command.originating_view_revision,
            source_revision=command.metadata.expected_source_revision,
            source_generation=command.metadata.expected_source_generation,
            formal_handoff_eligible=True,
        )
        stale = tuple(
            replace(
                item,
                status=ScenarioSelectionContextStatus.STALE,
                formal_handoff_eligible=False,
            )
            for item in inventory.selection_contexts
        )
        result = SelectFormalScenarioSetResult(
            receipt=self._accepted_receipt(command.metadata, operation),
            selection_context_id=identity,
            scenario_set_id=scenario_set.scenario_set_id,
            selection_context=selection,
        )
        self._remember(command.metadata, operation, result)
        self._set_inventory(
            replace(
                inventory,
                selection_contexts=(*stale, selection),
            )
        )
        return result


class DeterministicFakeScenarioLabAdapter(_ScenarioLabAdapter):
    def __init__(
        self,
        *,
        inventory: ScenarioLabInventory | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        scripted_results: tuple[ScenarioLabApplicationInventoryResult, ...] = (),
        ai_authoring_available: bool | None = None,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        materialization_scheduler: (
            Callable[[Callable[[], None]], None] | None
        ) = None,
        formal_strategy_ids: tuple[StrategyUnderTestId, ...] = (
            _DEFAULT_FORMAL_STRATEGY_IDS
        ),
    ) -> None:
        resolved_clock = clock or (lambda: datetime.now(timezone.utc))
        resolved_inventory = inventory or _default_inventory()
        if ai_authoring_available is not None:
            resolved_inventory = replace(
                resolved_inventory,
                authoring_capabilities=(
                    ScenarioRecipeAuthoringCapabilitiesProjection(
                        manual_authoring_available=True,
                        ai_authoring_available=ai_authoring_available,
                        ai_provider=ai_provider,
                        ai_model=ai_model,
                    )
                ),
            )
        application = _DeterministicFakeScenarioLabApplication(
            resolved_inventory,
            clock=resolved_clock,
            scripted_results=scripted_results,
            materialization_scheduler=(
                materialization_scheduler or _schedule_fake_materialization
            ),
            formal_strategy_ids=formal_strategy_ids,
        )
        self._deterministic_application = application
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

    def fail_next_materialization(self) -> None:
        """Inject one retryable failure without changing the shared contract body."""

        self._deterministic_application.fail_next_materialization()

    def fail_next_materialization_integrity(self) -> None:
        """Inject one terminal artifact integrity conflict for conformance."""

        self._deterministic_application.fail_next_materialization_integrity()

    def advance_to_dependency_change(self) -> None:
        """Expose one deterministic authority-invalidation conformance step."""

        inventory = self._deterministic_application._inventory()
        catalog = inventory.transformation_catalog
        self._deterministic_application._set_inventory(
            replace(
                inventory,
                transformation_catalog=replace(
                    catalog,
                    catalog_version=f"{catalog.catalog_version}.changed",
                ),
            )
        )

    def advance_to_dependency_unavailable(self) -> None:
        """Remove admitted inputs without rewriting immutable approval history."""

        inventory = self._deterministic_application._inventory()
        self._deterministic_application._set_inventory(
            replace(inventory, historical_segments=())
        )

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
    return ()


def _filtered_inventory(
    inventory: ScenarioLabInventory,
    context: ScenarioLabContext,
) -> tuple[
    tuple[HistoricalSegmentEntry, ...],
    tuple[ReferenceMarketPathEntry, ...],
    tuple[MarketScenarioEntry, ...],
    TransformationCatalogProjection,
    tuple[ScenarioRecipeDraftProjection, ...],
    tuple[ScenarioRecipeValidationProjection, ...],
    tuple[ApprovedScenarioRecipeVersionProjection, ...],
    tuple[ScenarioLabTaskHandle, ...],
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
    catalog_families = {
        item.transformation_id: item.family
        for item in inventory.transformation_catalog.entries
    }
    drafts = tuple(
        item
        for item in inventory.recipe_drafts
        if item.payload.historical_segment_id in market_segment_ids
        and (
            not context.recipe_versions
            or (
                item.based_on_recipe_version_id is not None
                and item.based_on_recipe_version_id.value
                in context.recipe_versions
            )
        )
        and (
            not context.transformation_families
            or any(
                catalog_families.get(transformation.transformation_id)
                in context.transformation_families
                for transformation in item.payload.transformations
            )
        )
        and (
            not needle
            or needle
            in " ".join(
                (
                    item.draft_id.value,
                    item.recipe_id,
                    item.payload.name,
                    item.payload.historical_segment_id.value,
                    *(value.transformation_id for value in item.payload.transformations),
                )
            ).casefold()
        )
    )
    draft_ids = {item.draft_id for item in drafts}
    validations = tuple(
        item
        for item in inventory.recipe_validations
        if item.draft_id in draft_ids
        and (
            not needle
            or needle
            in " ".join(
                (
                    item.validation_id.value,
                    item.draft_id.value,
                    item.dependencies.historical_segment_id.value,
                    *(finding.rule_code for finding in item.findings),
                )
            ).casefold()
        )
    )
    approved_versions = tuple(
        item
        for item in inventory.approved_recipe_versions
        if (
            not context.recipe_versions
            or item.recipe_version_id.value in context.recipe_versions
        )
        and (
            not needle
            or needle
            in " ".join(
                (
                    item.recipe_version_id.value,
                    item.recipe_id,
                    item.approval.approval_id.value,
                    (
                        ""
                        if item.approval.validation_id is None
                        else item.approval.validation_id.value
                    ),
                    item.approval.draft_id.value,
                    item.authority_state.value,
                )
            ).casefold()
        )
    )
    task_handles = tuple(
        item
        for item in inventory.task_handles
        if not needle
        or needle
        in " ".join(
            (
                item.identity.value,
                item.operation.value,
                item.target_identity.value,
            )
        ).casefold()
    )
    return (
        segments,
        paths,
        scenarios,
        catalog,
        drafts,
        validations,
        approved_versions,
        task_handles,
    )


def _contains_identity(
    identity: str | None,
    segments: tuple[HistoricalSegmentEntry, ...],
    paths: tuple[ReferenceMarketPathEntry, ...],
    scenarios: tuple[MarketScenarioEntry, ...],
    drafts: tuple[ScenarioRecipeDraftProjection, ...],
    validations: tuple[ScenarioRecipeValidationProjection, ...],
    approved_versions: tuple[ApprovedScenarioRecipeVersionProjection, ...],
    task_handles: tuple[ScenarioLabTaskHandle, ...],
) -> bool:
    if identity is None:
        return False
    return identity in {
        *(item.segment_id.value for item in segments),
        *(item.path_id.value for item in paths),
        *(item.scenario_id.value for item in scenarios),
        *(item.draft_id.value for item in drafts),
        *(item.validation_id.value for item in validations),
        *(item.recipe_version_id.value for item in approved_versions),
        *(item.approval.approval_id.value for item in approved_versions),
        *(item.identity.value for item in task_handles),
    }


def _fake_selection_case_binding(
    scenario: MarketScenarioEntry,
    path: ReferenceMarketPathEntry,
) -> ScenarioSelectionCaseBindingProjection:
    return ScenarioSelectionCaseBindingProjection(
        campaign_case_id=scenario.scenario_id,
        recipe_version_id=scenario.recipe_version_id,
        recipe_content_hash=scenario.recipe_content_hash,
        reference_path_id=path.path_id,
        reference_path_content_hash=path.path_id.value,
        segment_id=scenario.segment_id,
        segment_content_hash=scenario.segment_content_hash,
        source_snapshot_id=scenario.source_snapshot_id,
        seed=scenario.seed,
        expander_version=path.expander_version,
        source_resolution=path.source_resolution,
        runtime_resolution=path.runtime_resolution,
        numeric_tolerance=path.numeric_tolerance,
        normalization_provenance=path.normalization_provenance,
        transformation_catalog_version=(
            scenario.transformation_catalog_version
        ),
        transformations=scenario.transformations,
        market_rule_profile_version=scenario.market_rule_profile_version,
        decision_cadence_minutes=scenario.decision_cadence_minutes,
    )


def _fake_isolated_scenario_slot(
    scenario: MarketScenarioEntry,
) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    transformation = scenario.transformations[0]
    return (
        transformation.family,
        transformation.transformation_id,
        transformation.implementation_version,
        transformation.parameters,
    )


def _fake_compound_scenario_slot(
    scenario: MarketScenarioEntry,
) -> tuple[
    tuple[str, str, str, tuple[tuple[str, str], ...]],
    ...,
]:
    return tuple(
        sorted(
            (
                transformation.family,
                transformation.transformation_id,
                transformation.implementation_version,
                transformation.parameters,
            )
            for transformation in scenario.transformations
        )
    )


def _reconcile_fake_selection_contexts(
    inventory: ScenarioLabInventory,
    *,
    formal_strategy_ids: frozenset[StrategyUnderTestId],
) -> tuple[ScenarioSelectionContextProjection, ...]:
    if not inventory.selection_contexts:
        return ()
    latest_set = inventory.scenario_sets[-1] if inventory.scenario_sets else None
    latest_resolution = (
        inventory.execution_resolutions[-1]
        if inventory.execution_resolutions
        else None
    )
    scenarios = {
        item.scenario_id: item for item in inventory.market_scenarios
    }
    paths = {item.path_id: item for item in inventory.reference_paths}
    reconciled: list[ScenarioSelectionContextProjection] = []
    for index, context in enumerate(inventory.selection_contexts):
        current = (
            index == len(inventory.selection_contexts) - 1
            and latest_set is not None
            and latest_resolution is not None
            and context.scenario_set_id == latest_set.scenario_set_id
            and context.scenario_set_projection_revision
            == latest_set.projection_revision
            and context.execution_resolution_id
            == latest_resolution.resolution_id
            and context.execution_resolution_projection_revision
            == latest_resolution.projection_revision
            and latest_set.formal_handoff_eligible
            and latest_resolution.formal_handoff_eligible
            and latest_resolution.scenario_set_id
            == latest_set.scenario_set_id
            and latest_resolution.scenario_set_projection_revision
            == latest_set.projection_revision
            and context.case_ids == latest_set.case_ids
            and {
                item.strategy_id for item in context.strategy_bindings
            }
            == formal_strategy_ids
            and all(
                case_id in scenarios
                and scenarios[case_id].path_id in paths
                for case_id in context.case_ids
            )
        )
        if current:
            assert latest_resolution is not None
            expected_case_bindings = tuple(
                _fake_selection_case_binding(
                    scenarios[case_id],
                    paths[scenarios[case_id].path_id],
                )
                for case_id in context.case_ids
            )
            expected_strategy_bindings_by_id: dict[
                StrategyUnderTestId,
                ScenarioSelectionStrategyBindingProjection,
            ] = {}
            for target in latest_resolution.targets:
                binding = ScenarioSelectionStrategyBindingProjection(
                    strategy_id=target.strategy_id,
                    strategy_version=target.strategy_version,
                    compatibility_manifest_hash=(
                        target.compatibility_manifest_hash
                    ),
                    guardrail_profile_id=target.guardrail_profile_id,
                    guardrail_profile_version=(
                        target.guardrail_profile_version
                    ),
                    execution_policy_version=(
                        target.execution_policy_version
                    ),
                )
                predecessor = expected_strategy_bindings_by_id.setdefault(
                    target.strategy_id,
                    binding,
                )
                if predecessor != binding:
                    current = False
            expected_strategy_bindings = tuple(
                expected_strategy_bindings_by_id[identity]
                for identity in sorted(
                    expected_strategy_bindings_by_id,
                    key=lambda item: item.value,
                )
            )
            current = (
                current
                and context.case_bindings == expected_case_bindings
                and context.strategy_bindings == expected_strategy_bindings
                and all(
                    item.transformation_catalog_version
                    == inventory.transformation_catalog.catalog_version
                    for item in context.case_bindings
                )
            )
        reconciled.append(
            replace(
                context,
                status=(
                    ScenarioSelectionContextStatus.CURRENT
                    if current
                    else ScenarioSelectionContextStatus.STALE
                ),
                formal_handoff_eligible=(
                    context.formal_handoff_eligible and current
                ),
            )
        )
    return tuple(reconciled)


def _fake_execution_target(
    target: ScenarioExecutionAssumptionTarget,
    scenario: MarketScenarioEntry,
) -> ScenarioExecutionTargetProjection:
    requested = scenario.requested_execution_assumptions
    requested_values = {
        "allow_partial_fills": (
            "true" if requested.allow_partial_fills else "false"
        ),
        "commission_bps": requested.commission_bps,
        "latency_nodes": str(requested.latency_nodes),
        "max_fill_fraction": requested.max_fill_fraction,
        "rejection_mode": "none",
        "slippage_bps": requested.slippage_bps,
    }
    effective_values = dict(requested_values)
    overridden: set[str] = set()
    for transformation in scenario.transformations:
        if transformation.family != "execution-stress":
            continue
        for name, value in transformation.parameters:
            if name in effective_values:
                effective_values[name] = value.casefold() if name == "allow_partial_fills" else value
                overridden.add(name)
    conditions = tuple(
        ScenarioExecutionConditionProjection(
            name=name,
            requested_value=requested_values[name],
            effective_value=effective_values[name],
            override_reason=(
                "scenario execution-stress.v1 override"
                if name in overridden
                else None
            ),
        )
        for name in (
            "allow_partial_fills",
            "commission_bps",
            "latency_nodes",
            "max_fill_fraction",
            "rejection_mode",
            "slippage_bps",
        )
    )
    after_decision_time = (
        None
        if target.decision_time is None
        else target.decision_time + timedelta(seconds=30)
    )
    activation_time = (
        None
        if after_decision_time is None
        else after_decision_time
        + timedelta(seconds=30 * int(effective_values["latency_nodes"]))
    )
    state = (
        ScenarioExecutionResolutionState.NOT_YET_RESOLVED
        if target.decision_time is None
        else ScenarioExecutionResolutionState.RESOLVED
    )
    strategy_digest = hashlib.sha256(
        target.strategy_id.value.encode("utf-8")
    ).hexdigest()
    return ScenarioExecutionTargetProjection(
        strategy_id=target.strategy_id,
        strategy_version="1.0",
        compatibility_manifest_hash=strategy_digest,
        guardrail_profile_id="guardrail-profile-" + strategy_digest[:24],
        guardrail_profile_version="1.0",
        campaign_case_id=target.campaign_case_id,
        state=state,
        decision_time=target.decision_time,
        after_decision_time=after_decision_time,
        activation_time=activation_time,
        decision_cadence_minutes=scenario.decision_cadence_minutes,
        decision_grid=(
            f"{scenario.decision_cadence_minutes}-minute simulation-time grid"
        ),
        activation_policy=(
            "first Reference Market Path node strictly later than Decision Time, "
            "then effective latency_nodes"
        ),
        execution_policy_version="a-share-baseline-execution-policy.v1",
        conditions=conditions,
        unavailability_reasons=(
            ()
            if state is ScenarioExecutionResolutionState.RESOLVED
            else ("Decision Time is required to resolve activation.",)
        ),
    )


def _authoring_capabilities(
    inventory: ScenarioLabInventory,
) -> ScenarioLabCapabilities:
    has_admitted_source = any(
        item.admission_state is ScenarioLabAdmissionState.ADMITTED
        and item.quality_state is ScenarioLabQualityState.PASSED
        for item in inventory.historical_segments
    )
    has_draft = bool(inventory.recipe_drafts)
    approved_draft_ids = {
        item.approval.draft_id
        for item in inventory.approved_recipe_versions
    }
    current_revision_by_recipe = {
        recipe_id: max(
            item.revision
            for item in inventory.recipe_drafts
            if item.recipe_id == recipe_id
        )
        for recipe_id in {item.recipe_id for item in inventory.recipe_drafts}
    }
    can_approve = any(
        validation.is_valid
        and validation.draft_id not in approved_draft_ids
        and any(
            draft.draft_id == validation.draft_id
            and draft.revision == validation.draft_revision
            and draft.payload_hash == validation.payload_hash
            and current_revision_by_recipe.get(draft.recipe_id) == draft.revision
            for draft in inventory.recipe_drafts
        )
        for validation in inventory.recipe_validations
    )
    return ScenarioLabCapabilities(
        can_browse=True,
        can_search=True,
        can_filter=True,
        can_inspect_bounded_preview=True,
        can_create_recipe_draft=has_admitted_source,
        can_create_ai_assisted_recipe_draft=(
            has_admitted_source
            and inventory.authoring_capabilities.ai_authoring_available
        ),
        can_revise_recipe_draft=has_draft,
        can_validate_recipe_draft=has_draft,
        can_approve_recipe=can_approve,
        can_materialize_reference_path=any(
            item.can_materialize
            for item in inventory.approved_recipe_versions
        ),
        can_retry_materialization=any(
            item.phase is TaskPhase.FAILED and item.retryable
            for item in inventory.task_handles
        ),
        can_compose_scenario_set=any(
            item.layer is MarketScenarioLayer.BASELINE
            for item in inventory.market_scenarios
        ),
        can_resolve_execution_assumptions=bool(inventory.scenario_sets),
        can_select_formal_scenario_set=any(
            scenario_set.formal_handoff_eligible
            and any(
                resolution.scenario_set_id == scenario_set.scenario_set_id
                and resolution.formal_handoff_eligible
                for resolution in inventory.execution_resolutions
            )
            for scenario_set in inventory.scenario_sets
        ),
    )


def _availability(
    inventory: ScenarioLabInventory,
) -> ScenarioLabApplicationAvailability:
    if any(
        item.integrity is not ScenarioLabIntegrityState.VERIFIED
        for item in inventory.reference_paths
    ):
        return ScenarioLabApplicationAvailability.PARTIAL
    if (
        inventory.historical_segments
        or inventory.reference_paths
        or inventory.market_scenarios
        or inventory.recipe_drafts
        or inventory.approved_recipe_versions
    ):
        return ScenarioLabApplicationAvailability.READY
    return ScenarioLabApplicationAvailability.EMPTY


def _fake_recipe_validation_findings(
    draft: ScenarioRecipeDraftProjection,
    catalog: TransformationCatalogProjection,
) -> tuple[ScenarioRecipeValidationFindingProjection, ...]:
    """Apply the published Recipe/Catalog rules for the deterministic fake."""

    findings: list[ScenarioRecipeValidationFindingProjection] = []

    def add(
        path: tuple[str, ...],
        rule: str,
        explanation: str,
        correction: str,
    ) -> None:
        findings.append(
            ScenarioRecipeValidationFindingProjection(
                path=path,
                rule_code=rule,
                severity=ScenarioRecipeValidationSeverity.ERROR,
                explanation=explanation,
                correction=correction,
                retryable=False,
                different_input_required=True,
            )
        )

    payload = draft.payload
    bounds_correction = (
        "Choose a value within the published ScenarioRecipeV1 bounds."
    )
    if payload.decision_cadence_minutes not in (30, 60):
        add(
            ("decision_cadence_minutes",),
            "bounds.invalid",
            "value is not a permitted decision cadence",
            bounds_correction,
        )
    if not 0 <= payload.materialization_seed <= 2_147_483_647:
        add(
            ("materialization_seed",),
            "bounds.invalid",
            "materialization seed is outside the published bounds",
            bounds_correction,
        )
    execution = payload.requested_execution_assumptions
    for field, raw, minimum, maximum, exclusive_minimum in (
        ("commission_bps", execution.commission_bps, Decimal("0"), Decimal("100"), False),
        ("slippage_bps", execution.slippage_bps, Decimal("0"), Decimal("1000"), False),
        ("max_fill_fraction", execution.max_fill_fraction, Decimal("0"), Decimal("1"), True),
    ):
        try:
            value = Decimal(raw)
            valid = value.is_finite() and value <= maximum and (
                value > minimum if exclusive_minimum else value >= minimum
            )
        except InvalidOperation:
            valid = False
        if not valid:
            add(
                ("execution_conditions", field),
                "bounds.invalid",
                f"{field} is outside the published bounds",
                bounds_correction,
            )
    if not 0 <= execution.latency_nodes <= 120:
        add(
            ("execution_conditions", "latency_nodes"),
            "bounds.invalid",
            "latency_nodes is outside the published bounds",
            bounds_correction,
        )
    if payload.market_rule_profile_version != "a-share-cash-equity.v1":
        add(
            ("market_rule_profile",),
            "schema.invalid",
            "unexpected value; permitted: 'a-share-cash-equity.v1'",
            "Correct the field to match the published ScenarioRecipeV1 schema.",
        )

    entries = {item.transformation_id: item for item in catalog.entries}
    seen_families: set[str] = set()
    for index, request in enumerate(payload.transformations):
        base_path = ("transformations", str(index))
        entry = entries.get(request.transformation_id)
        if entry is None:
            add(
                (*base_path, "transformation_id"),
                "transformation.not-registered",
                f"Transformation {request.transformation_id!r} is not registered.",
                "Remove it or choose a registered Transformation Catalog entry.",
            )
            continue
        if (
            "a-share-cash-equity.v1" in entry.compatibility_rules
            and payload.market_rule_profile_version != "a-share-cash-equity.v1"
        ):
            add(
                ("market_rule_profile",),
                "transformation.incompatible-market-profile",
                "The transformation is incompatible with the market profile.",
                "Use market_rule_profile='a-share-cash-equity.v1'.",
            )
        if (
            "one-transform-per-family" in entry.compatibility_rules
            and entry.family in seen_families
        ):
            add(
                (*base_path, "transformation_id"),
                "transformation.incompatible-combination",
                f"Transformation family {entry.family!r} is already present.",
                "Keep only one transformation from this family.",
            )
        seen_families.add(entry.family)
        values = {item.name: item for item in request.parameters}
        definitions = {item.name: item for item in entry.parameters}
        for name in sorted(set(values) - set(definitions)):
            rule, explanation, correction = _fake_unknown_parameter_finding(name)
            add((*base_path, "parameters", name), rule, explanation, correction)
        for name, definition in definitions.items():
            path = (*base_path, "parameters", name)
            provided = values.get(name)
            if provided is None:
                if definition.required:
                    add(
                        path,
                        "transformation.parameter-required",
                        f"Parameter {name!r} is required.",
                        "Provide the parameter using the published type and bounds.",
                    )
                continue
            expected_kind = {
                "decimal": "decimal",
                "integer": "integer",
                "boolean": "boolean",
                "enum": "choice",
            }.get(definition.value_type, "choice")
            if provided.kind.value != expected_kind:
                add(
                    path,
                    "transformation.parameter-type",
                    f"Parameter {name!r} must use the published type.",
                    "Provide the parameter using the published type and bounds.",
                )
                continue
            if definition.value_type == "enum":
                if str(provided.value) not in definition.choices:
                    add(
                        path,
                        "transformation.parameter-type",
                        f"Parameter {name!r} must be one of {definition.choices!r}.",
                        "Choose one of the published values.",
                    )
                continue
            if definition.value_type not in {"decimal", "integer"}:
                continue
            numeric = Decimal(str(provided.value))
            if (
                definition.minimum is not None
                and numeric < Decimal(definition.minimum)
            ) or (
                definition.maximum is not None
                and numeric > Decimal(definition.maximum)
            ):
                add(
                    path,
                    "transformation.parameter-bounds",
                    f"Parameter {name!r} is outside the published bounds.",
                    (
                        f"Choose a value from {definition.minimum or '0'} "
                        f"through {definition.maximum or '0'}."
                    ),
                )
    return tuple(findings)


def _fake_recipe_validation_dependencies(
    draft: ScenarioRecipeDraftProjection,
    inventory: ScenarioLabInventory,
    findings: tuple[ScenarioRecipeValidationFindingProjection, ...],
) -> ScenarioRecipeValidationDependenciesProjection | None:
    """Derive the same complete typed dependency binding for fake gates."""

    segment = next(
        (
            item
            for item in inventory.historical_segments
            if item.segment_id == draft.payload.historical_segment_id
        ),
        None,
    )
    if segment is None:
        return None
    catalog_entries = {
        item.transformation_id: item
        for item in inventory.transformation_catalog.entries
    }
    selected_entries = tuple(
        catalog_entries[item.transformation_id]
        for item in draft.payload.transformations
        if item.transformation_id in catalog_entries
    )
    compatibility_observations = (
        ScenarioRecipeCompatibilityObservation(
            subject=f"historical-segment:{segment.segment_id.value}",
            state=ScenarioRecipeCompatibilityState.COMPATIBLE,
            explanation="The exact Historical Market Segment is admitted.",
        ),
        *(
            ScenarioRecipeCompatibilityObservation(
                subject=f"transformation:{item.transformation_id}",
                state=ScenarioRecipeCompatibilityState.COMPATIBLE,
                explanation="The registered implementation and policy are bound.",
            )
            for item in selected_entries
        ),
        *(
            ScenarioRecipeCompatibilityObservation(
                subject=f"validation-rule:{finding.rule_code}",
                state=ScenarioRecipeCompatibilityState.INCOMPATIBLE,
                explanation=finding.explanation,
            )
            for finding in findings
        ),
    )
    return ScenarioRecipeValidationDependenciesProjection(
        historical_segment_id=draft.payload.historical_segment_id,
        historical_segment_content_hash=segment.content_hash,
        source_snapshot_id=segment.source_snapshot_id,
        source_snapshot_content_hash=segment.source_snapshot_content_hash,
        recipe_schema_identity="scenario_recipe.v1",
        recipe_schema_hash=hashlib.sha256(b"scenario_recipe.v1").hexdigest(),
        transformation_catalog_version=(
            inventory.transformation_catalog.catalog_version
        ),
        transformation_catalog_hash=hashlib.sha256(
            repr(inventory.transformation_catalog).encode("utf-8")
        ).hexdigest(),
        transformation_implementation_identities=tuple(
            f"{item.transformation_id}@{item.implementation_version}"
            for item in selected_entries
        ),
        data_policy=draft.payload.data_policy,
        causality_rule_identities=tuple(
            sorted(
                {
                    rule
                    for item in selected_entries
                    for rule in item.causality_constraints
                }
            )
        ),
        market_rule_profile_version=draft.payload.market_rule_profile_version,
        market_rule_profile_hash=hashlib.sha256(
            draft.payload.market_rule_profile_version.encode("utf-8")
        ).hexdigest(),
        compatibility_observations=compatibility_observations,
    )


def _reconcile_fake_recipe_approval(
    version: ApprovedScenarioRecipeVersionProjection,
    inventory: ScenarioLabInventory,
) -> ApprovedScenarioRecipeVersionProjection:
    draft = next(
        (
            item
            for item in inventory.recipe_drafts
            if item.draft_id == version.approval.draft_id
        ),
        None,
    )
    if draft is None:
        authority_state = ScenarioRecipeApprovalAuthorityState.UNAVAILABLE
        summary = "The exact Approved Recipe Draft dependency is unavailable."
    else:
        findings = _fake_recipe_validation_findings(
            draft,
            inventory.transformation_catalog,
        )
        current_dependencies = _fake_recipe_validation_dependencies(
            draft,
            inventory,
            findings,
        )
        if current_dependencies is None:
            authority_state = ScenarioRecipeApprovalAuthorityState.UNAVAILABLE
            summary = "One or more exact approval dependencies are unavailable."
        elif any(
            item.state is ScenarioRecipeCompatibilityState.INCOMPATIBLE
            for item in current_dependencies.compatibility_observations
        ):
            authority_state = ScenarioRecipeApprovalAuthorityState.INCOMPATIBLE
            summary = (
                "Current dependency compatibility is incompatible with approval."
            )
        elif current_dependencies != version.approval.dependencies:
            authority_state = ScenarioRecipeApprovalAuthorityState.OUTDATED
            summary = (
                "Approval dependencies changed; historical truth is retained."
            )
        else:
            return replace(
                version,
                authority_state=ScenarioRecipeApprovalAuthorityState.CURRENT,
                authority_reasons=(),
                can_materialize=True,
            )
    reason_code = {
        ScenarioRecipeApprovalAuthorityState.OUTDATED: (
            ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_OUTDATED
        ),
        ScenarioRecipeApprovalAuthorityState.INCOMPATIBLE: (
            ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_INCOMPATIBLE
        ),
        ScenarioRecipeApprovalAuthorityState.UNAVAILABLE: (
            ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_DEPENDENCY_UNAVAILABLE
        ),
    }[authority_state]
    return replace(
        version,
        authority_state=authority_state,
        authority_reasons=(
            ScenarioLabUnavailabilityReason(
                code=reason_code,
                summary=summary,
                corrective_guidance=(
                    "Reread authoritative dependencies, create a successor Draft, "
                    "then validate and approve the exact corrected revision."
                ),
            ),
        ),
        can_materialize=False,
    )


def _fake_unknown_parameter_finding(name: str) -> tuple[str, str, str]:
    normalized = name.lower().replace("-", "_")
    if any(token in normalized for token in ("python", "code", "script", "executable")):
        return (
            "transformation.executable-code-forbidden",
            "Scenario Recipes cannot contain executable transformation code.",
            "Choose a reviewed registered transformation and declared parameters.",
        )
    if any(token in normalized for token in ("expression", "formula", "expr")):
        return (
            "transformation.expression-forbidden",
            "Scenario Recipes cannot contain arbitrary expressions or formulas.",
            "Use only parameters declared by the Transformation Catalog.",
        )
    if "final" in normalized and any(
        token in normalized for token in ("price", "close", "ohlc", "market_data")
    ):
        return (
            "transformation.final-price-edit-forbidden",
            "Scenario Recipes cannot edit final market prices directly.",
            "Describe the condition through a registered transformation.",
        )
    if any(token in normalized for token in ("path", "file", "directory", "folder")):
        return (
            "transformation.path-forbidden",
            "Scenario Recipes cannot contain filesystem paths.",
            "Select admitted data and catalog capabilities by durable identity.",
        )
    return (
        "transformation.parameter-unknown",
        f"Parameter {name!r} is not declared by the catalog entry.",
        "Remove the unsupported parameter.",
    )


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
        authoring_capabilities=(
            ScenarioRecipeAuthoringCapabilitiesProjection.manual_only()
        ),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _fake_payload_hash(payload: object) -> str:
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


__all__ = [
    "DeterministicFakeScenarioLabAdapter",
    "LiveScenarioLabAdapter",
    "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
]
