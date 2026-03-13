# python
# file: persistence/models_event_log.py
"""事件日志模型 (platform-hardening Task3)

用于持久化核心事件，支持回放、审计与恢复。
"""
from __future__ import annotations
from sqlalchemy import Text, Index
from .models_imports import Base, Column, BigInteger, Integer, String

class EventLog(Base):
    __tablename__ = "event_log"
    # sqlite 自增要求 INTEGER PRIMARY KEY，这里使用 Integer 兼容；MySQL 也可自动扩展
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_ms = Column(BigInteger, index=True, nullable=False)
    type = Column(String(64), index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=True)
    payload = Column(Text, nullable=True)  # JSON 字符串 (压缩可在上层实现)
    shard = Column(Integer, default=0, nullable=False)

# 复合索引 (symbol, ts_ms)
Index("ix_event_log_symbol_ts", EventLog.symbol, EventLog.ts_ms)
