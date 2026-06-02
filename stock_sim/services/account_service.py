# python
"""AccountService

当前目标：
- 提供稳定、可理解的账户/持仓/冻结/批量结算语义
- 不大拆现有 OrderService 调用面
- 补足账本、事件、空头回补等主链路能力

设计取舍：
- 维持现有公开方法签名，避免牵连面扩大
- 先把“真实交易主链路”做对，再考虑更细的保证金/已实现盈亏模型
- SELL 冻结仍兼容当前系统的“允许形成空头”设定，但不在 freeze 阶段直接篡改 quantity
"""
from __future__ import annotations

from typing import Iterable, Any

try:
    from stock_sim.persistence.models_account import Account  # type: ignore
    from stock_sim.persistence.models_position import Position  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType, OrderSide  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
    from stock_sim.settings import settings  # type: ignore
except Exception:  # noqa
    from persistence.models_account import Account  # type: ignore
    from persistence.models_position import Position  # type: ignore
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType, OrderSide  # type: ignore
    from services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
    from settings import settings  # type: ignore

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

try:
    from stock_sim.services.account_persistence_service import AccountPersistenceService  # type: ignore
    from stock_sim.services.run_context import RunContext  # type: ignore
except Exception:  # noqa
    from services.account_persistence_service import AccountPersistenceService  # type: ignore
    from services.run_context import RunContext  # type: ignore


