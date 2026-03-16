"""multi_strategy_retail.py
多标的(only) 多策略 Agent 页面:
  支持策略: mean_revert / momentum_chase / breakout / scalping
  所有 Agent 必须绑定 >=1 个 symbol, 不再支持单标独立实现, 统一走多标调度/评分路径。
使用示例:
  from agents.multi_strategy_retail import MultiStrategyPage
  msp = MultiStrategyPage(main)
  agent = msp.add_pool_agent(["T1","T2"])  # 仅此接口
"""
from __future__ import annotations
import random, time
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce, EventType
from stock_sim.infra.event_bus import event_bus
from stock_sim.services.ipo_grant_queue import enqueue_ipo_grant, ensure_ipo_grant_worker_started  # 新增
from stock_sim.services.ipo_grant_queue import fallback_direct_grant  # 新增: 直接授予回退

# ---- Agent ----
STRATEGIES = ["mean_revert", "momentum_chase", "breakout", "scalping"]
OLD_STRAT_MAP = {"A": "mean_revert", "B": "momentum_chase", "C": "breakout", "D": "scalping"}

@dataclass
class AgentState:
    strategy: str
    price_window: List[float]
    max_window: int = 200
    position: int = 0
    avg_price: float = 0.0
    initial_nav: Optional[float] = None
    last_nav: Optional[float] = None
    last_switch_nav: Optional[float] = None
    last_tick_ts: float = 0.0
    orders: int = 0

@dataclass
class MSRStatsCompat:
    orders: int = 0
    last_side: str | None = None
    last_ts: float = 0.0
    strategy: str = 'mean_revert'

class StrategyRegistry:
    def __init__(self):
        self._acc_strategy: dict[str,str] = {}
        self._agent_acc: dict[str,str] = {}
    def register(self, agent_name: str, account_id: str, strategy: str):
        self._acc_strategy[account_id] = strategy; self._agent_acc[agent_name]=account_id
    def update(self, account_id: str, strategy: str):
        self._acc_strategy[account_id] = strategy
    def get(self, account_id: str) -> str | None:
        return self._acc_strategy.get(account_id)
    def all(self): return dict(self._acc_strategy)

strategy_registry = StrategyRegistry()

# --- 新增: 多标的 slot 结构（供统一 MultiStrategyAgent 使用） ---
@dataclass
class _MSymbolSlot:
    symbol: str
    prices: list[float] = field(default_factory=list)
    last_price: float = 0.0
    position: int = 0
    avg_price: float = 0.0
    max_window: int = 240

