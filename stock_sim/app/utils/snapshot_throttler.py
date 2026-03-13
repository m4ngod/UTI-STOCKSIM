# python
"""SnapshotThrottler: 以时间桶节流快照的重计算/刷新调用次数。

设计目标:
- 输入事件(增量更新)可能达到 50+ 次/秒
- 对昂贵的下游 refresh 逻辑限制为 <= 10 次/秒
- 采用简单的最小间隔(min_interval)控制; 首次事件立即刷新, 后续只有距离上次刷新 >= min_interval 才执行
- 若在间隔内有多次 update, 仅保留最后一次(覆盖 pending)

可测试性:
- 暴露 refresh_count 计数, 单测模拟 50Hz 事件后断言 <=10

线程模型:
- 目前假设在单线程(事件驱动)上下文调用; 若未来需要跨线程, 可加锁.
"""
from __future__ import annotations
import time
from typing import Callable, Optional, Any
from observability.metrics import metrics

class SnapshotThrottler:
    def __init__(self, refresh_fn: Callable[[Any], None], *, max_refresh_per_sec: int = 10):
        if max_refresh_per_sec <= 0:
            raise ValueError("max_refresh_per_sec must be positive")
        self._refresh_fn = refresh_fn
        self._interval = 1.0 / float(max_refresh_per_sec)
        self._last_flush: Optional[float] = None
        self._pending: Any = None
        self._refresh_count = 0
        self._max_per_sec = max_refresh_per_sec

    @property
    def refresh_count(self) -> int:
        return self._refresh_count

    def update(self, snapshot: Any):
        """提交一次增量(替换 pending). 在需要时触发节流刷新。"""
        self._pending = snapshot
        now = time.perf_counter()
        if self._last_flush is None:
            # 首次直接刷新
            self._flush(now)
            return
        if (now - self._last_flush) >= self._interval:
            self._flush(now)
        # 否则等待后续事件或外部 force_flush

    def force_flush(self):
        """强制刷新 pending (若存在) 且不违反 ‘每秒 <= 限制’ 的统计语义。
        语义: 若已经在当前 1s 时间窗内达到配额, 但仍调用 force_flush, 仍可刷新一次, 但此刷新计入下一时间窗逻辑。
        实现: 判断距离上次 flush 是否 >= interval; 若未到间隔, 直接跳过 (保持严格限制)。"""
        if self._pending is None:
            return
        now = time.perf_counter()
        if self._last_flush is None or (now - self._last_flush) >= self._interval:
            self._flush(now)

    def _flush(self, now: float):
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        self._last_flush = now
        self._refresh_count += 1
        metrics.inc("snapshot_throttled_refresh")
        try:
            self._refresh_fn(pending)
        except Exception:  # noqa: BLE001
            metrics.inc("snapshot_throttled_refresh_error")
            raise

