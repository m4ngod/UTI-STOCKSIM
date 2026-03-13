"""RingBuffer (Task 5)

逐笔滚动窗口结构:
- 固定容量 capacity, 追加满后覆盖最旧元素 (evict oldest)
- O(1) append / eviction
- 提供 to_list() 返回按时间顺序 (oldest -> newest)
- 统计 appended_count / evicted_count (并上报 metrics)

适用: L2 / 逐笔成交窗口, 避免频繁 list shift
"""
from __future__ import annotations
from typing import Generic, TypeVar, List, Optional, Iterable

from stock_sim.observability.metrics import metrics

T = TypeVar("T")

class RingBuffer(Generic[T]):
    __slots__ = ("_buf", "_capacity", "_start", "_count", "appended_count", "evicted_count", "metrics_prefix")
    def __init__(self, capacity: int, *, metrics_prefix: str = "ring"):
        if capacity <= 0:
            raise ValueError("capacity must be >0")
        self._capacity = capacity
        self._buf: List[Optional[T]] = [None] * capacity
        self._start = 0  # 指向最旧元素索引
        self._count = 0
        self.appended_count = 0
        self.evicted_count = 0
        self.metrics_prefix = metrics_prefix

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return self._count

    def is_full(self) -> bool:  # noqa: D401 (简单辅助)
        return self._count == self._capacity

    def append(self, item: T) -> Optional[T]:
        """追加元素; 如满则覆盖最旧并返回被驱逐元素."""
        evicted: Optional[T] = None
        if self._count < self._capacity:
            idx = (self._start + self._count) % self._capacity
            self._buf[idx] = item
            self._count += 1
        else:  # 覆盖最旧
            idx = self._start
            evicted = self._buf[idx]
            self._buf[idx] = item
            self._start = (self._start + 1) % self._capacity
            self.evicted_count += 1
            metrics.inc(f"{self.metrics_prefix}_evicted")
        self.appended_count += 1
        return evicted

    def extend(self, items: Iterable[T]):
        for it in items:
            self.append(it)

    def to_list(self) -> List[T]:
        if self._count == 0:
            return []
        out: List[T] = []
        for i in range(self._count):
            idx = (self._start + i) % self._capacity
            v = self._buf[idx]
            if v is not None:
                out.append(v)  # type: ignore[arg-type]
        return out

    def clear(self):
        self._buf = [None] * self._capacity
        self._start = 0
        self._count = 0

__all__ = ["RingBuffer"]
