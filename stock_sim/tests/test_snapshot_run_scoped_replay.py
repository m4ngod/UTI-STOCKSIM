import time

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.services.replay_service import replay_service
from stock_sim.services.snapshot_listener import SnapshotPersistenceListener
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType


def test_snapshot_rows_are_run_scoped_for_replay_validation():
    models_init.init_models()
    listener = SnapshotPersistenceListener()

    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'AAA',
        'run_id': 'RUN-SNAP-A',
        'sim_day': 1,
        'sim_dt': '0001-01-01T00:00:00',
        'snapshot': {
            'symbol': 'AAA',
            'last': 10.0,
            'vol': 100,
            'turnover': 1000.0,
            'bid1': 9.9,
            'ask1': 10.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })
    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'AAA',
        'run_id': 'RUN-SNAP-B',
        'sim_day': 2,
        'sim_dt': '0001-01-02T00:00:00',
        'snapshot': {
            'symbol': 'AAA',
            'last': 11.0,
            'vol': 200,
            'turnover': 2200.0,
            'bid1': 10.9,
            'ask1': 11.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })

    s = SessionLocal()
    try:
        assert s.query(Snapshot1s).filter(Snapshot1s.run_id == 'RUN-SNAP-A').count() >= 1
        assert s.query(Snapshot1s).filter(Snapshot1s.run_id == 'RUN-SNAP-B').count() >= 1
    finally:
        s.close()


def test_replay_snapshot_validation_uses_run_scoped_snapshot_rows():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)
    listener = SnapshotPersistenceListener()

    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'BBB',
        'run_id': 'RUN-VAL-A',
        'sim_day': 3,
        'sim_dt': '0001-01-03T00:00:00',
        'snapshot': {
            'symbol': 'BBB',
            'last': 20.0,
            'vol': 100,
            'turnover': 2000.0,
            'bid1': 19.9,
            'ask1': 20.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })
    event_bus.publish(EventType.SNAPSHOT_UPDATED, {
        'symbol': 'BBB',
        'run_id': 'RUN-VAL-A',
        'sim_day': 3,
        'sim_dt': '0001-01-03T00:00:00',
        'snapshot': {
            'symbol': 'BBB',
            'last': 20.0,
            'vol': 100,
            'turnover': 2000.0,
        },
    })

    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'BBB',
        'run_id': 'RUN-VAL-B',
        'sim_day': 4,
        'sim_dt': '0001-01-04T00:00:00',
        'snapshot': {
            'symbol': 'BBB',
            'last': 21.0,
            'vol': 100,
            'turnover': 2100.0,
            'bid1': 20.9,
            'ask1': 21.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })
    time.sleep(0.05)

    report = replay_service.validate_against_persisted_facts('RUN-VAL-A')
    s = SessionLocal()
    try:
        run_a_count = s.query(Snapshot1s).filter(Snapshot1s.run_id == 'RUN-VAL-A').count()
        total_count = s.query(Snapshot1s).count()
        assert run_a_count >= 1
        assert total_count >= run_a_count
        assert report['persisted']['snapshots'] == run_a_count
        assert total_count > run_a_count
    finally:
        s.close()
