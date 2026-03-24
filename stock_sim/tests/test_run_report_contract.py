from stock_sim.persistence import models_init
from stock_sim.services.replay_service import replay_service
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
import time


def test_run_report_contains_summary_validation_and_ok():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    run_id = 'RUN-REPORT-001'
    event_bus.publish(EventType.ACCOUNT_UPDATED, {'run_id': run_id, 'i': 1})
    time.sleep(0.05)

    report = replay_service.build_run_report(run_id)
    assert report['run_id'] == run_id
    assert 'summary' in report
    assert 'validation' in report
    assert 'ok' in report
    assert report['summary']['run_id'] == run_id
