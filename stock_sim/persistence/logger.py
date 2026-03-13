"""
事务日志模块
author: you
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS trade_log (
    trade_id     TEXT PRIMARY KEY,
    symbol       TEXT NOT NULL,
    price        REAL NOT NULL,
    quantity     INTEGER NOT NULL,
    buy_order_id TEXT NOT NULL,
    sell_order_id TEXT NOT NULL,
    ts           TEXT NOT NULL          -- ISO8601
);

CREATE TABLE IF NOT EXISTS order_change_log (
    change_id    TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,
    action       TEXT NOT NULL,         -- NEW / FILL / CANCEL / MODIFY
    price        REAL,
    quantity     INTEGER,
    remaining    INTEGER,
    ts           TEXT NOT NULL
);
"""

class TransactionLogger:
    """
    线程安全、支持 WAL 的简易 SQLite 日志器。
    """
    def __init__(self, db_path: str | Path = "trade_log.db") -> None:
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,       # autocommit
        )
        self._lock = threading.Lock()
        self._initialize_schema()

    # ------------------------- PUBLIC API -------------------------
    def log_trade(
        self,
        *,
        trade_id: str,
        symbol: str,
        price: float,
        quantity: int,
        buy_order_id: str,
        sell_order_id: str,
        ts: Optional[str] = None,
    ) -> None:
        ts = ts or datetime.utcnow().isoformat(timespec="milliseconds")
        sql = """INSERT INTO trade_log
                 (trade_id, symbol, price, quantity,
                  buy_order_id, sell_order_id, ts)
                 VALUES (?,?,?,?,?,?,?);"""
        self._execute(sql, (trade_id, symbol, price, quantity,
                            buy_order_id, sell_order_id, ts))

    def log_order_change(
        self,
        *,
        change_id: str,
        order_id: str,
        symbol: str,
        side: str,
        action: str,
        price: float | None,
        quantity: int | None,
        remaining: int | None,
        ts: Optional[str] = None,
    ) -> None:
        ts = ts or datetime.utcnow().isoformat(timespec="milliseconds")
        sql = """INSERT INTO order_change_log
                 (change_id, order_id, symbol, side, action,
                  price, quantity, remaining, ts)
                 VALUES (?,?,?,?,?,?,?,?,?);"""
        self._execute(sql, (change_id, order_id, symbol, side, action,
                            price, quantity, remaining, ts))

    # ----------------------- INTERNAL METHODS ---------------------
    def _initialize_schema(self) -> None:
        with self._lock, self._conn as cur:
            cur.executescript(DB_SCHEMA)

    def _execute(self, sql: str, params: tuple) -> None:
        with self._lock, self._conn as cur:
            cur.execute(sql, params)

    # -------------------------- CLEANUP ---------------------------
    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:   # pragma: no cover
            pass
