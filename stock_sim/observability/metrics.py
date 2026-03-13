# file: observability/metrics.py
# python
import time
from collections import defaultdict
from threading import RLock
from functools import wraps  # 新增

class Metrics:
    def __init__(self):
        self.counters = defaultdict(int)
        self.timings = defaultdict(list)
        self._lock = RLock()

    def inc(self, name: str, value: int = 1):
        with self._lock:
            self.counters[name] += value

    def timeit(self, name: str):
        class _Ctx:
            def __enter__(self_non):
                self_non._t0 = time.perf_counter()
            def __exit__(self_non, exc_type, exc, tb):
                dt = (time.perf_counter() - self_non._t0) * 1000
                with self._lock:
                    self.timings[name].append(dt)
        return _Ctx()

    def gauge(self, name: str, value: float):
        with self._lock:
            self.counters[f"gauge::{name}"] = value
    def add_timing(self, name: str, value_ms: float):
        with self._lock:
            self.timings[name].append(value_ms)
    def get_percentile(self, name: str, p: float) -> float:
        with self._lock:
            arr = self.timings.get(name, [])
        if not arr:
            return 0.0
        arr = sorted(arr)
        k = (len(arr)-1) * p/100.0
        import math
        f = math.floor(k); c = math.ceil(k)
        if f == c:
            return arr[f]
        return arr[f] + (arr[c]-arr[f])*(k-f)

metrics = Metrics()

# ---- slow_op 装饰器 ----
# 需求: 记录函数耗时, 若耗时 > threshold_ms 则计数 slow_op::<name>
# 设计目标: 调用开销 <5µs (尽量少锁/分支); 仅在超阈值时加锁自增

def slow_op(name: str, threshold_ms: float):
    """装饰器: 若被装饰函数执行耗时超过 threshold_ms (毫秒) 则 metrics.inc('slow_op::<name>').

    行为:
    - 无论函数是否抛异常都统计耗时并在超阈值时计数
    - 不存储分布, 仅计数, 以降低开销
    - 使用 perf_counter 精度
    """
    key = f"slow_op::{name}"
    thr = float(threshold_ms)
    def _decorator(fn):
        @wraps(fn)
        def _wrap(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if dt_ms > thr:
                    metrics.inc(key, 1)
        return _wrap
    return _decorator

__all__ = [
    'metrics',
    'slow_op',
]
