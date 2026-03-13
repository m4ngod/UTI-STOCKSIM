"""PerformanceMonitor

目标:
- 低开销(<1%)记录 UI 潜在卡顿/耗时片段
- 使用上下文管理器 monitor.section(name) 包裹代码段
- 聚合(total_ms,count) 内存累积, 周期 flush -> metrics
- flush 输出: metrics.add_timing("perf::name", avg_ms); metrics.inc("perf_count::name", count)
- 线程安全, 可停止后台 flush 线程

用法:
    pm = PerformanceMonitor(flush_interval_ms=2000)
    with pm.section('ui_freeze.paint'):
        heavy_op()
    pm.flush()  # 手动触发 (测试场景)

测试判定: 包裹 dummy block 后 flush, metrics.timings 存在 perf::section 名称.
"""
from __future__ import annotations
import time
from threading import RLock, Event, Thread
from typing import Dict, Tuple, Optional
from observability.metrics import metrics

__all__ = ["PerformanceMonitor"]

class PerformanceMonitor:
    def __init__(self, *, flush_interval_ms: int = 5000, auto_start: bool = True, enabled: bool = True):
        self._flush_interval = flush_interval_ms / 1000.0
        self._enabled = enabled
        self._data: Dict[str, Tuple[float, int]] = {}  # name -> (total_ms, count)
        self._lock = RLock()
        self._stop_evt = Event()
        self._th: Optional[Thread] = None
        if auto_start and enabled:
            self.start()

    # ---------- Public ----------
    def start(self):
        if (self._th and self._th.is_alive()) or not self._enabled:
            return
        self._stop_evt.clear()
        self._th = Thread(target=self._loop, daemon=True)
        self._th.start()

    def stop(self):
        self._stop_evt.set()
        th = self._th
        if th and th.is_alive():
            th.join(timeout=0.5)
        # 最终 flush 一次
        self.flush()

    def section(self, name: str):
        if not self._enabled:
            # 返回空上下文, 保持接口兼容
            class _Dummy:
                def __enter__(self_non): return None
                def __exit__(self_non, *a): return False
            return _Dummy()
        monitor = self
        class _Ctx:
            __slots__ = ("_t0",)
            def __enter__(self_non):
                self_non._t0 = time.perf_counter()
                return None
            def __exit__(self_non, exc_type, exc, tb):  # noqa: D401
                dt_ms = (time.perf_counter() - self_non._t0) * 1000.0
                # 聚合: 只做一次锁操作, 最小化开销
                with monitor._lock:
                    total, cnt = monitor._data.get(name, (0.0, 0))
                    monitor._data[name] = (total + dt_ms, cnt + 1)
                return False  # 不吞异常
        return _Ctx()

    def flush(self):
        if not self._enabled:
            return
        with self._lock:
            if not self._data:
                return
            snapshot = self._data
            self._data = {}
        for name, (total_ms, cnt) in snapshot.items():
            if cnt == 0:
                continue
            avg = total_ms / cnt
            metrics.add_timing(f"perf::{name}", avg)
            metrics.inc(f"perf_count::{name}", cnt)

    # ---------- Internal ----------
    def _loop(self):
        # 使用 Event.wait 避免忙轮询
        while not self._stop_evt.wait(self._flush_interval):
            self.flush()

# 提供一个默认实例 (可按需引入)
performance_monitor = PerformanceMonitor(auto_start=True)

