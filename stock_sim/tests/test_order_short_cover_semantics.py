from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService
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
    engine = MatchingEngine(symbol, create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=initial_price, settlement_cycle=1))
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)
    return s, osrv, acc_svc



def test_buy_trade_can_fully_cover_short_back_to_flat_without_flipping_long():
    s, osrv, acc_svc = _prepare_runtime("SHO1")
    try:
        seller = acc_svc.get_or_create("ACC_SHO_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "SHO1")
        seller_pos.quantity = 300
        seller_pos.avg_price = 10.0

        buyer = acc_svc.get_or_create("ACC_SHO_BUY", cash=100000.0)
        buyer_pos = acc_svc.get_position(buyer, "SHO1")
        buyer_pos.quantity = -300
        buyer_pos.borrowed_qty = 300
        buyer_pos.avg_price = 10.0
        s.flush()

        sell_order = Order(
            symbol="SHO1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=300,
            account_id="ACC_SHO_SELL",
        )
        osrv.place_order(sell_order)

        buy_order = Order(
            symbol="SHO1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=300,
            account_id="ACC_SHO_BUY",
        )
        trades = osrv.place_order(buy_order)
        s.flush()
        s.refresh(buyer_pos)

        assert len(trades) == 1
        assert buy_order.status == OrderStatus.FILLED
        assert buyer_pos.quantity == 0
        assert buyer_pos.borrowed_qty == 0
        assert buyer_pos.avg_price == 0.0
    finally:
        s.close()



def test_buy_trade_can_partially_cover_short_without_flipping_long():
    s, osrv, acc_svc = _prepare_runtime("SHC1")
    try:
        seller = acc_svc.get_or_create("ACC_SHC_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "SHC1")
        seller_pos.quantity = 100
        seller_pos.avg_price = 10.0

        buyer = acc_svc.get_or_create("ACC_SHC_BUY", cash=100000.0)
        buyer_pos = acc_svc.get_position(buyer, "SHC1")
        buyer_pos.quantity = -300
        buyer_pos.borrowed_qty = 300
        buyer_pos.avg_price = 10.0
        s.flush()

        sell_order = Order(
            symbol="SHC1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=100,
            account_id="ACC_SHC_SELL",
        )
        osrv.place_order(sell_order)

        buy_order = Order(
            symbol="SHC1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=100,
            account_id="ACC_SHC_BUY",
        )
        trades = osrv.place_order(buy_order)
        s.flush()
        s.refresh(buyer_pos)

        assert len(trades) == 1
        assert buy_order.status == OrderStatus.FILLED
        assert buyer_pos.quantity == -200
        assert buyer_pos.borrowed_qty == 200
        assert buyer_pos.avg_price == 10.0
    finally:
        s.close()
