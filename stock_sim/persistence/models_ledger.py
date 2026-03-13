# python
from datetime import datetime
from .models_imports import Base, Column, Integer, String, Float, DateTime, SimTimeMixin

class Ledger(Base, SimTimeMixin):
    __tablename__ = "ledgers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    account_id = Column(String(64), index=True)
    symbol = Column(String(32), index=True)
    side = Column(String(16))  # BUY / SELL / BORROW_FEE / 其他扩展
    price = Column(Float)
    qty = Column(Integer, default=0)  # 交易/计提数量（BORROW_FEE 用 borrowed_qty）
    cash_delta = Column(Float)
    fee = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    pnl_real = Column(Float, default=0.0)
    order_id = Column(String(64), nullable=True, index=True)  # 关联订单，可为空
    extra_json = Column(String(1024), nullable=True)  # 附加信息 (借券费用明细等)

__all__ = ["Ledger"]
