# python
from __future__ import annotations
from .models_imports import Base, Column, Integer, String, Float, ForeignKey, relationship, SimTimeMixin
from sqlalchemy import UniqueConstraint, Index


class Position(Base, SimTimeMixin):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), ForeignKey("accounts.id"), index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    quantity = Column(Integer, default=0)
    frozen_qty = Column(Integer, default=0)
    avg_price = Column(Float, default=0.0)
    # 融券借入数量 (若允许卖空且形成净空头, borrowed_qty = |-quantity|)
    borrowed_qty = Column(Integer, default=0, index=True)
    # 最近一次计提借券费用的模拟日 (sim_day) 防重复
    borrow_fee_last_day = Column(Integer, default=-1, index=True)

    account = relationship("Account", back_populates="positions")

    __table_args__ = (
        UniqueConstraint('account_id', 'symbol', name='uq_account_symbol'),
        Index('idx_pos_account_symbol', 'account_id', 'symbol'),
    )


__all__ = ["Position"]
