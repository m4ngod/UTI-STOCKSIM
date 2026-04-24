import time

from stock_sim.persistence import models_init
from stock_sim.persistence.models_event_log import EventLog
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument


def test_snapshot_updated_event_persists_run_id_from_producer_contract():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    eng = MatchingEngine('AAA', inst)
    book = eng.get_book('AAA')
    book.instrument_meta['run_id'] = 'RUN-SNAPSHOT-EVT-001'

    eng._refresh_snapshot_book(book, levels=5)
    time.sleep(0.05)

    s = SessionLocal()
    try:
        row = (
            s.query(EventLog)
            .filter(EventLog.type == 'SnapshotUpdated', EventLog.run_id == 'RUN-SNAPSHOT-EVT-001')
            .order_by(EventLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.symbol == 'AAA'
        assert row.run_id == 'RUN-SNAPSHOT-EVT-001'
        assert row.sim_day is not None
        assert row.sim_dt is not None
    finally:
        s.close()


def test_snapshot_updated_event_persists_producer_ts_ms_when_present():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    ts_ms = 1704067204321
    event_bus_payload = {
        'symbol': 'BBB',
        'run_id': 'RUN-SNAPSHOT-EVT-TS-001',
        'ts_ms': ts_ms,
        'snapshot': {
            'symbol': 'BBB',
            'last': 20.0,
            'vol': 50,
            'turnover': 1000.0,
        },
    }

    from stock_sim.infra.event_bus import event_bus
    from stock_sim.core.const import EventType

    event_bus.publish(EventType.SNAPSHOT_UPDATED, event_bus_payload)
    time.sleep(0.05)

    s = SessionLocal()
    try:
        row = (
            s.query(EventLog)
            .filter(EventLog.type == 'SnapshotUpdated', EventLog.run_id == 'RUN-SNAPSHOT-EVT-TS-001')
            .order_by(EventLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.ts_ms == ts_ms
    finally:
        s.close()
