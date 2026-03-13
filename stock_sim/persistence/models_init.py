# python
from .models_imports import Base, engine
from .models_account import Account
from .models_position import Position
from .models_ledger import Ledger
from .models_order import OrderORM
from .models_trade import TradeORM
from .models_order_event import OrderEvent
from .models_snapshot import Snapshot1s
from .models_instrument import Instrument  # 新增
from .models_bars import Bar1m, Bar1h, Bar1d  # 新增
from .models_agent_binding import AgentBinding  # 新增: 代理/散户绑定表
from .models_feature_buffer import FeatureBuffer  # 新增: 模型特征缓冲表
from .models_event_log import EventLog  # 新增: 事件日志表
from sqlalchemy import inspect, text
from stock_sim.persistence.models_imports import engine

# 新增: 确保 sqlite 下 event_log 表存在 (若 metadata 未创建前调用)
def _ensure_event_log_sqlite():
    try:
        if engine.dialect.name != 'sqlite':
            return
        from sqlalchemy import inspect
        insp = inspect(engine)
        if 'event_log' in insp.get_table_names():
            return
        # 若不存在则显式创建 (与 Base.metadata.create_all 不冲突)
        try:
            EventLog.__table__.create(engine)
        except Exception:
            pass
    except Exception:
        pass

def _ensure_snapshot_columns():
    """执行B: 自动迁移 snapshots_1s 缺失列 (开发期简单 ALTER, 生产建议 Alembic)。"""
    required = {
        'prev_close': 'DOUBLE NULL',
        'change_pct': 'DOUBLE NULL',
        'change_speed': 'DOUBLE NULL',
        'volume_delta': 'INT NULL',
        'turnover_delta': 'DOUBLE NULL',
        'turnover_rate': 'DOUBLE NULL',
        'spread': 'DOUBLE NULL',
        'imbalance': 'DOUBLE NULL',
        'trade_count_sec': 'INT NULL',
        'vwap': 'DOUBLE NULL'
    }
    insp = inspect(engine)
    if 'snapshots_1s' not in insp.get_table_names():
        return
    try:
        cols = {c['name'] for c in insp.get_columns('snapshots_1s')}
        missing = [k for k in required if k not in cols]
        if not missing:
            return
        ddl_parts = []
        for col in missing:
            ddl_parts.append(f"ADD COLUMN {col} {required[col]}")
        if ddl_parts:
            ddl = f"ALTER TABLE snapshots_1s {', '.join(ddl_parts)}"  # MySQL
            with engine.begin() as conn:
                conn.execute(text(ddl))
    except Exception:
        # 忽略以免阻断启动
        pass

def _ensure_sim_time_columns():
    tables = [
        'accounts','positions','orders','trades','ledgers','agent_bindings',
        'snapshots_1s','bars_1m','bars_1h','bars_1d','instruments'
    ]
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    for t in tables:
        if t not in existing:
            continue
        try:
            cols = {c['name'] for c in insp.get_columns(t)}
            ddl_parts = []
            if 'sim_day' not in cols:
                ddl_parts.append('ADD COLUMN sim_day INT NULL')
            if 'sim_dt' not in cols:
                ddl_parts.append('ADD COLUMN sim_dt DATETIME NULL')
            if ddl_parts:
                ddl = f"ALTER TABLE {t} {', '.join(ddl_parts)}"
                with engine.begin() as conn:
                    conn.execute(text(ddl))
        except Exception:
            pass

def init_models():
    try:
        if engine.dialect.name == 'sqlite':
            # 彻底清理旧表 (可能含有历史 UNIQUE 约束)
            with engine.begin() as conn:
                conn.exec_driver_sql('DROP TABLE IF EXISTS positions')
            Base.metadata.drop_all(engine)
    except Exception:
        pass
    _ensure_event_log_sqlite()
    Base.metadata.create_all(engine)
    _ensure_snapshot_columns()
    _ensure_sim_time_columns()
    # 调试：打印 positions 索引
    try:
        if engine.dialect.name == 'sqlite':
            from sqlalchemy import inspect
            insp = inspect(engine)
            if 'positions' in insp.get_table_names():
                idx = insp.get_indexes('positions')
                print('[init_models][debug] positions indexes:', idx)
    except Exception:
        pass
