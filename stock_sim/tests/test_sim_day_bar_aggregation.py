from __future__ import annotations

from datetime import datetime, timedelta
import uuid

from stock_sim.persistence import models_init
from stock_sim.persistence.models_bars import Bar1d, Bar1m
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.bar_aggregator import BarAggregator
from stock_sim.services.runtime_query_service import RuntimeQueryService
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_day_bars_are_built_from_internal_sim_day_not_wall_clock_date():
    models_init.init_models()
    symbol = f"DBAR{uuid.uuid4().hex[:6].upper()}"
    run_id = f"RUN-DBAR-{uuid.uuid4().hex[:8].upper()}"
    ts0 = datetime.utcnow().replace(second=0, microsecond=0)

    session = SessionLocal()
    try:
        session.add(
            Bar1m(
                symbol=symbol,
                run_id=run_id,
                ts=ts0,
                open=10.0,
                high=10.2,
                low=9.9,
                close=10.1,
                volume=100,
                turnover=1_000.0,
                sim_day=0,
            )
        )
        session.add(
            Bar1m(
                symbol=symbol,
                run_id=run_id,
                ts=ts0 + timedelta(minutes=1),
                open=10.1,
                high=10.4,
                low=10.0,
                close=10.3,
                volume=110,
                turnover=1_120.0,
                sim_day=0,
            )
        )
        session.add(
            Bar1m(
                symbol=symbol,
                run_id=run_id,
                ts=ts0 + timedelta(minutes=2),
                open=11.0,
                high=11.2,
                low=10.8,
                close=11.1,
                volume=90,
                turnover=1_010.0,
                sim_day=1,
            )
        )
        session.commit()
    finally:
        session.close()

    agg = BarAggregator()
    agg._build_day_bar_by_sim_day(0)
    agg._build_day_bar_by_sim_day(1)

    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id=run_id)
    try:
        rows = RuntimeQueryService().get_bars(symbol, "1d", limit=10)
        assert [row["ts"] for row in rows] == [0, 86_400_000]
        assert [round(float(row["close"]), 4) for row in rows] == [10.3, 11.1]
    finally:
        if hasattr(clk, "configure"):
            clk.configure(run_id="")

    session = SessionLocal()
    try:
        day_rows = (
            session.query(Bar1d)
            .filter(Bar1d.symbol == symbol, Bar1d.run_id == run_id)
            .order_by(Bar1d.sim_day.asc())
            .all()
        )
        assert [row.sim_day for row in day_rows] == [0, 1]
    finally:
        session.close()
