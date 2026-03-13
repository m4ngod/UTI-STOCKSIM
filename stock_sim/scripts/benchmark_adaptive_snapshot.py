#!/usr/bin/env python
"""benchmark_adaptive_snapshot

用途 (Req1): 评估自适应快照策略对撮合快照刷新频率及吞吐的影响。

指标:
  - ops_per_sec: 提交订单(撮合+入簿)操作吞吐 (订单/秒)
  - snapshots: 期间触发的快照刷新次数
  - snapshot_ops_ratio: snapshots / total_ops
  - avg_threshold: 自适应策略期间平均阈值 (若启用)

用法:
  python -m scripts.benchmark_adaptive_snapshot --orders 5000 --adaptive 1
  python -m scripts.benchmark_adaptive_snapshot --orders 5000 --adaptive 0

参数:
  --orders N            生成订单数量 (默认 10000)
  --symbols M           模拟标的数量 (默认 1)
  --adaptive {0,1}      是否启用 AdaptiveSnapshotPolicyManager (默认 1)
  --base-threshold K    基础阈值 (默认 settings.SNAPSHOT_THROTTLE_N_PER_SYMBOL)
  --seed S              随机种子 (默认 42)

说明:
  - 订单简单在买/卖之间交替, 价格在基准价附近微扰, 数量固定 100。
  - 若 adaptive=1, 每 symbol 由 manager 统计速率并可能放大阈值。
  - 为便于观察, 输出中包含初始与最终阈值列表。

"""
from __future__ import annotations
import argparse
import random
import time
from dataclasses import dataclass
from typing import List

try:
    from stock_sim.core.order import Order
    from stock_sim.core.const import OrderSide, OrderType, TimeInForce, EventType
    from stock_sim.core.matching_engine import MatchingEngine
    from stock_sim.infra.event_bus import event_bus
    from stock_sim.settings import settings
    from stock_sim.services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager
except Exception:  # 源码根目录 fallback
    from core.order import Order  # type: ignore
    from core.const import OrderSide, OrderType, TimeInForce, EventType  # type: ignore
    from core.matching_engine import MatchingEngine  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from settings import settings  # type: ignore
    from services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager  # type: ignore

@dataclass
class BenchResult:
    orders: int
    symbols: int
    elapsed: float
    snapshots: int
    avg_threshold: float | None
    thresholds_final: dict
    thresholds_initial: dict

    def as_dict(self):
        ops_per_sec = self.orders / self.elapsed if self.elapsed > 0 else 0
        return {
            'orders': self.orders,
            'symbols': self.symbols,
            'elapsed_sec': round(self.elapsed, 4),
            'ops_per_sec': round(ops_per_sec, 2),
            'snapshots': self.snapshots,
            'snapshot_ops_ratio': round(self.snapshots / max(1, self.orders), 4),
            'avg_threshold': self.avg_threshold,
            'initial_thresholds': self.thresholds_initial,
            'final_thresholds': self.thresholds_final,
        }

class _DummyInstrument:
    tick_size = 0.01
    lot_size = 100
    min_qty = 100
    settlement_cycle = 0
    market_cap = 1_000_000_000
    total_shares = 100_000_000
    free_float_shares = 80_000_000
    initial_price = 100.0

# ---------------- core bench -----------------
def run_bench(num_orders: int, num_symbols: int, adaptive: bool, base_threshold: int | None, seed: int) -> BenchResult:
    random.seed(seed)
    symbols = [f"SYM{i+1}" for i in range(num_symbols)]
    inst = _DummyInstrument()
    engine = MatchingEngine(symbols[0], inst)
    for s in symbols[1:]:
        engine.register_symbol(s, inst)
    mgr = None
    if adaptive:
        mgr = AdaptiveSnapshotPolicyManager(base_threshold=base_threshold)
        engine.set_adaptive_snapshot_manager(mgr)
    snapshot_events: List[dict] = []
    event_bus.subscribe(EventType.SNAPSHOT_UPDATED, lambda t, p: snapshot_events.append(p))
    # 记录初始阈值
    thresholds_initial = {}
    if mgr:
        for s in symbols:
            thresholds_initial[s] = mgr.get_threshold(s)
    base_px = 100.0
    t0 = time.perf_counter()
    for i in range(num_orders):
        sym = symbols[i % num_symbols]
        side = OrderSide.BUY if (i & 1) == 0 else OrderSide.SELL
        # 轻微波动 ±0.5%
        px = base_px * (1 + random.uniform(-0.005, 0.005))
        qty = 100
        o = Order(symbol=sym, side=side, price=px, quantity=qty, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
        engine.submit_order(o)
    elapsed = time.perf_counter() - t0
    # 最终阈值
    thresholds_final = {}
    avg_threshold = None
    if mgr:
        total = 0
        for s in symbols:
            th = mgr.get_threshold(s)
            thresholds_final[s] = th
            total += th
        avg_threshold = round(total / len(symbols), 2)
    return BenchResult(
        orders=num_orders,
        symbols=num_symbols,
        elapsed=elapsed,
        snapshots=len(snapshot_events),
        avg_threshold=avg_threshold,
        thresholds_final=thresholds_final,
        thresholds_initial=thresholds_initial,
    )

# ---------------- main -----------------
def main():
    parser = argparse.ArgumentParser(description="Benchmark adaptive snapshot policy")
    parser.add_argument('--orders', type=int, default=10_000)
    parser.add_argument('--symbols', type=int, default=1)
    parser.add_argument('--adaptive', type=int, default=1)
    parser.add_argument('--base-threshold', type=int, default=getattr(settings, 'SNAPSHOT_THROTTLE_N_PER_SYMBOL', 5))
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    res = run_bench(
        num_orders=args.orders,
        num_symbols=args.symbols,
        adaptive=bool(args.adaptive),
        base_threshold=args.base_threshold,
        seed=args.seed
    )
    print("[benchmark_adaptive_snapshot]", res.as_dict())

if __name__ == '__main__':  # pragma: no cover
    main()

