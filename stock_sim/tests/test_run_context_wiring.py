from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_order_event import OrderEvent
from stock_sim.persistence.models_trade import TradeORM
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.persistence.models_account_equity_snapshot import AccountEquitySnapshot
from stock_sim.services.account_service import AccountService
from stock_sim.services.run_context import RunContext
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce
from stock_sim.services.order_service import OrderService
from stock_sim.core.instruments import create_instrument
from stock_sim.core.matching_engine import MatchingEngine


def test_account_service_writes_run_id_and_equity_snapshot():
    models_init.init_models()
    s = SessionLocal()
    ctx = RunContext(run_id="RUN-ACC-001", run_type="test")
    svc = AccountService(s, run_context=ctx)
    acc = svc.get_or_create("ACC_RUN_CTX", cash=100000.0)
    pos = svc.get_position(acc, "AAA")
    pos.quantity = 200
    pos.avg_price = 10.0
    s.flush()

    svc.write_equity_snapshot(acc)
    s.flush()

    snap = s.query(AccountEquitySnapshot).filter(AccountEquitySnapshot.account_id == "ACC_RUN_CTX").order_by(AccountEquitySnapshot.id.desc()).first()
    assert snap is not None
    assert snap.run_id == "RUN-ACC-001"
    assert snap.equity >= 100000.0
    s.close()


def test_order_service_writes_run_id_to_order_event_trade_and_ledger():
    models_init.init_models()
    s = SessionLocal()
    ctx = RunContext(run_id="RUN-ORD-001", run_type="test")
    inst = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    engine = MatchingEngine('AAA', inst)
    svc = OrderService(s, engine=engine, run_context=ctx)

    buyer = svc.accounts.get_or_create("BUYER_RUN", cash=100000.0)
    seller = svc.accounts.get_or_create("SELLER_RUN", cash=100000.0)
    seller_pos = svc.accounts.get_position(seller, "AAA")
    seller_pos.quantity = 100
    seller_pos.frozen_qty = 0
    seller_pos.avg_price = 9.5
    s.flush()

    sell_order = Order(symbol='AAA', side=OrderSide.SELL, order_type=OrderType.LIMIT, price=10.0, quantity=100, tif=TimeInForce.GFD, account_id='SELLER_RUN')
    buy_order = Order(symbol='AAA', side=OrderSide.BUY, order_type=OrderType.LIMIT, price=10.0, quantity=100, tif=TimeInForce.GFD, account_id='BUYER_RUN')

    svc.place_order(sell_order)
    svc.place_order(buy_order)
    s.commit()

    assert s.query(OrderORM).filter(OrderORM.run_id == "RUN-ORD-001").count() >= 2
    assert s.query(OrderEvent).filter(OrderEvent.run_id == "RUN-ORD-001").count() >= 2
    assert s.query(TradeORM).filter(TradeORM.run_id == "RUN-ORD-001").count() >= 1
    assert s.query(Ledger).filter(Ledger.run_id == "RUN-ORD-001").count() >= 2
    assert s.query(AccountEquitySnapshot).filter(AccountEquitySnapshot.run_id == "RUN-ORD-001").count() >= 1
    s.close()
