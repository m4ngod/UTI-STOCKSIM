"""Risk Rule Registry
提供风险规则注册/列出功能，供 RiskEngine 使用。

当前最小真实规则集：
- NoopAllowAllRule: 占位/兜底
- TPlusOneSellRestrictionRule: A 股 T+1 卖出限制
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

try:
    from stock_sim.infra.interfaces import IRiskRule  # type: ignore
    from stock_sim.core.const import OrderSide  # type: ignore
except Exception:  # noqa
    from infra.interfaces import IRiskRule  # type: ignore
    from core.const import OrderSide  # type: ignore


@dataclass
class RiskReject:
    ok: bool = False
    reason: str = "rejected"
    code: str = "REJECTED"


class RiskRuleRegistry:
    def __init__(self):
        self._rules: List[IRiskRule] = []  # type: ignore

    def register(self, rule: IRiskRule):  # type: ignore
        names = {getattr(r, 'name', None) for r in self._rules}
        nm = getattr(rule, 'name', None)
        if nm and nm in names:
            return
        self._rules.append(rule)

    def list_rules(self) -> List[IRiskRule]:  # type: ignore
        return list(self._rules)


risk_rule_registry = RiskRuleRegistry()


class TPlusOneSellRestrictionRule:
    """最小真实 T+1 规则。

    语义：
    - 仅在 SELL 时生效
    - 仅当 settlement_cycle >= 1 时生效（A 股 T+1）
    - 当日可卖数量 = max(0, 当前多头持仓数量 - 当日买入累计量)
    - 若卖出数量超过可卖数量，则拒绝

    说明：
    - 这里不依赖 frozen_qty 来表达 T+1，而是用日内买入统计 + 当前仓位做规则判定
    - 若账户允许卖空（其它规则放行），未来可在更高层组合；当前先对 T+1 多头卖出限制给出保守实现
    """
    name = "TPlusOneSellRestriction"

    def evaluate(self, **kwargs):
        side = kwargs.get('side')
        if side is not OrderSide.SELL:
            return None

        qty = int(kwargs.get('qty') or 0)
        symbol = kwargs.get('symbol') or ''
        positions = kwargs.get('positions') or []
        context = kwargs.get('context') or {}
        settlement_cycle = int(context.get('settlement_cycle') or 0)
        risk_engine = context.get('risk_engine')

        if qty <= 0 or settlement_cycle < 1 or risk_engine is None:
            return None

        account = kwargs.get('account')
        account_id = getattr(account, 'id', None)
        if not account_id:
            return None

        pos = next((p for p in positions if getattr(p, 'symbol', None) == symbol), None)
        long_qty = max(0, int(getattr(pos, 'quantity', 0) or 0)) if pos is not None else 0
        frozen_qty = max(0, int(getattr(pos, 'frozen_qty', 0) or 0)) if pos is not None else 0
        memory_same_day_buy_qty = int(risk_engine.get_tplus(account_id, symbol, OrderSide.BUY) or 0)
        persisted_same_day_buy_qty = (
            int(context.get("same_day_buy_qty") or 0)
            if "same_day_buy_qty" in context
            else 0
        )
        same_day_buy_qty = max(memory_same_day_buy_qty, persisted_same_day_buy_qty)

        sellable_qty = max(0, long_qty - same_day_buy_qty - frozen_qty)
        if qty > sellable_qty:
            return RiskReject(
                ok=False,
                code='TPLUS1_SELL_BLOCKED',
                reason=f'T+1 restriction: sellable={sellable_qty}, requested={qty}'
            )
        return None


class NoopAllowAllRule:
    name = "NoopAllowAll"

    def evaluate(self, **kwargs):
        return None


risk_rule_registry.register(TPlusOneSellRestrictionRule())
risk_rule_registry.register(NoopAllowAllRule())

__all__ = [
    "risk_rule_registry",
    "RiskRuleRegistry",
    "RiskReject",
    "TPlusOneSellRestrictionRule",
    "NoopAllowAllRule",
]
