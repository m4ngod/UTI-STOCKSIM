# python
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

try:
    from stock_sim.core.const import OrderSide, OrderStatus, OrderType, TimeInForce  # type: ignore
    from stock_sim.persistence.db_config import build_database_config  # type: ignore
    from stock_sim.settings import settings  # type: ignore
except Exception:
    from core.const import OrderSide, OrderStatus, OrderType, TimeInForce  # type: ignore
    from persistence.db_config import build_database_config  # type: ignore
    from settings import settings  # type: ignore


_db_config = build_database_config(default_url=settings.assembled_db_url(), default_echo=settings.ECHO_SQL)
_db_url = _db_config.url

engine = create_engine(_db_url, **_db_config.engine_kwargs)

if _db_config.dialect == "sqlite":
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=30000"))
    except Exception:
        pass

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()


class SimTimeMixin:
    sim_day = Column(Integer, default=0, index=True)
    sim_dt = Column(DateTime, nullable=True, index=True)
