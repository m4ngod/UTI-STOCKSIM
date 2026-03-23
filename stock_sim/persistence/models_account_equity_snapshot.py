from datetime import datetime

from .models_imports import Base, Column, Integer, String, Float, DateTime


class AccountEquitySnapshot(Base):
    __tablename__ = "account_equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=True, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    sim_day = Column(Integer, default=0, index=True)
    sim_dt = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    cash = Column(Float, default=0.0)
    frozen_cash = Column(Float, default=0.0)
    market_value = Column(Float, default=0.0)
    gross_exposure = Column(Float, default=0.0)
    net_exposure = Column(Float, default=0.0)
    equity = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)
    borrowed_notional = Column(Float, default=0.0)


__all__ = ["AccountEquitySnapshot"]
