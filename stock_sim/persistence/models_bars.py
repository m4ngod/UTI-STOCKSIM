# python
from datetime import datetime
from .models_imports import Base, Column, Integer, String, Float, DateTime, Index, SimTimeMixin

class Bar1m(Base, SimTimeMixin):
    __tablename__ = "bars_1m"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, index=True)  # 窗口起始 UTC 时间
    symbol = Column(String(32), index=True)
    open = Column(Float); high = Column(Float); low = Column(Float); close = Column(Float)
    volume = Column(Integer, default=0)
    turnover = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
Index("idx_bars1m_symbol_ts", Bar1m.symbol, Bar1m.ts, unique=True)

class Bar1h(Base, SimTimeMixin):
    __tablename__ = "bars_1h"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, index=True)
    symbol = Column(String(32), index=True)
    open = Column(Float); high = Column(Float); low = Column(Float); close = Column(Float)
    volume = Column(Integer, default=0)
    turnover = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
Index("idx_bars1h_symbol_ts", Bar1h.symbol, Bar1h.ts, unique=True)

class Bar1d(Base, SimTimeMixin):
    __tablename__ = "bars_1d"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, index=True)  # 交易日日期 00:00 (UTC 或本地需统一)
    symbol = Column(String(32), index=True)
    open = Column(Float); high = Column(Float); low = Column(Float); close = Column(Float)
    volume = Column(Integer, default=0)
    turnover = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
Index("idx_bars1d_symbol_ts", Bar1d.symbol, Bar1d.ts, unique=True)
