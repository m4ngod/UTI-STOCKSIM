# python
from datetime import datetime
from .models_imports import Base, Column, String, Float, Integer, DateTime, SimTimeMixin

class TradeORM(Base, SimTimeMixin):
    __tablename__ = "trades"
    id = Column(String(64), primary_key=True)
    symbol = Column(String(32), index=True)
    price = Column(Float)
    quantity = Column(Integer)
    buy_order_id = Column(String(64), index=True)
    sell_order_id = Column(String(64), index=True)
    buy_account_id = Column(String(64), index=True)
    sell_account_id = Column(String(64), index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)