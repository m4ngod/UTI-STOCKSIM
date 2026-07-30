"""Live and deterministic fake Adapters for Diagnostic Tasks 1.0."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from .diagnostic_tasks import (
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTasksBlockingCode,
    DiagnosticTasksBlockingReason,
    DiagnosticTasksCapabilities,
    DiagnosticTasksCommandResult,
    DiagnosticTasksContext,
    DiagnosticTasksObserver,
    DiagnosticTasksPresentationState,
    DiagnosticTasksSource,
    DiagnosticTasksViewState,
    ReproductionManifestAvailability,
)
from .diagnostic_tasks_application import (
    ApproveDiagnosticTaskConfiguration,
    AppliedScenarioTransformation,
    ApprovedScenarioRecipeInput,
    ApprovedScenarioRecipeVersionId,
    CancelDiagnosticTarget,
    CampaignCaseId,
    CreateDiagnosticTask,
    DiagnosticCampaignLayer,
    DiagnosticStrategyInput,
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationCommand,
    DiagnosticTasksApplicationError,
    DiagnosticTasksApplicationInventoryResult,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksInventory,
    ExecutionPolicyValue,
    GuardrailProfileId,
    GuardrailThresholdInput,
    HistoricalMarketSegmentId,
    MarketScenarioInput,
    MarketScenarioMaterializationProvenance,
    MaterializedMarketScenarioId,
    PauseDiagnosticTarget,
    ResumeDiagnosticTarget,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    SourceSnapshotId,
    StartFormalDiagnosticCampaign,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    TransformationParameterValue,
    ValidateDiagnosticTaskConfiguration,
)
from .run_monitoring import (
    Freshness,
    Completeness,
    SourceGenerationId,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .versioning import (
    DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _DiagnosticTasksSubscription:
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


class _UnavailableDiagnosticTasksCommands:
    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def start_formal_diagnostic_campaign(
        self,
        command: StartFormalDiagnosticCampaign,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def pause_diagnostic_target(
        self,
        command: PauseDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def resume_diagnostic_target(
        self,
        command: ResumeDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def cancel_diagnostic_target(
        self,
        command: CancelDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def retry_failed_campaign_node(
        self,
        command: RetryFailedCampaignNode,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    @staticmethod
    def _not_yet_available(
        command: DiagnosticTasksApplicationCommand,
    ) -> DiagnosticTasksCommandResult:
        return DiagnosticTasksCommandResult(
            disposition=DiagnosticTasksCommandDisposition.REJECTED,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            message="This Diagnostic Tasks capability is not yet available.",
            rejection_reason=(
                DiagnosticTaskCommandRejectionReason.NOT_YET_AVAILABLE
            ),
            task_handle=None,
            current_revision=None,
            affected_task_id=None,
            affected_campaign_id=None,
            affected_campaign_node_id=None,
            retryable=False,
            correlation_id=None,
        )


class LiveDiagnosticTasksAdapter(_UnavailableDiagnosticTasksCommands):
    """Typed Feature Adapter over the Diagnostic Tasks Application Interface."""

    def __init__(
        self,
        *,
        application: StrategyDiagnosticsV1DiagnosticTasksApplication,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        self._application = application
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._states: dict[DiagnosticTasksContext, DiagnosticTasksViewState] = {}
        self._source_tokens: dict[
            DiagnosticTasksContext,
            SourceRevisionToken,
        ] = {}
        self._subscriptions: dict[
            int,
            tuple[
                DiagnosticTasksContext,
                DiagnosticTasksObserver,
                _DiagnosticTasksSubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return DIAGNOSTIC_TASKS_INTERFACE_VERSION

    def snapshot(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTasksViewState:
        source = DiagnosticTasksSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="strategy-diagnostics-v1-diagnostic-tasks",
            generation=SourceGenerationId(1),
        )
        with self._lock:
            self._ensure_open()
            current = self._states.get(context)
            current_token = self._source_tokens.get(context)
            if current is None:
                loading = _loading_view_state(
                    context=context,
                    now=_aware(self._clock()),
                    source=source,
                    freshness_threshold=self._freshness_threshold,
                )
                self._states[context] = loading
                return loading
        result = self._application.read_inventory()
        now = _aware(self._clock())
        state = _next_view_state(
            context=context,
            result=result,
            previous=current,
            previous_token=current_token,
            now=now,
            source=source,
            freshness_threshold=self._freshness_threshold,
        )
        with self._lock:
            self._ensure_open()
            if current is state:
                return state
            self._states[context] = state
            if result.source_token is not None and result.error is None:
                self._source_tokens[context] = result.source_token
            observers = tuple(
                observer
                for subscribed_context, observer, subscription in (
                    item for item in self._subscriptions.values()
                )
                if subscribed_context == context and not subscription.disposed
            )
        for observer in observers:
            observer(state)
        return state

    def subscribe(
        self,
        context: DiagnosticTasksContext,
        observer: DiagnosticTasksObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _DiagnosticTasksSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
        observer(state)
        return subscription

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                item[2] for item in self._subscriptions.values()
            )
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Diagnostic Tasks Adapter is closed")


class DeterministicFakeDiagnosticTasksAdapter(
    _UnavailableDiagnosticTasksCommands
):
    """Deterministic Adapter exercising the same formal Feature Interface."""

    def __init__(
        self,
        *,
        inventory: DiagnosticTasksInventory | None = None,
        scripted_results: (
            tuple[DiagnosticTasksApplicationInventoryResult, ...] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        if inventory is not None and scripted_results is not None:
            raise ValueError("inventory and scripted_results are mutually exclusive")
        self._clock = clock or (lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
        self._freshness_threshold = freshness_threshold
        initial_inventory = inventory or _default_inventory()
        self._scripted_results = list(
            scripted_results
            or (
                DiagnosticTasksApplicationInventoryResult(
                    availability=DiagnosticTasksApplicationAvailability.READY,
                    inventory=initial_inventory,
                    source_token=SourceRevisionToken(
                        "0" * 64
                    ),
                    observed_at=_aware(self._clock()),
                    error=None,
                ),
            )
        )
        self._last_scripted_result = self._scripted_results[-1]
        self._states: dict[
            DiagnosticTasksContext,
            DiagnosticTasksViewState,
        ] = {}
        self._source_tokens: dict[
            DiagnosticTasksContext,
            SourceRevisionToken,
        ] = {}
        self._subscriptions: list[
            tuple[
                DiagnosticTasksContext,
                DiagnosticTasksObserver,
                _DiagnosticTasksSubscription,
            ]
        ] = []
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return DIAGNOSTIC_TASKS_INTERFACE_VERSION

    def snapshot(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTasksViewState:
        source = DiagnosticTasksSource(
            kind=SourceKind.DETERMINISTIC_FAKE,
            identity="deterministic-diagnostic-tasks",
            generation=SourceGenerationId(1),
        )
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context)
            previous_token = self._source_tokens.get(context)
            if previous is None:
                loading = _loading_view_state(
                    context=context,
                    now=_aware(self._clock()),
                    source=source,
                    freshness_threshold=self._freshness_threshold,
                )
                self._states[context] = loading
                return loading
            if self._scripted_results:
                self._last_scripted_result = self._scripted_results.pop(0)
            result = self._last_scripted_result
        state = _next_view_state(
            context=context,
            result=result,
            previous=previous,
            previous_token=previous_token,
            now=_aware(self._clock()),
            source=source,
            freshness_threshold=self._freshness_threshold,
        )
        with self._lock:
            self._ensure_open()
            if state is previous:
                return state
            self._states[context] = state
            if result.source_token is not None and result.error is None:
                self._source_tokens[context] = result.source_token
            observers = tuple(
                observer
                for subscribed_context, observer, subscription in self._subscriptions
                if subscribed_context == context and not subscription.disposed
            )
        for observer in observers:
            observer(state)
        return state

    def subscribe(
        self,
        context: DiagnosticTasksContext,
        observer: DiagnosticTasksObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        subscription = _DiagnosticTasksSubscription(lambda: None)
        with self._lock:
            self._ensure_open()
            self._subscriptions.append((context, observer, subscription))
        observer(state)
        return subscription

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(item[2] for item in self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Diagnostic Tasks Adapter is closed")


_UNAVAILABLE_CAPABILITIES = DiagnosticTasksCapabilities(
    can_create=False,
    can_revise=False,
    can_validate=False,
    can_approve=False,
    can_start_campaign=False,
    can_pause=False,
    can_resume=False,
    can_cancel=False,
    can_retry_failed_node=False,
)
_COMMANDS_NOT_YET_AVAILABLE = DiagnosticTasksBlockingReason(
    code=DiagnosticTasksBlockingCode.COMMAND_NOT_YET_AVAILABLE,
    message=(
        "Create, revise, validate, approve, start, lifecycle, and retry "
        "commands are not_yet_available in Issue #56."
    ),
    dependent_operations=(
        "create_diagnostic_task",
        "revise_configuration",
        "validate_configuration",
        "approve_configuration",
        "start_formal_diagnostic_campaign",
        "pause_diagnostic_target",
        "resume_diagnostic_target",
        "cancel_diagnostic_target",
        "retry_failed_campaign_node",
    ),
)


def _loading_view_state(
    *,
    context: DiagnosticTasksContext,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    return DiagnosticTasksViewState(
        interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
        revision=1,
        observed_at=now,
        last_reliable_at=None,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        source=source,
        context=context,
        phase=ViewPhase.LOADING,
        presentation=DiagnosticTasksPresentationState.LOADING,
        completeness=Completeness.UNKNOWN,
        last_reliable_inventory=None,
        task=None,
        capabilities=_UNAVAILABLE_CAPABILITIES,
        blocking_reasons=(_COMMANDS_NOT_YET_AVAILABLE,),
        reproduction_manifest_availability=(
            ReproductionManifestAvailability.NOT_YET_AVAILABLE
        ),
        reproduction_manifest_id=None,
        error=None,
    )


def _next_view_state(
    *,
    context: DiagnosticTasksContext,
    result: DiagnosticTasksApplicationInventoryResult,
    previous: DiagnosticTasksViewState | None,
    previous_token: SourceRevisionToken | None,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    if result.error is not None:
        return _failed_or_degraded_state(
            context=context,
            error=result.error,
            previous=previous,
            now=now,
            source=source,
            freshness_threshold=freshness_threshold,
        )
    if (
        previous is None
        or result.source_token is None
        or result.source_token != previous_token
    ):
        return _reliable_view_state(
            context=context,
            availability=result.availability,
            inventory=result.inventory,
            observed_at=now,
            revision=1 if previous is None else previous.revision + 1,
            source=source,
            freshness_threshold=freshness_threshold,
        )
    previous_reliable_at = previous.last_reliable_at or previous.observed_at
    result_observed_at = _aware(result.observed_at)
    last_reliable_at = max(previous_reliable_at, result_observed_at)
    age = max(now - last_reliable_at, timedelta(0))
    stale = age > freshness_threshold
    presentation, completeness = _inventory_presentation(
        result.availability,
        previous.last_reliable_inventory,
    )
    error = (
        StructuredFeatureError(
            code="diagnostic_tasks_inventory_stale",
            message=(
                "Diagnostic Tasks inventory is older than its freshness "
                "threshold; showing the last reliable state."
            ),
            retryable=True,
        )
        if stale
        else None
    )
    candidate = replace(
        previous,
        revision=previous.revision + 1,
        observed_at=now,
        last_reliable_at=last_reliable_at,
        freshness=Freshness.STALE if stale else Freshness.FRESH,
        age=age,
        phase=ViewPhase.DEGRADED if stale else ViewPhase.READY,
        presentation=(
            DiagnosticTasksPresentationState.DEGRADED
            if stale
            else presentation
        ),
        completeness=completeness,
        blocking_reasons=_inventory_blocking_reasons(
            previous.last_reliable_inventory
        ),
        error=error,
    )
    if (
        candidate.observed_at == previous.observed_at
        and candidate.freshness is previous.freshness
        and candidate.age == previous.age
        and candidate.phase is previous.phase
        and candidate.presentation is previous.presentation
        and candidate.completeness is previous.completeness
        and candidate.blocking_reasons == previous.blocking_reasons
        and candidate.error == previous.error
    ):
        return previous
    return candidate


def _failed_or_degraded_state(
    *,
    context: DiagnosticTasksContext,
    error: DiagnosticTasksApplicationError,
    previous: DiagnosticTasksViewState | None,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    structured_error = StructuredFeatureError(
        code=error.code.value,
        message=error.message,
        retryable=error.retryable,
        correlation_id=error.correlation_id,
    )
    if previous is None or previous.last_reliable_inventory is None:
        return DiagnosticTasksViewState(
            interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
            revision=1 if previous is None else previous.revision + 1,
            observed_at=now,
            last_reliable_at=None,
            freshness=Freshness.STALE,
            age=timedelta(0),
            freshness_threshold=freshness_threshold,
            source=source,
            context=context,
            phase=ViewPhase.FAILED,
            presentation=DiagnosticTasksPresentationState.FAILED,
            completeness=Completeness.UNKNOWN,
            last_reliable_inventory=None,
            task=None,
            capabilities=_UNAVAILABLE_CAPABILITIES,
            blocking_reasons=(
                DiagnosticTasksBlockingReason(
                    code=DiagnosticTasksBlockingCode.INVENTORY_READ_FAILED,
                    message=error.message,
                    dependent_operations=("read_inventory",),
                ),
                _COMMANDS_NOT_YET_AVAILABLE,
            ),
            reproduction_manifest_availability=(
                ReproductionManifestAvailability.NOT_YET_AVAILABLE
            ),
            reproduction_manifest_id=None,
            error=structured_error,
        )
    last_reliable_at = previous.last_reliable_at or previous.observed_at
    age = max(now - last_reliable_at, timedelta(0))
    return replace(
        previous,
        revision=previous.revision + 1,
        observed_at=now,
        freshness=Freshness.STALE,
        age=age,
        phase=ViewPhase.DEGRADED,
        presentation=DiagnosticTasksPresentationState.DEGRADED,
        blocking_reasons=(
            DiagnosticTasksBlockingReason(
                code=DiagnosticTasksBlockingCode.INVENTORY_READ_FAILED,
                message=error.message,
                dependent_operations=("read_inventory",),
            ),
            *_inventory_blocking_reasons(
                previous.last_reliable_inventory
            ),
        ),
        error=structured_error,
    )


def _reliable_view_state(
    *,
    context: DiagnosticTasksContext,
    availability: DiagnosticTasksApplicationAvailability,
    inventory: DiagnosticTasksInventory | None,
    observed_at: datetime,
    revision: int,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    resolved = inventory or DiagnosticTasksInventory(
        strategies=(),
        approved_recipes=(),
        market_scenarios=(),
    )
    presentation, completeness = _inventory_presentation(
        availability,
        resolved,
    )
    return DiagnosticTasksViewState(
        interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
        revision=revision,
        observed_at=observed_at,
        last_reliable_at=observed_at,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        source=source,
        context=context,
        phase=ViewPhase.READY,
        presentation=presentation,
        completeness=completeness,
        last_reliable_inventory=resolved,
        task=None,
        capabilities=_UNAVAILABLE_CAPABILITIES,
        blocking_reasons=_inventory_blocking_reasons(resolved),
        reproduction_manifest_availability=(
            ReproductionManifestAvailability.NOT_YET_AVAILABLE
        ),
        reproduction_manifest_id=None,
        error=None,
    )


def _inventory_presentation(
    availability: DiagnosticTasksApplicationAvailability,
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTasksPresentationState, Completeness]:
    if availability is DiagnosticTasksApplicationAvailability.EMPTY:
        return DiagnosticTasksPresentationState.EMPTY, Completeness.EMPTY
    if availability is DiagnosticTasksApplicationAvailability.INPUT_UNAVAILABLE:
        return (
            DiagnosticTasksPresentationState.INPUT_UNAVAILABLE,
            Completeness.PARTIAL,
        )
    if availability is DiagnosticTasksApplicationAvailability.FAILED:
        return DiagnosticTasksPresentationState.FAILED, Completeness.UNKNOWN
    if inventory is None:
        return DiagnosticTasksPresentationState.EMPTY, Completeness.EMPTY
    return DiagnosticTasksPresentationState.READY, Completeness.COMPLETE


def _inventory_blocking_reasons(
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTasksBlockingReason, ...]:
    reasons: list[DiagnosticTasksBlockingReason] = []
    if inventory is None or not inventory.strategies:
        reasons.append(
            DiagnosticTasksBlockingReason(
                code=(
                    DiagnosticTasksBlockingCode.STRATEGY_LIBRARY_NOT_AVAILABLE
                ),
                message=(
                    "Strategy Library inventory is not available; no strategy "
                    "identity is synthesized."
                ),
                dependent_operations=("create_diagnostic_task",),
            )
        )
    if inventory is None or not inventory.approved_recipes:
        reasons.extend(
            (
                DiagnosticTasksBlockingReason(
                    code=(
                        DiagnosticTasksBlockingCode.APPROVED_RECIPE_NOT_AVAILABLE
                    ),
                    message="No backend-approved Scenario Recipe is available.",
                    dependent_operations=("create_diagnostic_task",),
                ),
                DiagnosticTasksBlockingReason(
                    code=DiagnosticTasksBlockingCode.SCENARIO_LAB_NOT_AVAILABLE,
                    message=(
                        "Scenario Lab authoring is outside Wave 2; no recipe "
                        "placeholder is synthesized."
                    ),
                    dependent_operations=("create_diagnostic_task",),
                ),
            )
        )
    if inventory is None or not inventory.market_scenarios:
        reasons.append(
            DiagnosticTasksBlockingReason(
                code=(
                    DiagnosticTasksBlockingCode.MATERIALIZED_SCENARIO_NOT_AVAILABLE
                ),
                message="No immutable materialized Market Scenario is available.",
                dependent_operations=("create_diagnostic_task",),
            )
        )
    reasons.append(_COMMANDS_NOT_YET_AVAILABLE)
    return tuple(reasons)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _default_inventory() -> DiagnosticTasksInventory:
    recipe_version_id = ApprovedScenarioRecipeVersionId(
        "scenario-recipe-baseline-v1@1"
    )
    return DiagnosticTasksInventory(
        strategies=(
            DiagnosticStrategyInput(
                strategy_id=StrategyUnderTestId("quentx-scenario-native"),
                strategy_version="1.0",
                compatibility_surface_version="1.0",
                compatibility_manifest_hash="sha256:fake-strategy-manifest",
                strategy_module="strategies.quentx_scenario_native",
                guardrail_profile_id=GuardrailProfileId(
                    "guardrail-profile-fake-quentx"
                ),
                guardrail_profile_version="1.0",
                guardrail_thresholds=(
                    GuardrailThresholdInput(
                        metric_name="max_drawdown",
                        operator="<=",
                        value="0.20",
                    ),
                ),
                required=True,
            ),
        ),
        approved_recipes=(
            ApprovedScenarioRecipeInput(
                recipe_version_id=recipe_version_id,
                recipe_id="scenario-recipe-baseline-v1",
                version_number=1,
                content_hash="sha256:fake-approved-recipe",
                schema_version="1.0",
                transformation_catalog_version="scenario-transformations.v1",
            ),
        ),
        market_scenarios=(
            MarketScenarioInput(
                market_scenario_id=MaterializedMarketScenarioId(
                    "sha256:fake-materialized-market-scenario"
                ),
                campaign_case_id=CampaignCaseId("campaign-case-baseline-v1"),
                layer=DiagnosticCampaignLayer.BASELINE,
                recipe_version_id=recipe_version_id,
                recipe_content_hash="sha256:fake-approved-recipe",
                historical_segment_id=HistoricalMarketSegmentId(
                    "historical-segment-baseline-v1"
                ),
                historical_segment_content_hash=(
                    "sha256:fake-historical-segment"
                ),
                source_snapshot_id=SourceSnapshotId(
                    "source-snapshot-baseline-v1"
                ),
                materialization_seed=1,
                transformation_catalog_version="scenario-transformations.v1",
                applied_transformations=(
                    AppliedScenarioTransformation(
                        transformation_id="baseline.v1",
                        family="baseline",
                        catalog_version="scenario-transformations.v1",
                        implementation_version="1.0",
                        parameters=(
                            TransformationParameterValue(
                                name="mode",
                                value="control",
                            ),
                        ),
                    ),
                ),
                materialization_provenance=(
                    MarketScenarioMaterializationProvenance(
                        expander_version="five-minute-to-thirty-second.v1",
                        source_resolution="5m",
                        runtime_resolution="30s",
                        reconstructed=True,
                        numeric_tolerance="1e-12",
                        normalization_provenance="fixture-normalization.v1",
                    )
                ),
                market_rule_profile_version="market-rules.v1",
                comparison_requirement="control",
                execution_policy_values=(
                    ExecutionPolicyValue(
                        name="allow_partial_fills",
                        value="true",
                        version="1.0",
                        source="Approved Scenario Recipe",
                    ),
                ),
            ),
        ),
    )


__all__ = [
    "DeterministicFakeDiagnosticTasksAdapter",
    "LiveDiagnosticTasksAdapter",
]
