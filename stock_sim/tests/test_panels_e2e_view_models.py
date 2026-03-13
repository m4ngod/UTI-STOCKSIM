from __future__ import annotations
"""E2E: 以无 UI (headless) 方式打开核心面板并校验 view model 结构.
核心面板名称与占位列表一致: account / market / agents / leaderboard / clock
限制: 不启动 Qt 事件循环; 使用最小 stub 依赖.
成功: 每个面板 get_view() 返回包含预期顶层键.
"""
import time
from typing import List, Dict, Any, Callable

from app.panels import register_builtin_panels, replace_panel, get_panel, reset_registry
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService, Timeframe
from app.controllers.market_controller import MarketController
from app.core_dto.account import AccountDTO, PositionDTO
from app.core_dto.leaderboard import LeaderboardRowDTO
from app.core_dto.clock import ClockStateDTO
from app.panels.account.panel import AccountPanel
from app.panels.agents.panel import AgentsPanel
from app.panels.leaderboard.panel import LeaderboardPanel
from app.panels.clock.panel import ClockPanel
from app.controllers.account_controller import AccountController

# ---------------- 简易 Stub SettingsStore -----------------
# 已移除 Settings 面板相关测试，保留最小占位（若有面板内部使用可替代）

# ---------------- Stubs -----------------
class _StubAccountService:
    def load_account(self, account_id: str):  # 返回固定账户
        pos = [
            PositionDTO(symbol="AAA", quantity=10, frozen_qty=0, avg_price=100.0, borrowed_qty=0, pnl_unreal=5.0),
            PositionDTO(symbol="BBB", quantity=20, frozen_qty=0, avg_price=50.0, borrowed_qty=0, pnl_unreal=-3.0),
        ]
        equity = 10000.0
        return AccountDTO(
            account_id=account_id,
            cash=5000.0,
            frozen_cash=0.0,
            positions=pos,
            realized_pnl=0.0,
            unrealized_pnl=sum(p.pnl_unreal or 0 for p in pos),
            equity=equity,
            utilization=0.25,
            snapshot_id="snap-1",
            sim_day="2024-01-01",
        )

class _StubAgentController:
    def list_agents(self):  # 返回空列表
        return []
    def control(self, agent_id: str, action: str):  # 不会在本测试调用
        raise RuntimeError("not implemented")

class _StubAgentService:
    def batch_create_retail(self, cfg):  # 不触发
        return []
    def tail_logs(self, agent_id: str, n: int):
        return []

class _StubLeaderboardController:
    def windows(self):
        return ["1d", "7d"]
    def refresh(self, window: str, limit: int = 50, force_refresh: bool = False):
        # 返回两行示例
        return [
            LeaderboardRowDTO(agent_id="ag1", rank=1, rank_delta=0, return_pct=0.10, sharpe=1.2, max_drawdown=0.05, win_rate=0.6, equity=110000.0),
            LeaderboardRowDTO(agent_id="ag2", rank=2, rank_delta=+1, return_pct=0.05, sharpe=0.9, max_drawdown=0.04, win_rate=0.55, equity=105000.0),
        ]
    def export(self, window: str, fmt: str = "csv", limit: int = 50):
        return f"leaderboard_{window}.{fmt}"

