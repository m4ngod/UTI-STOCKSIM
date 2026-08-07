"""EventBridge.

Responsibilities:
- subscribe to backend snapshot topics and batch them for frontend refresh
- allow manual snapshot injection for tests/headless flows
- support Redis subscriber fallback to local EventBus
- provide a process-level singleton bridge for GUI/headless startup paths
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any, Callable, Dict, List, Optional, Union

from infra.event_bus import event_bus

try:
    from stock_sim.infra.event_bus import event_bus as runtime_event_bus  # type: ignore
except Exception:  # pragma: no cover
    runtime_event_bus = event_bus  # type: ignore

from app.core_dto import SnapshotDTO
from observability.metrics import metrics


BACKEND_SNAPSHOT_TOPIC = "market.snapshot"
BACKEND_RUNTIME_SNAPSHOT_TOPIC = "SnapshotUpdated"
FRONTEND_SNAPSHOT_BATCH_TOPIC = "frontend.snapshot.batch"
AGENT_STATUS_CHANGED_TOPIC = "agent-status-changed"
INSTRUMENT_CREATED_TOPIC = "instrument-created"
TRADE_EXECUTED_TOPIC = "trade.executed"
ORDER_SUBMITTED_TOPIC = "order.submitted"
ACCOUNT_CREATED_TOPIC = "account.created.canonical"
ACCOUNT_UPDATED_TOPIC = "account.updated"
ORDER_REJECTED_TOPIC = "order.rejected"
ORDER_CANCELED_TOPIC = "order.canceled"


@dataclass(frozen=True, slots=True)
class EventBridgeGenerationId:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("EventBridge generation must be positive")


class EventBridgeConnectionPhase(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class EventBridgeSourceMode(str, Enum):
    PRIMARY = "primary"
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class EventBridgeConnectionSequence:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("EventBridge connection sequence must be positive")


class EventBridgeTerminalPhase(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class EventBridgeConnectionState:
    generation: EventBridgeGenerationId
    sequence: EventBridgeConnectionSequence
    phase: EventBridgeConnectionPhase
    source_mode: EventBridgeSourceMode


@dataclass(frozen=True, slots=True)
class EventBridgeRunTerminal:
    run_id: str
    phase: EventBridgeTerminalPhase


@dataclass(frozen=True, slots=True)
class EventBridgeBatch:
    generation: EventBridgeGenerationId
    snapshots: tuple[Dict[str, Any], ...]
    terminal: bool
    run_terminals: tuple[EventBridgeRunTerminal, ...]

    def terminal_phase_for(
        self,
        run_id: str,
    ) -> EventBridgeTerminalPhase | None:
        for terminal in reversed(self.run_terminals):
            if terminal.run_id == run_id:
                return terminal.phase
        return None


def _terminal_phase(
    snapshot: Dict[str, Any],
) -> EventBridgeTerminalPhase | None:
    status = str(
        snapshot.get("status")
        or snapshot.get("lifecycle")
        or ""
    ).strip().lower()
    if status == "completed":
        return EventBridgeTerminalPhase.COMPLETED
    if status == "failed":
        return EventBridgeTerminalPhase.FAILED
    if status in {"canceled", "cancelled"}:
        return EventBridgeTerminalPhase.CANCELED
    if snapshot.get("terminal"):
        return EventBridgeTerminalPhase.COMPLETED
    return None


try:  # pragma: no cover
    from PySide6.QtCore import QObject, Signal  # type: ignore
except Exception:  # pragma: no cover
    class QObject:  # type: ignore
        pass

    class Signal:  # type: ignore
        def __init__(self, *_, **__):
            pass

        def emit(self, *_: Any, **__: Any):
            pass


class _BridgeSignals(QObject):
    snapshots = Signal(list)


try:  # pragma: no cover
    from app.services.redis_subscriber import RedisSubscriber  # type: ignore
except Exception:  # pragma: no cover
    RedisSubscriber = None  # type: ignore


class EventBridge:
    def __init__(
        self,
        *,
        flush_interval_ms: int = 50,
        max_batch_size: int = 500,
        subscribe_backend: bool = True,
        use_redis: bool = False,
        redis_channels: Optional[List[str]] = None,
        redis_subscriber_factory: Optional[Callable[[List[str], Callable[[str, Any], None]], Any]] = None,
    ):
        self.flush_interval_ms = flush_interval_ms
        self.max_batch_size = max_batch_size
        self._subscribe_backend = subscribe_backend
        self._running = False
        self._th: Optional[Thread] = None
        self._stop_evt = Event()
        self._lock = RLock()
        self._snapshots: List[
            tuple[EventBridgeGenerationId, Dict[str, Any]]
        ] = []
        self.flush_count = 0
        self.signals = _BridgeSignals()
        self._last_flush_ts = time.time()
        self._use_redis = use_redis and (RedisSubscriber is not None)
        self._redis_channels = redis_channels or [BACKEND_SNAPSHOT_TOPIC]
        self._redis_subscriber_factory = redis_subscriber_factory
        self._redis_subscriber: Optional[Any] = None
        self._fallback_done = False
        self._local_subscribed = False
        self._local_handlers: list[tuple[Any, str, Callable[[str, dict], None]]] = []
        self._batch_observers: dict[
            int,
            Callable[[EventBridgeBatch], None],
        ] = {}
        self._next_batch_observer_id = 1
        self._connection_generation = EventBridgeGenerationId(1)
        self._connection_sequence = EventBridgeConnectionSequence(1)
        self._connection_phase = EventBridgeConnectionPhase.CONNECTED
        self._source_mode = EventBridgeSourceMode.PRIMARY
        self._connection_observers: dict[
            int,
            Callable[[EventBridgeConnectionState], None],
        ] = {}
        self._next_connection_observer_id = 1

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        if self._subscribe_backend and not self._use_redis:
            self._enable_local_subscription()
        if self._use_redis:
            self._start_redis()
        self._th = Thread(target=self._loop, daemon=True)
        self._th.start()

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._redis_subscriber:
            try:
                self._redis_subscriber.stop()
            except Exception:
                pass
        thread = self._th
        if thread is not None and thread is not current_thread():
            thread.join()
        if thread is not None and not thread.is_alive():
            self._th = None
        self.flush(force=True)
        self._disable_local_subscription()

    @property
    def connection_generation(self) -> EventBridgeGenerationId:
        return self.connection_state.generation

    @property
    def connection_state(self) -> EventBridgeConnectionState:
        with self._lock:
            return self._connection_state_locked()

    def on_snapshot(
        self,
        snap: Union[SnapshotDTO, Dict[str, Any]],
        *,
        generation: EventBridgeGenerationId | int | None = None,
    ):
        if isinstance(snap, SnapshotDTO):
            payload = snap.model_dump() if hasattr(snap, "model_dump") else snap.dict()
        else:
            payload = snap
        with self._lock:
            generation_id = self._coerce_generation(generation)
            self._snapshots.append((generation_id, payload))
            if len(self._snapshots) >= self.max_batch_size:
                self._flush_locked()

    def flush(self, *, force: bool = False):
        with self._lock:
            if not self._snapshots:
                return
            if force:
                self._flush_locked()
            else:
                self._flush_locked()

    def subscribe_batches(
        self,
        observer: Callable[[EventBridgeBatch], None],
    ) -> Callable[[], None]:
        with self._lock:
            observer_id = self._next_batch_observer_id
            self._next_batch_observer_id += 1
            self._batch_observers[observer_id] = observer

        def _dispose() -> None:
            with self._lock:
                self._batch_observers.pop(observer_id, None)

        return _dispose

    def subscribe_connection_state(
        self,
        observer: Callable[[EventBridgeConnectionState], None],
        *,
        replay_current: bool = False,
    ) -> Callable[[], None]:
        with self._lock:
            observer_id = self._next_connection_observer_id
            self._next_connection_observer_id += 1
            self._connection_observers[observer_id] = observer
            current = (
                self._connection_state_locked()
                if replay_current
                else None
            )

        if current is not None:
            self._notify_connection_observers((observer,), current)

        def _dispose() -> None:
            with self._lock:
                self._connection_observers.pop(observer_id, None)

        return _dispose

    def mark_disconnected(self) -> EventBridgeConnectionState:
        with self._lock:
            if self._connection_phase is EventBridgeConnectionPhase.DISCONNECTED:
                return self._connection_state_locked()
            self._connection_phase = EventBridgeConnectionPhase.DISCONNECTED
            self._advance_connection_sequence_locked()
            state = self._connection_state_locked()
            observers = tuple(self._connection_observers.values())
        self._notify_connection_observers(observers, state)
        return state

    def mark_reconnected(self) -> EventBridgeConnectionState:
        with self._lock:
            if self._connection_phase is EventBridgeConnectionPhase.CONNECTED:
                return self._connection_state_locked()
            self._connection_generation = EventBridgeGenerationId(
                self._connection_generation.value + 1
            )
            self._connection_phase = EventBridgeConnectionPhase.CONNECTED
            self._source_mode = EventBridgeSourceMode.PRIMARY
            self._advance_connection_sequence_locked()
            state = self._connection_state_locked()
            observers = tuple(self._connection_observers.values())
        self._notify_connection_observers(observers, state)
        return state

    def mark_fallback_active(self) -> EventBridgeConnectionState:
        """Expose a safe source-mode transition for live Adapter recovery."""

        with self._lock:
            if (
                self._connection_phase is EventBridgeConnectionPhase.CONNECTED
                and self._source_mode is EventBridgeSourceMode.FALLBACK
            ):
                return self._connection_state_locked()
            self._connection_generation = EventBridgeGenerationId(
                self._connection_generation.value + 1
            )
            self._connection_phase = EventBridgeConnectionPhase.CONNECTED
            self._source_mode = EventBridgeSourceMode.FALLBACK
            self._advance_connection_sequence_locked()
            state = self._connection_state_locked()
            observers = tuple(self._connection_observers.values())
        self._notify_connection_observers(observers, state)
        return state

    def _loop(self):
        interval_sec = self.flush_interval_ms / 1000.0
        while self._running and not self._stop_evt.wait(interval_sec):
            self._check_fallback()
            with self._lock:
                if not self._snapshots:
                    continue
                self._flush_locked()
        self._check_fallback()

    def _flush_locked(self):
        if not self._snapshots:
            return
        entries = self._snapshots
        self._snapshots = []
        self.flush_count += 1
        self._last_flush_ts = time.time()
        batch = [payload for _, payload in entries]
        try:
            self.signals.snapshots.emit(batch)  # type: ignore[attr-defined]
        except Exception:
            pass
        payload = {"snapshots": batch, "count": len(batch)}
        try:
            event_bus.publish(FRONTEND_SNAPSHOT_BATCH_TOPIC, payload)
        except Exception:
            pass
        if runtime_event_bus is not event_bus:
            try:
                runtime_event_bus.publish(FRONTEND_SNAPSHOT_BATCH_TOPIC, payload)
            except Exception:
                pass
        grouped: dict[EventBridgeGenerationId, list[Dict[str, Any]]] = {}
        for generation, item in entries:
            grouped.setdefault(generation, []).append(item)
        observers = tuple(self._batch_observers.values())
        for generation, items in grouped.items():
            immutable_batch = tuple(dict(item) for item in items)
            terminal_phases = tuple(
                phase
                for item in items
                if (phase := _terminal_phase(item)) is not None
            )
            run_terminals = tuple(
                EventBridgeRunTerminal(
                    run_id=run_id,
                    phase=phase,
                )
                for item in items
                if (phase := _terminal_phase(item)) is not None
                if (run_id := str(item.get("run_id") or "").strip())
            )
            envelope = EventBridgeBatch(
                generation=generation,
                snapshots=immutable_batch,
                terminal=bool(terminal_phases),
                run_terminals=run_terminals,
            )
            for observer in observers:
                try:
                    observer(envelope)
                except Exception:
                    pass

    def _normalize_snapshot_payload(self, topic: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        if topic == BACKEND_SNAPSHOT_TOPIC:
            return dict(payload)
        if topic != BACKEND_RUNTIME_SNAPSHOT_TOPIC:
            return None
        snap = payload.get("snapshot") or {}
        symbol = payload.get("symbol") or snap.get("symbol")
        if not symbol:
            return None
        ts_ms = payload.get("ts_ms") or snap.get("ts_ms") or snap.get("ts") or int(time.time() * 1000)
        try:
            ts_ms = int(ts_ms)
        except Exception:
            ts_ms = int(time.time() * 1000)
        sim_dt = payload.get("sim_dt")
        if isinstance(sim_dt, str) and sim_dt:
            try:
                ts_ms = int(time.mktime(time.strptime(sim_dt.split(".")[0], "%Y-%m-%dT%H:%M:%S")) * 1000)
            except Exception:
                ts_ms = int(time.time() * 1000)
        return {
            "symbol": symbol,
            "run_id": payload.get("run_id"),
            "last": float(snap.get("last") or 0.0),
            "bid_levels": list(snap.get("bids") or []),
            "ask_levels": list(snap.get("asks") or []),
            "volume": int(snap.get("vol") or 0),
            "turnover": float(snap.get("turnover") or 0.0),
            "ts": ts_ms,
            "snapshot_id": f"{symbol}-{payload.get('run_id') or 'runtime'}-{ts_ms}",
        }

    def _on_backend_snapshot(self, topic: str, payload: Dict[str, Any]):
        normalized = self._normalize_snapshot_payload(topic, payload)
        if normalized is None:
            return
        self.on_snapshot(normalized)

    def _start_redis(self):
        if not self._use_redis:
            return
        if self._redis_subscriber is not None:
            return
        try:
            factory = self._redis_subscriber_factory or self._default_redis_factory
            self._redis_subscriber = factory(self._redis_channels, self._on_redis_message)
            self._redis_subscriber.start()
        except Exception:
            self._fallback_done = True
            metrics.inc("redis_fallback")
            self._rotate_connection_generation()
            if self._subscribe_backend:
                self._enable_local_subscription()

    def _default_redis_factory(self, channels: List[str], cb: Callable[[str, Any], None]):
        if RedisSubscriber is None:
            raise RuntimeError("RedisSubscriber unavailable")
        return RedisSubscriber(channels, lambda ch, data: cb(ch, data))

    def _on_redis_message(self, channel: str, data: Any):
        if channel == BACKEND_SNAPSHOT_TOPIC and isinstance(data, dict):
            self.on_snapshot(data)

    def _check_fallback(self):
        if self._fallback_done:
            return
        rs = self._redis_subscriber
        if not rs:
            return
        try:
            fallback = getattr(rs, "fallback", False)
        except Exception:
            fallback = False
        if fallback:
            self._fallback_done = True
            metrics.inc("redis_fallback")
            self._rotate_connection_generation()
            if self._subscribe_backend and not self._local_subscribed:
                self._enable_local_subscription()

    def _rotate_connection_generation(self) -> EventBridgeConnectionState:
        with self._lock:
            self._connection_generation = EventBridgeGenerationId(
                self._connection_generation.value + 1
            )
            self._connection_phase = EventBridgeConnectionPhase.CONNECTED
            self._source_mode = EventBridgeSourceMode.FALLBACK
            self._advance_connection_sequence_locked()
            state = self._connection_state_locked()
            observers = tuple(self._connection_observers.values())
        self._notify_connection_observers(observers, state)
        return state

    def _connection_state_locked(self) -> EventBridgeConnectionState:
        return EventBridgeConnectionState(
            generation=self._connection_generation,
            sequence=self._connection_sequence,
            phase=self._connection_phase,
            source_mode=self._source_mode,
        )

    def _advance_connection_sequence_locked(self) -> None:
        self._connection_sequence = EventBridgeConnectionSequence(
            self._connection_sequence.value + 1
        )

    @staticmethod
    def _notify_connection_observers(
        observers: tuple[Callable[[EventBridgeConnectionState], None], ...],
        state: EventBridgeConnectionState,
    ) -> None:
        for observer in observers:
            try:
                observer(state)
            except Exception:
                pass

    def _coerce_generation(
        self,
        value: EventBridgeGenerationId | int | None,
    ) -> EventBridgeGenerationId:
        if value is None:
            return self._connection_generation
        if isinstance(value, EventBridgeGenerationId):
            return value
        return EventBridgeGenerationId(int(value))

    def _enable_local_subscription(self):
        if self._local_subscribed:
            return
        self._subscribe_local_bus(event_bus)
        if runtime_event_bus is not event_bus:
            self._subscribe_local_bus(runtime_event_bus)
        self._local_subscribed = True

    def _disable_local_subscription(self):
        if not self._local_handlers:
            self._local_subscribed = False
            return
        for bus, topic, handler in list(self._local_handlers):
            try:
                bus.unsubscribe(topic, handler)
            except Exception:
                pass
        self._local_handlers.clear()
        self._local_subscribed = False

    def _subscribe_local_bus(self, bus: Any) -> None:
        for topic in (BACKEND_SNAPSHOT_TOPIC, BACKEND_RUNTIME_SNAPSHOT_TOPIC):
            try:
                handler = bus.subscribe(topic, self._on_backend_snapshot)
                self._local_handlers.append((bus, topic, handler))
            except Exception:
                pass


_frontend_bridge_lock = RLock()
_frontend_bridge: Optional[EventBridge] = None


def subscribe_topic(topic: str, handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    registered = [(event_bus, event_bus.subscribe(topic, handler, async_mode=async_mode))]
    if runtime_event_bus is not event_bus:
        registered.append((runtime_event_bus, runtime_event_bus.subscribe(topic, handler, async_mode=async_mode)))

    def _cancel():
        for bus, sub in list(registered):
            try:
                bus.unsubscribe(topic, sub)
            except Exception:
                pass

    return _cancel


def on_agent_status_changed(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return subscribe_topic(AGENT_STATUS_CHANGED_TOPIC, handler, async_mode=async_mode)


def on_instrument_created(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return subscribe_topic(INSTRUMENT_CREATED_TOPIC, handler, async_mode=async_mode)


def _subscribe_deduped_topics(
    handler: Callable[[str, dict], None],
    topics: list[str],
    *,
    async_mode: bool = False,
) -> Callable[[], None]:
    seen: dict[int, float] = {}
    seen_lock = RLock()

    def _wrapped(topic: str, payload: dict) -> None:
        key = id(payload)
        now = time.time()
        with seen_lock:
            last = seen.get(key)
            seen[key] = now
            stale = [k for k, ts in seen.items() if now - ts > 1.0]
            for stale_key in stale:
                seen.pop(stale_key, None)
        if last is not None and (now - last) <= 1.0:
            return
        handler(topic, payload)

    cancels = [subscribe_topic(topic, _wrapped, async_mode=async_mode) for topic in topics]

    def _cancel() -> None:
        for cancel in list(cancels):
            try:
                cancel()
            except Exception:
                pass

    return _cancel


def on_trade_executed(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [TRADE_EXECUTED_TOPIC, "Trade", "TradeEvent"], async_mode=async_mode)


def on_order_submitted(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [ORDER_SUBMITTED_TOPIC, "frontend.order.submitted"], async_mode=async_mode)


def on_account_created(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [ACCOUNT_CREATED_TOPIC, "account.created"], async_mode=async_mode)


def on_account_updated(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [ACCOUNT_UPDATED_TOPIC, "AccountUpdated"], async_mode=async_mode)


def on_order_rejected(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [ORDER_REJECTED_TOPIC, "OrderRejected"], async_mode=async_mode)


def on_order_canceled(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return _subscribe_deduped_topics(handler, [ORDER_CANCELED_TOPIC, "OrderCanceled"], async_mode=async_mode)


def publish_agent_status_changed(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(AGENT_STATUS_CHANGED_TOPIC, payload)
        except Exception:
            pass


def publish_instrument_created(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(INSTRUMENT_CREATED_TOPIC, payload)
        except Exception:
            pass


def publish_trade_payload(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(TRADE_EXECUTED_TOPIC, payload)
        except Exception:
            pass
        try:
            bus.publish("Trade", payload)
        except Exception:
            pass
        try:
            bus.publish("TradeEvent", payload)
        except Exception:
            pass


def publish_order_submitted(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(ORDER_SUBMITTED_TOPIC, payload)
        except Exception:
            pass
        try:
            bus.publish("frontend.order.submitted", payload)
        except Exception:
            pass


def publish_account_created(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(ACCOUNT_CREATED_TOPIC, payload)
        except Exception:
            pass
        try:
            bus.publish("account.created", payload)
        except Exception:
            pass


def publish_account_updated(payload: Dict[str, Any]) -> None:
    for bus in ({event_bus} if runtime_event_bus is event_bus else {event_bus, runtime_event_bus}):
        try:
            bus.publish(ACCOUNT_UPDATED_TOPIC, payload)
        except Exception:
            pass
        try:
            bus.publish("AccountUpdated", payload)
        except Exception:
            pass


def get_frontend_bridge() -> Optional[EventBridge]:
    with _frontend_bridge_lock:
        return _frontend_bridge


def start_frontend_bridge(*, flush_interval_ms: int = 50, max_batch_size: int = 500) -> EventBridge:
    global _frontend_bridge
    with _frontend_bridge_lock:
        if _frontend_bridge is None:
            _frontend_bridge = EventBridge(
                flush_interval_ms=flush_interval_ms,
                max_batch_size=max_batch_size,
                subscribe_backend=True,
            )
            _frontend_bridge.start()
        return _frontend_bridge


def stop_frontend_bridge() -> None:
    global _frontend_bridge
    with _frontend_bridge_lock:
        bridge = _frontend_bridge
        _frontend_bridge = None
    if bridge is None:
        return
    try:
        bridge.stop()
    except Exception:
        pass


__all__ = [
    "EventBridge",
    "EventBridgeBatch",
    "EventBridgeConnectionPhase",
    "EventBridgeConnectionSequence",
    "EventBridgeConnectionState",
    "EventBridgeGenerationId",
    "EventBridgeRunTerminal",
    "EventBridgeTerminalPhase",
    "BACKEND_SNAPSHOT_TOPIC",
    "BACKEND_RUNTIME_SNAPSHOT_TOPIC",
    "FRONTEND_SNAPSHOT_BATCH_TOPIC",
    "AGENT_STATUS_CHANGED_TOPIC",
    "INSTRUMENT_CREATED_TOPIC",
    "TRADE_EXECUTED_TOPIC",
    "ORDER_SUBMITTED_TOPIC",
    "ACCOUNT_CREATED_TOPIC",
    "ACCOUNT_UPDATED_TOPIC",
    "ORDER_REJECTED_TOPIC",
    "ORDER_CANCELED_TOPIC",
    "get_frontend_bridge",
    "start_frontend_bridge",
    "stop_frontend_bridge",
    "subscribe_topic",
    "publish_trade_payload",
    "publish_order_submitted",
    "publish_account_created",
    "publish_account_updated",
    "publish_agent_status_changed",
    "publish_instrument_created",
    "on_agent_status_changed",
    "on_instrument_created",
    "on_trade_executed",
    "on_order_submitted",
    "on_account_created",
    "on_account_updated",
    "on_order_rejected",
    "on_order_canceled",
]
