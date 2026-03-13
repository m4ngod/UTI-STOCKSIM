# python
from datetime import datetime
from .models_imports import Base, Column, String, Float, Integer, DateTime, SimTimeMixin  # existing
from sqlalchemy import Boolean  # 新增

class Instrument(Base, SimTimeMixin):
    __tablename__ = "instruments"
    symbol = Column(String(32), primary_key=True)
    name = Column(String(128), default="")
    tick_size = Column(Float, default=0.01)
    lot_size = Column(Integer, default=1)
    min_qty = Column(Integer, default=1)
    settlement_cycle = Column(Integer, default=1)  # 0=T+0 1=T+1
    pe = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)  # 流通市值 (金额)
    total_shares = Column(Float, nullable=True)
    free_float_shares = Column(Float, nullable=True)
    initial_price = Column(Float, nullable=True)  # 新增: 初始/发行价
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True, index=True)  # 软删除标志
    # 新增: IPO 开盘集合竞价是否已完成
    ipo_opened = Column(Boolean, default=False, index=True)
