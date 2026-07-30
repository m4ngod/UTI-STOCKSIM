from __future__ import annotations

from stock_sim.persistence import models_init
from stock_sim.persistence.logger import TransactionLogger
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order_event import OrderEvent
from stock_sim.persistence.models_trade import TradeORM


def test_transaction_logger_writes_trade_to_authoritative_table():
    models_init.init_models()
    logger = TransactionLogger()

    logger.log_trade(
        trade_id="T-LOGGER-001",
        symbol="aaa",
        price=10.5,
        quantity=100,
        buy_order_id="B-1",
        sell_order_id="S-1",
        ts="2026-04-25T10:00:00",
    )

    session = SessionLocal()
    try:
        row = session.get(TradeORM, "T-LOGGER-001")
        assert row is not None
        assert row.symbol == "AAA"
        assert row.price == 10.5
        assert row.quantity == 100
    finally:
        session.close()


def test_transaction_logger_writes_order_change_to_order_events():
    models_init.init_models()
    logger = TransactionLogger()

    logger.log_order_change(
        change_id="C-LOGGER-001",
        order_id="O-1",
        symbol="bbb",
        side="BUY",
        action="NEW",
        price=9.9,
        quantity=200,
        remaining=200,
        ts="2026-04-25T10:00:01",
    )

    session = SessionLocal()
    try:
        row = session.query(OrderEvent).filter(OrderEvent.order_id == "O-1").one()
        assert row.event == "NEW"
        assert "change_id=C-LOGGER-001" in row.detail
        assert "symbol=BBB" in row.detail
    finally:
        session.close()
