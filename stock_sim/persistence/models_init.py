from __future__ import annotations

from threading import RLock

from sqlalchemy import inspect, text

from .models_account import Account
from .models_account_equity_snapshot import AccountEquitySnapshot
from .models_agent_binding import AgentBinding
from .models_bars import Bar1d, Bar1h, Bar1m
from .models_event_log import EventLog
from .models_feature_buffer import FeatureBuffer
from .models_imports import Base, engine
from .models_instrument import Instrument
from .models_ledger import Ledger
from .models_order import OrderORM
from .models_order_event import OrderEvent
from .models_position import Position
from .models_simulation_run import SimulationRun
from .models_snapshot import Snapshot1s
from .models_trade import TradeORM

_SCHEMA_LOCK = RLock()

_RUNTIME_RUN_TABLES = {
    "orders",
    "trades",
    "ledgers",
    "order_events",
    "agent_bindings",
    "account_equity_snapshots",
    "event_log",
    "snapshots_1s",
    "bars_1m",
    "bars_1h",
    "bars_1d",
}


def _dialect_name() -> str:
    return str(getattr(engine.dialect, "name", "") or "unknown").lower()


def _type_sql(kind: str) -> str:
    dialect = _dialect_name()
    if kind == "int":
        return "INTEGER" if dialect in {"sqlite", "postgresql"} else "INT"
    if kind == "bigint":
        return "BIGINT"
    if kind == "float":
        return "DOUBLE PRECISION" if dialect == "postgresql" else "DOUBLE"
    if kind == "datetime":
        return "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    if kind.startswith("varchar"):
        size = kind.split(":", 1)[1] if ":" in kind else "64"
        return f"VARCHAR({size})"
    return kind


def _execute_ddl(sql: str) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception:
        pass


def _ensure_columns(table: str, required: dict[str, str]) -> None:
    try:
        insp = inspect(engine)
        if table not in set(insp.get_table_names()):
            return
        cols = {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return
    for column, kind in required.items():
        if column in cols:
            continue
        _execute_ddl(f"ALTER TABLE {table} ADD COLUMN {column} {_type_sql(kind)} NULL")


def _ensure_index(table: str, name: str, columns: tuple[str, ...]) -> None:
    try:
        insp = inspect(engine)
        if table not in set(insp.get_table_names()):
            return
        existing_indexes = {idx.get("name") for idx in insp.get_indexes(table)}
        if name in existing_indexes:
            return
        existing_columns = {c["name"] for c in insp.get_columns(table)}
        if not set(columns).issubset(existing_columns):
            return
    except Exception:
        return
    cols_sql = ", ".join(columns)
    _execute_ddl(f"CREATE INDEX {name} ON {table} ({cols_sql})")


def _ensure_event_log_table():
    try:
        insp = inspect(engine)
        if "event_log" in insp.get_table_names():
            return
        EventLog.__table__.create(engine)
    except Exception:
        pass


def _ensure_snapshot_columns():
    _ensure_columns(
        "snapshots_1s",
        {
            "prev_close": "float",
            "change_pct": "float",
            "change_speed": "float",
            "volume_delta": "int",
            "turnover_delta": "float",
            "turnover_rate": "float",
            "spread": "float",
            "imbalance": "float",
            "trade_count_sec": "int",
            "vwap": "float",
        },
    )


def _ensure_sim_time_columns():
    tables = [
        "accounts",
        "positions",
        "orders",
        "trades",
        "ledgers",
        "order_events",
        "agent_bindings",
        "snapshots_1s",
        "bars_1m",
        "bars_1h",
        "bars_1d",
        "instruments",
        "account_equity_snapshots",
        "event_log",
    ]
    for table in tables:
        required = {
            "sim_day": "int",
            "sim_dt": "datetime",
        }
        if table in _RUNTIME_RUN_TABLES:
            required["run_id"] = "varchar:64"
        _ensure_columns(table, required)


def _ensure_run_indexes():
    for table, name, columns in [
        ("orders", "ix_orders_run_symbol_created", ("run_id", "symbol", "ts_created")),
        ("orders", "ix_orders_run_account_status", ("run_id", "account_id", "status")),
        ("trades", "ix_trades_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("trades", "ix_trades_run_buy_account", ("run_id", "buy_account_id")),
        ("trades", "ix_trades_run_sell_account", ("run_id", "sell_account_id")),
        ("ledgers", "ix_ledgers_run_account_ts", ("run_id", "account_id", "ts")),
        ("ledgers", "ix_ledgers_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("order_events", "ix_order_events_run_order_ts", ("run_id", "order_id", "ts")),
        ("event_log", "ix_event_log_run_ts", ("run_id", "ts_ms")),
        ("snapshots_1s", "ix_snapshots_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("bars_1m", "ix_bars1m_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("bars_1h", "ix_bars1h_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("bars_1d", "ix_bars1d_run_symbol_ts", ("run_id", "symbol", "ts")),
        ("agent_bindings", "ix_agent_bindings_run_agent", ("run_id", "agent_name")),
        ("account_equity_snapshots", "ix_equity_run_account_day", ("run_id", "account_id", "sim_day")),
    ]:
        _ensure_index(table, name, columns)


def ensure_models():
    with _SCHEMA_LOCK:
        _ensure_models_locked()


def _ensure_models_locked():
    _ensure_event_log_table()
    Base.metadata.create_all(engine)
    _ensure_snapshot_columns()
    _ensure_sim_time_columns()
    _ensure_run_indexes()


def init_models():
    with _SCHEMA_LOCK:
        _init_models_locked()


def _init_models_locked():
    try:
        if _dialect_name() == "sqlite":
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP TABLE IF EXISTS positions")
            Base.metadata.drop_all(engine)
    except Exception:
        pass
    _ensure_models_locked()


__all__ = ["ensure_models", "init_models"]
