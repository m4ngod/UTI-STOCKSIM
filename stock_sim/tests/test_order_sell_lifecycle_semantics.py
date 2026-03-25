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



def test_sell_partial_fill_keeps_only_remaining_quantity_frozen():
    s, osrv, acc_svc = _prepare_runtime("SPF1")
    try:
        seller = acc_svc.get_or_create("ACC_SPF_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "SPF1")
        seller_pos.quantity = 300
        seller_pos.avg_price = 10.0

        buyer = acc_svc.get_or_create("ACC_SPF_BUY", cash=100000.0)
        s.flush()

        sell_order = Order(
            symbol="SPF1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=300,
            account_id="ACC_SPF_SELL",
        )
        osrv.place_order(sell_order)
        s.flush()
        s.refresh(seller_pos)

        assert sell_order.status == OrderStatus.NEW
        assert seller_pos.quantity == 300
        assert seller_pos.frozen_qty == 300

        buy_order = Order(
            symbol="SPF1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=100,
            account_id="ACC_SPF_BUY",
        )
        trades = osrv.place_order(buy_order)
        s.flush()
        s.refresh(seller_pos)

        assert len(trades) == 1
        assert sell_order.status == OrderStatus.PARTIAL
        assert sell_order.filled == 100
        assert sell_order.remaining == 200
        assert seller_pos.quantity == 200
        assert seller_pos.frozen_qty == 200
        assert seller_pos.borrowed_qty == 0
    finally:
        s.close()



def test_ioc_partial_sell_fill_releases_unfilled_frozen_quantity():
    s, osrv, acc_svc = _prepare_runtime("SPI1")
    try:
        seller = acc_svc.get_or_create("ACC_SPI_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "SPI1")
        seller_pos.quantity = 300
        seller_pos.avg_price = 10.0

        buyer = acc_svc.get_or_create("ACC_SPI_BUY", cash=100000.0)
        s.flush()

        resting_sell = Order(
            symbol="SPI1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=300,
            account_id="ACC_SPI_SELL",
        )
        osrv.place_order(resting_sell)
        s.flush()
        s.refresh(seller_pos)
        assert seller_pos.frozen_qty == 300

        ioc_buy = Order(
            symbol="SPI1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=100,
            tif=TimeInForce.IOC,
            account_id="ACC_SPI_BUY",
        )
        trades = osrv.place_order(ioc_buy)
        s.flush()
        s.refresh(seller_pos)

        assert len(trades) == 1
        assert ioc_buy.status == OrderStatus.FILLED
        assert resting_sell.status == OrderStatus.PARTIAL
        assert resting_sell.filled == 100
        assert resting_sell.remaining == 200
        assert seller_pos.quantity == 200
        assert seller_pos.frozen_qty == 200
        assert seller_pos.borrowed_qty == 0
    finally:
        s.close()
