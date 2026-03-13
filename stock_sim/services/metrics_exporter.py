# python
"""MetricsExporter (platform-hardening Task9)

职责:
  - 汇总系统内存指标并以文本 (默认类 Prometheus) 或 JSON 形式导出。
  - collect(fmt='prom'|'json')->str

覆盖指标集合 (若存在):
  - order_latency_hist: 从 metrics.timings['order_latency'] 计算 count / p50 / p90 / p99
  - event_queue_size: event_bus 内部异步队列长度
  - persistence_failures_total: metrics.counters['event_persist_failures']
  - snapshot_threshold{symbol}: 来自 AdaptiveSnapshotPolicyManager._states
  - risk_reject_total{rule}: counters 中前缀 risk_reject_total__<rule>
    * 若存在汇总 key risk_reject_total 也输出
  - crash_counter: metrics.counters['crash_counter'] (若存在)

其他: 统一导出 metrics.counters 与自定义 gauge，避免与上面重复时跳过（防止覆盖）。

设计:
  - 仅依赖轻量内存对象，不做 I/O。
  - 不引入第三方库，保持最小侵入。
  - 采用容错导出, 单项错误不影响整体。

后续可扩展: 支持直启一个 HTTP 线程 (未在当前任务范围内)。
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import json
import time

# --- 依赖注入与回退导入 ---
try:  # 优先包方式
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
except Exception:  # 源码本地运行
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore

# 自适应快照管理器是可选的
try:  # pragma: no cover - 容错导入
    from services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager  # type: ignore
except Exception:  # noqa
    AdaptiveSnapshotPolicyManager = None  # type: ignore


class MetricsExporter:
    def __init__(self, *, metrics_store=None, event_bus_inst=None, adaptive_snapshot_mgr: Any | None = None):
        self.metrics = metrics_store or metrics
        self.event_bus = event_bus_inst or event_bus
        self.adaptive = adaptive_snapshot_mgr  # 允许 None
        # 上次导出时间 (可用于速率计算, 目前未用)
        self._last_export_ts = None

    # ---- PUBLIC ----
    def collect(self, fmt: str = 'prom') -> str:
        """收集并序列化指标。

        fmt='prom' (默认): 近似 Prometheus 文本格式, 每行一个 metric。
        fmt='json' : 返回 JSON 字符串 (dict)。
        """
        data: Dict[str, Any] = {}
        # 基础 counters/gauges
        try:
            for k, v in list(self.metrics.counters.items()):  # type: ignore[attr-defined]
                data[k] = v
        except Exception:
            pass

        # 动态: event_queue_size
        try:
            qsize = len(getattr(self.event_bus, '_queue', []))
            data['event_queue_size'] = qsize
        except Exception:
            pass

        # persistence_failures_total 兼容命名
        if 'event_persist_failures' in data and 'persistence_failures_total' not in data:
            data['persistence_failures_total'] = data['event_persist_failures']

        # crash_counter 若不存在置 0 (方便外部监控差异)
        data.setdefault('crash_counter', data.get('crash_counter', 0))

        # 风险拒绝: risk_reject_total__<rule>
        risk_rule_totals: List[Tuple[str, int]] = []
        for k, v in list(data.items()):
            if k.startswith('risk_reject_total__'):
                rule = k.split('__', 1)[1]
                risk_rule_totals.append((rule, v))
        # 汇总 risk_reject_total (若 counters 没有则根据规则聚合)
        if 'risk_reject_total' not in data and risk_rule_totals:
            data['risk_reject_total'] = sum(v for _, v in risk_rule_totals)

        # snapshot_threshold per symbol
        snapshot_threshold_rows: List[Tuple[str, int]] = []
        try:
            if self.adaptive and hasattr(self.adaptive, '_states'):
                states = getattr(self.adaptive, '_states')  # dict[symbol, state]
                for sym, st in states.items():
                    th = getattr(st, 'current_threshold', None)
                    if th is not None:
                        snapshot_threshold_rows.append((sym, int(th)))
        except Exception:
            pass

        # order_latency_hist (timings 列表)
        latency_stats = {}
        try:
            timings = getattr(self.metrics, 'timings', {})
            lat_arr = []
            # 支持 key: 'order_latency' 或 包含 'order_latency'
            if 'order_latency' in timings:
                lat_arr = list(timings.get('order_latency', []))
            else:
                for k, arr in timings.items():
                    if 'order_latency' in k:
                        lat_arr.extend(list(arr))
            if lat_arr:
                lat_arr_sorted = sorted(lat_arr)
                def _pct(p: float) -> float:
                    if not lat_arr_sorted:
                        return 0.0
                    k = (len(lat_arr_sorted)-1) * p/100.0
                    import math
                    f = math.floor(k); c = math.ceil(k)
                    if f == c:
                        return float(lat_arr_sorted[f])
                    return float(lat_arr_sorted[f] + (lat_arr_sorted[c]-lat_arr_sorted[f])*(k-f))
                latency_stats = {
                    'count': len(lat_arr_sorted),
                    'p50': _pct(50),
                    'p90': _pct(90),
                    'p99': _pct(99),
                }
        except Exception:
            pass

        # 组装输出
        if fmt == 'json':
            out = {
                'timestamp_ms': int(time.time() * 1000),
                'metrics': data,
                'order_latency_hist': latency_stats,
                'snapshot_threshold': {sym: th for sym, th in snapshot_threshold_rows},
                'risk_reject_total_per_rule': {rule: v for rule, v in risk_rule_totals},
            }
            return json.dumps(out, ensure_ascii=False, separators=(',', ':'))

        # prom-like 文本
        lines: List[str] = []
        lines.append(f"# scrape_ts_ms {int(time.time()*1000)}")
        # 简单 counters/gauges
        for k, v in sorted(data.items()):
            if isinstance(v, (int, float)):
                lines.append(f"{k} {v}")
        # snapshot_threshold{symbol="X"}
        for sym, th in snapshot_threshold_rows:
            lines.append(f'snapshot_threshold{{symbol="{sym}"}} {th}')
        # risk_reject_total{rule="RULE"}
        for rule, val in risk_rule_totals:
            lines.append(f'risk_reject_total{{rule="{rule}"}} {val}')
        # order_latency_hist_*
        if latency_stats:
            lines.append(f'order_latency_hist_count {latency_stats.get("count",0)}')
            lines.append(f'order_latency_hist_p50_ms {latency_stats.get("p50",0):.3f}')
            lines.append(f'order_latency_hist_p90_ms {latency_stats.get("p90",0):.3f}')
            lines.append(f'order_latency_hist_p99_ms {latency_stats.get("p99",0):.3f}')
        return '\n'.join(lines) + '\n'

# 单例便捷实例
def _detect_adaptive() -> Any | None:
    # 尝试从全局已创建对象中探测 (若用户把实例保存在 services.adaptive_snapshot_service 模块级变量可引用)
    try:  # pragma: no cover
        import services.adaptive_snapshot_service as m  # type: ignore
        for attr in ('adaptive_manager', 'adaptive_snapshot_manager', 'ASPM', 'manager'):
            if hasattr(m, attr):
                return getattr(m, attr)
    except Exception:  # noqa
        return None
    return None

metrics_exporter = MetricsExporter(adaptive_snapshot_mgr=_detect_adaptive())

__all__ = ["MetricsExporter", "metrics_exporter"]

