from __future__ import annotations

from typing import Any

from stock_sim.core.const import OrderSide, OrderStatus, Phase
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order import Order
from stock_sim.core.validators import (
    align_lot_quantity,
    basic_order_checks,
    normalize_price,
    validate_lot,
)
from stock_sim.infra.event_bus import event_bus
from stock_sim.observability.metrics import metrics
from stock_sim.observability.struct_logger import logger
from stock_sim.settings import settings


class OrderPreTradeService:
    """Own normalize/risk/freeze/reject policy before matching."""

    def __init__(
        self,
        *,
        accounts,
        fees,
        risk,
        run_id_provider,
        persist_order,
        trace_orders: bool = False,
    ) -> None:
        self._accounts = accounts
        self._fees = fees
        self._risk = risk
        self._run_id_provider = run_id_provider
        self._persist_order = persist_order
        self._trace_orders = trace_orders

    def prepare_order(
        self,
        order: Order,
        *,
        params,
        engine: MatchingEngine,
        debug_mode: bool,
    ) -> tuple[bool, Any | None]:
        normalized_ok, normalized_reason = self.normalize_order(order, params)
        if not normalized_ok:
            self.reject_order(order, reason=str(normalized_reason or "NORMALIZE_FAIL"))
            return False, None

        ok, reason = basic_order_checks(order.price, order.quantity)
        if self._trace_orders:
            print(
                f"[TRACE OrderService.basic_checks] oid={order.order_id} ok={ok} reason={reason}"
            )
        if not ok:
            self.reject_order(order, reason=reason)
            return False, None

        acc = self._accounts.get_or_create(order.account_id)
        if self._trace_orders:
            try:
                pos_state = [(p.symbol, p.quantity, p.frozen_qty) for p in acc.positions]
            except Exception:
                pos_state = "ERR"
            print(
                "[TRACE OrderService.before_risk] "
                f"oid={order.order_id} cash={acc.cash:.4f} "
                f"frozen_cash={acc.frozen_cash:.4f} frozen_fee={acc.frozen_fee:.4f} "
                f"positions={pos_state}"
            )

        risk_positions = acc.positions
        settlement_cycle = getattr(params, "settlement_cycle", 0) if params else 0
        rr = self._risk.validate(
            account=acc,
            positions=risk_positions,
            symbol=order.symbol,
            side=order.side,
            price=order.price,
            qty=order.quantity,
            context={
                "settlement_cycle": settlement_cycle,
                "tif": order.tif,
                "engine": engine,
            },
            order_type=order.order_type,
        )
        if not rr.ok:
            if debug_mode:
                print(f"[DBG OrderService.reject.risk] code={rr.code} reason={rr.reason}")
            self.reject_order(order, reason=rr.reason, metric_code=rr.code)
            if self._trace_orders:
                print(
                    f"[TRACE OrderService.reject.risk] oid={order.order_id} "
                    f"code={rr.code} reason={rr.reason}"
                )
            return False, None

        fee_est = self._fees.estimate_order(order.side, order.price, order.quantity)
        if self._trace_orders:
            print(
                f"[TRACE OrderService.fee_est] oid={order.order_id} "
                f"est_fee={fee_est.est_fee} est_tax={fee_est.est_tax} "
                f"notional_basis={fee_est.basis_notional}"
            )
        order.attach_meta(est_fee=fee_est.est_fee)
        logger.log(
            "order_fee_est",
            order_id=order.order_id,
            est_fee=fee_est.est_fee,
            est_tax=fee_est.est_tax,
            notional=fee_est.basis_notional,
        )

        if not self.freeze_order_resources(
            order,
            acc,
            fee_est.est_fee,
            engine=engine,
            debug_mode=debug_mode,
        ):
            return False, None

        return True, acc

    def normalize_order(self, order: Order, params) -> tuple[bool, str | None]:
        if not params:
            return True, None
        try:
            tick = getattr(params, "tick_size", 0) or 0
            if tick > 0:
                new_price = normalize_price(order.price, tick)
                if new_price != order.price and self._trace_orders:
                    print(
                        f"[TRACE OrderService.norm_price] oid={order.order_id} "
                        f"from={order.price} to={new_price} tick={tick}"
                    )
                order.price = new_price
            lot = getattr(params, "lot_size", 1) or 1
            min_qty = getattr(params, "min_qty", 1) or 1
            if not validate_lot(order.quantity, lot, min_qty):
                aligned = align_lot_quantity(order.quantity, lot, min_qty)
                if aligned <= 0:
                    if self._trace_orders:
                        print(
                            f"[TRACE OrderService.reject.MIN_QTY] oid={order.order_id} "
                            f"sym={order.symbol} qty={order.quantity} lot={lot} min={min_qty}"
                        )
                    return False, "MIN_QTY"
                if self._trace_orders:
                    print(
                        f"[TRACE OrderService.align_qty] oid={order.order_id} "
                        f"from={order.quantity} to={aligned} lot={lot} min={min_qty}"
                    )
                logger.log(
                    "order_norm_qty",
                    order_id=order.order_id,
                    src=order.quantity,
                    dst=aligned,
                )
                order.quantity = aligned
        except Exception:
            pass
        return True, None

    def reject_order(
        self,
        order: Order,
        *,
        reason: str,
        metric_code: str | None = None,
    ) -> None:
        code = (metric_code or reason).lower()
        order.status = OrderStatus.REJECTED
        self._persist_order(order, "REJECT", reason)
        metrics.inc("orders_rejected")
        metrics.inc(settings.REJECT_METRIC_PREFIX + code)
        try:
            event_bus.publish(
                "OrderRejected",
                {
                    "order": order.to_dict(),
                    "reason": reason,
                    "run_id": self._run_id_provider(),
                    "symbol": order.symbol,
                },
            )
        except Exception:
            pass
        logger.log("order_reject", order_id=order.order_id, reason=reason)

    def release_order_reservations(
        self,
        *,
        acc,
        symbol: str,
        side,
        price: float,
        remaining: int,
        total_quantity: int,
        mem_order: Order | None,
    ) -> None:
        if remaining > 0:
            self._accounts.release(acc, symbol, side, price, remaining)
        if (
            mem_order is None
            or mem_order.side is not OrderSide.BUY
            or "est_fee" not in mem_order._meta
            or total_quantity <= 0
        ):
            return
        unfilled_ratio = remaining / total_quantity if remaining > 0 else 0.0
        if unfilled_ratio <= 0:
            return
        refund_fee = mem_order._meta["est_fee"] * unfilled_ratio
        self._accounts.refund_fee(acc, refund_fee)

    def freeze_order_resources(
        self,
        order: Order,
        acc,
        estimated_fee: float,
        *,
        engine: MatchingEngine,
        debug_mode: bool,
    ) -> bool:
        if order.side is OrderSide.BUY:
            if not self._accounts.freeze_fee(acc, estimated_fee):
                if self._trace_orders:
                    print(
                        f"[TRACE OrderService.reject.fee_freeze_fail] oid={order.order_id} "
                        f"fee={estimated_fee} cash={acc.cash}"
                    )
                self.reject_order(order, reason="FEE_FREEZE_FAIL")
                return False
            if order.status == OrderStatus.REJECTED and debug_mode:
                print("[DBG OrderService.reject.fee_freeze]")

        if self._trace_orders:
            print(
                f"[TRACE OrderService.freeze_main.try] oid={order.order_id} "
                f"side={order.side.name} symbol={order.symbol} px={order.price} qty={order.quantity}"
            )

        if self.should_skip_main_freeze(order, engine):
            if self._trace_orders:
                print(
                    f"[TRACE OrderService.freeze_main.skip_call_auction] "
                    f"oid={order.order_id} symbol={order.symbol} qty={order.quantity}"
                )
            return True

        if self._accounts.freeze(acc, order.symbol, order.side, order.price, order.quantity):
            return True

        if debug_mode:
            print(
                f"[DBG OrderService.reject.freeze] cash={acc.cash} frozen_cash={acc.frozen_cash}"
            )
        if order.side is OrderSide.BUY and estimated_fee > 0:
            self._accounts.refund_fee(acc, estimated_fee)
        if self._trace_orders:
            print(
                f"[TRACE OrderService.reject.freeze_fail] oid={order.order_id} "
                f"cash={acc.cash:.4f} frozen_cash={acc.frozen_cash:.4f}"
            )
        self.reject_order(order, reason="FREEZE_FAIL")
        return False

    def should_skip_main_freeze(self, order: Order, engine: MatchingEngine) -> bool:
        if order.side is not OrderSide.BUY:
            return False
        try:
            return engine.get_book(order.symbol).phase is Phase.CALL_AUCTION
        except Exception:
            return False


__all__ = ["OrderPreTradeService"]
