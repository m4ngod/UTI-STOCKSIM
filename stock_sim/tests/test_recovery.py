from stock_sim.services.recovery_service import recovery_service, is_readonly, mark_failed
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType, OrderStatus, OrderSide, OrderType, TimeInForce
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order import OrderORM
from stock_sim.core.order import Order
from stock_sim.services.order_service import OrderService
from stock_sim.services.run_context import RunContext
from stock_sim.core.instruments import create_instrument
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.event_persistence_service import enable_event_persistence, disable_event_persistence


def test_recovery_service_emits_resumed_event_and_report():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)
    event_bus.publish(EventType.ACCOUNT_UPDATED, {'run_id': 'RUN-REC-OK-001', 'i': 1})
    captured = []
    event_bus.subscribe(EventType.RECOVERY_RESUMED, lambda t, p: captured.append(p))
    rep = recovery_service.recover()
    assert rep['status'] in ('ok', 'degraded')
    if rep['status'] == 'ok':
        assert captured and captured[-1]['status'] == 'ok'
        assert 'replay_validation' in rep['checks']
        if rep['checks']['replay_validation']:
            first = next(iter(rep['checks']['replay_validation'].values()))
            assert 'summary' in first and 'validation' in first


def test_recovery_service_switches_readonly_on_mismatch():
    models_init.init_models()
    s = SessionLocal()
    ctx = RunContext(run_id="RUN-REC-001", run_type="simulation")
    inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    engine = MatchingEngine('AAA', inst)
    engine_registry.register('AAA', engine, overwrite=True)
    svc = OrderService(s, engine=engine, run_context=ctx)

    order = Order(symbol='AAA', side=OrderSide.BUY, order_type=OrderType.LIMIT, price=10.0, quantity=100, tif=TimeInForce.GFD, account_id='REC_ACC')
    svc._persist_order(order, "NEW", "")
    orm = s.get(OrderORM, order.order_id)
    orm.status = OrderStatus.FILLED
    s.commit()
    s.close()

    rep = recovery_service.recover()
    assert rep['status'] == 'degraded'
    assert rep['readonly'] is True
    assert is_readonly() is True
    assert 'RUN-REC-001' in rep['checks']['inconsistent_runs']


def test_mark_failed_sets_readonly():
    mark_failed("MANUAL_TEST_FAILURE")
    assert is_readonly() is True


def test_recovery_service_degrades_when_run_report_is_not_ok_even_without_trade_rows():
    models_init.init_models()
    disable_event_persistence()
    assert enable_event_persistence(force=True)

    run_id = "RUN-REC-REPORT-GAP-001"
    event_bus.publish(EventType.TRADE, {"run_id": run_id, "symbol": "AAA", "trade": {"symbol": "AAA", "price": 10.0, "quantity": 100}})

    rep = recovery_service.recover()

    assert rep["status"] == "degraded"
    assert rep["readonly"] is True
    assert run_id in rep["checks"]["inconsistent_runs"]
    assert "trade_event_trade_row_gap" in rep["checks"]["inconsistent_run_reasons"][run_id]
    assert "run_report_not_ok" in rep["checks"]["inconsistent_run_reasons"][run_id]


def test_recovery_service_exposes_order_event_gap_reason_from_run_report():
    models_init.init_models()

    s = SessionLocal()
    try:
        ctx = RunContext(run_id="RUN-REC-ORDER-GAP-001", run_type="simulation")
        inst = create_instrument('BBB', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
        engine = MatchingEngine('BBB', inst)
        engine_registry.register('BBB', engine, overwrite=True)
        svc = OrderService(s, engine=engine, run_context=ctx)
        order = Order(symbol='BBB', side=OrderSide.BUY, order_type=OrderType.LIMIT, price=10.0, quantity=100, tif=TimeInForce.GFD, account_id='REC_ACC_2')
        svc._persist_order(order, "NEW", "")
        s.commit()
    finally:
        s.close()

    rep = recovery_service.recover()

    assert rep["status"] == "degraded"
    assert "RUN-REC-ORDER-GAP-001" in rep["checks"]["inconsistent_runs"]
    assert "order_event_order_row_gap" in rep["checks"]["inconsistent_run_reasons"]["RUN-REC-ORDER-GAP-001"]
