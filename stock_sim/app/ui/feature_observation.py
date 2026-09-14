"""Nonblocking observation of an existing typed Feature, never execution ownership."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock, Thread
from typing import Generic, Protocol, TypeVar

from PySide6.QtCore import QObject, Qt, Signal, Slot

from app.features import Subscription

ContextT = TypeVar("ContextT", contravariant=True)
StateT = TypeVar("StateT", covariant=True)


class ObservableFeature(Protocol[ContextT, StateT]):
    def snapshot(self, context: ContextT) -> StateT: ...

    def subscribe(self, context: ContextT, observer: Callable[[StateT], None]) -> Subscription: ...


class FeatureObservation(QObject, Generic[ContextT, StateT]):
    """Own only a cancellable read/Subscription, including its initial read.

    An inactive initial read can resolve an exact legacy bookmark without keeping
    an inactive page subscribed. The caller keeps the last typed state; this
    module does not fabricate a domain state, generation, command or identity.
    """

    stateReady = Signal(int, object)
    statusChanged = Signal()
    finished = Signal(int, bool)

    def __init__(self, feature: ObservableFeature[ContextT, StateT], *, parent: QObject) -> None:
        super().__init__(parent)
        self._feature = feature
        self._lock = Lock()
        self._generation = 0
        self._closed = False
        self._subscription: Subscription | None = None
        self.pending = False
        self.failed = False
        self.finished.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return not self._closed and generation == self._generation

    def _invalidate(self) -> int:
        with self._lock:
            self._generation += 1
            generation = self._generation
            subscription = self._subscription
            self._subscription = None
        if subscription is not None:
            subscription.dispose()
        return generation

    def start(self, context: ContextT, *, observe: bool) -> None:
        if self._closed:
            return
        generation = self._invalidate()
        self.pending = True
        self.failed = False
        self.statusChanged.emit()
        Thread(target=self._read, args=(generation, context, observe),
               name="feature-page-observation", daemon=True).start()

    def stop(self) -> None:
        self._invalidate()
        self.pending = False
        self.statusChanged.emit()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.stop()

    def _read(self, generation: int, context: ContextT, observe: bool) -> None:
        def deliver(state: StateT) -> None:
            if self.is_current(generation):
                try:
                    self.stateReady.emit(generation, state)
                except RuntimeError:
                    pass  # The QObject can be deleted after the generation check.

        failed = False
        try:
            deliver(self._feature.snapshot(context))
            if not self.is_current(generation):
                return
            if observe:
                subscription = self._feature.subscribe(context, deliver)
                with self._lock:
                    obsolete = self._closed or generation != self._generation
                    if not obsolete:
                        self._subscription = subscription
                if obsolete:
                    subscription.dispose()
            else:
                # Existing Features can first return a typed loading state. A
                # second snapshot resolves that read without a lasting observer.
                deliver(self._feature.snapshot(context))
        except Exception:  # noqa: BLE001 - contain failures at the Feature read seam.
            failed = True
        try:
            self.finished.emit(generation, failed)
        except RuntimeError:
            pass

    @Slot(int, bool)
    def _finish(self, generation: int, failed: bool) -> None:
        if not self.is_current(generation):
            return
        self.pending = False
        self.failed = failed
        self.statusChanged.emit()
