"""线程安全 O(1) Ring Buffer 与简单 Tick 聚合器.

设计目标:
- 固定容量, 追加为摊还 O(1)
- 迭代按时间(写入)顺序: oldest -> newest
- 超出容量覆盖最旧元素
- append 返回被淘汰元素 (若有)
- 线程安全: 使用 RLock
- 聚合器: 支持 last_price / volume / turnover 的加总与平均, 随淘汰增量更新

无第三方依赖; TickDTO 复用 services.market_data_query_service 中定义.
"""
from __future__ import annotations
from typing import Generic, Iterator, List, Optional, TypeVar
from threading import RLock

try:
    # 运行时可能未加载该模块, 延迟导入即可; 类型提示路径保持
    from services.market_data_query_service import TickDTO  # type: ignore
except Exception:  # pragma: no cover - 测试中一定存在
    class TickDTO:  # type: ignore
        def __init__(self, ts, last=None, volume=None, turnover=None, **_):  # minimal stub
            self.ts = ts
            self.last = last
            self.volume = volume
            self.turnover = turnover

T = TypeVar("T")

class RingBuffer(Generic[T]):
    __slots__ = [
        "_capacity", "_buf", "_write_idx", "_size", "_lock"
    ]

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._capacity = capacity
        self._buf: List[Optional[T]] = [None] * capacity
        self._write_idx = 0  # 下次写入位置
        self._size = 0
        self._lock = RLock()

    # ------------- 基本属性 -------------
    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:  # 元素数
        return self._size

    def append(self, item: T) -> Optional[T]:
        """追加元素; 若缓冲区已满返回被淘汰的最旧元素, 否则返回 None."""
        with self._lock:
            evicted: Optional[T] = None
            if self._size == self._capacity:
                # write_idx 指向最旧元素位置 (覆盖)
                evicted = self._buf[self._write_idx]
            self._buf[self._write_idx] = item
            self._write_idx = (self._write_idx + 1) % self._capacity
            if self._size < self._capacity:
                self._size += 1
            return evicted

    def latest(self) -> Optional[T]:
        with self._lock:
            if self._size == 0:
                return None
            idx = (self._write_idx - 1) % self._capacity
            return self._buf[idx]

    def get(self, idx: int) -> T:
        """按时间顺序第 idx (0=最旧) 元素."""
        with self._lock:
            if idx < 0 or idx >= self._size:
                raise IndexError("index out of range")
            start = (self._write_idx - self._size) % self._capacity
            real = (start + idx) % self._capacity
            item = self._buf[real]
            assert item is not None
            return item

    def snapshot(self) -> List[T]:
        with self._lock:
            return list(self)  # 利用迭代器

    def __iter__(self) -> Iterator[T]:
        # 为避免长时间持锁, 复制引用后再 yield; 但 ring 很小, 简化为一次性锁内遍历
        with self._lock:
            if self._size == 0:
                return iter(())  # 空迭代器
            start = (self._write_idx - self._size) % self._capacity
            out: List[T] = []
            for i in range(self._size):
                real = (start + i) % self._capacity
                item = self._buf[real]
                if item is not None:
                    out.append(item)
            return iter(out)

class TickAggregator:
    """基于 RingBuffer 的增量聚合; 针对 TickDTO.

    维护:
    - 计数 (含 None 值 tick)
    - last_price 总和 / 计数 (仅 last 非 None)
    - volume / turnover 总和 (None 视 0)
    可 O(1) 更新并在淘汰时修正.
    """
    __slots__ = [
        "_ring", "_lock", "_sum_last", "_count_last", "_sum_volume", "_sum_turnover"
    ]

    def __init__(self, capacity: int):
        self._ring: RingBuffer[TickDTO] = RingBuffer(capacity)
        self._lock = RLock()
        self._sum_last = 0.0
        self._count_last = 0
        self._sum_volume = 0
        self._sum_turnover = 0.0

    @property
    def capacity(self) -> int:
        return self._ring.capacity

    def append(self, tick: TickDTO):
        with self._lock:
            evicted = self._ring.append(tick)
            # 加新
            if tick.last is not None:
                self._sum_last += float(tick.last)
                self._count_last += 1
            if tick.volume is not None:
                self._sum_volume += int(tick.volume)
            if tick.turnover is not None:
                self._sum_turnover += float(tick.turnover)
            # 减旧
            if evicted is not None:
                if getattr(evicted, "last", None) is not None:
                    self._sum_last -= float(evicted.last)  # type: ignore[arg-type]
                    self._count_last -= 1
                if getattr(evicted, "volume", None) is not None:
                    self._sum_volume -= int(evicted.volume)  # type: ignore[arg-type]
                if getattr(evicted, "turnover", None) is not None:
                    self._sum_turnover -= float(evicted.turnover)  # type: ignore[arg-type]

    # ---- 查询 ----
    def size(self) -> int:
        return len(self._ring)

    def latest(self) -> Optional[TickDTO]:
        return self._ring.latest()

    def avg_last_price(self) -> float | None:
        if self._count_last == 0:
            return None
        return self._sum_last / self._count_last

    def total_volume(self) -> int:
        return self._sum_volume

    def total_turnover(self) -> float:
        return self._sum_turnover

    def snapshot(self) -> List[TickDTO]:
        return self._ring.snapshot()

__all__ = ["RingBuffer", "TickAggregator"]

