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
