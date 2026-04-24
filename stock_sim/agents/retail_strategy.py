from __future__ import annotations

"""Retail strategy registry and population helpers."""

from dataclasses import dataclass
import random
import statistics
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from stock_sim.core.const import OrderSide


Decision = Optional[Tuple[OrderSide, int]]


class IRetailStrategy(Protocol):
    name: str

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        ...


def _safe_dev(last_price: float | None, ref: float) -> float:
    if not last_price or ref <= 0:
        return 0.0
    return (last_price - ref) / ref


class MomentumChaseStrategy:
    name = "momentum_chase"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 3:
            return None
        p1, p2, p3 = price_window[-3:]
        if p1 < p2 < p3:
            return OrderSide.BUY, lot_size
        if p1 > p2 > p3:
            return OrderSide.SELL, lot_size
        if random.random() < 0.03:
            side = OrderSide.BUY if random.random() < 0.5 else OrderSide.SELL
            return side, lot_size
        return None


class MeanRevertStrategy:
    name = "mean_revert"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 10 or not last_price:
            return None
        ma = sum(price_window[-10:]) / 10
        dev = _safe_dev(last_price, ma)
        if dev > 0.003:
            return OrderSide.SELL, lot_size
        if dev < -0.003:
            return OrderSide.BUY, lot_size
        return None


class BreakoutStrategy:
    name = "breakout"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 25 or not last_price:
            return None
        recent = price_window[-25:]
        hi = max(recent)
        lo = min(recent)
        if last_price >= hi and random.random() < 0.7:
            return OrderSide.BUY, lot_size
        if last_price <= lo and random.random() < 0.7:
            return OrderSide.SELL, lot_size
        return None


class VolatilityScalingStrategy:
    name = "vol_scaling"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 15 or not last_price:
            return None
        returns = [
            (price_window[i] - price_window[i - 1]) / price_window[i - 1]
            for i in range(1, len(price_window))
            if price_window[i - 1] > 0
        ]
        if len(returns) < 5:
            return None
        vol = statistics.pstdev(returns[-15:]) if len(returns) >= 15 else statistics.pstdev(returns)
        if vol < 0.0008 and random.random() < 0.5:
            return OrderSide.BUY, lot_size
        if vol > 0.002 and random.random() < 0.5:
            return OrderSide.SELL, lot_size
        return None


class RandomNoiseStrategy:
    name = "noise"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if not last_price or len(price_window) < 3:
            return None
        r = random.random()
        if r < 0.02:
            return OrderSide.BUY, lot_size
        if r < 0.04:
            return OrderSide.SELL, lot_size
        return None


class BuyTheDipStrategy:
    name = "buy_the_dip"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 6 or not last_price:
            return None
        short_ma = sum(price_window[-3:]) / 3
        long_ma = sum(price_window[-6:]) / 6
        dev = _safe_dev(last_price, long_ma)
        if dev < -0.01 and last_price <= short_ma and random.random() < 0.75:
            return OrderSide.BUY, lot_size
        if dev > 0.012 and random.random() < 0.45:
            return OrderSide.SELL, lot_size
        return None


class ProfitTakingStrategy:
    name = "profit_taking"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 8 or not last_price:
            return None
        anchor = sum(price_window[-8:]) / 8
        dev = _safe_dev(last_price, anchor)
        if dev > 0.009 and random.random() < 0.65:
            return OrderSide.SELL, lot_size
        if dev < -0.006 and random.random() < 0.25:
            return OrderSide.BUY, lot_size
        return None


class LiquidityNoiseStrategy:
    name = "liquidity_noise"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if not last_price:
            return None
        window_len = len(price_window)
        if window_len < 4:
            if random.random() < 0.18:
                side = OrderSide.BUY if random.random() < 0.55 else OrderSide.SELL
                return side, lot_size
            return None
        recent = price_window[-4:]
        drift = recent[-1] - recent[0]
        r = random.random()
        if abs(drift) < 0.003 * max(last_price, 1.0):
            if r < 0.12:
                return OrderSide.BUY, lot_size
            if r < 0.24:
                return OrderSide.SELL, lot_size
            return None
        if drift > 0 and r < 0.08:
            return OrderSide.SELL, lot_size
        if drift < 0 and r < 0.08:
            return OrderSide.BUY, lot_size
        return None


class SlowFundamentalAllocatorStrategy:
    name = "slow_fundamental_allocator"

    def decide(self, price_window: List[float], last_price: float | None, lot_size: int) -> Decision:
        if len(price_window) < 12 or not last_price:
            return None
        slow_anchor = sum(price_window[-12:]) / 12
        deviation = _safe_dev(last_price, slow_anchor)
        if deviation < -0.02 and random.random() < 0.7:
            return OrderSide.BUY, lot_size
        if deviation > 0.025 and random.random() < 0.45:
            return OrderSide.SELL, lot_size
        return None


