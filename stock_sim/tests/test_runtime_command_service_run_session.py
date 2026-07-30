from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.runtime_command_service import RuntimeCommandService
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_runtime_command_service_uses_stable_clock_run_for_orders_and_completion():
    models_init.init_models()
    symbol = "RUNSVC1"
    account_id = "ACC-RUNSVC1"

    clk = ensure_sim_clock_started()
    if hasattr(clk, "stop_loop"):
        clk.stop_loop()
    if hasattr(clk, "set_day"):
        clk.set_day(0)
    if hasattr(clk, "configure"):
        clk.configure(run_id="")
    engine_registry.remove(symbol)

    svc = RuntimeCommandService()
    start_snap = svc.start_clock(sim_day=0, day_seconds=120.0, speed=1.0)
    run_id = str((start_snap or {}).get("run_id") or "").strip()

    assert run_id.startswith("RUN-DESKTOP-")

    svc.create_instrument(
        symbol=symbol,
        name="Run Session Test",
        price_step=0.01,
        initial_price=10.0,
        float_shares=1000,
        market_cap=10000.0,
        total_shares=1000,
    )
    svc.bootstrap_agent_account(account_id=account_id, initial_cash=100_000.0)
    result = svc.submit_order(
        symbol=symbol,
        side="buy",
        price=10.0,
        qty=1,
        account_id=account_id,
    )

    assert result["order_id"]

    session = SessionLocal()
    try:
        run_row = session.get(SimulationRun, run_id)
        assert run_row is not None
        assert run_row.status == "running"
        assert run_row.started_at is not None

        order_row = session.get(OrderORM, result["order_id"])
        assert order_row is not None
        assert order_row.run_id == run_id
    finally:
        session.close()

    stop_snap = svc.stop_clock()
    assert stop_snap.get("run_id") is None

    session = SessionLocal()
    try:
        run_row = session.get(SimulationRun, run_id)
        assert run_row is not None
        assert run_row.status == "completed"
        assert run_row.ended_at is not None
    finally:
        session.close()

