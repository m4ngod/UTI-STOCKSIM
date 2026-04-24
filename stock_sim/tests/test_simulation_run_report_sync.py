from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.services.run_context import RunContext
from stock_sim.services.simulation_run_service import SimulationRunService
from stock_sim.services.recovery_service import recovery_service
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence


def test_recovery_syncs_simulation_run_from_run_report():
    models_init.init_models()
    s = SessionLocal()
    try:
        ctx = RunContext(run_id='RUN-SYNC-001', run_type='simulation', scenario_name='sync-check')
        svc = SimulationRunService(s)
        svc.create_run(ctx)
        s.commit()
    finally:
        s.close()

    disable_event_persistence()
    assert enable_event_persistence(force=True)
    event_bus.publish(EventType.ACCOUNT_UPDATED, {'run_id': 'RUN-SYNC-001', 'sim_day': 9, 'sim_dt': '0001-01-09T00:00:00', 'i': 1})

    rep = recovery_service.recover()
    assert rep['status'] in ('ok', 'degraded')

    s = SessionLocal()
    try:
        row = s.get(SimulationRun, 'RUN-SYNC-001')
        assert row is not None
        assert row.event_count >= 1
        assert row.last_sim_day == 9
        assert row.last_sim_dt is not None
        assert row.status in ('running', 'completed', 'recovered', 'created', 'degraded', 'failed') or row.status is not None
    finally:
        s.close()
