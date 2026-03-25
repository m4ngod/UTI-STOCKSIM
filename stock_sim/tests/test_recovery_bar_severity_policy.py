from datetime import datetime

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_bars import Bar1m
from stock_sim.services.recovery_service import recovery_service


def test_recovery_degrades_when_snapshots_exist_but_bars_1m_missing_for_run():
    models_init.init_models()
    s = SessionLocal()
    run_id = 'RUN-REC-BAR-SEVERE-001'
    try:
        s.add(Snapshot1s(symbol='AAA', run_id=run_id, ts=datetime.utcnow(), last_price=10.0, volume=100, turnover=1000.0, sim_day=7))
        s.commit()
    finally:
        s.close()

    rep = recovery_service.recover()
    assert rep['status'] == 'degraded'
    assert run_id in rep['checks']['inconsistent_runs']


def test_recovery_warns_when_bars_1m_exist_but_1h_or_1d_missing():
    models_init.init_models()
    s = SessionLocal()
    run_id = 'RUN-REC-BAR-WARN-001'
    ts = datetime.utcnow().replace(second=0, microsecond=0)
    try:
        s.add(Bar1m(symbol='AAA', run_id=run_id, ts=ts, open=10.0, high=10.1, low=9.9, close=10.0, volume=100, turnover=1000.0, sim_day=8))
        s.commit()
    finally:
        s.close()

    rep = recovery_service.recover()
    assert run_id in rep['checks']['warning_runs']
