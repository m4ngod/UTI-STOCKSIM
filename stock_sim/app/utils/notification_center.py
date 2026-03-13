"""In-memory NotificationCenter (Spec Task: Notification Center)

目标:
- 线程安全内存通知中心, 支持观察者回调
- push 时若超出容量仅保留最近 N 条 (默认 1000)
- 无 Qt 依赖, 纯 Python + RingBuffer
- 用例: UI 轮询 get_all() 或注册 observer 即时更新

API:
    center = NotificationCenter(capacity=1000)
    def on_note(note: Notification): ...
    center.add_observer(on_note)
    center.push(level="info", message="Loaded", meta={...})
    notes = center.get_all()

线程安全策略:
- 内部状态 (ring buffer / observers / counter) 受同一 RLock 保护
- 回调执行放在锁外 (复制列表) 避免死锁 & 回调阻塞写

性能取舍:
- RingBuffer O(1) append + 覆盖, to_list O(n) 适合容量 1k 级
- 回调同步执行; 若后续需要异步可接入线程池/事件循环

成功标准:
- 单测 push 1100 条后 size==1000 且最早 id 对应 100 (0-based 推入)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, List, Optional
import time
from threading import RLock

from observability.metrics import metrics
from .ring_buffer import RingBuffer

__all__ = ["Notification", "NotificationCenter"]

@dataclass(slots=True)
class Notification:
    id: int
    ts: int  # epoch ms
    level: str
    message: str
    meta: dict[str, Any]

Observer = Callable[[Notification], None]

class NotificationCenter:
    def __init__(self, capacity: int = 1000):
        if capacity <= 0:
            raise ValueError("capacity must >0")
        self._ring: RingBuffer[Notification] = RingBuffer(capacity=capacity, metrics_prefix="notif")
        self._lock = RLock()
        self._observers: List[Observer] = []
        self._next_id = 0

    # ---- Observer Management ----
    def add_observer(self, cb: Observer):  # noqa: D401
        if not callable(cb):
            raise TypeError("observer must be callable")
        with self._lock:
            if cb not in self._observers:
                self._observers.append(cb)

    def remove_observer(self, cb: Observer):  # noqa: D401
        with self._lock:
            try:
                self._observers.remove(cb)
            except ValueError:
                return

    # ---- Push & Read ----
    def push(self, level: str, message: str, *, meta: Optional[dict[str, Any]] = None) -> Notification:
        note: Notification
        with self._lock:
            note = Notification(id=self._next_id, ts=int(time.time() * 1000), level=level, message=message, meta=meta or {})
            self._next_id += 1
            self._ring.append(note)
            observers_copy = list(self._observers)
        metrics.inc("notification_push")
        # 回调在锁外执行
        for cb in observers_copy:
            try:
                cb(note)
            except Exception:  # pragma: no cover - 忽略单个观察者错误
                pass
        return note

    def get_all(self) -> List[Notification]:  # noqa: D401
        with self._lock:
            return list(self._ring.to_list())

    def size(self) -> int:  # noqa: D401
        with self._lock:
            return self._ring.size

    def capacity(self) -> int:  # noqa: D401
        with self._lock:
            return self._ring.capacity

    def clear(self):  # noqa: D401
        with self._lock:
            self._ring.clear()
            self._next_id = 0
            metrics.inc("notification_clear")