class MultiStrategyAgent:
    def __init__(self,
                 name: str,
                 symbols: list[str],
                 account_id: str,
                 order_service_provider: Callable[[str], object],
                 snapshot_provider: Callable[[str], object],
                 lot_size: int = 10,
                 interval: float = 1.5,
                 switch_threshold: float = 0.20,
                 initial_strategy: str | None = None,
                 debug: bool = True,
                 ipo_auto_grant_shares: int | None = None,
                 first_day_random: bool = False):  # 新增 first_day_random
        self.name = name; self.account_id = account_id
        self._osp = order_service_provider; self._ssp = snapshot_provider
        self.lot_size = lot_size; self.interval = max(0.4, float(interval))
        self.switch_threshold = switch_threshold
        init_stg = initial_strategy or random.choice(STRATEGIES)
        init_stg = OLD_STRAT_MAP.get(init_stg, init_stg)
        if init_stg not in STRATEGIES: init_stg = 'mean_revert'
        self.state = AgentState(strategy=init_stg, price_window=[])
        self.enabled = False; self.debug = debug
        self.stats = MSRStatsCompat(strategy=self.state.strategy)
        strategy_registry.register(name, account_id, self.state.strategy)
        event_bus.subscribe(EventType.ACCOUNT_UPDATED, self._on_account_update)
        event_bus.subscribe(EventType.STRATEGY_CHANGED, self._on_external_strategy_change)
        self._min_windows = {'mean_revert':30,'momentum_chase':15,'breakout':40,'scalping':12}
        self._fast_warmup = 5
        self._debug_tick_count = 0; self._debug_force_first = False
        self.dynamic_sizing = True; self.base_lot = max(1, lot_size); self.max_position_lots = 50
        self.max_order_lots = 30; self.sell_pct_cap = 0.18; self.sell_pct_min = 0.03
        self._baseline_ipo_pos = 0
        # 多标专用
        self.symbols = [s for s in symbols if s]
        if not self.symbols:
            raise ValueError("symbols 不能为空 (multi-only agent)")
        self._multi_slots: dict[str, _MSymbolSlot] = {s: _MSymbolSlot(s) for s in self.symbols}
        self._last_trade_symbol: str | None = None
        self._ipo_auto_grant_shares = ipo_auto_grant_shares or 0; self._ipo_granted_flag = False
        self._ipo_enqueue_ok = False  # 新增: 记录是否成功入队
        # 首日随机配置（多标版本）
        self.first_day_random = bool(first_day_random)
        self.first_day_random_interval_ticks = 5
        self._last_first_day_random_tick_map: dict[str,int] = {s:-999 for s in self.symbols}
        self._first_day_flag_map: dict[str,bool] = {}
        self.debug_explain = True; self.debug_price_detail = False; self.debug_no_signal_every = 25
        if self.debug:
            print(f"[MSP Init] name={self.name} symbols={self.symbols} strat={self.state.strategy} interval={self.interval} lot={self.lot_size} fdr={self.first_day_random}")
        # 播种所有 symbol 的初始价格（若缺 last_price）
        self._seed_all_initial_prices()

    # 兼容属性：primary_symbol（用于 IPO 授权等单一上下文需求）
    @property
    def primary_symbol(self) -> str:
        return self.symbols[0]

    @property
    def symbol(self) -> str:  # 兼容旧引用
        return self.primary_symbol

    def enable_force_first(self, on: bool = True):
        self._debug_force_first = bool(on)
        if self.debug:
            print(f"[MSP Debug] force_first set to {self._debug_force_first} for {self.name}")
        return self

    def enable_seed_entry(self, on: bool = True):
        self._enable_seed_entry = bool(on)
        if self.debug:
            print(f"[MSP Debug] seed_entry set to {self._enable_seed_entry} for {self.name}")
        return self

    # ---- lifecycle ----
    def start(self): self.enabled = True; self._maybe_grant_initial()
    def stop(self): self.enabled = False

    def _maybe_grant_initial(self):
        if self._ipo_auto_grant_shares <= 0 or self._ipo_granted_flag:
            return
        # 先尝试同步直接授予，避免队列慢导致 10s+ 延迟
        try:
            fb_direct = False
            try:
                fb_direct = fallback_direct_grant(self.account_id, self.symbols, int(self._ipo_auto_grant_shares))
            except Exception:
                fb_direct = False
            if fb_direct:
                self._ipo_granted_flag = True
                if self.debug:
                    self._dbg('ipo_direct_grant', shares=self._ipo_auto_grant_shares, symbols=self.symbols)
                return
        except Exception:
            pass
        # 队列异步方案（保留原逻辑）
        try:
            ensure_ipo_grant_worker_started()
            ok = enqueue_ipo_grant(self.account_id, self.symbols, int(self._ipo_auto_grant_shares))
            self._ipo_enqueue_ok = ok
            if not ok:
                fb = fallback_direct_grant(self.account_id, self.symbols, int(self._ipo_auto_grant_shares))
                if self.debug:
                    self._dbg('ipo_fallback_direct', ok=fb)
                if not fb:
                    return
            self._ipo_granted_flag = True
            if self.debug:
                self._dbg('ipo_enqueue', shares=self._ipo_auto_grant_shares, symbols=self.symbols, queued=ok)
        except Exception as e:
            if self.debug:
                self._dbg('ipo_enqueue_err', e)
            return

    # 新增: 播种所有 symbol snapshot 的初始价
    def _seed_all_initial_prices(self):
        try:
            from stock_sim.services.engine_registry import engine_registry as _er
            for sym in self.symbols:
                try:
                    eng = _er.get(sym)
                    if not eng: continue
                    snap = getattr(eng, 'snapshot', None)
                    inst = getattr(eng, 'instrument', None)
                    if not snap or not inst: continue
                    lp = getattr(snap, 'last_price', None)
                    if (lp is None or lp <= 0) and getattr(inst, 'initial_price', None):
                        ip = float(inst.initial_price or 0)
                        if ip > 0:
                            snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = ip
                            lp = ip
                    # 预热价格窗口(若为空) —— 立即达到 warmup 要求，避免长时间 warm len=1
                    slot = self._multi_slots.get(sym)
                    if slot and lp and lp > 0 and not slot.prices:
                        for _ in range(self._fast_warmup):
                            slot.prices.append(lp)
                        slot.last_price = lp
                except Exception:
                    continue
        except Exception:
            pass

    # 新增: 从 DB/缓存解析 NAV（首日随机下单 nav 为空时兜底）
    def _resolve_nav(self) -> float | None:
        try:
            svc = self._osp(self.primary_symbol)
            session = getattr(svc, 's', None)
            if not session:
                return None
            from stock_sim.persistence.models_account import Account as AccountORM
            acc = session.get(AccountORM, self.account_id)
            if not acc:
                return None
            cash = float(getattr(acc, 'cash', 0.0) or 0.0)
            pos_val = 0.0
            for p in getattr(acc, 'positions', []) or []:
                sym = getattr(p, 'symbol', None)
                if not sym: continue
                slot = self._multi_slots.get(sym)
                px = slot.last_price if slot else getattr(p, 'avg_price', 0.0)
                if px and getattr(p, 'quantity', 0) > 0:
                    pos_val += px * p.quantity
            return cash + pos_val
        except Exception:
            return None

    # ===== 恢复: 账户事件 & 外部策略切换回调 =====
    def _on_account_update(self, topic: str, payload: dict):  # event_bus 回调签名 (topic, payload)
        try:
            acc = (payload or {}).get('account') or {}
            if acc.get('id') != self.account_id:
                return
            nav = acc.get('nav')
            if nav is not None:
                nav = float(nav)
                if self.state.initial_nav is None:
                    self.state.initial_nav = nav
                    self.state.last_switch_nav = nav
                self.state.last_nav = nav
            # 映射持仓
            pos_map = {p.get('symbol'): p for p in acc.get('positions', [])}
            total_pos = 0
            for sym, slot in self._multi_slots.items():
                p = pos_map.get(sym)
                if p:
                    slot.position = int(p.get('quantity', 0) or 0)
                    slot.avg_price = float(p.get('avg_price', 0.0) or 0.0)
                else:
                    slot.position = 0
                    slot.avg_price = 0.0
                total_pos += slot.position
            self.state.position = total_pos
        except Exception:
            if self.debug:
                self._dbg('acct_update_err')

    def _on_external_strategy_change(self, topic: str, payload: dict):
        try:
            if not isinstance(payload, dict):
                return
            if payload.get('account_id') != self.account_id:
                return
            new_stg = payload.get('new_strategy') or payload.get('strategy')
            if not new_stg:
                return
            if self.set_strategy(new_stg) and self.debug:
                self._dbg('external_switch', from_=self.state.strategy, to=new_stg)
        except Exception:
            if self.debug:
                self._dbg('external_switch_err')

            return False
        self._place_multi(sym, slot, side, trade_px, 'first_day_random')
        self._last_first_day_random_tick_map[sym] = self._debug_tick_count
        if self.debug:
            self._dbg('rnd_order', sym, side=side.name, qty=qty, px=trade_px, nav=round(nav, 2))
        return True

