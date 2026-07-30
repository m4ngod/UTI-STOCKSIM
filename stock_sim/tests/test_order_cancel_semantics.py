from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.account_service import AccountService
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderStatus


def _prepare_runtime(symbol: str, *, initial_price: float = 10.0):
    engine_registry.remove(symbol)
    models_init.init_models()
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    inst_srv.create(
        symbol=symbol,
        name=symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=500_000,
        initial_price=initial_price,
        ipo_opened=True,
    )
    engine = MatchingEngine(
        symbol,
        create_instrument(
            symbol,
            tick_size=0.01,
            lot_size=100,
            min_qty=100,
            initial_price=initial_price,
            settlement_cycle=1,
        ),
    )
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)
    return s, osrv, acc_svc


def test_user_cancel_releases_buy_reservations_and_marks_order_canceled():
    s, osrv, _acc_svc = _prepare_runtime("CXL1")
    try:
        buyer = osrv.accounts.get_or_create("ACC_CXL_BUY", cash=100000.0)
        s.flush()
        cash_before = buyer.cash

        order = Order(
            symbol="CXL1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=200,
            account_id="ACC_CXL_BUY",
        )
        trades = osrv.place_order(order)
        assert trades == []
        assert order.status == OrderStatus.NEW

        ok = osrv.cancel(order.order_id)
        s.flush()
        s.refresh(buyer)

        assert ok is True
        assert order.status == OrderStatus.CANCELED
        assert buyer.frozen_cash == 0.0
        assert buyer.frozen_fee == 0.0
        assert buyer.cash == cash_before
    finally:
        s.close()
