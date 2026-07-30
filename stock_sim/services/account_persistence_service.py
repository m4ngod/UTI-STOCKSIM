from __future__ import annotations

from sqlalchemy.orm import Session

from stock_sim.persistence.models_account_equity_snapshot import AccountEquitySnapshot
from stock_sim.persistence.models_ledger import Ledger


class AccountPersistenceService:
    """Persistence collaborator for ledger/equity snapshot writes."""

    def __init__(self, session: Session):
        self.s = session

    def write_ledger(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        price: float,
        qty: int,
        cash_delta: float,
        pnl_real: float,
        fee: float,
        tax: float,
        order_id: str | None,
        extra_json: str | None,
        run_id: str | None,
        stamp_fn,
    ) -> Ledger:
        led = Ledger(
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
            run_id=run_id,
        )
        stamp_fn(led)
        self.s.add(led)
        return led

    def write_equity_snapshot(
        self,
        *,
        run_id: str | None,
        account_id: str,
        sim_day: int,
        sim_dt,
        cash: float,
        frozen_cash: float,
        market_value: float,
        gross_exposure: float,
        net_exposure: float,
        equity: float,
        drawdown: float,
        borrowed_notional: float,
    ) -> AccountEquitySnapshot:
        snap = AccountEquitySnapshot(
            run_id=run_id,
            account_id=account_id,
            sim_day=sim_day,
            sim_dt=sim_dt,
            cash=cash,
            frozen_cash=frozen_cash,
            market_value=market_value,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            equity=equity,
            drawdown=drawdown,
            borrowed_notional=borrowed_notional,
        )
        self.s.add(snap)
        return snap