class _StubClockController:
    def __init__(self):
        self._state = ClockStateDTO(status="STOPPED", sim_day="2024-01-01", speed=1.0, ts=int(time.time()*1000))
        self._cps: List[Dict[str, Any]] = []
    def state(self):
        return self._state
    def start(self, sim_day=None):
        if sim_day:
            self._state = ClockStateDTO(status="RUNNING", sim_day=sim_day, speed=self._state.speed, ts=int(time.time()*1000))
        else:
            self._state = ClockStateDTO(status="RUNNING", sim_day=self._state.sim_day, speed=self._state.speed, ts=int(time.time()*1000))
        return self._state
    def pause(self):
        self._state = ClockStateDTO(status="PAUSED", sim_day=self._state.sim_day, speed=self._state.speed, ts=int(time.time()*1000))
        return self._state
    def resume(self):
        self._state = ClockStateDTO(status="RUNNING", sim_day=self._state.sim_day, speed=self._state.speed, ts=int(time.time()*1000))
        return self._state
    def stop(self):
        self._state = ClockStateDTO(status="STOPPED", sim_day=self._state.sim_day, speed=self._state.speed, ts=int(time.time()*1000))
        return self._state
    def set_speed(self, speed: float):
        self._state = ClockStateDTO(status=self._state.status, sim_day=self._state.sim_day, speed= speed, ts=int(time.time()*1000))
        return self._state
    def create_checkpoint(self, label: str):
        cid = f"cp-{len(self._cps)+1}"
        self._cps.append({"id": cid, "label": label, "sim_day": self._state.sim_day, "created_ms": int(time.time()*1000), "is_current": True})
        # 取消旧 current
        for c in self._cps[:-1]:
            c["is_current"] = False
        return cid
    def list_checkpoints(self):
        return list(self._cps)
    def rollback(self, checkpoint_id: str, simulate_inconsistent: bool = False):
        # 简化: 直接标记该 cp 为 current
        for c in self._cps:
            c["is_current"] = (c["id"] == checkpoint_id)
        return self._state

# 市场 fetcher (小数据)
def _mini_fetcher(symbol: str, timeframe: Timeframe, limit: int):
    n = 10
    now = int(time.time()*1000)
    interval = 60_000
    start = now - (n-1)*interval
    bars = []
    for i in range(n):
        ts = start + i*interval
        price = 100 + i
        bars.append({
            "ts": ts,
            "open": price - 0.5,
            "high": price + 0.5,
            "low": price - 1.0,
            "close": price,
            "volume": 100 + i,
        })
    return bars

# ---------------- Test -----------------

def test_open_all_core_panels_and_validate_view_models():
    reset_registry()
    register_builtin_panels()  # 注册占位

    # AccountPanel
    acct_service = _StubAccountService()
    acct_ctl = AccountController(acct_service)
    def _account_factory():
        p = AccountPanel(acct_ctl, None)
        p.switch_account("ACC-1")
        return p
    replace_panel("account", _account_factory, title="Account")

    # MarketPanel
    mkt_svc = MarketDataService(fetcher=_mini_fetcher, default_limit=10)
    mkt_ctl = MarketController(mkt_svc)
    def _market_factory():
        p = MarketPanel(mkt_ctl, mkt_svc)
        p.select_symbol("SYM1", timeframe="1m")
        return p
    replace_panel("market", _market_factory, title="Market")

    # AgentsPanel
    ag_ctl = _StubAgentController()
    ag_svc = _StubAgentService()
    def _agents_factory():
        return AgentsPanel(ag_ctl, ag_svc)
    replace_panel("agents", _agents_factory, title="Agents")

    # LeaderboardPanel
    lb_ctl = _StubLeaderboardController()
    def _leaderboard_factory():
        return LeaderboardPanel(lb_ctl)
    replace_panel("leaderboard", _leaderboard_factory, title="Leaderboard")

    # ClockPanel
    clock_ctl = _StubClockController()
    def _clock_factory():
        return ClockPanel(clock_ctl)
    replace_panel("clock", _clock_factory, title="Clock")

    expected_keys = {
        "account": {"account", "positions", "filter"},
        "market": {"watchlist", "filter", "sort_by", "selected"},
        "agents": {"agents", "batch"},
        "leaderboard": {"window", "windows", "sort_by", "rows", "selected", "last_refresh_ts"},
        "clock": {"state", "checkpoints", "current_checkpoint", "last_action_ms"},
    }

    for name, keys in expected_keys.items():
        panel = get_panel(name)
        assert panel is not None, f"panel {name} 未创建"
        assert hasattr(panel, "get_view"), f"panel {name} 缺少 get_view 方法"
        view = panel.get_view()
        assert isinstance(view, dict), f"panel {name} get_view 返回类型应为 dict"
        missing = keys - set(view.keys())
        assert not missing, f"panel {name} view 缺少键: {missing}"