class AccountService:
    def __init__(self, session: Session, run_context: RunContext | None = None):
        self.s = session
        self.run_context = run_context
        self.persistence = AccountPersistenceService(session)

    # ---- Public API ----
    def get_or_create(self, account_id: str, *, cash: float | None = None) -> Account:
        acc = self.s.get(Account, account_id)
        if acc:
            self._ensure_stamped(acc)
            return acc
        init_cash = float(settings.DEFAULT_CASH if cash is None else cash)
        acc = Account(id=account_id, cash=init_cash)
        self._stamp(acc)
        self.s.add(acc)
        self.s.flush()
        self._publish_account(acc)
        return acc

    def get_position(self, account: Account, symbol: str) -> Position:
        pos = (
            self.s.query(Position)
            .filter(Position.account_id == account.id, Position.symbol == symbol)
            .first()
        )
        if pos:
            self._ensure_stamped(pos)
            return pos
        pos = Position(
            account_id=account.id,
            symbol=symbol,
            quantity=0,
            frozen_qty=0,
            avg_price=0.0,
            borrowed_qty=0,
        )
        self._stamp(pos)
        self.s.add(pos)
        try:
            self.s.flush()
        except IntegrityError:
            self.s.rollback()
            pos = (
                self.s.query(Position)
                .filter(Position.account_id == account.id, Position.symbol == symbol)
                .first()
            )
            if not pos:
                raise
        try:
            self.s.expire(account, ["positions"])
        except Exception:
            pass
        metrics.inc("pos_create")
        return pos

    def freeze_fee(self, acc: Account, fee: float) -> bool:
        if fee <= 0:
            return True
        if acc.cash + 1e-9 < fee:
            return False
        acc.cash -= fee
        acc.frozen_fee += fee
        metrics.inc("fee_frozen")
        return True

    def refund_fee(self, acc: Account, fee: float):
        if fee <= 0:
            return
        delta = min(float(fee), float(acc.frozen_fee or 0.0))
        if delta <= 0:
            return
        acc.frozen_fee -= delta
        acc.cash += delta
        metrics.inc("fee_refund")
        self._publish_account(acc)

    def freeze(self, acc: Account, symbol: str, side: OrderSide, price: float, qty: int) -> bool:
        """主体冻结。

        BUY:
          - 冻结 price * qty 现金
        SELL:
          - 冻结可用多头仓位；若不足，兼容当前系统允许继续卖空，不在此处改 quantity，
            仅把可冻结的多头部分冻结，剩余部分交由成交结算形成净空头。
        """
        if qty <= 0:
            return False
        if side is OrderSide.BUY:
            need = float(price) * int(qty)
            if acc.cash + 1e-9 < need:
                return False
            acc.cash -= need
            acc.frozen_cash += need
            metrics.inc("cash_frozen")
            self._publish_account(acc)
            return True

        pos = self.get_position(acc, symbol)
        available_long = max(0, int(pos.quantity) - int(pos.frozen_qty))
        lock_qty = min(int(qty), available_long)
        if lock_qty > 0:
            pos.frozen_qty += lock_qty
            metrics.inc("qty_frozen")
        self._publish_account(acc)
        return True

    def release(self, acc: Account, symbol: str, side: OrderSide, price: float, qty: int):
        if qty <= 0:
            return
        if side is OrderSide.BUY:
            notional = float(price) * int(qty)
            refund = min(notional, float(acc.frozen_cash or 0.0))
            if refund > 0:
                acc.frozen_cash -= refund
                acc.cash += refund
                metrics.inc("cash_release")
                self._publish_account(acc)
            return

        pos = self.get_position(acc, symbol)
        delta = min(int(qty), int(pos.frozen_qty or 0))
        if delta > 0:
            pos.frozen_qty -= delta
            metrics.inc("qty_release")
            self._publish_account(acc)

    def settle_trades_batch(self, batch_entries, fee_entries):
        """批量成交结算。

        batch_entries: (buy_acc, sell_acc, symbol, price, qty, buy_oid, sell_oid)
        fee_entries:   (fee_buy, fee_sell, tax_sell)

        关键语义：
        - 买方：释放对应冻结现金；增加持仓；若在回补空头则优先减少 borrowed_qty/空头仓
        - 卖方：减少/释放多头；若卖超出已有多头则形成净空头并提高 borrowed_qty；增加卖出现金净额
        - 双方都写 Ledger
        - 同一批撮合只为每个受影响账户发布一次 ACCOUNT_UPDATED / equity snapshot
        """
        touched_accounts: dict[str, Account] = {}
        for idx, entry in enumerate(batch_entries):
            buy_acc, sell_acc, symbol, price, qty, buy_oid, sell_oid = entry
            fee_buy, fee_sell, tax_sell = fee_entries[idx]
            price = float(price)
            qty = int(qty)
            notional = price * qty

            if buy_acc is not None:
                self._settle_buy_leg(
                    buy_acc=buy_acc,
                    symbol=symbol,
                    price=price,
                    qty=qty,
                    order_id=buy_oid,
                    fee_buy=float(fee_buy or 0.0),
                    frozen_notional=notional,
                    publish_account=False,
                )
                touched_accounts[buy_acc.id] = buy_acc

            if sell_acc is not None:
                self._settle_sell_leg(
                    sell_acc=sell_acc,
                    symbol=symbol,
                    price=price,
                    qty=qty,
                    order_id=sell_oid,
                    fee_sell=float(fee_sell or 0.0),
                    tax_sell=float(tax_sell or 0.0),
                    gross_notional=notional,
                    publish_account=False,
                )
                touched_accounts[sell_acc.id] = sell_acc

            metrics.inc("trades_settled")

        for acc in touched_accounts.values():
            self.write_equity_snapshot(acc)
            self._publish_account(acc)

    # ---- Internal settlement helpers ----
    def _settle_buy_leg(self, *, buy_acc: Account, symbol: str, price: float, qty: int,
                        order_id: str | None, fee_buy: float, frozen_notional: float,
                        publish_account: bool = True):
        if frozen_notional > 0:
            reduce = min(frozen_notional, float(buy_acc.frozen_cash or 0.0))
            buy_acc.frozen_cash -= reduce

        if fee_buy > 0:
            used = min(fee_buy, float(buy_acc.frozen_fee or 0.0))
            buy_acc.frozen_fee -= used
            remain = fee_buy - used
            if remain > 0:
                buy_acc.cash -= remain

        pos = self.get_position(buy_acc, symbol)
        old_qty = int(pos.quantity or 0)
        old_avg = float(pos.avg_price or 0.0)
        old_borrowed = int(pos.borrowed_qty or 0)

        # 先处理回补空头
        if old_qty < 0:
            cover_qty = min(qty, -old_qty)
            new_qty = old_qty + qty
            pos.quantity = new_qty
            pos.borrowed_qty = max(0, old_borrowed - cover_qty, -new_qty)
            if new_qty < 0:
                # 仍为空头，均价保持原空头参考价
                pass
            elif new_qty == 0:
                pos.avg_price = 0.0
            else:
                # 已由空翻多，仅剩余部分构成新多头成本
                open_long_qty = qty - cover_qty
                pos.avg_price = price if open_long_qty > 0 else 0.0
        else:
            prev_cost = old_avg * old_qty
            new_qty = old_qty + qty
            pos.quantity = new_qty
            pos.avg_price = ((prev_cost + price * qty) / new_qty) if new_qty > 0 else 0.0
            pos.borrowed_qty = max(0, -new_qty)

        self._write_ledger(
            buy_acc.id,
            symbol,
            "BUY",
            price,
            qty,
            cash_delta=0.0,
            pnl_real=0.0,
            fee=fee_buy,
            tax=0.0,
            order_id=order_id,
            extra_json=None,
        )
        if publish_account:
            self._publish_account(buy_acc)

    def _settle_sell_leg(self, *, sell_acc: Account, symbol: str, price: float, qty: int,
                         order_id: str | None, fee_sell: float, tax_sell: float, gross_notional: float,
                         publish_account: bool = True):
        pos = self.get_position(sell_acc, symbol)
        old_qty = int(pos.quantity or 0)
        old_borrowed = int(pos.borrowed_qty or 0)
        old_avg = float(pos.avg_price or 0.0)

        long_released = min(max(old_qty, 0), min(qty, int(pos.frozen_qty or 0)))
        if long_released > 0:
            pos.frozen_qty -= long_released

        new_qty = old_qty - qty
        pos.quantity = new_qty
        if new_qty > 0:
            # 仍为多头，均价保持不变
            pos.avg_price = old_avg
            pos.borrowed_qty = 0
        elif new_qty == 0:
            pos.avg_price = 0.0
            pos.borrowed_qty = 0
        else:
            # 形成/扩大空头
            pos.avg_price = price if old_qty >= 0 else old_avg
            pos.borrowed_qty = max(old_borrowed, -new_qty)

        total_fee = fee_sell + tax_sell
        sell_acc.cash += gross_notional - total_fee

        self._write_ledger(
            sell_acc.id,
            symbol,
            "SELL",
            price,
            qty,
            cash_delta=(gross_notional - total_fee),
            pnl_real=0.0,
            fee=fee_sell,
            tax=tax_sell,
            order_id=order_id,
            extra_json=None,
        )
        if publish_account:
            self._publish_account(sell_acc)

    # ---- Internal helpers ----
    def _write_ledger(self, account_id: str, symbol: str, side: str, price: float, qty: int,
                      cash_delta: float, pnl_real: float, fee: float, tax: float,
                      order_id: str | None = None, extra_json: str | None = None):
        self.persistence.write_ledger(
            account_id=account_id,
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            cash_delta=cash_delta,
            pnl_real=pnl_real,
            fee=fee,
            tax=tax,
            order_id=order_id,
            extra_json=extra_json,
            run_id=self._get_run_id(),
            stamp_fn=self._stamp,
        )

    def _get_run_id(self) -> str | None:
        return None if self.run_context is None else self.run_context.run_id

    def write_equity_snapshot(self, acc: Account):
        self._ensure_stamped(acc)
        positions = list(getattr(acc, "positions", []) or [])
        market_value = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        borrowed_notional = 0.0
        for p in positions:
            qty = int(getattr(p, "quantity", 0) or 0)
            avg_price = float(getattr(p, "avg_price", 0.0) or 0.0)
            borrowed_qty = int(getattr(p, "borrowed_qty", 0) or 0)
            notional = qty * avg_price
            market_value += notional
            gross_exposure += abs(notional)
            net_exposure += notional
            borrowed_notional += borrowed_qty * avg_price
        cash = float(getattr(acc, "cash", 0.0) or 0.0)
        frozen_cash = float(getattr(acc, "frozen_cash", 0.0) or 0.0)
        equity = cash + frozen_cash + market_value
        self.persistence.write_equity_snapshot(
            run_id=self._get_run_id(),
            account_id=acc.id,
            sim_day=getattr(acc, "sim_day", 0) or 0,
            sim_dt=getattr(acc, "sim_dt", None),
            cash=cash,
            frozen_cash=frozen_cash,
            market_value=market_value,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            equity=equity,
            drawdown=0.0,
            borrowed_notional=borrowed_notional,
        )

    def _account_payload(self, acc: Account) -> dict[str, Any]:
        positions = []
        try:
            iterable: Iterable[Position] = getattr(acc, "positions", []) or []
            for p in iterable:
                positions.append({
                    "symbol": p.symbol,
                    "quantity": int(getattr(p, "quantity", 0) or 0),
                    "frozen_qty": int(getattr(p, "frozen_qty", 0) or 0),
                    "avg_price": float(getattr(p, "avg_price", 0.0) or 0.0),
                    "borrowed_qty": int(getattr(p, "borrowed_qty", 0) or 0),
                    "settlement_cycle": int(getattr(p, "settlement_cycle", 0) or 0) if hasattr(p, "settlement_cycle") else 0,
                })
        except Exception:
            positions = []
        return {
            "id": acc.id,
            "cash": float(getattr(acc, "cash", 0.0) or 0.0),
            "frozen_cash": float(getattr(acc, "frozen_cash", 0.0) or 0.0),
            "frozen_fee": float(getattr(acc, "frozen_fee", 0.0) or 0.0),
            "positions": positions,
            "sim_day": getattr(acc, "sim_day", None),
            "sim_dt": getattr(acc, "sim_dt", None),
            "run_id": self._get_run_id(),
        }

    def _publish_account(self, acc: Account):
        self._ensure_stamped(acc)
        try:
            event_bus.publish(EventType.ACCOUNT_UPDATED, self._account_payload(acc))
        except Exception:
            pass

    # ---- Time stamping ----
    def _ensure_stamped(self, obj):
        if getattr(obj, "sim_day", None):
            return
        self._stamp(obj)

    def _stamp(self, obj):
        try:
            sd = current_sim_day()
            if sd is not None:
                if hasattr(obj, "sim_day"):
                    obj.sim_day = sd
                if hasattr(obj, "sim_dt"):
                    obj.sim_dt = virtual_datetime(sd)
        except Exception:
            pass


__all__ = ["AccountService"]