# ---- 顶层页面与兼容包装类（从内部类提升） ----
class MultiStrategyPage:
    def __init__(self, main):
        self.main = main
        self.agents: List[MultiStrategyAgent] = []
        self.scheduler = getattr(main, 'scheduler', None)
    def add_agent(self, *args, **kwargs):  # 单标接口废弃
        raise RuntimeError("单标 agent 已移除，请使用 add_pool_agent(symbols=[...])")
    def add_pool_agent(self, symbols: list[str], account_id: str | None = None, lot_size: int = 10, interval: float = 1.5, ipo_grant: int | None = 10000, first_day_random: bool = True):
        acct_svc = getattr(self.main, 'account_service', None)
        if account_id is None and acct_svc:
            acc = acct_svc.create_retail(); account_id = acc.id
        name = self._gen_name()
        # 改进: 优先使用 StrategyPage 预创建的 _order_services
        def _order_service_provider(sym: str):
            # 统一使用主 OrderService；若未初始化则懒创建
            try:
                svc = getattr(self.main, 'order_service', None)
                if svc is None:
                    from stock_sim.services.order_service import OrderService
                    setattr(self.main, 'order_service', OrderService(self.main._session, None))
                    svc = self.main.order_service
                return svc
            except Exception:
                return None
        def _snapshot_provider(sym: str):
            # 直接从 engine_registry 获取对应引擎 snapshot
            try:
                from stock_sim.services.engine_registry import engine_registry as _er
                eng = _er.get(sym)
                return getattr(eng, 'snapshot', None) if eng else None
            except Exception:
                return None
        agent = MultiStrategyAgent(
            name=name,
            symbols=symbols,
            account_id=account_id,
            order_service_provider=_order_service_provider,
            snapshot_provider=_snapshot_provider,
            lot_size=lot_size,
            interval=interval,
            debug=True,
            ipo_auto_grant_shares=ipo_grant,
            first_day_random=first_day_random
        )
        self.agents.append(agent)
        # (A) 移除内部 msp_tick_ 调度注册, 统一由 StrategyPage 使用 agent_tick_<name>
        # if self.scheduler:
        #     try:
        #         self.scheduler.add_task(f"msp_tick_{name}", agent.interval, agent.tick, enabled=False)
        #     except Exception:
        #         pass
        return agent
    def start_all(self):
        if self.scheduler:
            for a in self.agents:
                a.start();
                try: self.scheduler.enable(f"msp_tick_{a.name}", True)
                except Exception: pass
    def stop_all(self):
        if self.scheduler:
            for a in self.agents:
                a.stop();
                try: self.scheduler.enable(f"msp_tick_{a.name}", False)
                except Exception: pass
    def statuses(self): return [a.status() for a in self.agents]
    def _gen_name(self):
        i=1; exist={a.name for a in self.agents}
        while True:
            cand=f"MSP{i:03d}"; i+=1
            if cand not in exist: return cand
