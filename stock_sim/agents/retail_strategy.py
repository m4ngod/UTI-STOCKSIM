from __future__ import annotations
"""零售(散户)策略抽象与注册中心。

提供最小可插拔接口, 便于在不修改 RetailClient 主类的情况下扩展与热切换:
  IRetailStrategy.decide(price_window: list[float], last_price: float | None, lot_size: int) -> (OrderSide, int) | None

默认内置: MomentumChaseStrategy (等价原 retail_client.decide_action 追涨杀跌示例)。
"""
from typing import Protocol, Callable, Dict, Tuple, Optional, List
from stock_sim.core.const import OrderSide
import random, statistics

class IRetailStrategy(Protocol):
    name: str
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Optional[Tuple[OrderSide, int]]: ...

# ---- 具体策略 ----
class MomentumChaseStrategy:
    name = "momentum_chase"
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int):
        if len(price_window) < 3:
            return None
        p1, p2, p3 = price_window[-3:]
        if p1 < p2 < p3:  # 上升 -> 买
            return OrderSide.BUY, lot_size
        if p1 > p2 > p3:  # 下跌 -> 卖
            return OrderSide.SELL, lot_size
        # 低概率噪声
        if random.random() < 0.03:
            return (OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL, lot_size)
        return None

class MeanRevertStrategy:
    name = "mean_revert"
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int):
        if len(price_window) < 10 or not last_price:
            return None
        ma = sum(price_window[-10:]) / 10
        dev = (last_price - ma) / ma if ma > 0 else 0
        # 偏高卖, 偏低买, 阈值 0.3% 以上才动作
        if dev > 0.003:
            return OrderSide.SELL, lot_size
        if dev < -0.003:
            return OrderSide.BUY, lot_size
        return None

class BreakoutStrategy:
    name = "breakout"
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int):
        if len(price_window) < 25 or not last_price:
            return None
        recent = price_window[-25:]
        hi = max(recent); lo = min(recent)
        if last_price >= hi and random.random() < 0.7:
            return OrderSide.BUY, lot_size
        if last_price <= lo and random.random() < 0.7:
            return OrderSide.SELL, lot_size
        return None

class VolatilityScalingStrategy:
    name = "vol_scaling"
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int):
        if len(price_window) < 15 or not last_price:
            return None
        rets = [ (price_window[i]-price_window[i-1])/price_window[i-1] for i in range(1,len(price_window)) if price_window[i-1]>0]
        if len(rets) < 5:
            return None
        vol = statistics.pstdev(rets[-15:]) if len(rets) >= 15 else statistics.pstdev(rets)
        # 低波动 -> 做突破 (买); 高波动 -> 反向 (卖)
        if vol < 0.0008 and random.random() < 0.5:
            return OrderSide.BUY, lot_size
        if vol > 0.002 and random.random() < 0.5:
            return OrderSide.SELL, lot_size
        return None

class RandomNoiseStrategy:
    name = "noise"
    def decide(self, price_window: List[float], last_price: float | None, lot_size: int):
        if not last_price or len(price_window) < 3:
            return None
        r = random.random()
        if r < 0.02:
            return OrderSide.BUY, lot_size
        if r < 0.04:
            return OrderSide.SELL, lot_size
        return None

# ---- 注册中心 ----
class StrategyRegistry:
    def __init__(self):
        self._factories: Dict[str, Callable[[], IRetailStrategy]] = {}
    def register(self, name: str, factory: Callable[[], IRetailStrategy]):
        self._factories[name] = factory
    def create(self, name: str) -> IRetailStrategy:
        if name not in self._factories:
            raise KeyError(f"strategy '{name}' 未注册")
        return self._factories[name]()
    def list(self):
        return list(self._factories.keys())

strategy_registry = StrategyRegistry()
strategy_registry.register(MomentumChaseStrategy.name, MomentumChaseStrategy)
strategy_registry.register(MeanRevertStrategy.name, MeanRevertStrategy)
strategy_registry.register(BreakoutStrategy.name, BreakoutStrategy)
strategy_registry.register(VolatilityScalingStrategy.name, VolatilityScalingStrategy)
strategy_registry.register(RandomNoiseStrategy.name, RandomNoiseStrategy)

# 便于 UI 获取列表
try:
    def list_registered_retail_strategies():
        return strategy_registry.list()
except Exception:
    pass
