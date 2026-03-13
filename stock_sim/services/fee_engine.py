# python
from __future__ import annotations
from dataclasses import dataclass
from stock_sim.settings import settings
from stock_sim.core.const import OrderSide

@dataclass
class OrderFeeEstimate:
    basis_notional: float
    est_fee: float          # commission + transfer (不含税)
    est_tax: float
    est_transfer: float
    total: float            # est_fee + est_tax

@dataclass
class FeeResult:
    fee: float              # commission + transfer (不含税)
    tax: float
    commission: float
    transfer: float
    total: float            # fee + tax

class FeeEngine:
    """
    费用模型:
      - 佣金: notional * (TAKER/MAKER) BPS
      - 卖方印花税: side=SELL * STAMP_DUTY_BPS
      - 过户费: notional * TRANSFER_FEE_BPS
    兼容调用:
      - estimate_order(side, price, qty)
      - calc(side, price, qty, is_taker)
      - compute_order / compute_trade (旧接口)
    """
    def _rate(self, side: OrderSide, is_taker: bool) -> float:
        base = settings.TAKER_FEE_BPS if is_taker else settings.MAKER_FEE_BPS
        return base / 10_000

    # ---- 新接口：下单前估算（默认假设吃单，可配置） ----
    def estimate_order(self, side: OrderSide, price: float, qty: int, *, is_taker_assume: bool = True) -> OrderFeeEstimate:
        notional = price * qty
        commission = notional * self._rate(side, is_taker_assume)
        transfer_fee = notional * settings.TRANSFER_FEE_BPS / 10_000
        tax = notional * settings.STAMP_DUTY_BPS / 10_000 if side is OrderSide.SELL else 0.0
        est_fee = commission + transfer_fee
        return OrderFeeEstimate(
            basis_notional=notional,
            est_fee=est_fee,
            est_tax=tax,
            est_transfer=transfer_fee,
            total=est_fee + tax
        )

    # ---- 新接口：实际成交费用计算 ----
    def calc(self, side: OrderSide, price: float, qty: int, *, is_taker: bool) -> FeeResult:
        notional = price * qty
        commission = notional * self._rate(side, is_taker)
        transfer_fee = notional * settings.TRANSFER_FEE_BPS / 10_000
        tax = notional * settings.STAMP_DUTY_BPS / 10_000 if side is OrderSide.SELL else 0.0
        fee = commission + transfer_fee
        return FeeResult(
            fee=fee,
            tax=tax,
            commission=commission,
            transfer=transfer_fee,
            total=fee + tax
        )

    # ---- 兼容旧方法 (保持原文件其它引用不报错) ----
    def compute_order(self, order, *, is_taker_assume: bool = True):
        est = self.estimate_order(order.side, order.price, order.quantity, is_taker_assume=is_taker_assume)
        return est

    def compute_trade(self, trade, side: OrderSide, price: float, qty: int, is_taker: bool):
        return self.calc(side, price, qty, is_taker=is_taker)