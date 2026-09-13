"""Exact-assets compatibility extension of Strategy Library, not a seventh Feature."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import replace
from threading import RLock
from typing import TYPE_CHECKING, cast

from strategy_diagnostics import asset_queries as application_queries
from strategy_diagnostics.strategy_inventory import StrategyUnderTestInventory, StrategyUnderTestInventoryEntry

from ._diagnostics_application_access import shared_diagnostics_application_access_gate
from .capabilities import FeatureExtensionDescriptor, FeatureOperationDescriptor
from .strategy_asset_contract import (
    AssetQueryDisposition, AssetQueryReason, AssetQueryReasonCode, ExactAssetKind,
    ExactAssetQuery, ExactAssetQueryResult, ExactStrategyAsset, StrategyAssetSummary,
    StrategyAssetQueryState,
)
from .strategy_library_application import project_strategy_library_entry
from .versioning import FeatureInterfaceVersion, FeatureModuleName
from .run_monitoring import Completeness, Freshness, SourceGenerationId, SourceKind, Subscription, ViewPhase
from app.event_bridge import EventBridgeConnectionPhase, EventBridgeConnectionState

if TYPE_CHECKING:
    from app.event_bridge import EventBridge
    from strategy_diagnostics.application import DiagnosticsApplication


def _reference(entry: StrategyUnderTestInventoryEntry) -> ExactStrategyAsset:
    target = application_queries.ExactStrategyAsset.from_entry(entry)
    return ExactStrategyAsset(ExactAssetKind(target.kind.value), target.lineage_id, target.version_id, target.content_hash)


def _application_request(request: ExactAssetQuery) -> application_queries.ExactAssetQuery:
    # Preserve malformed fields for the application's structured validation;
    # never misclassify a projection error as a transient source outage.
    if isinstance(request.target, ExactStrategyAsset):
        kind = (application_queries.ExactAssetKind(request.target.kind.value)
                if isinstance(request.target.kind, ExactAssetKind)
                else cast(application_queries.ExactAssetKind, request.target.kind))
        target = application_queries.ExactStrategyAsset(kind, request.target.lineage_id,
            request.target.version_id, request.target.content_hash)
    else:
        target = cast(application_queries.ExactStrategyAsset, request.target)
    return application_queries.ExactAssetQuery(request.operation_id, target, request.expected_revision,
        request.frozen_input_hash, request.operation, request.operation_version)


def _result(request: ExactAssetQuery, result: application_queries.ExactAssetQueryResult) -> ExactAssetQueryResult:
    reason = result.reason
    return ExactAssetQueryResult(request, AssetQueryDisposition(result.disposition.value), result.source_revision,
        None if result.asset is None else project_strategy_library_entry(result.asset),
        None if reason is None else AssetQueryReason(AssetQueryReasonCode(reason.code.value), reason.message,
                                                     reason.semantic_target, reason.retryable))


class _Subscription:
    def __init__(self, remove: Callable[[], None]) -> None:
        self._remove = remove
        self._disposed = False
        self._revision = 0
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
        self._remove()

    def deliver(self, observer: Callable[[StrategyAssetQueryState], None], state: StrategyAssetQueryState) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._revision:
                return
            self._revision = state.revision
            try:
                observer(state)
            except Exception:  # noqa: BLE001 - isolate presentation observers
                return


class StrategyAssetQueriesAdapter:
    """Public observation seam; execution/receipts remain owned by the application."""

    @property
    def extension_descriptor(self) -> FeatureExtensionDescriptor:
        return FeatureExtensionDescriptor(
            FeatureModuleName.STRATEGY_LIBRARY, "exact_assets", FeatureInterfaceVersion(1, 0),
            ("exact-asset-query/1.0", "legacy-strategy-asset/1.0", "strategy-asset-observation/1.0"),
            tuple(FeatureOperationDescriptor(name, FeatureInterfaceVersion(1, 0))
                  for name in ("snapshot", "subscribe", "refresh", "query_exact_asset", "close")),
            "strategy_library_queries",
        )

    def __init__(
        self, *, read_inventory: Callable[[], StrategyUnderTestInventory],
        query: Callable[[ExactAssetQuery], ExactAssetQueryResult],
        source_kind: SourceKind, executor: Executor | None = None,
        event_bridge: EventBridge | None = None,
    ) -> None:
        self._read_inventory = read_inventory
        self._query = query
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="strategy-assets")
        self._owns_executor = executor is None
        self._lock = RLock()
        self._closed = False
        self._epoch = 0
        self._subscriptions: dict[_Subscription, Callable[[StrategyAssetQueryState], None]] = {}
        self._state = StrategyAssetQueryState(
            1, SourceGenerationId(1 if event_bridge is None else event_bridge.connection_state.generation.value),
            source_kind, None, ViewPhase.READY, Freshness.AWAITING_FIRST_STATE, Completeness.UNKNOWN,
        )
        connection = None if event_bridge is None else event_bridge.connection_state
        self._connection_sequence = 0 if connection is None else connection.sequence.value
        self._connected = connection is None or connection.phase is EventBridgeConnectionPhase.CONNECTED
        if not self._connected:
            self._state = replace(self._state, phase=ViewPhase.DEGRADED, freshness=Freshness.DISCONNECTED)
        self._dispose_connection: Callable[[], None] = (
            (lambda: None) if event_bridge is None else
            event_bridge.subscribe_connection_state(self._on_connection, replay_current=True)
        )

    def snapshot(self) -> StrategyAssetQueryState:
        with self._lock:
            self._ensure_open()
            return self._state

    def subscribe(self, observer: Callable[[StrategyAssetQueryState], None]) -> Subscription:
        with self._lock:
            self._ensure_open()
            subscription = _Subscription(lambda: self._remove(subscription))
            self._subscriptions[subscription] = observer
            state = self._state
        subscription.deliver(observer, state)
        return subscription

    def refresh(self) -> StrategyAssetQueryState:
        return self._submit(self._read_inventory, None)

    def query_exact_asset(self, request: ExactAssetQuery, expected_source_generation: SourceGenerationId) -> StrategyAssetQueryState:
        return self._submit(lambda: self._query(request), request, expected_source_generation)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._epoch += 1
            subscriptions = tuple(self._subscriptions)
        self._dispose_connection()
        for subscription in subscriptions:
            subscription.dispose()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, work: Callable[[], StrategyUnderTestInventory | ExactAssetQueryResult], request: ExactAssetQuery | None,
                expected_generation: SourceGenerationId | None = None) -> StrategyAssetQueryState:
        with self._lock:
            self._ensure_open()
            self._epoch += 1
            epoch = self._epoch
            error = None
            if expected_generation is not None and expected_generation != self._state.source_generation:
                error = AssetQueryReason(AssetQueryReasonCode.STALE_SOURCE_GENERATION,
                                         "来源连接已改变；请重新读取精确资产。", "source_generation")
            elif not self._connected:
                error = AssetQueryReason(AssetQueryReasonCode.SOURCE_UNAVAILABLE,
                                         "来源连接不可用；请恢复连接后重新读取。", "source", True)
            retained = self._state.retained_content
            if retained is not None and request is not None and retained.request.target != request.target:
                retained = None
            state = replace(self._state, revision=self._state.revision + 1,
                            phase=ViewPhase.LOADING if error is None else ViewPhase.DEGRADED,
                            request=request, result=(None if error is None or request is None else
                                ExactAssetQueryResult(request, AssetQueryDisposition.REJECTED, self._state.source_revision, None, error)),
                            error=error, retained_content=retained,
                            content_freshness=Freshness.STALE if retained is not None else Freshness.AWAITING_FIRST_STATE)
            self._state = state
        self._deliver(state)
        if error is not None:
            return state
        try:
            future = self._executor.submit(work)
        except RuntimeError as error:
            future = Future()
            future.set_exception(error)
        future.add_done_callback(lambda completed: self._complete(epoch, completed))
        return state

    def _complete(self, epoch: int, future: Future[StrategyUnderTestInventory | ExactAssetQueryResult]) -> None:
        with self._lock:
            if self._closed or epoch != self._epoch:
                return
        try:
            value = future.result()
        except Exception:  # noqa: BLE001 - sanitize failures crossing the worker seam
            with self._lock:
                if self._closed or epoch != self._epoch:
                    return
                error = AssetQueryReason(AssetQueryReasonCode.SOURCE_UNAVAILABLE,
                                         "读取未完成；保留有效旧数据，可重新读取。", "source", True)
                request = self._state.request
                state = replace(self._state, revision=self._state.revision + 1,
                                phase=ViewPhase.FAILED, freshness=Freshness.STALE,
                                content_freshness=Freshness.STALE,
                                error=error, result=(None if request is None else
                                    ExactAssetQueryResult(request, AssetQueryDisposition.REJECTED,
                                                         self._state.source_revision, None, error)))
                self._state = state
            self._deliver(state)
            return
        with self._lock:
            if self._closed or epoch != self._epoch:
                return
            if isinstance(value, StrategyUnderTestInventory):
                assets = tuple(StrategyAssetSummary(_reference(item), item.display.display_name)
                               for item in sorted(value.entries, key=lambda item: (item.strategy_id, item.strategy_version)))
                retained = self._state.retained_content
                if retained is not None and not any(item.reference == retained.request.target for item in assets):
                    retained = None
                state = replace(self._state, revision=self._state.revision + 1,
                                phase=ViewPhase.READY, freshness=Freshness.FRESH,
                                completeness=Completeness.COMPLETE if assets else Completeness.EMPTY,
                                source_revision=value.content_hash, assets=assets, error=None,
                                retained_content=retained)
            else:
                invalid_catalog = value.reason is not None and value.reason.code in {
                    AssetQueryReasonCode.STALE_REVISION, AssetQueryReasonCode.SOURCE_UNAVAILABLE,
                    AssetQueryReasonCode.ASSET_NOT_FOUND, AssetQueryReasonCode.ASSET_CONTENT_MISMATCH,
                }
                catalog_freshness = Freshness.STALE if invalid_catalog else self._state.freshness
                retained = (value if value.asset is not None else self._state.retained_content
                            if value.reason is not None and value.reason.code is AssetQueryReasonCode.SOURCE_UNAVAILABLE
                            else None)
                state = replace(self._state, revision=self._state.revision + 1,
                                phase=ViewPhase.READY if value.reason is None else ViewPhase.FAILED,
                                freshness=catalog_freshness, result=value, error=value.reason,
                                retained_content=retained,
                                content_freshness=(Freshness.FRESH if value.asset is not None
                                    and value.source_revision == self._state.source_revision
                                    and catalog_freshness is Freshness.FRESH else Freshness.STALE))
            self._state = state
        self._deliver(state)

    def _on_connection(self, connection: EventBridgeConnectionState) -> None:
        with self._lock:
            if (self._closed or connection.sequence.value <= self._connection_sequence
                    or connection.generation.value < self._state.source_generation.value):
                return
            self._connection_sequence = connection.sequence.value
            self._connected = connection.phase is EventBridgeConnectionPhase.CONNECTED
            self._epoch += 1
            error = AssetQueryReason(
                AssetQueryReasonCode.SOURCE_UNAVAILABLE,
                "连接已恢复，请显式重新读取。" if self._connected else "来源已断开；保留的数据已标记过期。",
                "source", True,
            )
            state = replace(self._state, revision=self._state.revision + 1,
                            source_generation=SourceGenerationId(connection.generation.value),
                            phase=ViewPhase.DEGRADED,
                            freshness=Freshness.STALE if self._connected else Freshness.DISCONNECTED,
                            content_freshness=Freshness.STALE,
                            error=error)
            self._state = state
        self._deliver(state)

    def _deliver(self, state: StrategyAssetQueryState) -> None:
        with self._lock:
            observers = tuple(self._subscriptions.items())
        for subscription, observer in observers:
            subscription.deliver(observer, state)

    def _remove(self, subscription: _Subscription) -> None:
        with self._lock:
            self._subscriptions.pop(subscription, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Strategy asset queries are closed")


class LiveStrategyAssetQueriesAdapter(StrategyAssetQueriesAdapter):
    def __init__(self, application: DiagnosticsApplication, *, executor: Executor | None = None, event_bridge: EventBridge | None = None) -> None:
        gate = shared_diagnostics_application_access_gate(application)

        def read() -> StrategyUnderTestInventory:
            with gate:
                return application.read_strategy_under_test_inventory()

        def query(request: ExactAssetQuery) -> ExactAssetQueryResult:
            with gate:
                return _result(request, application.query_exact_strategy_asset(_application_request(request)))

        super().__init__(read_inventory=read, query=query, source_kind=SourceKind.LIVE_RUNTIME,
                         executor=executor, event_bridge=event_bridge)


class DeterministicFakeStrategyAssetQueriesAdapter(StrategyAssetQueriesAdapter):
    def __init__(self, inventory: StrategyUnderTestInventory | None = None, *, executor: Executor | None = None, event_bridge: EventBridge | None = None) -> None:
        frozen = inventory
        lock = RLock()

        def read() -> StrategyUnderTestInventory:
            nonlocal frozen
            with lock:
                if frozen is None:
                    from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION
                    from strategy_diagnostics.strategy_inventory import build_strategy_under_test_inventory
                    frozen = build_strategy_under_test_inventory(
                        guardrail_profiles=(), persistence_migration_revision=DIAGNOSTIC_SCHEMA_REVISION,
                    )
                return frozen

        journal = application_queries.ExactStrategyQueries(read)
        super().__init__(read_inventory=read, query=lambda request: _result(request, journal.query(_application_request(request))),
                         source_kind=SourceKind.DETERMINISTIC_FAKE,
                         executor=executor, event_bridge=event_bridge)
