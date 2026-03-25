import time

from stock_sim.persistence import models_init
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.services.snapshot_listener import SnapshotPersistenceListener
from stock_sim.services.replay_service import replay_service
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType


def test_run_report_snapshot_validation_carries_symbol_and_sim_day_sets():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    run_id = 'RUN-SNAP-REPORT-001'
    listener = SnapshotPersistenceListener()

    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'CCC',
        'run_id': run_id,
        'sim_day': 5,
        'sim_dt': '0001-01-05T00:00:00',
        'snapshot': {
            'symbol': 'CCC',
            'last': 30.0,
            'vol': 100,
            'turnover': 3000.0,
            'bid1': 29.9,
            'ask1': 30.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })
    event_bus.publish(EventType.SNAPSHOT_UPDATED, {
        'symbol': 'CCC',
        'run_id': run_id,
        'sim_day': 5,
        'sim_dt': '0001-01-05T00:00:00',
        'snapshot': {
            'symbol': 'CCC',
            'last': 30.0,
            'vol': 100,
            'turnover': 3000.0,
        },
    })
    time.sleep(0.05)

    report = replay_service.build_run_report(run_id)
    validation = report['validation']

    assert validation['snapshot_symbols']['persisted'] == ['CCC']
    assert validation['snapshot_sim_days']['persisted'] == [5]
    assert 'snapshot_event_coverage_available' in validation
    if validation['snapshot_event_coverage_available']:
        assert validation['snapshot_symbols']['event_side'] == ['CCC']
        assert validation['snapshot_sim_days']['event_side'] == [5]
        assert validation['checks']['snapshot_symbol_set_match'] is True
        assert validation['checks']['snapshot_sim_day_set_match'] is True
    else:
        assert validation['checks']['snapshot_symbol_set_match'] is None
        assert validation['checks']['snapshot_sim_day_set_match'] is None
