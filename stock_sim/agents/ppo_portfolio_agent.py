from __future__ import annotations
"""PPOPortfolioAgent
桥接 PPO+LSTM (Recurrent Policy) 输出的多标目标权重 -> 实际下单 (PortfolioExecutor)。
MVP 行为:
  - tick() 周期:
      1. 获取 universe (symbols)
      2. 若模型/环境未绑定: 使用随机权重占位 (可 set_model,set_env 后启用真实推理)
      3. 调用 _infer_weights(symbols) -> dict[symbol, weight]
      4. 通过 PortfolioExecutor.rebalance() 生成订单
  - 支持热插: set_model(policy, device), set_env(env)  (env 可用于获取最新观测)
  - 状态查询: status_dict()

注意:
  - 真实环境下需要将 obs 构建逻辑与训练一致；此处仅提供占位.
  - 权重范围可通过配置或从 policy.act_low / act_high 读取 (若存在)。
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import time, random, numpy as np

try:
    import torch
except Exception:
    torch = None  # type: ignore

from stock_sim.core.const import OrderSide, EventType  # 添加 EventType
from stock_sim.infra.event_bus import event_bus  # 新增事件总线
from stock_sim.services.portfolio_executor import PortfolioExecutor
from stock_sim.services.universe_provider import UniverseProvider

@dataclass
class PPOPortfolioStats:
    ticks: int = 0
    last_rebalance_orders: int = 0
    last_rebalance_notional: float = 0.0
    last_ts: float = 0.0

class PPOPortfolioAgent:
    def __init__(self,
                 name: str,
                 account_id: str | None,
                 universe_provider: UniverseProvider,
                 order_service_provider: Callable[[], object],
                 account_cache_provider: Callable[[], dict],
                 interval: float = 2.0,
                 min_notional: float = 0.0):
        self.name = name
        self.account_id = account_id
        self.universe_provider = universe_provider
        self._osp = order_service_provider
        self._acp = account_cache_provider
        self.interval = max(0.5, float(interval))
        self.min_notional = float(min_notional)
        self.enabled = False
        self._last_run = 0.0
        self.stats = PPOPortfolioStats()
        self._executor: PortfolioExecutor | None = None
        # 模型 / 环境相关
        self._policy = None  # 期望接口: forward(obs, (h,c)) -> (det_action, value, raw_mean,(h,c)) / 或 policy.act(obs) -> action
        self._device = 'cpu'
        self._hidden = None  # (h,c)
        self._env = None  # 可选: 提供特征构建 / 正规化器等
        self._weight_low = -2.0
        self._weight_high = 1.5
        self._max_symbols_infer = 64  # 防止超大维度阻塞 UI

    # ----- 注入 -----
    def set_model(self, policy, device: str = 'cpu'):
        self._policy = policy
        self._device = device
        if torch and hasattr(policy, 'to'):
            try: self._policy.to(device)
            except Exception: pass
        # 初始化隐藏状态 (若支持)
        if hasattr(policy, 'initial_state'):
            try:
                h, c = policy.initial_state(batch_size=1)
                self._hidden = (h.to(device), c.to(device)) if torch else (h, c)
            except Exception:
                self._hidden = None
        # 读取动作范围
        for attr in ('act_low', 'act_high'):
            if hasattr(policy, attr):
                try:
                    v = getattr(policy, attr)
                    if attr == 'act_low': self._weight_low = float(np.min(v.cpu().numpy() if torch and isinstance(v, torch.Tensor) else v))
                    else: self._weight_high = float(np.max(v.cpu().numpy() if torch and isinstance(v, torch.Tensor) else v))
                except Exception:
                    pass
        return None  # 防止静态分析缺失返回; 不改变原逻辑流程

    def set_env(self, env):
        self._env = env
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    def set_account(self, account_id: str):
        self.account_id = account_id
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    def set_interval(self, sec: float):
        self.interval = max(0.5, float(sec))
        try:
            event_bus.publish(EventType.AGENT_META_UPDATE, {"agent": self.name})
        except Exception:
            pass

    # ----- 生命周期 -----
    def start(self):
        if not self.account_id:
            return False
        self.enabled = True
        return True

    def stop(self):
        self.enabled = False

    # ----- 内部: 构建执行器 -----
    def _ensure_executor(self):
        if self._executor is None:
            svc = self._osp()
            if not svc:
                return False
            self._executor = PortfolioExecutor(
                order_service=svc,
                account_fetcher=lambda aid=self.account_id: self._acp() or {},
                instrument_info_provider=lambda s: {}
            )
        return True

    # ----- 推理权重 -----
    def _infer_weights(self, symbols: List[str]) -> Dict[str, float]:
        if not symbols:
            return {}
        n = min(len(symbols), self._max_symbols_infer)
        usable = symbols[:n]
        # 真实模式
        if self._policy is not None and torch is not None:
            try:
                obs_vec = self._build_obs(usable)  # shape (F,)
                obs_tensor = torch.tensor(obs_vec, dtype=torch.float32, device=self._device).unsqueeze(0).unsqueeze(1)  # (B=1,T=1,F)
                if self._hidden is None and hasattr(self._policy, 'initial_state'):
                    h,c = self._policy.initial_state(batch_size=1)
                    self._hidden=(h.to(self._device), c.to(self._device))
                det, val, raw_mean, self._hidden = self._policy(obs_tensor, self._hidden)
                # raw_mean shape (1,1,A) -> 取 tanh squash 若模型训练一致
                if hasattr(self._policy, 'log_std'):
                    act_mid = (self._policy.act_high + self._policy.act_low)/2.0 if hasattr(self._policy,'act_high') else 0.0
                    act_amp = (getattr(self._policy,'act_high',1.0) - getattr(self._policy,'act_low',-1.0))/2.0
                    act = torch.tanh(raw_mean) * act_amp + act_mid
                else:
                    act = raw_mean
                w = act.squeeze().detach().cpu().numpy()
                # Clip 并生成映射 (若动作维度 != usable 长度, 截断/填充)
                if w.shape[0] < len(usable):
                    w = np.pad(w, (0, len(usable)-w.shape[0]), constant_values=0.0)
                elif w.shape[0] > len(usable):
                    w = w[:len(usable)]
                w = np.clip(w, self._weight_low, self._weight_high)
                return {sym: float(w[i]) for i, sym in enumerate(usable)}
            except Exception:
                pass
        # 随机占位 (无模型)
        return {sym: random.uniform(self._weight_low, self._weight_high) for sym in usable}

    def _build_obs(self, symbols: List[str]):
        # 占位: 返回零向量 (可在 set_env 后复用 env 的 _observe)
        if self._env is not None and hasattr(self._env, '_observe'):
            try:
                return self._env._observe()
            except Exception:
                pass
        return np.zeros(32, dtype=np.float32)

    # ----- Tick -----
    def tick(self):
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_run < self.interval:
            return
        self._last_run = now
        if not self.account_id:
            return
        if not self._ensure_executor():
            return
        symbols = self.universe_provider.symbols()
        if not symbols:
            return
        weights = self._infer_weights(symbols)
        if not weights:
            return
        res = self._executor.rebalance(self.account_id, weights, min_notional=self.min_notional)
        self.stats.ticks += 1
        self.stats.last_rebalance_orders = res.orders
        self.stats.last_rebalance_notional = res.gross_notional
        self.stats.last_ts = now

    # ----- 信息 -----
    def status_dict(self) -> dict:
        return {
            'name': self.name,
            'account': self.account_id or '-',
            'enabled': self.enabled,
            'interval': self.interval,
            'orders': self.stats.last_rebalance_orders,
            'last_notional': self.stats.last_rebalance_notional,
            'ticks': self.stats.ticks,
        }
