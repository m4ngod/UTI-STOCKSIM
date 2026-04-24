from __future__ import annotations

from sqlalchemy.orm import Session

from stock_sim.persistence.models_trade import TradeORM


class TradePersistenceService:
    """Persistence collaborator for trade row writes."""

    def __init__(self, session: Session):
        self.s = session

    def create_trade_record(self, trade, *, sim_day: int, sim_dt, run_id: str | None) -> TradeORM:
        row = TradeORM(
            id=trade.trade_id,
            symbol=trade.symbol,
            price=trade.price,
            quantity=trade.quantity,
            buy_order_id=trade.buy_order_id,
            sell_order_id=trade.sell_order_id,
            buy_account_id=trade.buy_account_id,
            sell_account_id=trade.sell_account_id,
            sim_day=sim_day,
            sim_dt=sim_dt,
            run_id=run_id,
        )
        self.s.add(row)
        return row
