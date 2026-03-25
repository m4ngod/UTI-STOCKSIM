from datetime import datetime

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_bars import Bar1m, Bar1h, Bar1d
from stock_sim.services.replay_service import replay_service


def test_run_report_carries_bar_family_persisted_facts():
    models_init.init_models()
    s = SessionLocal()
    run_id = 'RUN-BAR-REPORT-001'
    ts = datetime.utcnow().replace(second=0, microsecond=0)
    try:
        s.add(Bar1m(symbol='AAA', run_id=run_id, ts=ts, open=10.0, high=10.2, low=9.9, close=10.1, volume=100, turnover=1000.0, sim_day=6))
        s.add(Bar1h(symbol='AAA', run_id=run_id, ts=ts.replace(minute=0), open=10.0, high=10.5, low=9.8, close=10.3, volume=500, turnover=5000.0, sim_day=6))
        s.add(Bar1d(symbol='AAA', run_id=run_id, ts=ts.replace(hour=0, minute=0), open=9.8, high=10.6, low=9.7, close=10.4, volume=1000, turnover=10000.0, sim_day=6))
        s.commit()
    finally:
        s.close()

    report = replay_service.build_run_report(run_id)
    validation = report['validation']

    assert validation['persisted']['bars_1m'] == 1
    assert validation['persisted']['bars_1h'] == 1
    assert validation['persisted']['bars_1d'] == 1
    assert validation['bars']['1m']['symbols'] == ['AAA']
    assert validation['bars']['1h']['symbols'] == ['AAA']
    assert validation['bars']['1d']['symbols'] == ['AAA']
    assert validation['bars']['1m']['sim_days'] == [6]
    assert validation['bars']['1h']['sim_days'] == [6]
    assert validation['bars']['1d']['sim_days'] == [6]
