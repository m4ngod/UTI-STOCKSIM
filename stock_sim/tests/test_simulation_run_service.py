from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.services.run_context import RunContext
from stock_sim.services.simulation_run_service import SimulationRunService
from stock_sim.services.sim_clock import virtual_datetime


def test_simulation_run_service_creates_run_from_context():
    models_init.init_models()
    s = SessionLocal()
    try:
        ctx = RunContext(
            run_id='RUN-META-001',
            run_type='simulation',
            scenario_name='baseline-a',
            sim_day=3,
            sim_dt=virtual_datetime(3),
            config_version='cfg-v1',
            speed_profile='30x',
        )
        svc = SimulationRunService(s)
        row = svc.create_run(ctx)
        s.commit()

        loaded = s.get(SimulationRun, 'RUN-META-001')
        assert loaded is not None
        assert loaded.run_id == 'RUN-META-001'
        assert loaded.run_type == 'simulation'
        assert loaded.scenario_name == 'baseline-a'
        assert loaded.last_sim_day == 3
        assert loaded.speed_profile == '30x'
    finally:
        s.close()


def test_simulation_run_service_marks_running_and_completed():
    models_init.init_models()
    s = SessionLocal()
    try:
        ctx = RunContext(run_id='RUN-META-002', run_type='simulation', sim_day=1, sim_dt=virtual_datetime(1))
        svc = SimulationRunService(s)
        svc.create_run(ctx)
        svc.mark_running('RUN-META-002', sim_day=2, sim_dt=virtual_datetime(2))
        svc.mark_completed('RUN-META-002', sim_day=4, sim_dt=virtual_datetime(4))
        s.commit()

        loaded = s.get(SimulationRun, 'RUN-META-002')
        assert loaded is not None
        assert loaded.status == 'completed'
        assert loaded.sim_start_day == 1
        assert loaded.last_sim_day == 4
        assert loaded.sim_end_day == 4
        assert loaded.started_at is not None
        assert loaded.ended_at is not None
    finally:
        s.close()
