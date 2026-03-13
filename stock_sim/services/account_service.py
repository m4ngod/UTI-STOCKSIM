# python
"""Simplified AccountService (reconstructed after corruption)
提供最小功能集, 满足借券费用计提与基础账户/持仓/流水写入测试需求。
原复杂逻辑(冻结/撮合/批量结算/融券池)已移除或简化, 后续若需可重新扩展。
"""
from __future__ import annotations
# 新增: 双路径容错导入
try:
    from stock_sim.persistence.models_account import Account  # type: ignore
    from stock_sim.persistence.models_position import Position  # type: ignore
    from stock_sim.persistence.models_ledger import Ledger  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
except Exception:  # noqa
    from persistence.models_account import Account  # type: ignore
    from persistence.models_position import Position  # type: ignore
    from persistence.models_ledger import Ledger  # type: ignore
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
# 新增: 引入 settings 以获取 DEFAULT_CASH
try:
    from stock_sim.settings import settings  # type: ignore
except Exception:  # noqa
    from settings import settings  # type: ignore
# 新增: 需要区分买卖方向
try:
    from stock_sim.core.const import OrderSide  # type: ignore
except Exception:  # noqa
    from core.const import OrderSide  # type: ignore

class AccountService:
    def __init__(self, session: Session):
        self.s = session

    # ---- Public API ----
    def get_or_create(self, account_id: str, *, cash: float | None = None) -> Account:
        acc = self.s.get(Account, account_id)
        if acc:
            self._ensure_stamped(acc)
            return acc
        # 若未指定现金则使用全局默认初始资金
        init_cash = float(settings.DEFAULT_CASH if cash is None else cash)
        acc = Account(id=account_id, cash=init_cash)
        self._stamp(acc)
        self.s.add(acc)
        self.s.flush()
        self._publish_account(acc)
        return acc

    def get_position(self, account: Account, symbol: str) -> Position:
        pos = (self.s.query(Position)
               .filter(Position.account_id == account.id, Position.symbol == symbol)
               .first())
        if pos:
            self._ensure_stamped(pos)
            return pos
        pos = Position(account_id=account.id, symbol=symbol, quantity=0, avg_price=0.0, borrowed_qty=0)
        self._stamp(pos)
        self.s.add(pos)
        try:
            self.s.flush()
        except IntegrityError:
            self.s.rollback()
            # 再查一次 (并发竞争) 返回
            pos = (self.s.query(Position)
                   .filter(Position.account_id == account.id, Position.symbol == symbol)
                   .first())
            if not pos:
                raise
        metrics.inc('pos_create')
        return pos

    def freeze_fee(self, acc: Account, fee: float) -> bool:
        """买单预冻结手续费 (简化)。"""
        if fee <= 0:
            return True
        if acc.cash + 1e-9 < fee:
            return False
        acc.cash -= fee
        acc.frozen_fee += fee
        try: metrics.inc('fee_frozen')
        except Exception: pass
        return True

    def refund_fee(self, acc: Account, fee: float):
        if fee <= 0:
            return
        delta = min(fee, acc.frozen_fee)
        if delta <= 0:
            return
        acc.frozen_fee -= delta
        acc.cash += delta
        try: metrics.inc('fee_refund')
        except Exception: pass

    def freeze(self, acc: Account, symbol: str, side: OrderSide, price: float, qty: int) -> bool:
        """主体冻结: BUY 冻结现金, SELL 冻结持仓数量 (不足时允许形成短仓, 简化逻辑)。"""
        if qty <= 0:
            return False
        if side is OrderSide.BUY:
            need = price * qty
            if acc.cash + 1e-9 < need:
                return False
            acc.cash -= need
            acc.frozen_cash += need
            try: metrics.inc('cash_frozen')
            except Exception: pass
            return True
        # SELL 方向: 冻结（或建立）持仓数量
        pos = self.get_position(acc, symbol)
        # 可用数量
        available = pos.quantity - pos.frozen_qty
        if available >= qty:
            pos.frozen_qty += qty
        else:
            # 不足 => 允许建立短仓: 直接增加冻结量并将数量减少 (形成负数)
            short_extra = qty - available
            pos.frozen_qty += qty  # 冻结目标数量
            pos.quantity -= short_extra  # 形成净空头 (quantity 下降)
            pos.borrowed_qty = max(pos.borrowed_qty, -pos.quantity)
        try: metrics.inc('qty_frozen')
        except Exception: pass
        return True

    def release(self, acc: Account, symbol: str, side: OrderSide, price: float, qty: int):
        if qty <= 0:
            return
        if side is OrderSide.BUY:
            notional = price * qty
            refund = min(notional, acc.frozen_cash)
            if refund > 0:
                acc.frozen_cash -= refund
                acc.cash += refund
                try: metrics.inc('cash_release')
                except Exception: pass
        else:  # SELL
            pos = self.get_position(acc, symbol)
            delta = min(qty, pos.frozen_qty)
            if delta > 0:
                pos.frozen_qty -= delta
                try: metrics.inc('qty_release')
                except Exception: pass

    def settle_trades_batch(self, batch_entries, fee_entries):
        """批量成交结算 (最小实现)。
        batch_entries: list[(buy_acc, sell_acc, symbol, price, qty, buy_oid, sell_oid)]
        fee_entries: list[(fee_buy, fee_sell, tax_sell)] 对应顺序
        """
        for idx, entry in enumerate(batch_entries):
            buy_acc, sell_acc, symbol, price, qty, _boid, _soid = entry
            fee_buy, fee_sell, tax_sell = fee_entries[idx]
            # 买方: 资金已冻结在冻结现金中 -> 释放实际成本 (转为已消耗)。剩余差额稍后在 order_service 中返还
            if buy_acc:
                cost = price * qty
                if cost > 0:
                    reduce = min(cost, buy_acc.frozen_cash)
                    buy_acc.frozen_cash -= reduce
                # 手续费实际扣除: 从 frozen_fee 中扣除; 不足部分直接从 cash 扣
                if fee_buy > 0:
                    used = min(fee_buy, buy_acc.frozen_fee)
                    buy_acc.frozen_fee -= used
                    remain = fee_buy - used
                    if remain > 0 and buy_acc.cash >= remain:
                        buy_acc.cash -= remain
                # 更新/创建持仓与均价
                pos_b = self.get_position(buy_acc, symbol)
                prev_qty = pos_b.quantity
                prev_cost = pos_b.avg_price * prev_qty
                new_qty = prev_qty + qty
                if new_qty != 0:
                    pos_b.avg_price = (prev_cost + price * qty) / new_qty
                pos_b.quantity = new_qty
            # 卖方: 释放冻结数量并增加现金 (扣除费用+税)
            if sell_acc:
                pos_s = self.get_position(sell_acc, symbol)
                if pos_s.frozen_qty > 0:
                    rel = min(qty, pos_s.frozen_qty)
                    pos_s.frozen_qty -= rel
                # 递减持仓 (可能转为空头)
                pos_s.quantity -= qty
                if pos_s.quantity < 0:
                    pos_s.borrowed_qty = max(pos_s.borrowed_qty, -pos_s.quantity)
                gross = price * qty
                sell_acc.cash += gross
                total_fee = fee_sell + tax_sell
                if total_fee > 0 and sell_acc.cash >= total_fee:
                    sell_acc.cash -= total_fee
            try: metrics.inc('trades_settled')
            except Exception: pass

    # ---- Internal helpers ----
    def _write_ledger(self, account_id: str, symbol: str, side: str, price: float, qty: int,
                      cash_delta: float, pnl_real: float, fee: float, tax: float,
                      order_id: str | None = None, extra_json: str | None = None):
        led = Ledger(account_id=account_id, symbol=symbol, side=side, price=price, qty=qty,
                     cash_delta=cash_delta, pnl_real=pnl_real, fee=fee, tax=tax, extra_json=extra_json)
        self._stamp(led)
        self.s.add(led)

    def _publish_account(self, acc: Account):
        self._ensure_stamped(acc)
        try:
            payload = {
                'id': acc.id,
                'cash': acc.cash,
                'frozen_cash': getattr(acc, 'frozen_cash', 0.0),
            }
            event_bus.publish(EventType.ACCOUNT_UPDATED, payload)
        except Exception:  # noqa
            pass

    # ---- Time stamping ----
    def _ensure_stamped(self, obj):
        if getattr(obj, 'sim_day', None):
            return
        self._stamp(obj)

    def _stamp(self, obj):
        try:
            sd = current_sim_day()
            if sd:
                if hasattr(obj, 'sim_day'):
                    obj.sim_day = sd
                if hasattr(obj, 'sim_dt'):
                    obj.sim_dt = virtual_datetime(sd)
        except Exception:
            pass

__all__ = ["AccountService"]
