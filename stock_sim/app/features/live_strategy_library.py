"""Live and deterministic fake Adapters for Strategy Library 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
)

from .diagnostic_tasks_application import GuardrailProfileId
from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .strategy_library import (
    CompareStrategies,
    SelectFormalStrategySet,
    StrategyComparisonDisposition,
    StrategyComparisonResult,
    StrategyLibraryAvailabilityFilter,
    StrategyLibraryBlockingCode,
    StrategyLibraryBlockingReason,
    StrategyLibraryCapabilities,
    StrategyLibraryContext,
    StrategyLibraryObserver,
    StrategyLibraryPresentationState,
    StrategyLibrarySource,
    StrategyLibraryViewState,
    StrategySelectionDisposition,
    StrategySelectionResult,
)
from .strategy_library_application import (
    StrategyAvailability,
    StrategyAvailabilityReason,
    StrategyAvailabilityReasonCode,
    StrategyCompatibilityManifest,
    StrategyDependencyIdentity,
    StrategyDependencyKind,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyDisplayMetadata,
    StrategyGuardrailProfile,
    StrategyGuardrailThreshold,
    StrategyLibraryApplicationAvailability,
    StrategyLibraryApplicationError,
    StrategyLibraryApplicationInventoryResult,
    StrategyLibraryEntry,
    StrategyLibraryInventory,
    StrategySourceIdentity,
)
from .versioning import (
    STRATEGY_LIBRARY_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _StrategyLibrarySubscription:
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
        observer: StrategyLibraryObserver,
        state: StrategyLibraryViewState,
    ) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._last_revision:
                return
            self._last_revision = state.revision
            try:
                observer(state)
            except Exception:  # noqa: BLE001 - observer failures stay isolated.
                return


class _StrategyLibraryAdapter:
    def __init__(
        self,
        *,
        read_inventory: Callable[[], StrategyLibraryApplicationInventoryResult],
        source_kind: SourceKind,
        source_identity: str,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        event_bridge: EventBridge | None = None,
    ) -> None:
        self._read_inventory = read_inventory
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._states: dict[StrategyLibraryContext, StrategyLibraryViewState] = {}
        self._last_reliable_inventory: StrategyLibraryInventory | None = None
        self._last_reliable_availability: (
            StrategyLibraryApplicationAvailability | None
        ) = None
        self._source_token: SourceRevisionToken | None = None
        self._last_reliable_at: datetime | None = None
        self._subscriptions: dict[
            int,
            tuple[
                StrategyLibraryContext,
                StrategyLibraryObserver,
                _StrategyLibrarySubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._revision = 0
        connection = event_bridge.connection_state if event_bridge else None
        self._generation = SourceGenerationId(
            1 if connection is None else connection.generation.value
        )
        self._connection_sequence = (
            1 if connection is None else connection.sequence.value
        )
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
        return STRATEGY_LIBRARY_INTERFACE_VERSION

    def snapshot(
        self,
        context: StrategyLibraryContext,
    ) -> StrategyLibraryViewState:
        with self._lock:
            self._ensure_open()
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
                state = self._disconnected_from_cache(context)
                self._states[context] = state
                return state
            if previous is None and self._last_reliable_inventory is not None:
                state = self._state_from_inventory(
                    context=context,
                    inventory=self._last_reliable_inventory,
                    source_token=self._source_token,
                    availability=(
                        self._last_reliable_availability
                        or _inventory_availability(
                            self._last_reliable_inventory
                        )
                    ),
                )
                self._states[context] = state
                return state
        assert previous is not None
        result = self._read_inventory()
        now = _aware(self._clock())
        with self._lock:
            if self._closed:
                return previous
            if (
                generation != self._generation
                or sequence != self._connection_sequence
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return self._states.get(context, previous)
            latest = self._states.get(context, previous)
            if latest is not previous:
                return latest
            if result.error is not None or result.inventory is None:
                state = self._failure_state(
                    context=context,
                    previous=previous,
                    error=result.error,
                    now=now,
                )
            elif (
                previous.freshness is Freshness.FRESH
                and result.source_token == self._source_token
                and previous.source.generation == self._generation
            ):
                return previous
            elif _has_lower_entity_revision(
                result.inventory,
                self._last_reliable_inventory,
            ):
                return previous
            else:
                self._last_reliable_inventory = result.inventory
                self._last_reliable_availability = result.availability
                self._source_token = result.source_token
                self._last_reliable_at = now
                state = self._state_from_inventory(
                    context=context,
                    inventory=result.inventory,
                    source_token=result.source_token,
                    availability=result.availability,
                    observed_at=now,
                )
            self._states[context] = state
            observers = self._observers_for(context)
        self._deliver(observers, state)
        return state

    def subscribe(
        self,
        context: StrategyLibraryContext,
        observer: StrategyLibraryObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _StrategyLibrarySubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
            state = self._states.get(context, state)
        subscription.deliver(observer, state)
        return subscription

    def compare_strategies(
        self,
        command: CompareStrategies,
    ) -> StrategyComparisonResult:
        with self._lock:
            self._ensure_open()
        return StrategyComparisonResult(
            disposition=StrategyComparisonDisposition.NOT_YET_AVAILABLE,
            entries=(),
            message="Strategy comparison is enabled by the next Wave 3 slice.",
        )

    def select_formal_strategy_set(
        self,
        command: SelectFormalStrategySet,
    ) -> StrategySelectionResult:
        with self._lock:
            self._ensure_open()
        return StrategySelectionResult(
            disposition=StrategySelectionDisposition.NOT_YET_AVAILABLE,
            selection=None,
            message="Formal Strategy selection is not available yet.",
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
            dispose_connection = self._dispose_connection_subscription
            dispose_batch = self._dispose_batch_subscription
            self._dispose_connection_subscription = lambda: None
            self._dispose_batch_subscription = lambda: None
        dispose_connection()
        dispose_batch()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _on_connection_state(
        self,
        connection: EventBridgeConnectionState,
    ) -> None:
        with self._lock:
            if (
                self._closed
                or connection.sequence.value <= self._connection_sequence
            ):
                return
            self._generation = SourceGenerationId(connection.generation.value)
            self._connection_sequence = connection.sequence.value
            self._connection_phase = connection.phase
            contexts = tuple(self._states)
        for context in contexts:
            self._publish_connection_state(context, connection.phase)
        if connection.phase is EventBridgeConnectionPhase.CONNECTED:
            for context in contexts:
                self.snapshot(context)

    def _publish_connection_state(
        self,
        context: StrategyLibraryContext,
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
        if not any(_is_strategy_library_invalidation(item) for item in batch.snapshots):
            return
        with self._lock:
            if (
                self._closed
                or batch.generation.value != self._generation.value
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return
            contexts = tuple(self._states)
        for context in contexts:
            self.snapshot(context)

    def _loading_state(
        self,
        context: StrategyLibraryContext,
    ) -> StrategyLibraryViewState:
        now = _aware(self._clock())
        return StrategyLibraryViewState(
            interface_version=STRATEGY_LIBRARY_INTERFACE_VERSION,
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
            presentation=StrategyLibraryPresentationState.LOADING,
            completeness=Completeness.UNKNOWN,
            entries=(),
            last_reliable_inventory=None,
            capabilities=_capabilities(False),
            blocking_reasons=(),
            focus_restoration_id=None,
            error=None,
        )

    def _state_from_inventory(
        self,
        *,
        context: StrategyLibraryContext,
        inventory: StrategyLibraryInventory,
        source_token: SourceRevisionToken | None,
        availability: StrategyLibraryApplicationAvailability,
        observed_at: datetime | None = None,
    ) -> StrategyLibraryViewState:
        now = observed_at or _aware(self._clock())
        entries = _filtered_entries(inventory, context)
        partial = availability is StrategyLibraryApplicationAvailability.PARTIAL
        presentation = (
            StrategyLibraryPresentationState.PARTIAL
            if partial
            else StrategyLibraryPresentationState.EMPTY
            if not entries
            else StrategyLibraryPresentationState.READY
        )
        completeness = (
            Completeness.PARTIAL
            if partial
            else Completeness.EMPTY
            if not entries
            else Completeness.COMPLETE
        )
        focus = (
            context.focus_strategy_id
            if context.focus_strategy_id is not None
            and any(
                item.strategy_id == context.focus_strategy_id for item in entries
            )
            else None
        )
        return StrategyLibraryViewState(
            interface_version=STRATEGY_LIBRARY_INTERFACE_VERSION,
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
            presentation=presentation,
            completeness=completeness,
            entries=entries,
            last_reliable_inventory=inventory,
            capabilities=_capabilities(True),
            blocking_reasons=(
                (
                    StrategyLibraryBlockingReason(
                        code=StrategyLibraryBlockingCode.INVENTORY_PARTIAL,
                        message=(
                            "The authoritative inventory is available, but some "
                            "formal Strategy entries are not campaign-ready."
                        ),
                        dependent_operations=("select_formal_strategy_set",),
                    ),
                )
                if partial
                else ()
            ),
            focus_restoration_id=focus,
            error=None,
        )

    def _failure_state(
        self,
        *,
        context: StrategyLibraryContext,
        previous: StrategyLibraryViewState,
        error: StrategyLibraryApplicationError | None,
        now: datetime,
    ) -> StrategyLibraryViewState:
        structured = StructuredFeatureError(
            code=(
                "strategy_library_inventory_read_failed"
                if error is None
                else error.code.value
            ),
            message=(
                "The authoritative Strategy inventory could not be read."
                if error is None
                else error.message
            ),
            retryable=False if error is None else error.retryable,
            correlation_id=None if error is None else error.correlation_id,
        )
        inventory = self._last_reliable_inventory
        entries: tuple[StrategyLibraryEntry, ...]
        if inventory is None:
            entries = ()
            presentation = StrategyLibraryPresentationState.FAILED
            completeness = Completeness.UNKNOWN
            phase = ViewPhase.FAILED
            freshness = Freshness.AWAITING_FIRST_STATE
        else:
            entries = _filtered_entries(inventory, context)
            presentation = StrategyLibraryPresentationState.STALE
            completeness = previous.completeness
            phase = ViewPhase.DEGRADED
            freshness = Freshness.STALE
        return replace(
            previous,
            revision=self._next_revision(),
            observed_at=now,
            last_reliable_at=self._last_reliable_at,
            freshness=freshness,
            age=(
                timedelta(0)
                if self._last_reliable_at is None
                else now - self._last_reliable_at
            ),
            phase=phase,
            presentation=presentation,
            completeness=completeness,
            entries=entries,
            last_reliable_inventory=inventory,
            capabilities=_capabilities(inventory is not None),
            blocking_reasons=(
                StrategyLibraryBlockingReason(
                    code=StrategyLibraryBlockingCode.INVENTORY_READ_FAILED,
                    message=structured.message,
                    dependent_operations=(
                        "compare_strategies",
                        "select_formal_strategy_set",
                    ),
                ),
            ),
            error=structured,
        )

    def _connection_state(
        self,
        previous: StrategyLibraryViewState,
        phase: EventBridgeConnectionPhase,
    ) -> StrategyLibraryViewState:
        now = _aware(self._clock())
        disconnected = phase is EventBridgeConnectionPhase.DISCONNECTED
        has_reliable = self._last_reliable_inventory is not None
        code = (
            StrategyLibraryBlockingCode.SOURCE_DISCONNECTED
            if disconnected
            else StrategyLibraryBlockingCode.SOURCE_RECONNECTING
        )
        message = (
            "Strategy Library is disconnected; retained data may be stale."
            if disconnected
            else "Strategy Library is reconnecting and rereading authority."
        )
        return replace(
            previous,
            revision=self._next_revision(),
            observed_at=now,
            freshness=(
                Freshness.DISCONNECTED if disconnected else Freshness.STALE
            ),
            age=(
                timedelta(0)
                if self._last_reliable_at is None
                else now - self._last_reliable_at
            ),
            source=self._source(),
            phase=ViewPhase.DEGRADED if has_reliable else ViewPhase.FAILED,
            presentation=(
                StrategyLibraryPresentationState.DISCONNECTED
                if disconnected
                else StrategyLibraryPresentationState.STALE
            ),
            capabilities=_capabilities(False),
            blocking_reasons=(
                StrategyLibraryBlockingReason(
                    code=code,
                    message=message,
                    dependent_operations=(
                        "compare_strategies",
                        "select_formal_strategy_set",
                    ),
                ),
            ),
            error=StructuredFeatureError(
                code=code.value,
                message=message,
                retryable=True,
            ),
        )

    def _disconnected_from_cache(
        self,
        context: StrategyLibraryContext,
    ) -> StrategyLibraryViewState:
        inventory = self._last_reliable_inventory
        if inventory is None:
            return self._connection_state(
                self._loading_state(context),
                EventBridgeConnectionPhase.DISCONNECTED,
            )
        return self._connection_state(
            self._state_from_inventory(
                context=context,
                inventory=inventory,
                source_token=self._source_token,
                availability=(
                    self._last_reliable_availability
                    or _inventory_availability(inventory)
                ),
            ),
            EventBridgeConnectionPhase.DISCONNECTED,
        )

    def _source(self) -> StrategyLibrarySource:
        return StrategyLibrarySource(
            kind=self._source_kind,
            identity=self._source_identity,
            generation=self._generation,
        )

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision

    def _observers_for(
        self,
        context: StrategyLibraryContext,
    ) -> tuple[
        tuple[StrategyLibraryObserver, _StrategyLibrarySubscription], ...
    ]:
        return tuple(
            (observer, subscription)
            for subscribed_context, observer, subscription in (
                item for item in self._subscriptions.values()
            )
            if subscribed_context == context and not subscription.disposed
        )

    @staticmethod
    def _deliver(
        observers: tuple[
            tuple[StrategyLibraryObserver, _StrategyLibrarySubscription], ...
        ],
        state: StrategyLibraryViewState,
    ) -> None:
        for observer, subscription in observers:
            subscription.deliver(observer, state)

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Strategy Library Adapter is closed")


class LiveStrategyLibraryAdapter(_StrategyLibraryAdapter):
    def __init__(
        self,
        *,
        application: StrategyDiagnosticsV1StrategyLibraryApplication,
        event_bridge: EventBridge | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        super().__init__(
            read_inventory=application.read_inventory,
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="strategy-diagnostics-v1-strategy-library",
            event_bridge=event_bridge,
            clock=clock,
            freshness_threshold=freshness_threshold,
        )


class DeterministicFakeStrategyLibraryAdapter(_StrategyLibraryAdapter):
    def __init__(
        self,
        *,
        inventory: StrategyLibraryInventory | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        scripted_results: tuple[
            StrategyLibraryApplicationInventoryResult, ...
        ] = (),
    ) -> None:
        resolved_inventory = inventory or _default_inventory()
        self._fake_clock = clock or (lambda: datetime.now(timezone.utc))
        self._scripted_results = list(scripted_results)
        self._default_result = StrategyLibraryApplicationInventoryResult(
            availability=_inventory_availability(resolved_inventory),
            inventory=resolved_inventory,
            source_token=SourceRevisionToken(
                hashlib.sha256(
                    repr(resolved_inventory).encode("utf-8")
                ).hexdigest()
            ),
            observed_at=_aware(self._fake_clock()),
            error=None,
        )
        super().__init__(
            read_inventory=self._read_fake_inventory,
            source_kind=SourceKind.DETERMINISTIC_FAKE,
            source_identity="deterministic-fake-strategy-library",
            clock=self._fake_clock,
            freshness_threshold=freshness_threshold,
        )

    def _read_fake_inventory(self) -> StrategyLibraryApplicationInventoryResult:
        if self._scripted_results:
            self._default_result = self._scripted_results.pop(0)
        return replace(
            self._default_result,
            observed_at=_aware(self._fake_clock()),
        )

    def advance_to_disconnected(self) -> None:
        self._advance_connection(EventBridgeConnectionPhase.DISCONNECTED, False)

    def advance_to_reconnected(self) -> None:
        self._advance_connection(EventBridgeConnectionPhase.CONNECTED, True)

    def deliver_invalidation(self, *, generation: int) -> None:
        with self._lock:
            if (
                self._closed
                or generation != self._generation.value
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return
            contexts = tuple(self._states)
        for context in contexts:
            self.snapshot(context)

    def _advance_connection(
        self,
        phase: EventBridgeConnectionPhase,
        increment_generation: bool,
    ) -> None:
        with self._lock:
            self._ensure_open()
            generation = self._generation.value + (1 if increment_generation else 0)
            self._generation = SourceGenerationId(generation)
            self._connection_sequence += 1
            self._connection_phase = phase
            contexts = tuple(self._states)
        for context in contexts:
            self._publish_connection_state(context, phase)
        if phase is EventBridgeConnectionPhase.CONNECTED:
            for context in contexts:
                self.snapshot(context)


def _filtered_entries(
    inventory: StrategyLibraryInventory,
    context: StrategyLibraryContext,
) -> tuple[StrategyLibraryEntry, ...]:
    search = " ".join(context.search_text.casefold().split())
    expected_availability = (
        None
        if context.availability_filter is StrategyLibraryAvailabilityFilter.ALL
        else StrategyAvailability(context.availability_filter.value)
    )
    return tuple(
        entry
        for entry in inventory.entries
        if (
            expected_availability is None
            or entry.availability is expected_availability
        )
        and (
            not search
            or search
            in " ".join(
                (
                    entry.strategy_id.value,
                    entry.strategy_version,
                    entry.display.display_name,
                    entry.display.summary,
                    *entry.source.lineage,
                    *entry.compatibility.declared_capabilities,
                )
            ).casefold()
        )
        and all(
            capability in entry.compatibility.declared_capabilities
            for capability in context.required_capabilities
        )
    )


def _capabilities(has_inventory: bool) -> StrategyLibraryCapabilities:
    return StrategyLibraryCapabilities(
        can_search=has_inventory,
        can_filter=has_inventory,
        can_inspect_details=has_inventory,
        can_compare=False,
        can_select_formal_strategy_set=False,
    )


def _inventory_availability(
    inventory: StrategyLibraryInventory,
) -> StrategyLibraryApplicationAvailability:
    if not inventory.entries:
        return StrategyLibraryApplicationAvailability.EMPTY
    if all(
        item.availability is StrategyAvailability.FORMAL_CAMPAIGN_READY
        for item in inventory.entries
    ):
        return StrategyLibraryApplicationAvailability.READY
    return StrategyLibraryApplicationAvailability.PARTIAL


def _has_lower_entity_revision(
    incoming: StrategyLibraryInventory,
    reliable: StrategyLibraryInventory | None,
) -> bool:
    if reliable is None:
        return False
    reliable_revisions = {
        (item.strategy_id, item.strategy_version): item.entity_revision
        for item in reliable.entries
    }
    return any(
        item.entity_revision
        < reliable_revisions.get(
            (item.strategy_id, item.strategy_version),
            item.entity_revision,
        )
        for item in incoming.entries
    )


def _is_strategy_library_invalidation(snapshot: dict[str, object]) -> bool:
    kind = str(snapshot.get("kind") or "").strip().casefold()
    return kind in {
        "strategy-library",
        "strategy-inventory",
        "strategy-registration",
        "strategy-guardrail-profile",
    }


def _default_inventory() -> StrategyLibraryInventory:
    return StrategyLibraryInventory(
        entries=(
            _default_entry(
                strategy_id="quentx-live-minute-scenario-native",
                strategy_version="quentx-live-minute-scenario-native.v1",
                display_name="QuentX Live Minute Scenario-native",
                profile_id="guardrail-profile-b7b800744246047283b94874",
                profile_version="live-minute-capital-preservation.v1",
                seed="live-minute",
            ),
            _default_entry(
                strategy_id="quentx-5.2.3-scenario-native",
                strategy_version="quentx-5.2.3-scenario-native.v1",
                display_name="QuentX 5.2.3 Scenario-native",
                profile_id="guardrail-profile-7616a340b156316d79f4b76c",
                profile_version="quentx-balanced-diagnostics.v1",
                seed="quentx-5-2-3",
            ),
        ),
        formal_campaign_required_strategy_count=2,
        persistence_migration_revision=(
            "0018_diagnostic_campaign_attempt_history"
        ),
    )


def _default_entry(
    *,
    strategy_id: str,
    strategy_version: str,
    display_name: str,
    profile_id: str,
    profile_version: str,
    seed: str,
) -> StrategyLibraryEntry:
    source_hash = _fake_hash(f"{seed}:source")
    manifest_hash = _fake_hash(f"{seed}:manifest")
    source = StrategySourceIdentity(
        module=f"strategy_diagnostics.{seed.replace('-', '_')}_strategy",
        source_relative_path=f"strategy_diagnostics/{seed}_strategy.py",
        packaged_relative_path=(
            f"strategy_diagnostics/formal_sources/{seed}_strategy.py.txt"
        ),
        content_sha256=source_hash,
        lineage=(display_name, "scenario-native-adaptation.v1"),
    )
    compatibility = StrategyCompatibilityManifest(
        surface_version="ptrade_surface.v1",
        content_hash=manifest_hash,
        lifecycle_callbacks=("initialize", "handle_data"),
        scheduled_callbacks=("scheduled_scan",),
        scheduling_calls=("run_daily",),
        context_fields=("current_dt", "portfolio", "state"),
        portfolio_fields=("available_cash", "total_value", "positions"),
        market_data_calls=("set_universe", "get_history", "get_current_data"),
        history_units=("1m",),
        configuration_calls=("set_slippage", "set_commission"),
        trading_calls=("order",),
        logging_calls=("log.info", "log.warning", "log.error"),
    )
    profile = StrategyGuardrailProfile(
        strategy_id=StrategyUnderTestId(strategy_id),
        strategy_version=strategy_version,
        profile_id=GuardrailProfileId(profile_id),
        profile_version=profile_version,
        thresholds=(
            StrategyGuardrailThreshold(
                metric_name="maximum_drawdown",
                operator="greater_than",
                value="0.20",
            ),
        ),
    )
    dependency_values = (
        (
            StrategyDependencyKind.RETAINED_SOURCE,
            source.source_relative_path,
            "1",
            source_hash,
        ),
        (
            StrategyDependencyKind.PACKAGED_SOURCE,
            source.packaged_relative_path,
            "1",
            source_hash,
        ),
        (
            StrategyDependencyKind.COMPATIBILITY_MANIFEST,
            f"{strategy_id}@{strategy_version}",
            strategy_version,
            manifest_hash,
        ),
        (
            StrategyDependencyKind.PTRADE_SURFACE,
            "ptrade_surface.v1",
            "ptrade_surface.v1",
            _fake_hash("ptrade_surface.v1"),
        ),
        (
            StrategyDependencyKind.CANDIDATE_DATA_POLICY,
            "active-scenario-point-in-time-only",
            "1",
            _fake_hash("active-scenario-point-in-time-only"),
        ),
        (
            StrategyDependencyKind.GUARDRAIL_PROFILE,
            profile_id,
            profile_version,
            profile_id,
        ),
    )
    return StrategyLibraryEntry(
        strategy_id=StrategyUnderTestId(strategy_id),
        strategy_version=strategy_version,
        entity_revision=1,
        display=StrategyDisplayMetadata(
            display_name=display_name,
            summary="Deterministic formal Strategy fixture.",
        ),
        source=source,
        compatibility=compatibility,
        candidate_data_policy="active-scenario-point-in-time-only",
        guardrail_profile=profile,
        dependencies=tuple(
            StrategyDependencyIdentity(
                kind=kind,
                identity=identity,
                version=version,
                content_hash=content_hash,
                available=True,
                compatible=True,
            )
            for kind, identity, version, content_hash in dependency_values
        ),
        required_for_v1_formal_campaign=True,
        formal_campaign_eligible=True,
        availability=StrategyAvailability.FORMAL_CAMPAIGN_READY,
        availability_reasons=(
            StrategyAvailabilityReason(
                code=StrategyAvailabilityReasonCode.FORMAL_CAMPAIGN_READY,
                summary="All formal Strategy dependencies are current.",
                corrective_guidance="No corrective action is required.",
            ),
        ),
    )


def _fake_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "DeterministicFakeStrategyLibraryAdapter",
    "LiveStrategyLibraryAdapter",
]
