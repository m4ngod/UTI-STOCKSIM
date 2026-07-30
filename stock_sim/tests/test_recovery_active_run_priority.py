from stock_sim.core.const import EventType
from stock_sim.infra.event_bus import event_bus
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.event_persistence_service import disable_event_persistence, enable_event_persistence
from stock_sim.services.recovery_service import recovery_service
from stock_sim.services.run_context import RunContext
from stock_sim.services.simulation_run_service import SimulationRunService


def test_recovery_report_exposes_active_run_id_and_prioritizes_it():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    s = SessionLocal()
    try:
        runs = SimulationRunService(s)
        older = RunContext(run_id="RUN-OLD-001", run_type="simulation", scenario_name="old", sim_day=0)
        active = RunContext(run_id="RUN-ACTIVE-001", run_type="simulation", scenario_name="active", sim_day=0)
        runs.create_run(older)
        runs.mark_completed(older.run_id, sim_day=0)
        runs.create_run(active)
        runs.mark_running(active.run_id, sim_day=0)
        s.commit()
    finally:
        s.close()

    event_bus.publish(EventType.ACCOUNT_UPDATED, {"run_id": "RUN-OLD-001", "account_id": "OLD_ACC"})
    event_bus.publish(EventType.ACCOUNT_UPDATED, {"run_id": "RUN-ACTIVE-001", "account_id": "ACTIVE_ACC"})

    report = recovery_service.recover()

    assert report["checks"]["active_run_id"] == "RUN-ACTIVE-001"
    validation_keys = list(report["checks"]["replay_validation"].keys())
    assert validation_keys
    assert validation_keys[0] == "RUN-ACTIVE-001"

