# python
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Enum as SAEnum, ForeignKey, Index, BigInteger, text  # 新增 text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
try:
    from stock_sim.core.const import OrderSide, OrderType, OrderStatus, TimeInForce  # type: ignore
    from stock_sim.settings import settings  # type: ignore
except Exception:  # 回退本地
    from core.const import OrderSide, OrderType, OrderStatus, TimeInForce  # type: ignore
    from settings import settings  # type: ignore

_db_url = settings.assembled_db_url()
if _db_url.startswith('sqlite'):  # 回退测试场景
    engine = create_engine(
        _db_url,
        echo=settings.ECHO_SQL,
        future=True,
        connect_args={
            "check_same_thread": False,
            "timeout": 30  # 增大 busy timeout
        }
    )
    # 设置 WAL 模式与较宽松同步，减少写锁 (测试环境)
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=30000"))  # 30s
    except Exception:
        pass
else:
    engine = create_engine(
        _db_url,
        echo=settings.ECHO_SQL,
        pool_pre_ping=True,
        future=True
    )
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

# 新增: 模拟时钟字段 Mixin (sim_day: 第几个模拟日; sim_dt: 虚拟日期时间)
class SimTimeMixin:
    sim_day = Column(Integer, default=0, index=True)
    sim_dt = Column(DateTime, nullable=True, index=True)
