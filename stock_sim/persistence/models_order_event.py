# python
from datetime import datetime
from .models_imports import Base, Column, Integer, String, DateTime

class OrderEvent(Base):
    __tablename__ = "order_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    order_id = Column(String(64), index=True)
    event = Column(String(32))
    detail = Column(String(128))