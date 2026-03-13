from __future__ import annotations
from typing import Protocol, runtime_checkable, Optional, Any
try:
    from stock_sim.core.const import OrderSide, OrderType  # type: ignore
except Exception:  # 回退本地
    from core.const import OrderSide, OrderType  # type: ignore

# 延迟类型注解导入，避免循环引用（在运行时 import risk_engine.RiskResult）
@runtime_checkable
class IRiskRule(Protocol):
    """风险规则协议。实现者只需提供 name 与 evaluate 方法。
    evaluate 返回:
      - None: 视为通过
      - RiskResult.ok=True: 通过（可附加信息）
      - RiskResult.ok=False: 拒绝，RiskEngine 立即返回该结果
    """
    name: str

    def evaluate(
        self,
        *,
        account: Any,
        positions: list[Any],
        symbol: str,
        side: OrderSide,
        price: float,
        qty: int,
        order_type: OrderType,
        context: Optional[dict] = None,
    ) -> Optional["RiskResult"]:  # 引用在运行时由 risk_engine 定义的 RiskResult
        ...

__all__ = ["IRiskRule"]
