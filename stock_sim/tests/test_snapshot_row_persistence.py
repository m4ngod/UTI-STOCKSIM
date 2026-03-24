from datetime import datetime

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.services.snapshot_listener import SnapshotPersistenceListener


def test_snapshot_listener_writes_snapshot_row_for_symbol():
    models_init.init_models()
    listener = SnapshotPersistenceListener()
    payload = {
        "symbol": "AAA",
        "sim_day": 9,
        "sim_dt": "0001-01-09T00:00:00",
        "snapshot": {
            "symbol": "AAA",
            "last": 10.0,
            "vol": 100,
            "turnover": 1000.0,
            "bid1": 9.9,
            "ask1": 10.1,
            "bid1_qty": 100,
            "ask1_qty": 120,
        },
    }

    listener._on_snapshot("SnapshotUpdated", payload)

    s = SessionLocal()
    try:
        row = s.query(Snapshot1s).filter(Snapshot1s.symbol == "AAA").order_by(Snapshot1s.id.desc()).first()
        assert row is not None
        assert row.symbol == "AAA"
        assert row.last_price == 10.0
        assert row.volume == 100
    finally:
        s.close()
