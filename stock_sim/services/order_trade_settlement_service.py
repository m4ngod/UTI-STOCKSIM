from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from stock_sim.core.const import OrderSide, OrderStatus
from stock_sim.core.snapshot import Snapshot
from stock_sim.infra.event_bus import event_bus
from stock_sim.observability.metrics import metrics
from stock_sim.observability.struct_logger import logger
from stock_sim.persistence.models_order import OrderORM
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime
from stock_sim.services.trade_persistence_service import TradePersistenceService


class OrderTradeSettlementService:
    """Own trade persistence + settlement orchestration after matching."""

    def __init__(
        self,
        *,
        session: Session,
        accounts,
        fees,
        risk,
        trade_persistence: TradePersistenceService,
        mem_orders: Mapping[str, Any],
        engine_lookup: Callable[[str], Any],
        order_book_locator: Callable[[Any], Any],
        run_id_provider: Callable[[], str | None],
        mem_order_updater: Callable[[str, OrderORM | None, Any | None], None],
        persist_order: Callable[[Any, str, str], None],
        persist_event: Callable[[str, str, str], None],
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._fees = fees
        self._risk = risk
        self._trade_persistence = trade_persistence
        self._mem_orders = mem_orders
        self._engine_lookup = engine_lookup
        self._order_book_locator = order_book_locator
        self._run_id_provider = run_id_provider
        self._mem_order_updater = mem_order_updater
        self._persist_order = persist_order
        self._persist_event = persist_event

    def settle_external_trades(self, trades) -> None:
        if not trades:
            return
        self.process_trades(trades, publish_trade_events=True, persist_missing_orders=True)
        try:
            self._session.flush()
        except Exception:
            pass

    def process_trades(
        self,
        trades,
        *,
        publish_trade_events: bool,
        persist_missing_orders: bool,
    ) -> None:
        if not trades:
            return

        first_trade = trades[0]
        first_engine = self._engine_lookup(first_trade.symbol)
        order_book = self._order_book_locator(first_engine)
        sim_day = current_sim_day()
        sim_dt = virtual_datetime(sim_day)
        cost_map: dict[str, float] = {}
        actual_buy_fee_accum: dict[str, float] = {}
        batch_entries = []
        fee_entries = []

        for trade in trades:
            trade_engine = (
                first_engine
                if trade.symbol == first_trade.symbol
                else self._engine_lookup(trade.symbol)
            )
            cost_map[trade.buy_order_id] = cost_map.get(trade.buy_order_id, 0.0) + (
                trade.price * trade.quantity
            )
            self._trade_persistence.create_trade_record(
                trade,
                sim_day=sim_day,
                sim_dt=sim_dt,
                run_id=self._run_id_provider(),
            )

            buy_orm = self._load_order_for_trade(
                trade.buy_order_id,
                persist_missing_orders=persist_missing_orders,
            )
            if buy_orm is not None:
                buy_orm.filled += trade.quantity
                buy_orm.status = (
                    OrderStatus.FILLED
                    if buy_orm.filled >= buy_orm.quantity
                    else OrderStatus.PARTIAL
                )
                self._persist_event(
                    buy_orm.id,
                    "FILL" if buy_orm.status == OrderStatus.FILLED else "PARTIAL",
                    "",
                )

            sell_orm = self._load_order_for_trade(
                trade.sell_order_id,
                persist_missing_orders=persist_missing_orders,
            )
            if sell_orm is not None:
                sell_orm.filled += trade.quantity
                sell_orm.status = (
                    OrderStatus.FILLED
                    if sell_orm.filled >= sell_orm.quantity
                    else OrderStatus.PARTIAL
                )
                self._persist_event(
                    sell_orm.id,
                    "FILL" if sell_orm.status == OrderStatus.FILLED else "PARTIAL",
                    "",
                )

            self._mem_order_updater(trade.buy_order_id, buy_orm, trade_engine)
            self._mem_order_updater(trade.sell_order_id, sell_orm, trade_engine)

            buy_acc = (
                self._accounts.get_or_create(buy_orm.account_id)
                if buy_orm is not None
                else None
            )
            sell_acc = (
                self._accounts.get_or_create(sell_orm.account_id)
                if sell_orm is not None
                else None
            )
            fee_buy_res = self._fees.calc(
                OrderSide.BUY,
                trade.price,
                trade.quantity,
                is_taker=True,
            )
            fee_sell_res = self._fees.calc(
                OrderSide.SELL,
                trade.price,
                trade.quantity,
                is_taker=True,
            )
            actual_buy_fee_accum[trade.buy_order_id] = (
                actual_buy_fee_accum.get(trade.buy_order_id, 0.0) + fee_buy_res.fee
            )
            batch_entries.append(
                (
                    buy_acc,
                    sell_acc,
                    trade.symbol,
                    trade.price,
                    trade.quantity,
                    trade.buy_order_id,
                    trade.sell_order_id,
                )
            )
            fee_entries.append((fee_buy_res.fee, fee_sell_res.fee, fee_sell_res.tax))

            if buy_acc is not None:
                self._risk.update_tplus(
                    buy_acc.id,
                    trade.symbol,
                    OrderSide.BUY,
                    trade.quantity,
                )
            if sell_acc is not None:
                self._risk.update_tplus(
                    sell_acc.id,
                    trade.symbol,
                    OrderSide.SELL,
                    trade.quantity,
                )

            self._update_order_book_snapshot(
                order_book=order_book,
                trade=trade,
                reference_symbol=first_trade.symbol,
            )
            if publish_trade_events:
                event_bus.publish(
                    "Trade",
                    {
                        "trade": trade.to_dict(),
                        "run_id": self._run_id_provider(),
                        "symbol": trade.symbol,
                    },
                )
                logger.log("trade", **trade.to_dict())
            metrics.inc("trades_processed")

        self._accounts.settle_trades_batch(batch_entries, fee_entries)
        self._session.flush()
        self._refund_buy_cash_price_improvements(cost_map)
        self._refund_buy_fee_overages(actual_buy_fee_accum)
        self._sync_filled_mem_orders(trades)

    def _load_order_for_trade(
        self,
        order_id: str,
        *,
        persist_missing_orders: bool,
    ) -> OrderORM | None:
        orm = self._session.get(OrderORM, order_id)
        if orm is not None or not persist_missing_orders:
            return orm

        mem_order = self._mem_orders.get(order_id)
        if mem_order is None:
            return None

        self._persist_order(mem_order, "REST", "IPO_EXTERNAL_PRESETTLE")
        try:
            self._session.flush()
        except Exception:
            pass
        return self._session.get(OrderORM, order_id)

    def _update_order_book_snapshot(
        self,
        *,
        order_book: Any,
        trade,
        reference_symbol: str,
    ) -> None:
        if order_book is None or trade.symbol != reference_symbol:
            return
        if not hasattr(order_book, "last_snapshot"):
            return
        try:
            previous = order_book.last_snapshot()
        except Exception:
            previous = None
        if previous is None or not isinstance(previous, Snapshot):
            previous = Snapshot(symbol=trade.symbol)
        previous.update_trade(trade.price, trade.quantity)
        try:
            setattr(order_book, "_last_snapshot", previous)
        except Exception:
            pass

    def _refund_buy_cash_price_improvements(self, cost_map: Mapping[str, float]) -> None:
        for order_id, actual_cost in cost_map.items():
            buy_orm = self._session.get(OrderORM, order_id)
            if buy_orm is None or buy_orm.status != OrderStatus.FILLED:
                continue
            frozen_should = buy_orm.price * buy_orm.quantity
            if frozen_should <= actual_cost:
                continue
            acc = self._accounts.get_or_create(buy_orm.account_id)
            refund = min(frozen_should - actual_cost, acc.frozen_cash)
            if refund <= 0:
                continue
            acc.frozen_cash -= refund
            acc.cash += refund
            metrics.inc("cash_refund_after_fill")

    def _refund_buy_fee_overages(
        self,
        actual_buy_fee_accum: Mapping[str, float],
    ) -> None:
        for buy_order_id, actual_fee in actual_buy_fee_accum.items():
            mem_order = self._mem_orders.get(buy_order_id)
            if mem_order is None:
                continue
            if mem_order.status != OrderStatus.FILLED or "est_fee" not in mem_order._meta:
                continue
            estimated_fee = mem_order._meta["est_fee"]
            if estimated_fee <= actual_fee + 1e-9:
                continue
            acc = self._accounts.get_or_create(mem_order.account_id)
            self._accounts.refund_fee(acc, estimated_fee - actual_fee)
            metrics.inc("fee_refund_after_fill")

    def _sync_filled_mem_orders(self, trades) -> None:
        seen: set[str] = set()
        for trade in trades:
            for order_id in (trade.buy_order_id, trade.sell_order_id):
                if order_id in seen:
                    continue
                seen.add(order_id)
                orm = self._session.get(OrderORM, order_id)
                if orm is None or orm.status != OrderStatus.FILLED:
                    continue
                mem = self._mem_orders.get(order_id)
                if mem is None:
                    continue
                mem.status = orm.status
                mem.filled = orm.filled


__all__ = ["OrderTradeSettlementService"]
