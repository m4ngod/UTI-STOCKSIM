"""Deterministic fake and real EventBridge adapters for issue #33."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from contract import SliceViewState, UiState, advance_state, build_state


class SliceAdapter(QObject):
    state_ready = Signal(object, int, object)

    def __init__(self, ui_state: UiState, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state: SliceViewState = build_state(ui_state)
        self._event_id = 0

    @property
    def state(self) -> SliceViewState:
        return self._state

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_ui_state(self, ui_state: UiState) -> None:
        self._state = build_state(ui_state, revision=self._state.revision + 1)
        self._emit()

    def _emit(self, emitted_ns: int | None = None) -> None:
        self._event_id += 1
        self._state = advance_state(self._state, self._event_id)
        self.state_ready.emit(
            self._state,
            self._event_id,
            emitted_ns if emitted_ns is not None else time.perf_counter_ns(),
        )


class DeterministicFakeAdapter(SliceAdapter):
    """A deterministic 50 ms source with no runtime dependencies."""

    def __init__(self, ui_state: UiState, parent: QObject | None = None) -> None:
        super().__init__(ui_state, parent)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._emit)

    def start(self) -> None:
        self._emit()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()


class RuntimeEventBridgeAdapter(SliceAdapter):
    """Exercise the repository's real EventBridge batching path.

    The injected snapshots are deterministic prototype data, but batching,
    publication, thread handoff, and the local event bus are the production
    runtime components. This keeps the prototype read-only.
    """

    def __init__(self, ui_state: UiState, parent: QObject | None = None) -> None:
        super().__init__(ui_state, parent)
        from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
        from infra.event_bus import event_bus

        self._topic = FRONTEND_SNAPSHOT_BATCH_TOPIC
        self._bus = event_bus
        self._bridge = EventBridge(flush_interval_ms=50, max_batch_size=500)
        self._source_timer = QTimer(self)
        self._source_timer.setInterval(5)
        self._source_timer.timeout.connect(self._inject_burst)
        self._pending_id = 0
        self._bus.subscribe(self._topic, self._on_batch)
        self._subscribed = True
        self._active = False

    def start(self) -> None:
        if not self._subscribed:
            self._bus.subscribe(self._topic, self._on_batch)
            self._subscribed = True
        self._active = True
        self._bridge.start()
        self._source_timer.start()

    def stop(self) -> None:
        # Quarantine a final forced flush from the old connection generation.
        self._active = False
        self._source_timer.stop()
        self._bridge.stop()
        if not self._subscribed:
            return
        unsubscribe = getattr(self._bus, "unsubscribe", None)
        if callable(unsubscribe):
            try:
                unsubscribe(self._topic, self._on_batch)
            except TypeError:
                pass
        self._subscribed = False

    def _inject_burst(self) -> None:
        now_ns = time.perf_counter_ns()
        for _ in range(5):
            self._pending_id += 1
            index = self._pending_id
            snapshot: dict[str, Any] = {
                "symbol": f"SYM{index % 50:03d}",
                "last": 100.0 + (index % 100) * 0.01,
                "volume": index,
                "snapshot_id": f"tech-slice-{index}",
                "_slice_event_id": index,
                "_inject_ns": now_ns,
            }
            self._bridge.on_snapshot(snapshot)

    def _on_batch(self, _topic: str, payload: dict[str, Any]) -> None:
        if not self._active:
            return
        snapshots = payload.get("snapshots") or ()
        if not snapshots:
            return
        latest = snapshots[-1]
        self._event_id = int(latest.get("_slice_event_id", self._event_id + 1))
        self._state = advance_state(self._state, self._event_id)
        self.state_ready.emit(
            self._state,
            self._event_id,
            int(latest.get("_inject_ns", time.perf_counter_ns())),
        )


def make_adapter(name: str, ui_state: UiState) -> SliceAdapter:
    if name == "runtime":
        return RuntimeEventBridgeAdapter(ui_state)
    return DeterministicFakeAdapter(ui_state)
