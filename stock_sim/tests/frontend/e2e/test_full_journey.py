import time
import os
import pytest

from infra.event_bus import event_bus
from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController
from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentService
from app.controllers.agent_config_controller import AgentConfigController
from app.state.version_store import VersionStore
from app.security.script_validator import ScriptValidator
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.services.leaderboard_service import LeaderboardService
from app.controllers.leaderboard_controller import LeaderboardController

# E2E 用户旅程覆盖: 启动(行情流) → 创建零售批量 → 指标开关(请求+回调) → 参数版本回滚 → 时钟回滚 → 排行榜导出
# 断言关键状态以模拟多面板交互 (R1-R5,R7,R8,R10)


def test_full_journey_e2e(tmp_path):
    # --- 启动: 行情事件流 & 市场控制器 ---
    bridge = EventBridge(flush_interval_ms=30, max_batch_size=128)
    market_ctrl = MarketController(MarketDataService())

    def on_batch(_topic: str, payload):
        snaps = payload.get("snapshots") or []
        cleaned = [{k: v for k, v in s.items() if k != "_t"} for s in snaps]
        if cleaned:
            market_ctrl.merge_batch(cleaned)

    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, on_batch)
    bridge.start()
    for i in range(120):  # 产生一些 snapshot
        bridge.on_snapshot({
            "symbol": f"SYM{i%5:02d}",
            "last": 100 + (i % 20) * 0.1,
            "bid_levels": [(100.0, 5)],
            "ask_levels": [(100.1, 6)],
            "volume": i,
            "turnover": float(i) * 5.0,
            "ts": int(time.time() * 1000),
            "snapshot_id": f"sj-{i}",
            "_t": time.perf_counter_ns(),
        })
    time.sleep(0.25)
    bridge.stop()
    view = market_ctrl.list_snapshots()
    assert view["total"] >= 5

    # --- 批量创建零售智能体 ---
    agent_service = AgentService()
    creation_ctrl = AgentCreationController(agent_service)
    batch_res = creation_ctrl.batch_create(agent_type="Retail", count=4, name_prefix="rt")
    assert len(batch_res["success_ids"]) == 4 and not batch_res["failed"]

    # --- 指标请求 (MA) & 回调轮询 ---
    symbol = view["items"][0].symbol
    indicator_done = {"flag": False, "meta": None, "result": None}

    def indicator_cb(result, meta):  # 修正签名 (MarketController 传入 (result, meta))
        indicator_done["flag"] = True
        indicator_done["meta"] = meta
        indicator_done["result"] = result

    # 请求 1m timeframe, window=10
    fut = market_ctrl.request_indicator(symbol=symbol, timeframe="1m", name="ma", callback=indicator_cb, window=10)

    # 先等待 future 完成（最多 5s），再轮询回调 (最长 5s)
    fut.result(timeout=5)
    from app.indicators.executor import indicator_executor
    t0 = time.time()
    while not indicator_done["flag"] and time.time() - t0 < 5.0:
        indicator_executor.poll_callbacks()
        time.sleep(0.02)
    if not indicator_done["flag"]:
        pending = indicator_executor.pending_count()
        pytest.fail(f"INDICATOR_CALLBACK_TIMEOUT pending={pending}")
    assert indicator_done["meta"]["error"] is None
    assert indicator_done["result"] is not None

    # --- 参数版本新增 + 回滚 ---
    vs = VersionStore(str(tmp_path / "version_store.json"))
    validator = ScriptValidator()
    cfg_ctrl = AgentConfigController(agent_service, vs, validator)
    aid = agent_service.list_agents()[0].agent_id
    v1 = cfg_ctrl.add_version(aid, {"lr": 0.01}, author="tester")
    v2 = cfg_ctrl.add_version(aid, {"lr": 0.02}, author="tester")
    v3 = cfg_ctrl.rollback(aid, target_version=1, author="tester")
    assert (v1.version, v2.version, v3.version) == (1, 2, 3) and v3.rollback_of == 1

    # --- 时钟回滚 (模拟交易日) ---
    clock = ClockService(); rb = RollbackService(clock)
    clock.start("2025-09-01"); cp = rb.create_checkpoint("base")
    clock.start("2025-09-02"); rb.rollback(cp)
    assert clock.get_state().sim_day == "2025-09-01"

    # --- 排行榜导出 ---
    lb_ctrl = LeaderboardController(LeaderboardService())
    lb_ctrl.refresh("1d", limit=15)
    export_path = lb_ctrl.export("1d", "csv", limit=15)
    assert os.path.isfile(export_path)
    with open(export_path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
    assert first.startswith("# meta ") and "window=1d" in first

    # 调试输出 (便于失败时查看)
    print(
        "journey_status", {
            "snapshots_total": view["total"],
            "agents": len(agent_service.list_agents()),
            "indicator_ms": indicator_done["meta"]["duration_ms"],
            "versions": [x.version for x in cfg_ctrl.list_versions(aid)],
            "export": export_path,
        }
    )
