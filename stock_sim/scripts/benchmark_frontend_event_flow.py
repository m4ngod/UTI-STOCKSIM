"""benchmark_frontend_event_flow.py (Spec Task 40)

目的:
- 模拟前端事件流: snapshot 以 ~target_rate 条/秒 注入 EventBridge.on_snapshot
- 混入少量代理控制/账户拉取操作以贴近真实 (轻量, 不计入核心延迟统计)
- 统计 snapshot 注入 -> 批量 flush 发布(frontend.snapshot.batch) 的延迟分布
- 输出: 总条数/实际速率/flush 次数/平均批大小/延迟 p50,p90,p95,p99,max (ms)
- 写入标准输出 + logs/struct.log (若结构化日志可用)

衡量指标对照 NFR: P95 < 250ms (设计 flush_interval_ms 默认 50ms, 理论 ~<=100ms)

使用:
python -m scripts.benchmark_frontend_event_flow \
  --duration-seconds 2 \
  --target-rate 1000 \
  --flush-interval-ms 50

可选参数:
--duration-seconds float  运行时长 (默认 2)
--target-rate int         每秒注入 snapshot 数 (默认 1000)
--flush-interval-ms int   EventBridge flush 间隔 (默认 50)
--max-batch-size int      Flush 批最大条数 (默认 500)
--no-mixed                关闭混合账户/代理模拟
--warmup-seconds float    预热时长 (默认 0.2) 不计入统计

实现笔记:
- 给每条 snapshot 附加字段 _inject_ts (time.perf_counter_ns)
- flush 回调计算 (now_ns - _inject_ts)/1e6 -> 单条延迟 ms
- 所有延迟保存在列表 latencies_ms
- 结束后计算分位数; 若无数据输出 N/A

"""
from __future__ import annotations
import argparse
import threading
import time
import statistics
from typing import List, Dict, Any

from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
from infra.event_bus import event_bus
from observability.metrics import metrics
from app.services.agent_service import AgentService, BatchCreateConfig
from app.services.account_service import AccountService

try:
    from observability.struct_logger import struct_log
except Exception:  # pragma: no cover
    def struct_log(**kw):  # type: ignore
        pass

# ------------- Percentile Helper -------------

