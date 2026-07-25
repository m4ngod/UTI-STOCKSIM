"""Run Monitoring Feature Interface types and deterministic fake Adapter."""

from __future__ import annotations

from dataclasses import dataclass
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


class SourceKind(str, Enum):
    DETERMINISTIC_FAKE = "deterministic_fake"


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


@dataclass(frozen=True, slots=True)
class RunMonitoringSelection:
    campaign_id: FormalDiagnosticCampaignId
    run_id: StrategyRunId

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, FormalDiagnosticCampaignId):
            raise TypeError("campaign_id must be a FormalDiagnosticCampaignId")
        if not isinstance(self.run_id, StrategyRunId):
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
        return cls(selection=selection)


@dataclass(frozen=True, slots=True)
class RunMonitoringSource:
    kind: SourceKind
    identity: str


@dataclass(frozen=True, slots=True)
class StructuredFeatureError:
    code: str
    message: str
    retryable: bool
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunMonitoringData:
    selection: RunMonitoringSelection


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

    def close(self) -> None: ...


def _default_fake_time() -> datetime:
    return datetime(2030, 1, 1, tzinfo=timezone.utc)


class _AdapterSubscription:
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
            tuple[RunMonitoringContext, RunMonitoringObserver, _AdapterSubscription],
        ] = {}
        self._next_subscription_id = 1
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
            subscription = _AdapterSubscription(
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
        observer(state)
        return subscription

    def advance_to_empty(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        if context != RunMonitoringContext.no_selection():
            raise ValueError("Only a no-selection context can advance to empty")
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context)
            if previous is None:
                previous = self._loading_state(context)
            state = RunMonitoringViewState(
                interface_version=self.interface_version,
                revision=previous.revision + 1,
                observed_at=self._clock(),
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
            self._states[context] = state
            observers = tuple(
                observer
                for subscribed_context, observer, _ in self._subscriptions.values()
                if subscribed_context == context
            )
        for observer in observers:
            observer(state)
        return state

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

    @staticmethod
    def _source() -> RunMonitoringSource:
        return RunMonitoringSource(
            kind=SourceKind.DETERMINISTIC_FAKE,
            identity="frontend-v2-run-monitoring-fake",
        )

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Run Monitoring Adapter is closed")


__all__ = [
    "Completeness",
    "DeterministicFakeRunMonitoringAdapter",
    "FormalDiagnosticCampaignId",
    "Freshness",
    "RunMonitoringContext",
    "RunMonitoringData",
    "RunMonitoringFeature",
    "RunMonitoringObserver",
    "RunMonitoringPresentationState",
    "RunMonitoringSelection",
    "RunMonitoringSource",
    "RunMonitoringViewState",
    "SourceKind",
    "StrategyRunId",
    "StructuredFeatureError",
    "Subscription",
    "ViewPhase",
]