class StrategyRegistry:
    def __init__(self):
        self._factories: Dict[str, Callable[[], IRetailStrategy]] = {}

    def register(self, name: str, factory: Callable[[], IRetailStrategy]):
        self._factories[name] = factory

    def create(self, name: str) -> IRetailStrategy:
        if name not in self._factories:
            raise KeyError(f"strategy '{name}' not registered")
        return self._factories[name]()

    def list(self) -> List[str]:
        return list(self._factories.keys())


strategy_registry = StrategyRegistry()
for _strategy in (
    MomentumChaseStrategy,
    MeanRevertStrategy,
    BreakoutStrategy,
    VolatilityScalingStrategy,
    RandomNoiseStrategy,
    BuyTheDipStrategy,
    ProfitTakingStrategy,
    LiquidityNoiseStrategy,
    SlowFundamentalAllocatorStrategy,
):
    strategy_registry.register(_strategy.name, _strategy)


@dataclass(frozen=True)
class WeightedStrategy:
    name: str
    weight: int


DEFAULT_RETAIL_NOISE_MIX = (
    WeightedStrategy("mean_revert", 3),
    WeightedStrategy("momentum_chase", 2),
    WeightedStrategy("buy_the_dip", 2),
    WeightedStrategy("profit_taking", 1),
    WeightedStrategy("liquidity_noise", 2),
    WeightedStrategy("noise", 1),
    WeightedStrategy("slow_fundamental_allocator", 1),
)


POST_IPO_COLD_START_MIX = (
    WeightedStrategy("liquidity_noise", 3),
    WeightedStrategy("momentum_chase", 1),
    WeightedStrategy("buy_the_dip", 1),
    WeightedStrategy("mean_revert", 2),
    WeightedStrategy("profit_taking", 2),
    WeightedStrategy("noise", 2),
    WeightedStrategy("slow_fundamental_allocator", 1),
)

POST_IPO_BOOTSTRAP_TEMPLATE = (
    "liquidity_noise",
    "buy_the_dip",
    "profit_taking",
    "mean_revert",
    "slow_fundamental_allocator",
    "momentum_chase",
    "noise",
)


def list_registered_retail_strategies() -> List[str]:
    return strategy_registry.list()


def allocate_retail_strategies(
    count: int,
    preferred: Optional[List[str]] = None,
    *,
    seed: int | None = None,
    mode: str = "normal",
) -> List[str]:
    if count <= 0:
        return []

    clean_preferred = [item.strip() for item in (preferred or []) if item and item.strip()]
    if clean_preferred:
        return [clean_preferred[i % len(clean_preferred)] for i in range(count)]

    if mode == "post_ipo_cold_start":
        bootstrap = list(POST_IPO_BOOTSTRAP_TEMPLATE[: min(count, len(POST_IPO_BOOTSTRAP_TEMPLATE))])
        if len(bootstrap) >= count:
            return bootstrap[:count]
    else:
        bootstrap = []

    mix = POST_IPO_COLD_START_MIX if mode == "post_ipo_cold_start" else DEFAULT_RETAIL_NOISE_MIX
    bag: List[str] = []
    for item in mix:
        bag.extend([item.name] * max(1, int(item.weight)))
    rng = random.Random(seed if seed is not None else count)
    rng.shuffle(bag)
    out = list(bootstrap)
    while len(out) < count:
        idx = len(out) - len(bootstrap)
        out.append(bag[idx % len(bag)])
    return out


def cold_start_profile() -> Dict[str, object]:
    return {
        "mode": "post_ipo_cold_start",
        "strategy_mix": [item.name for item in POST_IPO_COLD_START_MIX],
        "bootstrap_template": list(POST_IPO_BOOTSTRAP_TEMPLATE),
        "ideas": [
            "favor two-sided liquidity_noise immediately after IPO open",
            "guarantee at least one early sell-leaning participant in small retail batches",
            "let slow_fundamental_allocator provide a slower valuation anchor than purely technical retail",
            "keep momentum_chase and buy_the_dip in the first wave to create small but real directional follow-through",
            "seed short-window agents first, and let longer-window mean_revert agents join after a few prints exist",
        ],
    }


__all__ = [
    "IRetailStrategy",
    "MomentumChaseStrategy",
    "MeanRevertStrategy",
    "BreakoutStrategy",
    "VolatilityScalingStrategy",
    "RandomNoiseStrategy",
    "BuyTheDipStrategy",
    "ProfitTakingStrategy",
    "LiquidityNoiseStrategy",
    "SlowFundamentalAllocatorStrategy",
    "WeightedStrategy",
    "DEFAULT_RETAIL_NOISE_MIX",
    "POST_IPO_COLD_START_MIX",
    "POST_IPO_BOOTSTRAP_TEMPLATE",
    "strategy_registry",
    "list_registered_retail_strategies",
    "allocate_retail_strategies",
    "cold_start_profile",
]
