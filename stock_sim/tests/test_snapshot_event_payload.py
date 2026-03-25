from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType


def test_matching_engine_snapshot_event_contains_symbol_and_sim_time():
    inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    eng = MatchingEngine('AAA', inst)
    book = eng.get_book('AAA')
    book.instrument_meta['run_id'] = 'RUN-SNAPSHOT-PRODUCER-001'

    captured = []
    def on_snapshot(topic, payload):
        captured.append(payload)

    event_bus.subscribe(EventType.SNAPSHOT_UPDATED, on_snapshot, async_mode=False)
    eng._refresh_snapshot_book(book, levels=5)

    assert captured
    payload = captured[-1]
    assert payload['symbol'] == 'AAA'
    assert payload['run_id'] == 'RUN-SNAPSHOT-PRODUCER-001'
    assert payload['snapshot']['symbol'] == 'AAA'
    assert 'sim_day' in payload
    assert 'sim_dt' in payload
