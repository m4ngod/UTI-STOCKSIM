# python
# file: rl/trading_env.py
import math
import dataclasses
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import List, Dict, Tuple, Optional, Callable
from datetime import datetime

# 新增导入供 LegacyTradingEnv 使用
from stock_sim.core.const import OrderSide, OrderType, TimeInForce
from stock_sim.core.order import Order
from stock_sim.services.order_service import OrderService
from stock_sim.core.matching_engine import MatchingEngine

from stock_sim.settings import settings

# 新增: 可选账户适配器导入 (Req7)
try:  # type: ignore
    from stock_sim.rl.account_adapter import AccountAdapter  # type: ignore
except Exception:  # noqa
    try:
        from rl.account_adapter import AccountAdapter  # type: ignore
    except Exception:  # noqa
        AccountAdapter = None  # 占位, 运行时再判断

# 保留原单标模拟（临时兼容）
class LegacyTradingEnv(gym.Env):
    """
    Observation 结构（示例）：
      [ last_price,
        bid1_px, bid1_qty, ask1_px, ask1_qty,
        ... N=5 档 ...
        pos_qty, cash, frozen_cash,
        unrealized_pnl, utilization, time_norm,
        k1_open, k1_high, k1_low, k1_close, ... K=10 根 (占位为 0)
      ]
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self, engine: MatchingEngine, order_service: OrderService, account_id: str, symbol: str,
                 n_levels: int = 5, k_bars: int = 10, account_adapter: AccountAdapter | None = None):
        self.engine = engine
        self.order_service = order_service
        self.account_id = account_id
        self.symbol = symbol
        self.n_levels = n_levels
        self.k_bars = k_bars
        self.account_adapter = account_adapter  # 可选真实账户适配器
        # 观测长度估算
        base = 1 + n_levels * 4 + 6 + k_bars * 4
        self.action_space = spaces.Box(low=np.array([-1, 0, 0]), high=np.array([1, 1, 1]), dtype=np.float32)
        self.observation_space = spaces.Box(low=-1e12, high=1e12, shape=(base,), dtype=np.float32)
        self._last_nav = 0.0
        self._step = 0
        self._k_buffer = []

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._step = 0
        self._last_nav = 0.0
        self._k_buffer.clear()
        return self._observe(), {}

    def step(self, action):
        # action: [side_bias(-1~1), qty_ratio(0~1), price_offset_ratio(0~1)]
        side = OrderSide.BUY if action[0] >= 0 else OrderSide.SELL
        qty_ratio = float(np.clip(action[1], 0, 1))
        px_off = float(np.clip(action[2], 0, 1))
        depth = self.engine.snapshot
        ref_px = depth.last_price or (depth.bid_levels[0][0] if depth.bid_levels else 100.0)
        price = ref_px * (1 + (0.001 * px_off if side is OrderSide.BUY else -0.001 * px_off))
        qty = int(100 * max(1, round(10 * qty_ratio)))
        reject_reason = None
        if qty > 0 and price > 0:
            order = Order(symbol=self.symbol, side=side, price=price, quantity=qty,
                          account_id=self.account_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            self.order_service.place_order(order)
            if order.status.name == 'REJECTED':
                reject_reason = 'REJECT'
        obs = self._observe()
        nav = obs[1] + obs[2]  # 简化：pos_qty*last_price + cash （示意）
        reward = (nav - self._last_nav) - settings.ENV_REWARD_COST_WEIGHT * 0.0
        if reject_reason:
            reward -= 0.001  # 微小惩罚
        self._last_nav = nav
        self._step += 1
        terminated = self._step >= 1000
        info = {'reject': reject_reason} if reject_reason else {}
        return obs, float(reward), terminated, False, info

    def _observe(self):
        snap = self.engine.snapshot
        last = snap.last_price or 100.0
        # 盘口
        vec = [last]
        for i in range(self.n_levels):
            if i < len(snap.bid_levels):
                vec.extend([snap.bid_levels[i][0], snap.bid_levels[i][1]])
            else:
                vec.extend([last, 0])
            if i < len(snap.ask_levels):
                vec.extend([snap.ask_levels[i][0], snap.ask_levels[i][1]])
            else:
                vec.extend([last, 0])
        # 账户 (若注入 account_adapter 则使用真实数据)
        if self.account_adapter is not None:
            try:
                state = self.account_adapter.get_account_state([self.symbol])
                pos_qty = state.positions[self.symbol]['qty']
                cash = state.cash
                last_px = last
                avg_price = state.positions[self.symbol]['avg_price'] or last_px
                unrealized = (last_px - avg_price) * pos_qty
                utilization = (pos_qty * last_px) / max(1.0, cash + pos_qty * last_px)
            except Exception:
                pos_qty = 0.0; cash = settings.DEFAULT_CASH; unrealized = 0.0; utilization = 0.0
        else:
            pos_qty = 0.0
            cash = settings.DEFAULT_CASH
            unrealized = 0.0
            utilization = pos_qty * last / max(1.0, cash + pos_qty * last)
        frozen = 0.0
        time_norm = (self._step % 3600) / 3600.0
        vec.extend([pos_qty, cash, frozen, unrealized, utilization, time_norm])
        # 简化 K 线缓存（此处不生成，填充 0）
        for _ in range(self.k_bars):
            vec.extend([0.0, 0.0, 0.0, 0.0])
        return np.array(vec, dtype=np.float32)

    def render(self):
        pass

# ==== M1 新环境: 事件节点 + 权重动作 ====
@dataclasses.dataclass
class EnvConfig:
    symbols: List[str]
    max_position_leverage: float = 3.0
    weight_low: float = -2.0
    weight_high: float = 1.5
    lookback_nodes: int = 10
    feature_list: Tuple[str, ...] = ("ret", "vol", "event", "time_sin", "time_cos")
    commission_rate: float = 0.0005
    stamp_duty: float = 0.001  # 卖出单边
    slippage: float = 0.0003
    max_steps: int = 10_000
    reward_cost_alpha: float = 1.0
    leverage_penalty_beta: float = 0.0
    leverage_target: float = 2.0
    clip_reward: float = 0.05
    seed: int = 42
    short_penalty: float = 0.001  # Req7: 禁止卖空或卖空被拒惩罚

class EventTradingEnv(gym.Env):
    """多标的权重型交易环境 (M1 MVP)
    - 动作: 目标权重向量 w ∈ [low, high]^N
    - 事件节点: 外部预生成传入 或 使用简单阈值算法生成
    - 观测: [per-symbol 最近L节点特征拼接 + 账户特征]
    可选注入: AccountAdapter (真实账户) -> 使用真实资金/持仓 & 通过订单服务调仓
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self,
                 config: EnvConfig,
                 bars_provider: Callable[[List[str]], Dict[str, np.ndarray]],
                 event_nodes_provider: Optional[Callable[[Dict[str, np.ndarray]], List[int]]] = None,
                 seed: Optional[int] = None,
                 event_flags: Optional[np.ndarray] = None,
                 instrument_provider: Optional[Callable[[List[str]], Dict[str, dict]]] = None,
                 account_adapter: AccountAdapter | None = None):
        super().__init__()
        self.config = config
        if seed is not None:
            self.np_rng = np.random.default_rng(seed)
        else:
            self.np_rng = np.random.default_rng(config.seed)
        self.symbols = config.symbols
        self.n = len(self.symbols)
        self.account_adapter = account_adapter
        # bars: dict symbol -> ndarray shape (T, 6) [ts, open, high, low, close, vol]
        self._bars_provider = bars_provider
        self._event_nodes_provider = event_nodes_provider
        self.bars: Dict[str, np.ndarray] = {}
        self.event_indices: List[int] = []  # 全局节点索引列表 (升序)
        self.ptr = 0
        self.account_equity = 1_000_000.0
        self.cash = self.account_equity
        self.positions_value = np.zeros(self.n, dtype=float)
        self.positions_qty = np.zeros(self.n, dtype=float)  # 简化：按价值/价格得到
        self.position_weights = np.zeros(self.n, dtype=float)
        self.last_equity = self.account_equity
        self.last_prices = np.ones(self.n, dtype=float)
        self._build_spaces()
        self.history_weights = []
        self.history_equity = []
        self._gen_observation_cache = None
        # Instrument 信息
        self.instrument_info: Dict[str, dict] = {}
        self.event_flags_external = event_flags  # 若外部直接给出每节点事件标记 (长度>=T)
        # 追加：执行层参数缓存
        self.lot_sizes = None
        self.tick_sizes = None
        self.contract_multipliers = None
        self.allow_short = None
        self.margin_long = None
        self.margin_short = None
        self._instrument_provider = instrument_provider

    # ---- spaces ----
    def _build_spaces(self):
        # 每标的特征 = 基础 feature_list*lookback + 2(当前权重, zscore)
        base_per_symbol = len(self.config.feature_list) * self.config.lookback_nodes
        extra = 2
        feat_per_symbol = base_per_symbol + extra
        self._feat_per_symbol_total = feat_per_symbol
        account_feats = 6
        obs_dim = self.n * feat_per_symbol + account_feats
        self.action_space = spaces.Box(low=self.config.weight_low, high=self.config.weight_high, shape=(self.n,), dtype=np.float32)
        self.observation_space = spaces.Box(low=-10, high=10, shape=(obs_dim,), dtype=np.float32)

    # ---- reset/load ----
    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self.np_rng = np.random.default_rng(seed)
        self.bars = self._bars_provider(self.symbols)
        # 基础检查
        lengths = {sym: arr.shape[0] for sym, arr in self.bars.items()}
        T = min(lengths.values())
        # 简化: 截断为统一长度
        for s in self.symbols:
            self.bars[s] = self.bars[s][:T]
        # 事件节点
        if self._event_nodes_provider:
            self.event_indices = self._event_nodes_provider(self.bars)
        else:
            self.event_indices = self._simple_event_nodes(self.bars, threshold=0.005, max_events_per_window=5)
        self.event_indices = sorted(set(self.event_indices))
        if self.event_indices[0] != 0:
            self.event_indices.insert(0, 0)
        self.ptr = 0
        # 账户 (内部或通过 adapter)
        if self.account_adapter is None:
            self.cash = self.account_equity
            self.positions_value[:] = 0
            self.positions_qty[:] = 0
            self.position_weights[:] = 0
            self.last_equity = self.account_equity
        else:
            # 从真实账户映射初始 equity
            st = self.account_adapter.get_account_state(self.symbols)
            self.last_equity = st.equity
            self.cash = st.cash
            for i, sym in enumerate(self.symbols):
                self.positions_qty[i] = st.positions[sym]['qty']
            prices0 = self._current_prices()
            self.positions_value = self.positions_qty * prices0
            self.position_weights = self._derive_weights_from_state(st, prices0)
        self.last_prices = self._current_prices()
        self.history_equity.clear()
        self.history_weights.clear()
        # Instrument 信息
        if self._instrument_provider:
            try:
                self.instrument_info = self._instrument_provider(self.symbols) or {}
            except Exception:
                self.instrument_info = {}
        # 构建向量属性
        self.lot_sizes = np.array([float(self.instrument_info.get(s, {}).get('lot_size', 1)) for s in self.symbols])
        self.tick_sizes = np.array([float(self.instrument_info.get(s, {}).get('tick_size', 0.01)) for s in self.symbols])
        self.contract_multipliers = np.array([float(self.instrument_info.get(s, {}).get('contract_multiplier', 1.0)) for s in self.symbols])
        self.allow_short = np.array([bool(self.instrument_info.get(s, {}).get('is_marginable_short', True)) for s in self.symbols])
        self.margin_long = np.array([float(self.instrument_info.get(s, {}).get('margin_rate_long', 0.0)) for s in self.symbols])
        self.margin_short = np.array([float(self.instrument_info.get(s, {}).get('margin_rate_short', 0.0)) for s in self.symbols])
        # 事件标记
        if self.event_flags_external is not None:
            self._event_flags = self.event_flags_external[:len(self.event_indices)]
        else:
            # 默认全部 0，若 provider 返回结构可自行覆盖
            self._event_flags = np.zeros(len(self.event_indices), dtype=np.int8)
        obs = self._observe()
        return obs, {}

    # ---- step ----
    def step(self, action: np.ndarray):
        action = np.asarray(action, dtype=float)
        action = np.clip(action, self.config.weight_low, self.config.weight_high)
        rejects: List[str] = []
        if self.account_adapter is not None:
            # 使用真实账户调仓
            try:
                costs, traded_value, rejects = self.account_adapter.rebalance_to_weights(
                    action, self.symbols, self.config.slippage, self.config.max_position_leverage,
                    short_allowed=list(self.allow_short) if self.allow_short is not None else None
                )
                # 获取最新账户状态用于后续指标
                st = self.account_adapter.get_account_state(self.symbols)
                prices_now = self._current_prices()
                self.positions_qty = np.array([st.positions[s]['qty'] for s in self.symbols], dtype=float)
                self.positions_value = self.positions_qty * prices_now
                self.position_weights = self._derive_weights_from_state(st, prices_now)
                self.cash = st.cash
                self.last_equity = st.equity  # baseline for raw_r diff 使用 mark-to-market 再更新
            except Exception:
                costs = 0.0; traded_value = 0.0
        else:
            # 执行调仓 (内部模拟)
            costs, traded_value = self._apply_target_weights(action)
        # 前进指针
        self.ptr += 1
        done = self.ptr >= len(self.event_indices)-1 or (self.account_adapter is None and self.account_equity <= 0.2 * settings.DEFAULT_CASH)
        obs = self._observe()
        # 计算收益
        equity = self._mark_to_market()
        raw_r = (equity - self.last_equity) / max(1e-9, self.last_equity)
        cost_pen = costs / max(1e-9, self.last_equity)
        leverage = np.sum(np.abs(self.positions_value)) / max(1e-9, equity)
        lev_pen = max(0.0, leverage - self.config.leverage_target)
        reward = raw_r - self.config.reward_cost_alpha * cost_pen - self.config.leverage_penalty_beta * lev_pen
        # 短卖被拒惩罚
        if any(r.startswith('SHORT_DISABLED') for r in rejects):
            reward -= self.config.short_penalty
        if self.config.clip_reward > 0:
            reward = float(np.clip(reward, -self.config.clip_reward, self.config.clip_reward))
        self.last_equity = equity
        info = {
            'timestamp': int(self._current_ts()),
            'account_value': equity,
            'cash': self.cash,
            'gross_exposure': float(np.sum(np.abs(self.positions_value))),
            'net_exposure': float(np.sum(self.positions_value)),
            'turnover': float(traded_value / max(1e-9, equity)),
            'cost': float(costs),
            'event_flag': 1 if self._is_event_node() else 0,
            'num_events_cum': int(self.ptr),
            'margin_util': 0.0,
            'drawdown': float(self._drawdown(equity)),
            'pnl_step': float(equity - self.last_equity),
            'reward_components': {'raw': raw_r, 'cost': cost_pen, 'leverage_pen': lev_pen},
            'rejects': rejects
        }
        truncated = False
        return obs, float(reward), done, truncated, info

    # ---- internal helpers ----
    def _current_ts(self) -> int:
        idx = self.event_indices[self.ptr]
        # bars[s][:,0] assumed ts
        first_sym = self.symbols[0]
        return int(self.bars[first_sym][idx, 0])

    def _current_prices(self) -> np.ndarray:
        idx = self.event_indices[self.ptr]
        px = []
        for s in self.symbols:
            arr = self.bars[s]
            px.append(arr[idx, 4])  # close
        return np.asarray(px, dtype=float)

    def _next_prices(self) -> np.ndarray:
        idx = self.event_indices[min(self.ptr+1, len(self.event_indices)-1)]
        return np.asarray([self.bars[s][idx, 4] for s in self.symbols], dtype=float)

    def _is_event_node(self):
        if hasattr(self, '_event_flags') and self.ptr < len(self._event_flags):
            return int(self._event_flags[self.ptr])
        return 0

    def _derive_weights_from_state(self, st, prices_now: np.ndarray) -> np.ndarray:
        eq = max(1e-9, st.equity)
        w = []
        for i, sym in enumerate(self.symbols):
            qty = st.positions[sym]['qty']
            w.append(qty * prices_now[i] / eq)
        return np.asarray(w, dtype=float)

    # ---- 执行逻辑增强 (原内部模拟路径) ----
    def _apply_target_weights(self, target_w: np.ndarray) -> Tuple[float, float]:
        # Short 约束: 不允许做空的直接 clip >=0
        if self.allow_short is not None:
            target_w = np.where(self.allow_short, target_w, np.clip(target_w, 0, None))
        equity = self._mark_to_market()
        # 杠杆限制预检: 若目标 gross 超限则等比例缩放
        gross_target = np.sum(np.abs(target_w)) * equity
        max_gross = self.config.max_position_leverage * equity
        if gross_target > max_gross and gross_target > 0:
            scale = max_gross / gross_target
            target_w = target_w * scale
        # 价格
        cur_px_now = self._current_prices()
        cur_px_exec = self._next_prices()  # 用下一节点作为成交流
        cm = self.contract_multipliers if self.contract_multipliers is not None else np.ones_like(target_w)
        lot = self.lot_sizes if self.lot_sizes is not None else np.ones_like(target_w)
        # 当前持仓价值 & qty -> positions_qty 表示份数(股/手)
        # 目标价值
        target_value = target_w * equity
        # 目标数量粗算
        raw_qty_target = np.where(cur_px_exec*cm != 0, target_value / (cur_px_exec*cm), 0.0)
        # 四舍五入到最接近的 lot（多头与空头分开处理）
        def round_lot(q, lot_size):
            sign = np.sign(q)
            q_abs = np.abs(q)
            return sign * np.floor(q_abs / lot_size) * lot_size
        qty_target = np.array([round_lot(q, lot[i]) for i,(q) in enumerate(raw_qty_target)], dtype=float)
        delta_qty = qty_target - self.positions_qty
        # 执行（逐标/向量化）
        slip = self.config.slippage
        rng = self.np_rng
        noise = rng.normal(0, 0.2, size=delta_qty.shape)  # 受控噪声
        exec_price = cur_px_exec * (1 + slip * (1 + 0.05*noise) * np.sign(delta_qty))
        trade_value = np.sum(np.abs(delta_qty * exec_price * cm))
        # 成本
        commission = trade_value * self.config.commission_rate
        sell_mask = delta_qty < 0
        sell_value = np.sum(np.abs(delta_qty[sell_mask] * exec_price[sell_mask] * cm[sell_mask]))
        stamp = sell_value * self.config.stamp_duty
        slippage_cost = trade_value * slip
        total_cost = commission + stamp + slippage_cost
        # 现金变化
        cash_flow = -np.sum(delta_qty * exec_price * cm)  # 买入为负
        self.cash += cash_flow - total_cost
        self.positions_qty += delta_qty
        # 保证金 (简化: 多头/空头分别占用) - 仅记录, 不冻结现金
        long_exposure = np.sum(np.clip(self.positions_qty, 0, None) * cur_px_now * cm)
        short_exposure = np.sum(np.clip(-self.positions_qty, 0, None) * cur_px_now * cm)
        self.margin_used = long_exposure * np.mean(self.margin_long) + short_exposure * np.mean(self.margin_short)
        self.history_weights.append(target_w.copy())
        self.history_equity.append(equity)
        self.position_weights = target_w.copy()
        # 记录执行价格便于调试
        self._last_exec_price = exec_price
        return float(total_cost), float(trade_value)

    def _observe(self) -> np.ndarray:
        # 构建特征缓存
        feat_blocks = []
        L = self.config.lookback_nodes
        idx_list = [self.event_indices[max(0, self.ptr - i)] for i in reversed(range(L))]
        t_frac = (self.ptr / max(1, len(self.event_indices)-1))
        time_sin = math.sin(math.pi * 2 * t_frac)
        time_cos = math.cos(math.pi * 2 * t_frac)
        # 为横截面 zscore 先收集 returns
        closes_dict = {s: self.bars[s][:,4] for s in self.symbols}
        rets_latest = []
        for s in self.symbols:
            idx = idx_list[-1]
            if idx == 0:
                rets_latest.append(0.0)
            else:
                c = closes_dict[s]; rets_latest.append((c[idx]/c[idx-1]-1.0) if c[idx-1]>0 else 0.0)
        rets_arr = np.array(rets_latest)
        if rets_arr.std() > 1e-9:
            zscore = (rets_arr - rets_arr.mean()) / (rets_arr.std()+1e-9)
        else:
            zscore = np.zeros_like(rets_arr)
        for si, s in enumerate(self.symbols):
            c = closes_dict[s]
            sub = []
            for gidx in idx_list:
                if gidx == 0:
                    ret = 0.0
                else:
                    p0 = c[gidx-1]; p1 = c[gidx]
                    ret = (p1/p0 -1.0) if p0>0 else 0.0
                start = max(0, gidx-3)
                ref = c[start:gidx+1]
                vol = float(np.std(ref)/(np.mean(ref)+1e-9)) if ref.size>1 else 0.0
                event_flag = float(self._is_event_node())
                sub.extend([ret, vol, event_flag, time_sin, time_cos])
            # 追加当前持仓权重与 zscore
            sub.extend([self.position_weights[si] if self.position_weights is not None else 0.0, zscore[si]])
            feat_blocks.extend(sub)
        equity = self._mark_to_market()
        gross = np.sum(np.abs(self.positions_value))
        cash_ratio = self.cash / max(1e-9, equity)
        leverage = gross / max(1e-9, equity)
        margin_util = (getattr(self, 'margin_used', 0.0) / max(1e-9, equity)) if hasattr(self, 'margin_used') else 0.0
        step_norm = self.ptr / max(1, len(self.event_indices)-1)
        account_vec = [cash_ratio, gross/equity if equity>0 else 0, np.sum(self.positions_value)/max(1e-9,equity), leverage, margin_util, step_norm]
        return np.array(feat_blocks + account_vec, dtype=np.float32)

    def _drawdown(self, equity: float) -> float:
        if not self.history_equity:
            return 0.0
        peak = max(max(self.history_equity), equity)
        return (equity - peak) / peak if peak > 0 else 0.0

    # ---- 简化事件节点生成 (基于 close 回溯) ----
    def _simple_event_nodes(self, bars: Dict[str, np.ndarray], threshold: float = 0.005, window: int = 30, max_events_per_window: int = 5) -> List[int]:
        first_sym = self.symbols[0]
        closes = bars[first_sym][:, 4]
        T = closes.shape[0]
        events = [0]
        last_base_px = closes[0]
        last_win_start = 0
        count_in_window = 0
        for i in range(1, T):
            if (i - last_win_start) >= window:
                last_win_start = i
                count_in_window = 0
            chg = abs(closes[i]/last_base_px - 1.0) if last_base_px > 0 else 0.0
            if chg >= threshold and count_in_window < max_events_per_window:
                events.append(i)
                last_base_px = closes[i]
                count_in_window += 1
        if events[-1] != T-1:
            events.append(T-1)
        return events

    def render(self):
        pass

# 对外暴露名称 (保持旧引用不崩)
TradingEnv = EventTradingEnv
