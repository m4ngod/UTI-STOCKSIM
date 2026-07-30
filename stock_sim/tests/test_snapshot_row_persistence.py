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
        "run_id": "RUN-SNAP-ROW-001",
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
        assert row.run_id == "RUN-SNAP-ROW-001"
        assert row.last_price == 10.0
        assert row.volume == 100
    finally:
        s.close()


def test_snapshot_listener_uses_payload_ts_ms_for_snapshot_row_second():
    models_init.init_models()
    listener = SnapshotPersistenceListener()
    payload = {
        "symbol": "BBB",
        "run_id": "RUN-SNAP-ROW-TS-001",
        "ts_ms": 1704067204321,
        "snapshot": {
            "symbol": "BBB",
            "last": 12.0,
            "vol": 10,
            "turnover": 120.0,
            "bid1": 11.9,
            "ask1": 12.1,
            "bid1_qty": 10,
            "ask1_qty": 12,
        },
    }

    listener._on_snapshot("SnapshotUpdated", payload)

    s = SessionLocal()
    try:
        row = (
            s.query(Snapshot1s)
            .filter(Snapshot1s.symbol == "BBB", Snapshot1s.run_id == "RUN-SNAP-ROW-TS-001")
            .order_by(Snapshot1s.id.desc())
            .first()
        )
        assert row is not None
        assert row.ts == datetime(2024, 1, 1, 0, 0, 4)
    finally:
        s.close()
