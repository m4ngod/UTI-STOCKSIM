"""
Compatibility transaction logger backed by the project ORM tables.

Historically this module wrote a private SQLite file (`trade_log.db`). Runtime
persistence is now PostgreSQL-first, so the compatibility surface writes through
`SessionLocal` into the authoritative trade/order-event tables instead.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .models_imports import SessionLocal
from .models_order_event import OrderEvent
from .models_trade import TradeORM


def _parse_ts(ts: str | None) -> datetime:
    if not ts:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


class TransactionLogger:
    """
    Backward-compatible logger for legacy callers.

    The `db_path` argument is accepted for API compatibility but ignored; the
    active SQLAlchemy database configuration decides the storage backend.
    """

    def __init__(self, db_path: str | Path | None = None, *, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

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
        session = self._session_factory()
        try:
            existing = session.get(TradeORM, trade_id)
            if existing is None:
                session.add(
                    TradeORM(
                        id=trade_id,
                        symbol=str(symbol or "").upper(),
                        price=float(price),
                        quantity=int(quantity),
                        buy_order_id=str(buy_order_id),
                        sell_order_id=str(sell_order_id),
                        buy_account_id="",
                        sell_account_id="",
                        ts=_parse_ts(ts),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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
        detail = {
            "symbol": str(symbol or "").upper(),
            "side": str(side or ""),
            "price": price,
            "quantity": quantity,
            "remaining": remaining,
        }
        compact_detail = ";".join(f"{k}={v}" for k, v in detail.items() if v is not None)
        session = self._session_factory()
        try:
            session.add(
                OrderEvent(
                    order_id=str(order_id),
                    event=str(action or "").upper(),
                    detail=f"change_id={change_id};{compact_detail}"[:128],
                    ts=_parse_ts(ts),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        return None


__all__ = ["TransactionLogger"]
