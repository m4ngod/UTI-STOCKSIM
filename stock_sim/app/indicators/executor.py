from __future__ import annotations
"""Indicator 异步执行器 (Spec Task 7)

功能目标:
- 并发计算多 symbol * 多指标, 回调在主线程安全执行
- 延迟: 典型 5 symbols * 3 指标 (≥1k bars) 计算完成并回调触发 ≤ 200ms (取决 CPU, 回调轮询频率)
- 可替换实现: 后续可接入 QThreadPool / 进程池

使用示例:
    from app.indicators.executor import IndicatorExecutor
    from app.indicators import indicator_registry

    execu = IndicatorExecutor(indicator_registry)
    def cb(result, *, symbol, name, params, error, duration_ms, cache_key):
        ...
    execu.submit('ma', prices, symbol='AAPL', window=20, callback=cb)
    # GUI 定时器 / 主循环中:
    execu.poll_callbacks()

设计要点:
- 线程池: concurrent.futures.ThreadPoolExecutor
- 回调: 结果放入队列, poll_callbacks() 中触发, 避免 GUI 线程问题
- cache_key: registry.generate_cache_key(name, data_len, params)
- 错误捕获: 回调参数 error!=None, result=None

限制 & 扩展:
- 未做数据内容哈希; 若后续需要缓存去重可在 submit 时传入 data_hash 参数扩展
- 若集成 Qt, 可在 poll_callbacks 内发射 Qt 信号代替直接执行用户回调

新增 (性能/稳定扩展):
- submit 支持 timeout_ms 指定单任务超时时间 (ms)
- poll_callbacks 非阻塞检查: 若任务未完成且已超过 timeout_ms, 逻辑超时 -> 记录 metrics.indicator_timeout 并丢弃该 Pending (不调用回调, 不返回部分结果)
- 无法强制中断已运行的线程任务 (ThreadPoolExecutor 限制), 但逻辑上视为取消, 资源完成后由 GC 释放
"""
import os
import time
import threading
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, Future
from observability.metrics import metrics

from .registry import IndicatorRegistry, indicator_registry

UserCallback = Callable[..., None]

@dataclass
class _Pending:
    future: Future
    user_cb: Optional[UserCallback]
    meta: Dict[str, Any]

