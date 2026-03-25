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



def test_ioc_partial_buy_fill_releases_remaining_cash_and_refunds_unfilled_fee_ratio():
    s, osrv, acc_svc = _prepare_runtime("IOP1")
    try:
        seller = acc_svc.get_or_create("ACC_IOP_SELL", cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "IOP1")
        seller_pos.quantity = 100
        seller_pos.avg_price = 10.0
        s.flush()

        resting_sell = Order(
            symbol="IOP1",
            side=OrderSide.SELL,
            price=10.0,
            quantity=100,
            account_id="ACC_IOP_SELL",
        )
        osrv.place_order(resting_sell)

        buyer = osrv.accounts.get_or_create("ACC_IOP_BUY", cash=100000.0)
        s.flush()
        cash_before = buyer.cash

        ioc_buy = Order(
            symbol="IOP1",
            side=OrderSide.BUY,
            price=10.0,
            quantity=200,
            tif=TimeInForce.IOC,
            account_id="ACC_IOP_BUY",
        )
        est_fee = osrv.fees.estimate_order(OrderSide.BUY, 10.0, 200).est_fee
        trades = osrv.place_order(ioc_buy)
        s.flush()
        s.refresh(buyer)

        actual_fee = osrv.fees.calc(OrderSide.BUY, 10.0, 100, is_taker=True).fee

        assert len(trades) == 1
        assert ioc_buy.status == OrderStatus.CANCELED
        assert ioc_buy.filled == 100
        assert ioc_buy.remaining == 100

        # IOC 剩余半单应释放全部未成交资金冻结
        assert buyer.frozen_cash == 0.0

        # 仅成交部分的费用应被保留，未成交部分预冻结手续费应退回
        assert buyer.frozen_fee == 0.0
        assert buyer.cash == cash_before - 1000.0 - actual_fee
        assert est_fee >= actual_fee
    finally:
        s.close()
