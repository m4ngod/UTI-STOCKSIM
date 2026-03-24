import time

from stock_sim.persistence import models_init
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.services.replay_service import replay_service
from stock_sim.services.recovery_service import recovery_service
from stock_sim.services.snapshot_listener import SnapshotPersistenceListener


def test_replay_and_recovery_integration():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    run_id = "RUN-REPLAY-001"
    n = 8
    for i in range(n):
        event_bus.publish(EventType.ACCOUNT_UPDATED, {"i": i, "balance": 1000 + i, "run_id": run_id})
    time.sleep(0.05)

    loaded = replay_service.load_events(run_id=run_id)
    assert len(loaded) >= n
    first_payload_keys = set(loaded[0]["payload"].keys())
    assert "i" in first_payload_keys

    collected = []
    replay_count = replay_service.replay(
        lambda ev: collected.append(ev["payload"].get("i")) if "i" in ev["payload"] else None,
        run_id=run_id,
    )
    assert replay_count == len(loaded)
    assert collected[:n] == list(range(n))

    summary = replay_service.dry_run_summary(run_id=run_id)
    assert summary["mode"] == "dry-run"
    assert summary["event_count"] >= n
    assert summary["run_id"] == run_id
    assert EventType.ACCOUNT_UPDATED.value in summary["type_counts"]

    rep = recovery_service.recover()
    assert rep["status"] == "ok"
    assert summary["event_count"] >= rep["counts"]["event_log"] or rep["counts"]["event_log"] >= summary["event_count"]

    sim_loaded = replay_service.load_events(run_id=run_id, start_sim_day=1, end_sim_day=1)
    assert len(sim_loaded) >= n
    sim_summary = replay_service.dry_run_summary(run_id=run_id)
    assert sim_summary["run_id"] == run_id

    captured_recovery = []
    event_bus.subscribe(EventType.RECOVERY_RESUMED, lambda t, p: captured_recovery.append(p))
    rep = recovery_service.recover()
    assert rep["status"] == "ok"
    assert captured_recovery and captured_recovery[0]["status"] == "ok"

    collected.clear()
    replay_service.replay(
        lambda ev: collected.append(ev["payload"].get("i")) if "i" in ev["payload"] else None,
        run_id=run_id,
        limit=n,
    )
    assert collected == list(range(n))


def test_replay_validate_against_persisted_facts_for_trade_run():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    run_id = 'RUN-VERIFY-001'
    for i in range(2):
        event_bus.publish(EventType.ACCOUNT_UPDATED, {'i': i, 'run_id': run_id})
    event_bus.publish(EventType.TRADE, {'run_id': run_id, 'symbol': 'AAA', 'trade': {'symbol': 'AAA', 'price': 10.0, 'quantity': 100}})
    listener = SnapshotPersistenceListener()
    listener._on_snapshot('SnapshotUpdated', {
        'symbol': 'AAA',
        'sim_day': 1,
        'sim_dt': '0001-01-01T00:00:00',
        'snapshot': {
            'symbol': 'AAA',
            'last': 10.0,
            'vol': 100,
            'turnover': 1000.0,
            'bid1': 9.9,
            'ask1': 10.1,
            'bid1_qty': 100,
            'ask1_qty': 120,
        },
    })
    event_bus.publish(EventType.SNAPSHOT_UPDATED, {'run_id': run_id, 'symbol': 'AAA', 'sim_day': 1, 'sim_dt': '0001-01-01T00:00:00', 'snapshot': {'symbol': 'AAA', 'last': 10.0, 'vol': 100, 'turnover': 1000.0}})
    time.sleep(0.05)

    report = replay_service.validate_against_persisted_facts(run_id)
    assert report['run_id'] == run_id
    assert report['event_side']['trades'] >= 1
    assert 'trade_event_vs_trade_row_gap' in report['checks']
    assert 'snapshot_event_vs_snapshot_row_gap' in report['checks']
