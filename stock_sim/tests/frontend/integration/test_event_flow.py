import time
import os
import math
from typing import List

from infra.event_bus import event_bus
from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController
from app.services.leaderboard_service import LeaderboardService
from app.controllers.leaderboard_controller import LeaderboardController
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.services.account_service import AccountService

# 该集成测试覆盖 R1-R5,R10 核心链路 (事件→控制器→视图/导出/回滚)
# 验证目标:
# 1. snapshot 事件经 EventBridge 聚合后被 MarketController 合并
# 2. 计算 snapshot 注入→flush→合并的延迟 P95 < 250ms (mock 环境)
# 3. LeaderboardController 刷新并产生 rank_delta
# 4. RollbackService 回滚成功
# 5. AccountService 提供缓存账户
# 6. 排行榜导出生成 meta 行


def _percentile(vals: List[float], pct: float) -> float:
    if not vals:
        return math.nan
    vals_sorted = sorted(vals)
    k = (len(vals_sorted) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(vals_sorted) - 1)
    if f == c:
        return vals_sorted[f]
    d0 = vals_sorted[f] * (c - k)
    d1 = vals_sorted[c] * (k - f)
    return d0 + d1


def test_event_flow_integration(tmp_path):
    # --- 1. 构建 EventBridge + MarketController 订阅 ---
    bridge = EventBridge(flush_interval_ms=40, max_batch_size=200)
    mc = MarketController(MarketDataService())
    latencies: List[float] = []

    def on_batch(_topic: str, payload):
        batch = payload.get("snapshots") or []
        now_ns = time.perf_counter_ns()
        clean = []
        for s in batch:
            inj = s.get("_t")
            if inj:
                latencies.append((now_ns - inj) / 1_000_000.0)
            # 去除内部计时键, 以免 DTO 校验失败
            clean.append({k: v for k, v in s.items() if k != "_t"})
        mc.merge_batch(clean)

    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, on_batch)
    bridge.start()

    total = 300  # 适中数量模拟
    symbols = 30
    for i in range(total):
        snap = {
            "symbol": f"SYM{i % symbols:03d}",
            "last": 100.0 + (i % 50) * 0.05,
            "bid_levels": [(100.0, 10)],
            "ask_levels": [(100.1, 12)],
            "volume": i,
            "turnover": float(i) * 10.0,
            "ts": int(time.time() * 1000),
            "snapshot_id": f"it-{i}",
            "_t": time.perf_counter_ns(),
        }
        bridge.on_snapshot(snap)
    # 等待 flush 完成
    time.sleep(0.25)
    bridge.stop()

    # MarketController 已合并
    snap_view = mc.list_snapshots()
    assert snap_view["total"] > 0

    p95 = _percentile(latencies, 95)
    # 若数据为空则失败 (说明事件未流动)
    assert latencies, "no latencies captured"
    assert p95 < 250, f"P95 latency {p95:.2f}ms should < 250ms"

    # --- 2. Leaderboard 刷新 & rank_delta 检验 ---
    lb_ctrl = LeaderboardController(LeaderboardService())
    rows1 = lb_ctrl.refresh("1d", limit=20)
    assert rows1 and len(rows1) <= 20
    rows2 = lb_ctrl.refresh("1d", limit=20, force_refresh=True)
    assert any(r.rank_delta is not None for r in rows2 if r.agent_id == rows1[0].agent_id) or any(
        r.rank_delta is not None for r in rows2
    )

    # --- 3. 账户缓存 ---
    acc_svc = AccountService()
    acc = acc_svc.load_account("ACC_INT")
    assert acc_svc.get_cached() is not None and acc.equity >= 0

    # --- 4. 回滚 ---
    clock = ClockService()
    rb = RollbackService(clock)
    clock.start("2025-08-01")
    cp = rb.create_checkpoint("base")
    clock.start("2025-08-02")
    rb.rollback(cp)
    assert clock.get_state().sim_day == "2025-08-01"

    # --- 5. 排行榜导出 ---
    export_path = lb_ctrl.export("1d", "csv", limit=10, force_refresh=False)
    assert os.path.isfile(export_path)
    with open(export_path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
    assert first.startswith("# meta ") and "window=1d" in first

    # 简单打印用于调试 (非断言)
    print(f"integration_event_flow_p95_ms={p95:.2f}")

