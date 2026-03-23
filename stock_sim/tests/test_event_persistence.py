import time

from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_event_log import EventLog
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence import models_init


def test_event_persistence_write_and_flush():
    models_init.init_models()
    disable_event_persistence()
    ok = enable_event_persistence(force=True)
    assert ok
    for i in range(5):
        event_bus.publish(EventType.ACCOUNT_UPDATED, {'i': i})
    time.sleep(0.1)
    s = SessionLocal()
    try:
        cnt = s.query(EventLog).count()
        assert cnt >= 5
    finally:
        s.close()


def test_event_log_carries_run_id_sim_day_and_trade_symbol():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    payload = {
        'run_id': 'RUN-EVT-001',
        'trade': {
            'symbol': 'AAA',
            'price': 10.0,
            'quantity': 100,
        }
    }
    event_bus.publish(EventType.TRADE, payload)
    time.sleep(0.1)

    s = SessionLocal()
    row = s.query(EventLog).filter(EventLog.type == EventType.TRADE.value).order_by(EventLog.id.desc()).first()
    assert row is not None
    assert row.run_id == "RUN-EVT-001"
    assert row.symbol == 'AAA'
    assert row.sim_day is not None
    assert row.sim_dt is not None
    s.close()


def test_event_log_carries_account_payload_run_id():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    payload = {
        'id': 'ACC-001',
        'cash': 1000.0,
        'frozen_cash': 0.0,
        'frozen_fee': 0.0,
        'positions': [],
        'run_id': 'RUN-ACC-EVT-001',
    }
    event_bus.publish(EventType.ACCOUNT_UPDATED, payload)
    time.sleep(0.1)

    s = SessionLocal()
    row = s.query(EventLog).filter(EventLog.type == EventType.ACCOUNT_UPDATED.value, EventLog.run_id == 'RUN-ACC-EVT-001').order_by(EventLog.id.desc()).first()
    assert row is not None
    assert row.run_id == 'RUN-ACC-EVT-001'
    s.close()
