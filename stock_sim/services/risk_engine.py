# python
# file: services/risk_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Any, Dict, Tuple  # 移除 Optional, 统一使用 | None 形式
from stock_sim.core.const import OrderSide, OrderType  # type: ignore
# 保留规则注册表导入 (双路径兼容)
try:  # type: ignore
    from stock_sim.services.risk_rule_registry import risk_rule_registry  # type: ignore
except Exception:  # noqa
    from services.risk_rule_registry import risk_rule_registry  # type: ignore

@dataclass
class RiskResult:
    """风险校验结果
    ok: True 表示通过; False 表示拒绝。
    reason: 人类可读描述
    rule: 触发的规则名称
    code: 供指标/错误码使用 (默认回退为规则名大写)
    extra: 规则可选扩展字段
    """
    ok: bool
    reason: str | None = None
    rule: str | None = None
    extra: dict | None = None
    code: str | None = None  # 与 OrderService 期望的 rr.code 保持兼容

class _DummyStorage:
    def reset_day(self):
        return True

class RiskEngine:
    """最小风险引擎实现: 迭代已注册规则, 首个拒绝返回 RiskResult(False,...)
    若所有规则通过或未产生拒绝则 ok=True。
    兼容 OrderService 需要的 update_tplus / reset_day_tplus / storage.reset_day 接口。"""
    def __init__(self):
        self._rules_loaded = False
        self.storage = _DummyStorage()
        # 日内 T+1 统计占位: {(account_id,symbol,side): qty}
        self._tplus: Dict[Tuple[str,str,OrderSide], int] = {}

    def _ensure_rules(self):
        if self._rules_loaded:
            return
        # risk_rule_registry 在导入时加载默认规则
        self._rules_loaded = True

    # ---- Public API ----
    def validate(self, *, account: Any = None, positions: List[Any] | None = None,
                 symbol: str = '', side: OrderSide = OrderSide.BUY,
                 price: float = 0.0, qty: int = 0,
                 order_type: OrderType = OrderType.LIMIT,
                 context: dict | None = None) -> RiskResult:
        self._ensure_rules()
        positions = positions or []
        ctx = context or {}
        for rule in risk_rule_registry.list_rules():  # type: ignore
            try:
                r = rule.evaluate(account=account, positions=positions, symbol=symbol,
                                   side=side, price=price, qty=qty, order_type=order_type,
                                   context=ctx)
            except Exception:
                # 单条规则异常 -> 忽略该规则继续，不使整体失败
                continue
            if r is None:
                continue
            if not getattr(r, 'ok', True):  # 拒绝
                reason = getattr(r, 'reason', 'rejected')
                name = getattr(rule, 'name', 'unknown')
                code = getattr(r, 'code', name.upper())
                return RiskResult(ok=False, reason=reason, rule=name, code=code)
        return RiskResult(ok=True, code="OK")

    # ---- Day / T+1 Tracking (占位实现) ----
    def update_tplus(self, account_id: str, symbol: str, side: OrderSide, qty: int):
        if qty <= 0:
            return
        key = (account_id, symbol, side)
        self._tplus[key] = self._tplus.get(key, 0) + qty

    def reset_day_tplus(self, positions: List[Any]):  # positions 仅占位
        self._tplus.clear()

__all__ = ["RiskEngine", "RiskResult"]
