"""Panels 包初始化 (Spec Task 23)

提供:
- register_panel / get_panel / list_panels / dispose_panel / reset_registry
- register_builtin_panels(): 注册占位面板（后续任务 24~30 将替换具体实现）

占位面板目的:
- 验证惰性加载机制: 初次访问才实例化
- 为 MainWindow （后续）提供基础名称集合
"""
from __future__ import annotations
from .registry import (
    register_panel,
    get_panel,
    list_panels,
    dispose_panel,
    reset_registry,
    replace_panel,  # 新增
)

__all__ = [
    "register_panel",
    "get_panel",
    "list_panels",
    "dispose_panel",
    "reset_registry",
    "register_builtin_panels",
    "replace_panel",
    "register_ui_adapters",
]

_PLACEHOLDER_NAMES = [
    "account",
    "market",
    "agents",
    "leaderboard",
    "clock",
    # "settings",  # 已移除 Settings 面板
    "orders",  # 新增占位
]

class _PlaceholderPanel:
    def __init__(self, name: str):
        self.name = name
        self.initialized = True

    def __repr__(self):  # pragma: no cover
        return f"<PlaceholderPanel {self.name}>"

def register_builtin_panels():
    for name in _PLACEHOLDER_NAMES:
        try:
            register_panel(name, lambda n=name: _PlaceholderPanel(n), title=name.capitalize(), meta={"i18n_key": f"panel.{name}"})
        except Exception:
            pass

# ---------------- 实现注入：用 UI 适配器替换占位 ----------------

def register_ui_adapters():
    """
    将占位面板替换为“逻辑面板 + Qt 适配器”实例。
    - 若缺少依赖/GUI 不可用，静默忽略，保留占位面板。
    - 仅在首次启动时调用一次（建议在 run_frontend 预加载前）。
    """
    # account
    try:
        from app.services.account_service import AccountService
        from app.controllers.account_controller import AccountController
        from app.panels.account.panel import AccountPanel as _AccountLogic
        from app.state.settings_store import SettingsStore
        from app.ui.adapters.account_adapter import AccountPanelAdapter
        def _account_factory():
            svc = AccountService()
            ctl = AccountController(svc)
            store = SettingsStore(path="frontend_settings.json", auto_save=False)
            logic = _AccountLogic(ctl, settings_store=store)
            return AccountPanelAdapter().bind(logic)  # type: ignore
        replace_panel("account", _account_factory, title="Account", meta={"i18n_key": "panel.account"})
    except Exception:
        pass
    # market
    try:
        from app.services.market_data_service import MarketDataService
        from app.controllers.market_controller import MarketController
        from app.panels.market.panel import MarketPanel as _MarketLogic
        from app.ui.adapters.market_adapter import MarketPanelAdapter
        def _market_factory():
            svc = MarketDataService()
            ctl = MarketController(svc)
            logic = _MarketLogic(ctl, svc)
            return MarketPanelAdapter().bind(logic)  # type: ignore
        replace_panel("market", _market_factory, title="Market", meta={"i18n_key": "panel.market"})
    except Exception:
        pass
    # settings -> 移除，不再注册 Settings 面板
    # clock
    try:
        from app.services.clock_service import ClockService
        from app.services.rollback_service import RollbackService
        from app.controllers.clock_controller import ClockController
        from app.panels.clock.panel import ClockPanel as _ClockLogic
        from app.ui.adapters.clock_adapter import ClockPanelAdapter
        def _clock_factory():
            clk = ClockService()
            rb = RollbackService(clk)
            ctl = ClockController(clk, rb)
            logic = _ClockLogic(ctl)
            return ClockPanelAdapter().bind(logic)  # type: ignore
        replace_panel("clock", _clock_factory, title="Clock", meta={"i18n_key": "panel.clock"})
    except Exception:
        pass
    # leaderboard
    try:
        from app.services.leaderboard_service import LeaderboardService
        from app.controllers.leaderboard_controller import LeaderboardController
        from app.panels.leaderboard.panel import LeaderboardPanel as _LbLogic
        from app.ui.adapters.leaderboard_adapter import LeaderboardPanelAdapter
        def _lb_factory():
            svc = LeaderboardService()
            ctl = LeaderboardController(svc)
            logic = _LbLogic(ctl)
            return LeaderboardPanelAdapter().bind(logic)  # type: ignore
        replace_panel("leaderboard", _lb_factory, title="Leaderboard", meta={"i18n_key": "panel.leaderboard"})
    except Exception:
        pass
    # agents（若有）
    try:
        from app.services.agent_service import AgentService  # type: ignore
        from app.controllers.agent_controller import AgentController  # type: ignore
        from app.panels.agents.panel import AgentsPanel as _AgentsLogic  # type: ignore
        from app.ui.adapters.agents_adapter import AgentsPanelAdapter  # type: ignore
        def _agents_factory():
            svc = AgentService()
            ctl = AgentController(svc)
            logic = _AgentsLogic(ctl, svc)
            return AgentsPanelAdapter().bind(logic)  # type: ignore
        replace_panel("agents", _agents_factory, title="Agents", meta={"i18n_key": "panel.agents"})
    except Exception:
        pass
    # orders（新增）
    try:
        from app.panels.orders import OrdersPanel as _OrdersLogic
        from app.ui.adapters.orders_adapter import OrdersPanelAdapter
        def _orders_factory():
            logic = _OrdersLogic()
            return OrdersPanelAdapter().bind(logic)  # type: ignore
        replace_panel("orders", _orders_factory, title="Orders", meta={"i18n_key": "panel.orders"})
    except Exception:
        pass