def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return float('nan')
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    k = (len(values) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1

# ------------- Benchmark Core -------------

class SnapshotInjector:
    def __init__(self, *, rate: int, duration: float, warmup: float, bridge: EventBridge,
                 mixed: bool, agent_svc: AgentService | None, account_svc: AccountService | None):
        self.rate = rate
        self.duration = duration
        self.warmup = warmup
        self.bridge = bridge
        self.mixed = mixed
        self.agent_svc = agent_svc
        self.account_svc = account_svc
        self._stop = threading.Event()
        self.total_sent = 0

    def run(self):
        start = time.perf_counter()
        end_time = start + self.duration + self.warmup
        interval = 1.0 / max(self.rate, 1)
        next_mixed_ts = start
        while not self._stop.is_set():
            now = time.perf_counter()
            if now >= end_time:
                break
            # 注入 snapshot
            snap = self._make_snapshot(self.total_sent)
            self.bridge.on_snapshot(snap)
            self.total_sent += 1
            # 混合操作 (每 ~0.2s 执行一次): 批量创建 + 账户拉取
            if self.mixed and now >= next_mixed_ts:
                next_mixed_ts = now + 0.2
                if self.agent_svc and (self.total_sent % (self.rate // 2 + 1) == 0):
                    try:
                        self.agent_svc.batch_create_retail(BatchCreateConfig(count=1, agent_type="Retail", name_prefix="bm"))
                    except Exception:  # noqa
                        pass
                if self.account_svc and (self.total_sent % (self.rate // 3 + 1) == 0):
                    cached = self.account_svc.get_cached()
                    if cached:
                        # 轻量一致性校验 (忽略结果)
                        try:
                            self.account_svc.check_consistency(cached)
                        except Exception:  # noqa
                            pass
            # 控速: 简单 sleep (可能引入抖动; 足够近似)
            target_next = start + (self.total_sent * interval)
            sleep_sec = target_next - time.perf_counter()
            if sleep_sec > 0:
                time.sleep(min(sleep_sec, 0.01))  # 限制最大 sleep 以降低延迟分布偏移

    def _make_snapshot(self, idx: int) -> Dict[str, Any]:
        now_ns = time.perf_counter_ns()
        return {
            "symbol": f"SYM{idx % 500:03d}",
            "last": 100.0 + (idx % 100) * 0.01,
            "bid_levels": [(100.0, 10)],
            "ask_levels": [(100.1, 10)],
            "volume": idx,
            "turnover": float(idx) * 100.0,
            "ts": int(time.time() * 1000),
            "snapshot_id": f"bench-{idx}",
            "_inject_ts": now_ns,
        }

# ------------- Main Benchmark -------------

def run_benchmark(args):
    bridge = EventBridge(flush_interval_ms=args.flush_interval_ms, max_batch_size=args.max_batch_size)
    bridge.start()
    agent_svc = AgentService() if not args.no_mixed else None
    account_svc = AccountService() if not args.no_mixed else None
    if account_svc:
        account_svc.load_account("BENCH_ACC")
    if agent_svc:
        agent_svc.batch_create_retail(BatchCreateConfig(count=2, agent_type="Retail", name_prefix="warm"))

    latencies_ms: List[float] = []
    flushed_snapshots = 0
    lock = threading.RLock()

    def on_batch(_topic: str, payload: Dict[str, Any]):
        nonlocal flushed_snapshots
        batch = payload.get("snapshots") or []
        now_ns = time.perf_counter_ns()
        local_lat: List[float] = []
        for item in batch:
            inj = item.get("_inject_ts")
            if inj:
                d_ms = (now_ns - inj) / 1_000_000.0
                local_lat.append(d_ms)
                metrics.add_timing("benchmark_snapshot_latency_ms", d_ms)
        with lock:
            latencies_ms.extend(local_lat)
            flushed_snapshots += len(batch)

    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, on_batch)

    injector = SnapshotInjector(
        rate=args.target_rate,
        duration=args.duration_seconds,
        warmup=args.warmup_seconds,
        bridge=bridge,
        mixed=not args.no_mixed,
        agent_svc=agent_svc,
        account_svc=account_svc,
    )
    t = threading.Thread(target=injector.run, daemon=True)
    t.start()
    t.join()
    # 结束前等待两次 flush_interval 以确保残留 flush
    time.sleep(args.flush_interval_ms / 1000.0 * 2)
    bridge.stop()

    # 过滤掉 warmup 时段的延迟: 通过基于时间窗口筛选 (简单：忽略前 warmup_seconds 注入的全部快照)
    # 为简化, 之前未保留注入时间序列索引映射, 这里近似: 去掉前 warmup_fraction * len(latencies)
    if injector.warmup > 0 and latencies_ms:
        warmup_fraction = injector.warmup / (injector.duration + injector.warmup)
        cut = int(len(latencies_ms) * warmup_fraction)
        latencies_ms = latencies_ms[cut:]

    latencies_ms.sort()
    total = injector.total_sent
    duration_actual = injector.duration + injector.warmup
    actual_rate = total / duration_actual if duration_actual > 0 else 0.0
    flushes = bridge.flush_count
    avg_batch = flushed_snapshots / flushes if flushes else 0

    def fmt(v: float) -> str:
        if v != v:  # NaN
            return "N/A"
        return f"{v:.2f}"

    p50 = _percentile(latencies_ms, 50)
    p90 = _percentile(latencies_ms, 90)
    p95 = _percentile(latencies_ms, 95)
    p99 = _percentile(latencies_ms, 99)
    pmax = max(latencies_ms) if latencies_ms else float('nan')
    pmin = min(latencies_ms) if latencies_ms else float('nan')

    summary = {
        "snapshots_total": total,
        "duration_s": round(duration_actual, 3),
        "target_rate": args.target_rate,
        "actual_rate": round(actual_rate, 1),
        "flushes": flushes,
        "avg_batch": round(avg_batch, 2),
        "latency_ms_min": pmin,
        "latency_ms_p50": p50,
        "latency_ms_p90": p90,
        "latency_ms_p95": p95,
        "latency_ms_p99": p99,
        "latency_ms_max": pmax,
    }

    # 控制台输出
    print("=== Frontend Event Flow Benchmark ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"{k}: {fmt(v)}")
        else:
            print(f"{k}: {v}")
    # 结构化日志
    struct_log(action="frontend_event_flow_benchmark", **{k: (float(v) if isinstance(v, (int, float)) else v) for k, v in summary.items()})

    # 简单合格判定 (提示, 不抛异常): P95 < 250ms
    if p95 != p95:  # NaN
        print("[WARN] 无有效延迟数据 (可能没有 flush)。")
    elif p95 > 250:
        print(f"[WARN] P95 {p95:.2f}ms 超过 250ms 目标。")
    else:
        print(f"[OK] P95 {p95:.2f}ms 满足 <250ms 目标。")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Frontend event flow benchmark (snapshots)")
    ap.add_argument("--duration-seconds", type=float, default=2.0)
    ap.add_argument("--target-rate", type=int, default=1000)
    ap.add_argument("--flush-interval-ms", type=int, default=50)
    ap.add_argument("--max-batch-size", type=int, default=500)
    ap.add_argument("--no-mixed", action="store_true", help="禁用混合账户/代理操作")
    ap.add_argument("--warmup-seconds", type=float, default=0.2)
    args = ap.parse_args()
    run_benchmark(args)

if __name__ == "__main__":  # pragma: no cover
    main()

