from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account_equity_snapshot import AccountEquitySnapshot
from stock_sim.persistence.models_order_event import OrderEvent
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



def test_buy_fill_refunds_price_improvement_difference_to_cash():
    s, osrv, acc_svc = _prepare_runtime("BFR1")

    seller = acc_svc.get_or_create("ACC_BFR_SELL", cash=100000.0)
    seller_pos = acc_svc.get_position(seller, "BFR1")
    seller_pos.quantity = 100
    seller_pos.avg_price = 9.5
    s.flush()

    sell_order = Order(
        symbol="BFR1",
        side=OrderSide.SELL,
        price=9.5,
        quantity=100,
        account_id="ACC_BFR_SELL",
    )
    osrv.place_order(sell_order)

    buyer = osrv.accounts.get_or_create("ACC_BFR_BUY", cash=100000.0)
    s.flush()
    cash_before = buyer.cash

    buy_order = Order(
        symbol="BFR1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        account_id="ACC_BFR_BUY",
    )
    trades = osrv.place_order(buy_order)
    s.flush()
    s.refresh(buyer)

    assert len(trades) == 1
    assert buy_order.status == OrderStatus.FILLED
    assert trades[0].price == 9.5
    assert buyer.frozen_cash == 0.0
    assert buyer.frozen_fee == 0.0
    assert buyer.cash == cash_before - 950.0
    s.close()



def test_sell_order_freeze_does_not_reduce_position_before_trade():
    s, osrv, acc_svc = _prepare_runtime("SFR1")

    seller = acc_svc.get_or_create("ACC_SFR_SELL", cash=100000.0)
    seller_pos = acc_svc.get_position(seller, "SFR1")
    seller_pos.quantity = 300
    seller_pos.avg_price = 10.0
    s.flush()

    sell_order = Order(
        symbol="SFR1",
        side=OrderSide.SELL,
        price=10.5,
        quantity=200,
        account_id="ACC_SFR_SELL",
    )
    trades = osrv.place_order(sell_order)
    s.flush()
    s.refresh(seller_pos)

    assert trades == []
    assert sell_order.status == OrderStatus.NEW
    assert seller_pos.quantity == 300
    assert seller_pos.frozen_qty == 200
    assert seller_pos.borrowed_qty == 0
    s.close()


def test_multi_fill_batch_writes_one_snapshot_per_touched_account_and_one_final_buy_event():
    s, osrv, acc_svc = _prepare_runtime("BATCHF")
    seller_ids = [f"ACC_BATCHF_SELL_{idx}" for idx in range(3)]
    for seller_id in seller_ids:
        seller = acc_svc.get_or_create(seller_id, cash=100000.0)
        seller_pos = acc_svc.get_position(seller, "BATCHF")
        seller_pos.quantity = 100
        seller_pos.avg_price = 10.0
        s.flush()
        osrv.place_order(
            Order(
                symbol="BATCHF",
                side=OrderSide.SELL,
                price=10.0,
                quantity=100,
                account_id=seller_id,
            )
        )

    buyer = acc_svc.get_or_create("ACC_BATCHF_BUY", cash=100000.0)
    s.flush()
    buy_order = Order(
        symbol="BATCHF",
        side=OrderSide.BUY,
        price=10.0,
        quantity=300,
        account_id=buyer.id,
    )
    trades = osrv.place_order(buy_order)
    s.flush()

    account_ids = seller_ids + [buyer.id]
    snapshot_count = (
        s.query(AccountEquitySnapshot)
        .filter(AccountEquitySnapshot.account_id.in_(account_ids))
        .count()
    )
    buy_events = (
        s.query(OrderEvent)
        .filter(OrderEvent.order_id == buy_order.order_id)
        .order_by(OrderEvent.id.asc())
        .all()
    )

    assert len(trades) == 3
    assert buy_order.status == OrderStatus.FILLED
    assert snapshot_count == len(account_ids)
    assert [event.event for event in buy_events] == ["NEW", "FILL"]
    s.close()