class IndicatorExecutor:
    """指标计算执行器 (带结果缓存 + 超时逻辑)."""
    def __init__(self, registry: IndicatorRegistry, max_workers: Optional[int] = None, *, default_timeout_ms: Optional[float] = None):
        if max_workers is None:
            cpu = os.cpu_count() or 4
            max_workers = min(32, max(4, cpu * 2))
            env_val = os.getenv("INDICATOR_MAX_WORKERS")
            if env_val:
                try:
                    max_workers = int(env_val)
                except ValueError:
                    pass
        self._registry = registry
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="indicator")
        self._lock = threading.Lock()
        self._pending: List[_Pending] = []
        self._shutdown = False
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._default_timeout_ms = default_timeout_ms

    # ---------- 缓存辅助 ----------
    def _build_cache_key(self, name: str, data_arr: List[float], params: Dict[str, Any], symbol: Optional[str]) -> str:
        # 数据哈希: 控制大小 (取前 16 hex) 防止不同数据同长度冲突
        if data_arr:
            mv = memoryview((b"" if isinstance(data_arr, bytes) else bytes()))  # 占位避免 mypy 报错
        arr_bytes = memoryview(bytearray())  # 默认空
        try:
            import numpy as _np  # 局部导入
            np_arr = _np.asarray(data_arr, dtype=_np.float64)
            arr_bytes = memoryview(np_arr.tobytes())
        except Exception:
            # 退化: 转字符串再编码 (慢) 仅在 numpy 不可用时
            arr_bytes = memoryview(str(data_arr).encode("utf-8"))
        digest = hashlib.sha1(arr_bytes).hexdigest()[:16]
        base_key = self._registry.generate_cache_key(name, data_len=len(data_arr), params=params)
        return f"{symbol or '_'}::{base_key}::h={digest}"

    # ---------------- Public API ----------------
    def submit(self, name: str, data: Iterable[float], *, symbol: Optional[str] = None,
               callback: Optional[UserCallback] = None, use_cache: bool = True, invalidate: bool = False,
               timeout_ms: Optional[float] = None, **params: Any) -> Future:
        if self._shutdown:
            raise RuntimeError("IndicatorExecutor already shutdown")
        arr_copy = list(data)
        cache_key = self._build_cache_key(name, arr_copy, dict(params), symbol)
        if invalidate:
            with self._lock:
                self._cache.pop(cache_key, None)
        if use_cache:
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached is not None:
                # 构造一个已完成 future
                fut: Future = Future()
                fut.set_result((cached[0], None, 0.0))  # duration 0
                meta = {"symbol": symbol, "name": name, "params": dict(params), "cache_key": cache_key, "submit_ts": time.perf_counter(), "from_cache": True}
                with self._lock:
                    self._pending.append(_Pending(future=fut, user_cb=callback, meta=meta))
                return fut

        def _work() -> Tuple[Any, Optional[Exception], float]:
            start = time.perf_counter()
            try:
                result = self._registry.compute(name, arr_copy, **params)
                err = None
                # 写缓存
                if use_cache and err is None:
                    with self._lock:
                        self._cache[cache_key] = (result, time.time())
            except Exception as e:  # noqa: BLE001
                result = None
                err = e
            dur_ms = (time.perf_counter() - start) * 1000
            return result, err, dur_ms

        fut = self._pool.submit(_work)
        meta = {
            "symbol": symbol,
            "name": name,
            "params": dict(params),
            "cache_key": cache_key,
            "submit_ts": time.perf_counter(),
            "from_cache": False,
            "timeout_ms": timeout_ms if timeout_ms is not None else self._default_timeout_ms,
        }
        with self._lock:
            self._pending.append(_Pending(future=fut, user_cb=callback, meta=meta))
        return fut

    def submit_batch(self, jobs: Iterable[Dict[str, Any]]) -> List[Future]:
        futures: List[Future] = []
        for job in jobs:
            job = dict(job)
            name = job.pop("name")
            data = job.pop("data")
            symbol = job.pop("symbol", None)
            callback = job.pop("callback", None)
            use_cache = job.pop("use_cache", True)
            invalidate = job.pop("invalidate", False)
            futures.append(self.submit(name, data, symbol=symbol, callback=callback, use_cache=use_cache, invalidate=invalidate, **job))
        return futures

    def poll_callbacks(self) -> int:
        """在主��程(或安全上下文)调用; 执行完成的用户回调.
        返回已执行回调数量.
        - 超时任务: 不执行回调, 直接丢弃 (逻辑取消), 记录 metrics.indicator_timeout
        """
        done: List[_Pending] = []
        now = time.perf_counter()
        with self._lock:
            remain: List[_Pending] = []
            for p in self._pending:
                fut = p.future
                if fut.done():
                    done.append(p)
                    continue
                to_ms = p.meta.get("timeout_ms")
                if to_ms is not None and (now - p.meta["submit_ts"]) * 1000.0 > to_ms:
                    # 逻辑超时: 记录指标并丢弃 (不回调, 不等待 future.result())
                    metrics.inc("indicator_timeout")
                    # 不加入 remain -> 丢弃; 未来结果完成被忽略
                    continue
                remain.append(p)
            self._pending = remain
        count = 0
        for p in done:
            if not p.user_cb:
                continue
            try:
                result, err, dur = p.future.result()
                p.user_cb(result,
                          symbol=p.meta["symbol"],
                          name=p.meta["name"],
                          params=p.meta["params"],
                          error=err,
                          duration_ms=dur,
                          cache_key=p.meta["cache_key"],)
            except Exception:
                pass
            count += 1
        return count

    # 新增: 失效 API
    def invalidate(self, predicate: Optional[Callable[[str], bool]] = None):
        with self._lock:
            if predicate is None:
                self._cache.clear()
            else:
                for k in list(self._cache.keys()):
                    if predicate(k):
                        self._cache.pop(k, None)

    def invalidate_symbol(self, symbol: str):
        prefix = f"{symbol}::"
        self.invalidate(lambda k: k.startswith(prefix))

    def cache_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"size": len(self._cache)}

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for p in self._pending if not p.future.done())

    def shutdown(self, wait: bool = True):
        if self._shutdown:
            return
        self._shutdown = True
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

# 全局实例 (可按需直接使用)
indicator_executor = IndicatorExecutor(indicator_registry)

__all__ = ["IndicatorExecutor", "indicator_executor"]
