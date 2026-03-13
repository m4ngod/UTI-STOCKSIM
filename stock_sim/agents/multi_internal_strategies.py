from __future__ import annotations
"""MultiStrategyRetail 内部 A/B/C/D 策略拆分实现。
每个策略返回 (p_buy, p_sell, scale_bias)
  p_buy / p_sell   : 0~1 概率 (未归一化, MultiStrategyRetail 会裁剪)
  scale_bias       : 额外的数量放大系数 (>=0)

策略含义:
 A Mean Reversion: 均值回归, 偏高卖偏低买
 B Momentum: 动量趋势跟随
 C Dip Buyer: 抄底 + 止盈/大亏止损
 D Risk Averse: 快速止损 + 让利润奔跑
"""
from dataclasses import dataclass
from typing import Protocol
import random

@dataclass
class StrategyContext:
    deviation: float          # (last - ma_long)/ma_long
    momentum: float           # 简单动量
    unreal_pct: float         # 浮盈亏百分比 (持仓>0 时)
    position_qty: int
    lot_size: int

class IInternalStrategy(Protocol):
    name: str
    def probs(self, ctx: StrategyContext) -> tuple[float, float, float]: ...

class StrategyA(IInternalStrategy):
    name = 'A'
    def probs(self, ctx: StrategyContext):
        p_buy = p_sell = 0.25
        if ctx.deviation > 0.02:
            p_sell = 0.6 + min(0.3, ctx.deviation)
            p_buy = 0.1
        elif ctx.deviation < -0.02:
            p_buy = 0.6 + min(0.3, -ctx.deviation)
            p_sell = 0.1
        return p_buy, p_sell, 1.0 + min(1.0, abs(ctx.deviation) * 5)

class StrategyB(IInternalStrategy):
    name = 'B'
    def probs(self, ctx: StrategyContext):
        p_buy = p_sell = 0.3
        if ctx.momentum > 0:
            p_buy = 0.6 + min(0.3, ctx.momentum)
            p_sell = 0.1
        elif ctx.momentum < 0:
            p_sell = 0.6 + min(0.3, -ctx.momentum)
            p_buy = 0.1
        return p_buy, p_sell, 1.0 + min(1.0, abs(ctx.momentum) * 2)

class StrategyC(IInternalStrategy):
    name = 'C'
    def probs(self, ctx: StrategyContext):
        p_buy = 0.2 if ctx.position_qty == 0 and ctx.deviation > 0 else 0.0
        p_sell = 0.0
        if ctx.deviation < -0.03:
            p_buy = max(p_buy, 0.55)
        if ctx.unreal_pct <= -0.5:
            p_sell = max(p_sell, 0.8)
        elif ctx.unreal_pct >= 0.08:
            p_sell = max(p_sell, 0.7)
        scale = 1.0 + min(1.0, abs(ctx.deviation) * 4)
        return p_buy, p_sell, scale

class StrategyD(IInternalStrategy):
    name = 'D'
    def probs(self, ctx: StrategyContext):
        p_buy = p_sell = 0.0
        if ctx.unreal_pct <= -0.05:
            p_sell = 0.7
        if ctx.unreal_pct <= -0.12:
            p_sell = 0.9
        if ctx.unreal_pct >= 0.1:
            p_buy = 0.4
        if ctx.momentum > 0.02:
            p_buy += 0.2
        if ctx.momentum < -0.02:
            p_sell += 0.2
        scale = 1.0 + min(1.0, abs(ctx.unreal_pct) * 5 + abs(ctx.momentum) * 2)
        return p_buy, p_sell, scale

INTERNAL_STRATEGIES = {s.name: s for s in (StrategyA(), StrategyB(), StrategyC(), StrategyD())}

def get_internal_strategy(name: str) -> IInternalStrategy:
    return INTERNAL_STRATEGIES.get(name, INTERNAL_STRATEGIES['A'])

