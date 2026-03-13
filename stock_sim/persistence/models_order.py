# python
from datetime import datetime
from .models_imports import Base, Column, String, Float, Integer, DateTime, SAEnum, Index, SimTimeMixin
from stock_sim.core.const import OrderSide, OrderType, OrderStatus, TimeInForce

class OrderORM(Base, SimTimeMixin):
    __tablename__ = "orders"
    id = Column(String(64), primary_key=True)
    account_id = Column(String(64), index=True)
    symbol = Column(String(32), index=True)
    side = Column(SAEnum(OrderSide))
    type = Column(SAEnum(OrderType))
    tif = Column(SAEnum(TimeInForce))
    price = Column(Float)
    orig_price = Column(Float)
    quantity = Column(Integer)
    filled = Column(Integer, default=0)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.NEW)
    ts_created = Column(DateTime, default=datetime.utcnow, index=True)
    ts_last = Column(DateTime, default=datetime.utcnow, index=True)

Index("idx_orders_symbol_status", OrderORM.symbol, OrderORM.status)