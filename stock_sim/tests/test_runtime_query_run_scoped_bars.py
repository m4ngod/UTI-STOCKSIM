from datetime import datetime, timedelta

from stock_sim.persistence import models_init
from stock_sim.persistence.models_bars import Bar1m
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.runtime_query_service import RuntimeQueryService
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_runtime_query_service_prefers_active_run_bars():
    models_init.init_models()
    symbol = "RUNBARX"
    run_a = "RUN-BAR-ACTIVE-001"
    run_b = "RUN-BAR-ACTIVE-002"
    ts0 = datetime.utcnow().replace(second=0, microsecond=0) - timedelta(minutes=2)

    s = SessionLocal()
    try:
        s.add(Bar1m(symbol=symbol, run_id=run_a, ts=ts0, open=10.0, high=10.2, low=9.9, close=10.1, volume=100, turnover=1000.0, sim_day=1))
        s.add(Bar1m(symbol=symbol, run_id=run_a, ts=ts0 + timedelta(minutes=1), open=10.1, high=10.3, low=10.0, close=10.2, volume=110, turnover=1110.0, sim_day=1))
        s.add(Bar1m(symbol=symbol, run_id=run_b, ts=ts0 + timedelta(minutes=5), open=20.0, high=20.2, low=19.9, close=20.1, volume=200, turnover=4000.0, sim_day=2))
        s.add(Bar1m(symbol=symbol, run_id=run_b, ts=ts0 + timedelta(minutes=6), open=20.1, high=20.3, low=20.0, close=20.2, volume=210, turnover=4242.0, sim_day=2))
        s.commit()
    finally:
        s.close()

    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id=run_a)

    rows = RuntimeQueryService().get_bars(symbol, "1m", limit=10)
    closes = [round(float(row["close"]), 4) for row in rows]

    assert closes == [10.1, 10.2]

    if hasattr(clk, "configure"):
        clk.configure(run_id="")

