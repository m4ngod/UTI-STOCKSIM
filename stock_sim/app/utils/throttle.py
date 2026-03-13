"""Throttle 工具 (Task 5)

用途:
- 控制高频调用 (如 snapshot 合并后触发 UI 刷新) 的执行频率
- 在一个时间窗口(interval_ms) 内只执行首次 + 可选尾部一次 (trailing)
- 统计被覆盖(丢弃)次数, 便于指标监控

策略:
submit() 规则:
1. 若距离上次实际执行 >= interval -> 立即执行 (leading)
2. 否则覆盖 pending (只保留最新一次参数), dropped_count +=1
flush_pending():
- 若存在 pending 且距离上次执行已超过 interval 则执行 (trailing)
- force=True 时无视时间直接执行 (用于测试或停机阶段)

线程安全: 使用 RLock. 不自建线程, 由外部 loop/定时器驱动 flush.
"""
from __future__ import annotations
from typing import Callable, Any, Optional, Tuple, Dict
import time
from threading import RLock

# 兼容导入 metrics：优先本项目 observability.metrics，其次 stock_sim.observability.metrics，最后哑实现
try:
    from observability.metrics import metrics  # type: ignore
except Exception:  # pragma: no cover
    try:
        from stock_sim.observability.metrics import metrics  # type: ignore
    except Exception:  # pragma: no cover
        class _DummyMetrics:
            def inc(self, *_a, **_kw):
                pass
            def add_timing(self, *_a, **_kw):
                pass
        metrics = _DummyMetrics()  # type: ignore

class Throttle:
    def __init__(self, interval_ms: int, fn: Callable[..., Any], *, metrics_prefix: str = "throttle"):
        if interval_ms <= 0:
            raise ValueError("interval_ms must be >0")
        self.interval_ms = interval_ms
        self.fn = fn
        self.metrics_prefix = metrics_prefix
        self._lock = RLock()
        self._last_exec_ts: float = 0.0
        self._pending: Optional[Tuple[Tuple[Any, ...], Dict[str, Any]]] = None
        self.executed_count = 0
        self.dropped_count = 0

    def submit(self, *args: Any, **kwargs: Any):
        now = time.perf_counter()
        with self._lock:
            if (now - self._last_exec_ts) * 1000.0 >= self.interval_ms:
                self._execute_locked(args, kwargs)
            else:
                self._pending = (args, kwargs)
                self.dropped_count += 1
                metrics.inc(f"{self.metrics_prefix}_dropped")

    def flush_pending(self, *, force: bool = False) -> bool:
        with self._lock:
            if not self._pending:
                return False
            now = time.perf_counter()
            if force or (now - self._last_exec_ts) * 1000.0 >= self.interval_ms:
                args, kwargs = self._pending
                self._pending = None
                self._execute_locked(args, kwargs)
                return True
            return False

    def _execute_locked(self, args: Tuple[Any, ...], kwargs: Dict[str, Any]):
        self._last_exec_ts = time.perf_counter()
        try:
            self.fn(*args, **kwargs)
        finally:
            self.executed_count += 1
            metrics.inc(f"{self.metrics_prefix}_executed")

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return self._pending is not None

__all__ = ["Throttle"]
