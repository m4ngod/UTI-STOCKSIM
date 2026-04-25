from stock_sim.services.sim_clock import ensure_sim_clock_started
from stock_sim.services.ipo_service import maybe_auto_open_ipo
from stock_sim.services.bar_aggregator import BarAggregator
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.const import EventType
from stock_sim.infra.event_bus import event_bus
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_bars import Bar1m
from datetime import datetime, timedelta


def test_sim_day_event_can_carry_run_id():
    clk = ensure_sim_clock_started()
    captured = []
    event_bus.subscribe(EventType.SIM_DAY, lambda t, p: captured.append(p), async_mode=False)
    clk.tick(run_id='RUN-SIMDAY-001')
    assert captured
    assert captured[-1]['run_id'] == 'RUN-SIMDAY-001'
    assert captured[-1]['sim_day'] is not None
    assert captured[-1]['sim_dt'] is not None


def test_ipo_opened_event_carries_run_id_from_instrument_meta():
    inst = create_instrument('IPO1', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    eng = MatchingEngine('IPO1', inst)
    book = eng.get_book('IPO1')
    book.instrument_meta['run_id'] = 'RUN-IPO-001'
    book.phase = eng.get_book('IPO1').phase
    eng._ipo_end_ts = 0
    eng._ipo_cleared = True
    eng._ipo_settle_end_ts = 0
    eng._ipo_auction_price = 10.0
    eng._ipo_trades_buffer = []

    captured = []
    event_bus.subscribe(EventType.IPO_OPENED, lambda t, p: captured.append(p), async_mode=False)
    opened = maybe_auto_open_ipo(eng, book)
    assert opened is True
    assert captured
    assert captured[-1]['run_id'] == 'RUN-IPO-001'


def test_bar_updated_event_carries_run_id_from_snapshot_rows():
    models_init.init_models()
    s = SessionLocal()
    try:
        minute_start = datetime.utcnow().replace(second=0, microsecond=0)
        snap1 = Snapshot1s(
            symbol='BAR1',
            run_id='RUN-BAR-001',
            ts=minute_start,
            last_price=10.0,
            bid1=9.9,
            ask1=10.1,
            bid1_qty=100,
            ask1_qty=120,
            volume=100,
            turnover=1000.0,
            sim_day=3,
        )
        snap2 = Snapshot1s(
            symbol='BAR1',
            run_id='RUN-BAR-001',
            ts=minute_start.replace(second=30),
            last_price=10.2,
            bid1=10.1,
            ask1=10.3,
            bid1_qty=100,
            ask1_qty=120,
            volume=150,
            turnover=1510.0,
            sim_day=3,
        )
        s.add(snap1)
        s.add(snap2)
        s.commit()
    finally:
        s.close()

    agg = BarAggregator()
    captured = []
    event_bus.subscribe(EventType.BAR_UPDATED, lambda t, p: captured.append(p), async_mode=False)
    agg._build_minute_bars(minute_start)
    assert captured
    assert captured[-1]['run_id'] == 'RUN-BAR-001'
    assert captured[-1]['symbol'] == 'BAR1'


def test_bar_aggregator_keeps_same_symbol_timestamp_separate_by_run():
    models_init.init_models()
    minute_start = datetime.utcnow().replace(second=0, microsecond=0)
    s = SessionLocal()
    try:
        for run_id, base_price in (('RUN-BAR-A', 10.0), ('RUN-BAR-B', 20.0)):
            s.add(
                Snapshot1s(
                    symbol='BARX',
                    run_id=run_id,
                    ts=minute_start,
                    last_price=base_price,
                    volume=100,
                    turnover=base_price * 100,
                    sim_day=4,
                )
            )
            s.add(
                Snapshot1s(
                    symbol='BARX',
                    run_id=run_id,
                    ts=minute_start.replace(second=30),
                    last_price=base_price + 0.5,
                    volume=150,
                    turnover=(base_price + 0.5) * 150,
                    sim_day=4,
                )
            )
        s.commit()
    finally:
        s.close()

    agg = BarAggregator()
    agg._build_minute_bars(minute_start)

    s = SessionLocal()
    try:
        rows = (
            s.query(Bar1m)
            .filter(Bar1m.symbol == 'BARX', Bar1m.ts == minute_start)
            .order_by(Bar1m.run_id.asc())
            .all()
        )
        assert [row.run_id for row in rows] == ['RUN-BAR-A', 'RUN-BAR-B']
        assert [row.close for row in rows] == [10.5, 20.5]
    finally:
        s.close()


def test_bar_aggregator_backfills_completed_snapshot_minutes():
    models_init.init_models()
    first_minute = (datetime.utcnow() - timedelta(minutes=6)).replace(second=0, microsecond=0)
    second_minute = first_minute + timedelta(minutes=1)
    run_id = 'RUN-BAR-BACKFILL-001'
    s = SessionLocal()
    try:
        for minute_start, first_price, second_price in (
            (first_minute, 10.0, 10.2),
            (second_minute, 10.2, 10.4),
        ):
            s.add(
                Snapshot1s(
                    symbol='BARBF',
                    run_id=run_id,
                    ts=minute_start,
                    last_price=first_price,
                    volume=100,
                    turnover=first_price * 100,
                    sim_day=5,
                )
            )
            s.add(
                Snapshot1s(
                    symbol='BARBF',
                    run_id=run_id,
                    ts=minute_start + timedelta(seconds=30),
                    last_price=second_price,
                    volume=150,
                    turnover=second_price * 150,
                    sim_day=5,
                )
            )
        s.commit()
    finally:
        s.close()

    agg = BarAggregator(backfill_lookback_minutes=30, max_backfill_minutes=10)
    agg._aggregate_pending_minutes()

    s = SessionLocal()
    try:
        rows = (
            s.query(Bar1m)
            .filter(Bar1m.symbol == 'BARBF', Bar1m.run_id == run_id)
            .order_by(Bar1m.ts.asc())
            .all()
        )
        assert [row.ts for row in rows] == [first_minute, second_minute]
        assert [row.close for row in rows] == [10.2, 10.4]
    finally:
        s.close()
