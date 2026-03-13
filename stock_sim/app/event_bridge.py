"""EventBridge

职责:
- 订阅后端事件 (如 market.snapshot) 并做前端友好批量聚合
- 提供 on_snapshot/on_event 手动注入接口 (便于测试或离线模式)
- 定时 flush (低延迟, 合并多条 snapshot 减少 UI 频繁刷新)
- 预留 Qt Signal (若 PySide6 可用) 以及 fallback 到 event_bus 发布前端批量主题
- (任务4) 可选 Redis 订阅 + 断线回退本地 EventBus (metrics.redis_fallback++)
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional, Union, Callable
from threading import Thread, Event, RLock
import time

from infra.event_bus import event_bus
from app.core_dto import SnapshotDTO
from observability.metrics import metrics

BACKEND_SNAPSHOT_TOPIC = "market.snapshot"
FRONTEND_SNAPSHOT_BATCH_TOPIC = "frontend.snapshot.batch"
# 新增：常用业务主题常量（供前端订阅器复用）
AGENT_STATUS_CHANGED_TOPIC = "agent-status-changed"
INSTRUMENT_CREATED_TOPIC = "instrument-created"

try:  # Qt 可选
    from PySide6.QtCore import QObject, Signal  # type: ignore
except Exception:  # noqa
    class QObject:  # type: ignore
        pass
    class Signal:  # type: ignore
        def __init__(self, *_, **__):
            pass
        def emit(self, *_: Any, **__: Any):
            pass

class _BridgeSignals(QObject):  # 仅在存在 Qt 环境时真正起作用
    snapshots = Signal(list)  # List[dict]

# ---------------- 新增: Redis 订阅支持 ----------------
try:
    from app.services.redis_subscriber import RedisSubscriber  # type: ignore
except Exception:  # noqa
    RedisSubscriber = None  # type: ignore

class EventBridge:
    def __init__(
        self,
        *,
        flush_interval_ms: int = 50,
        max_batch_size: int = 500,
        subscribe_backend: bool = True,
        # Redis 相关参数
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
        self._snapshots: List[Dict[str, Any]] = []
        self.flush_count = 0  # 仅测试/监控
        self.signals = _BridgeSignals()
        self._last_flush_ts = time.time()
        # Redis
        self._use_redis = use_redis and (RedisSubscriber is not None)
        self._redis_channels = redis_channels or [BACKEND_SNAPSHOT_TOPIC]
        self._redis_subscriber_factory = redis_subscriber_factory
        self._redis_subscriber: Optional[Any] = None
        self._fallback_done = False
        self._local_subscribed = False

    # ---------------- Public API ----------------
    def start(self):
        if self._running:
            return
        self._running = True
        # 若直接本地���阅 (无 Redis)
        if self._subscribe_backend and not self._use_redis:
            self._enable_local_subscription()
        # Redis 模式
        if self._use_redis:
            self._start_redis()
        self._th = Thread(target=self._loop, daemon=True)
        self._th.start()

    def stop(self):
        self._running = False
        self._stop_evt.set()
        # 优先尝试停止 redis 订阅 (避免晚于主循环的属性读取竞争)
        if self._redis_subscriber:
            try:
                self._redis_subscriber.stop()
            except Exception:
                pass
        if self._th:
            self._th.join(timeout=1)
        # 最后一次 flush
        self.flush(force=True)

    def on_snapshot(self, snap: Union[SnapshotDTO, Dict[str, Any]]):
        """手动注入 snapshot (DTO 或 dict)。"""
        if isinstance(snap, SnapshotDTO):
            payload = snap.dict()
        else:
            payload = snap
        with self._lock:
            self._snapshots.append(payload)
            # 超过 max_batch_size 立即 flush
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

    # --------------- Internal --------------------
    def _loop(self):
        interval_sec = self.flush_interval_ms / 1000.0
        while self._running and not self._stop_evt.wait(interval_sec):
            # Fallback 检测
            self._check_fallback()
            with self._lock:
                if not self._snapshots:
                    continue
                self._flush_locked()
        # 结束前再做一次 fallback 检测 (保证测试中 stop 之后仍可订阅本地, 虽然后续可能无用)
        self._check_fallback()

    def _flush_locked(self):
        if not self._snapshots:
            return
        batch = self._snapshots
        self._snapshots = []
        self.flush_count += 1
        self._last_flush_ts = time.time()
        # Qt Signal (若有效)
        try:
            self.signals.snapshots.emit(batch)  # type: ignore[attr-defined]
        except Exception:
            pass
        # 事件总线广播
        event_bus.publish(FRONTEND_SNAPSHOT_BATCH_TOPIC, {"snapshots": batch, "count": len(batch)})

    def _on_backend_snapshot(self, _topic: str, payload: Dict[str, Any]):
        # 后端发布的 snapshot payload 直接聚合
        self.on_snapshot(payload)

    # --- Redis / Fallback 逻辑 --------------------------------------
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
            # 立即标记 fallback
            self._fallback_done = True
            metrics.inc("redis_fallback")
            if self._subscribe_backend:
                self._enable_local_subscription()

    def _default_redis_factory(self, channels: List[str], cb: Callable[[str, Any], None]):
        if RedisSubscriber is None:
            raise RuntimeError("RedisSubscriber unavailable")
        return RedisSubscriber(channels, lambda ch, data: cb(ch, data))

    def _on_redis_message(self, channel: str, data: Any):
        # 仅关心 snapshot 频道
        if channel == BACKEND_SNAPSHOT_TOPIC:
            # data 预期为 dict
            if isinstance(data, dict):
                self.on_snapshot(data)

    def _check_fallback(self):
        if self._fallback_done:
            return
        rs = self._redis_subscriber
        if not rs:
            return
        try:
            fb = getattr(rs, "fallback", False)
        except Exception:
            fb = False
        if fb:
            self._fallback_done = True
            metrics.inc("redis_fallback")  # 运行期检测到 redis 订阅失效 -> 回退计数
            if self._subscribe_backend and not self._local_subscribed:
                self._enable_local_subscription()

    def _enable_local_subscription(self):
        if self._local_subscribed:
            return
        event_bus.subscribe(BACKEND_SNAPSHOT_TOPIC, self._on_backend_snapshot)
        self._local_subscribed = True

# ---------------- 订阅帮助方法（可取消） ----------------

def subscribe_topic(topic: str, handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    """订阅任意主题，返回取消函数以避免内存泄漏。"""
    h = event_bus.subscribe(topic, handler, async_mode=async_mode)
    def _cancel():
        try:
            event_bus.unsubscribe(topic, h)
        except Exception:
            pass
    return _cancel

def on_agent_status_changed(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return subscribe_topic(AGENT_STATUS_CHANGED_TOPIC, handler, async_mode=async_mode)

def on_instrument_created(handler: Callable[[str, dict], None], *, async_mode: bool = False) -> Callable[[], None]:
    return subscribe_topic(INSTRUMENT_CREATED_TOPIC, handler, async_mode=async_mode)

__all__ = [
    "EventBridge",
    "BACKEND_SNAPSHOT_TOPIC",
    "FRONTEND_SNAPSHOT_BATCH_TOPIC",
    "AGENT_STATUS_CHANGED_TOPIC",
    "INSTRUMENT_CREATED_TOPIC",
    "subscribe_topic",
    "on_agent_status_changed",
    "on_instrument_created",
]
