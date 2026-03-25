from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.services.run_context import RunContext
from stock_sim.services.order_service import OrderService
from stock_sim.core.instruments import create_instrument
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce


def test_order_service_registers_simulation_run_when_run_context_present():
    models_init.init_models()
    s = SessionLocal()
    try:
        ctx = RunContext(run_id='RUN-AUTO-REG-001', run_type='simulation', scenario_name='auto-reg')
        inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
        engine = MatchingEngine('AAA', inst)
        engine_registry.register('AAA', engine, overwrite=True)
        svc = OrderService(s, engine=engine, run_context=ctx)

        order = Order(symbol='AAA', side=OrderSide.BUY, order_type=OrderType.LIMIT, price=10.0, quantity=100, tif=TimeInForce.GFD, account_id='ACC-AUTO-REG')
        svc.place_order(order)
        s.commit()

        row = s.get(SimulationRun, 'RUN-AUTO-REG-001')
        assert row is not None
        assert row.run_type == 'simulation'
        assert row.status == 'running'
        assert row.started_at is not None
    finally:
        s.close()
