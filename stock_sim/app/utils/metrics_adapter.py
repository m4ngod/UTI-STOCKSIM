"""Metrics Adapter (Spec Task 34)

目标:
- 将 observability.metrics 中收集的 counters / timings 结构化输出到 struct_logger.
- 仅当存在 >0 的计数或 timings 非空时写日志 (避免噪音)。
- 支持 percentile 汇总 (p50/p95/p99) 与单个 timing 数量 count。
- 支持 reset / snapshot / flush / inject logger.
- 用途: 前端渲染延迟、事件丢弃、指标耗时、i18n 缺失等指标统一落盘结构化。

API:
- snapshot(include_zeros: bool=False) -> dict
- flush_metrics(forced: bool=False, logger=logger, reason: str|None=None) -> dict|None
- reset_metrics()
- set_logger(l)
- dump_metrics(include_zeros: bool=False, reset: bool=False) -> dict   # (Task49) 提供给可视化/外部导出

Log Schema 示例 (cat="metrics"):
{
  "ts": ..., "cat": "metrics", "reason": "manual", "counters": {...}, "timings": {
       "latency.render": {"p50": 10.2, "p95": 18.3, "p99": 30.1, "count": 25}
  }}

线程安全: 复用 metrics 自身锁；此适配器只做读+简单计算。
"""
from __future__ import annotations
from typing import Dict, Any, Optional
import time
from stock_sim.observability.metrics import metrics
from stock_sim.observability.struct_logger import logger as _default_logger

__all__ = [
    'snapshot', 'flush_metrics', 'reset_metrics', 'set_logger', 'dump_metrics'
]

_active_logger = _default_logger

def set_logger(l):  # 简单注入 (测试可替换)
    global _active_logger
    _active_logger = l

# ---------------- Core ----------------

def _timing_summary(name: str, arr: list[float]) -> Dict[str, float]:  # arr 已拷贝
    if not arr:
        return {}
    arr_sorted = sorted(arr)
    def pct(p: float):
        if not arr_sorted:
            return 0.0
        k = (len(arr_sorted)-1) * p/100.0
        import math
        f = math.floor(k); c = math.ceil(k)
        if f == c:
            return float(arr_sorted[f])
        return float(arr_sorted[f] + (arr_sorted[c]-arr_sorted[f]) * (k-f))
    return {
        'p50': pct(50),
        'p95': pct(95),
        'p99': pct(99),
        'count': float(len(arr_sorted)),
    }

def snapshot(*, include_zeros: bool = False) -> Dict[str, Any]:
    # 复制当前指标 (避免持锁长时间排序)
    counters = dict(metrics.counters)
    timings_copy = {k: list(v) for k, v in metrics.timings.items()}
    if not include_zeros:
        counters = {k: v for k, v in counters.items() if v}
    timing_out: Dict[str, Any] = {}
    for name, arr in timings_copy.items():
        if not arr and not include_zeros:
            continue
        timing_out[name] = _timing_summary(name, arr)
    return {'counters': counters, 'timings': timing_out}

def flush_metrics(*, forced: bool = False, logger=None, reason: str | None = None) -> Optional[Dict[str, Any]]:
    logger = logger or _active_logger
    snap = snapshot(include_zeros=False)
    if not forced and not snap['counters'] and not snap['timings']:
        return None
    payload = {**snap}
    if reason:
        payload['reason'] = reason
    try:
        logger.log('metrics', **payload)
    except Exception:  # 日志失败不抛出
        return None
    return payload

def reset_metrics():
    metrics.counters.clear()
    metrics.timings.clear()

# -------------- Task49 新增 --------------

def dump_metrics(*, include_zeros: bool = False, reset: bool = False) -> Dict[str, Any]:
    """导出当前全部指标快照 (JSON 可序列化)。

    参数:
        include_zeros: 是否包含值为 0 的计数/空 timings 占位。
        reset: 导出后是否自动 reset (适合周期性抓取)。

    返回:
        dict: { 'ts': 毫秒时间戳, 'counters': {...}, 'timings': {...} }
              timings 内同 flush(snapshot) 结构 (p50/p95/p99/count)。
    """
    snap = snapshot(include_zeros=include_zeros)
    out = {
        'ts': int(time.time() * 1000),
        **snap
    }
    if reset:
        reset_metrics()
    return out
