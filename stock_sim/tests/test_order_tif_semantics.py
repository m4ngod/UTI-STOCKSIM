from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderStatus, TimeInForce



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
    engine = MatchingEngine(symbol, create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=initial_price, settlement_cycle=1))
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)
    return s, osrv, acc_svc



def test_ioc_unfilled_releases_buy_freeze_and_cancels_order():
    s, osrv, _acc_svc = _prepare_runtime("IOC1")

    buyer = osrv.accounts.get_or_create("ACC_IOC_BUY", cash=100000.0)
    s.flush()
    cash_before = buyer.cash

    order = Order(
        symbol="IOC1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        tif=TimeInForce.IOC,
        account_id="ACC_IOC_BUY",
    )
    trades = osrv.place_order(order)
    s.flush()
    s.refresh(buyer)

    assert trades == []
    assert order.status == OrderStatus.CANCELED
    assert buyer.frozen_cash == 0.0
    assert buyer.cash == cash_before
    assert buyer.frozen_fee == 0.0
    s.close()



def test_fok_unfillable_does_not_partially_fill_and_releases_buy_freeze():
    s, osrv, acc_svc = _prepare_runtime("FOK1")

    seller = acc_svc.get_or_create("ACC_FOK_SELL", cash=100000.0)
    seller_pos = acc_svc.get_position(seller, "FOK1")
    seller_pos.quantity = 100
    seller_pos.avg_price = 10.0
    s.flush()

    sell_order = Order(
        symbol="FOK1",
        side=OrderSide.SELL,
        price=10.0,
        quantity=100,
        account_id="ACC_FOK_SELL",
    )
    osrv.place_order(sell_order)

    buyer = osrv.accounts.get_or_create("ACC_FOK_BUY", cash=100000.0)
    s.flush()
    cash_before = buyer.cash

    fok_order = Order(
        symbol="FOK1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=200,
        tif=TimeInForce.FOK,
        account_id="ACC_FOK_BUY",
    )
    trades = osrv.place_order(fok_order)
    s.flush()
    s.refresh(buyer)

    assert trades == []
    assert fok_order.status == OrderStatus.CANCELED
    assert fok_order.filled == 0
    assert buyer.frozen_cash == 0.0
    assert buyer.frozen_fee == 0.0
    assert buyer.cash == cash_before
    s.close()
