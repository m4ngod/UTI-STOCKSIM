from time import sleep
import time
import uuid

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService
from stock_sim.services.ipo_service import maybe_auto_open_ipo
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderStatus, Phase
from stock_sim.services.run_context import RunContext
from stock_sim.services.runtime_query_service import RuntimeQueryService
from stock_sim.services.sim_clock import ensure_sim_clock_started
from stock_sim.settings import settings


def test_same_day_buy_then_sell_is_blocked_for_t1_instrument():
    engine_registry.remove('T1X')
    models_init.init_models()
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    inst_srv.create(
        symbol='T1X',
        name='T1X',
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=500_000,
        initial_price=10.0,
        ipo_opened=True,
    )

    engine = MatchingEngine('T1X', create_instrument('T1X', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0, settlement_cycle=1))
    osrv = OrderService(s, engine, instrument_service=inst_srv)

    acc_svc = AccountService(s)
    acc = acc_svc.get_or_create('ACC_T1_RULE', cash=100000.0)
    pos = acc_svc.get_position(acc, 'T1X')
    pos.quantity = 100
    pos.avg_price = 10.0
    s.flush()
    osrv.risk.update_tplus(acc.id, 'T1X', OrderSide.BUY, 100)

    same_day_sell = Order(symbol='T1X', side=OrderSide.SELL, price=10.0, quantity=100, account_id='ACC_T1_RULE')
    trades = osrv.place_order(same_day_sell)

    assert trades == []
    assert same_day_sell.status == OrderStatus.REJECTED
    s.close()


def test_same_day_buy_then_sell_is_blocked_across_order_service_instances():
    symbol = f"T1P{uuid.uuid4().hex[:6].upper()}"
    run_id = f"RUN-T1-{uuid.uuid4().hex[:8].upper()}"
    engine_registry.remove(symbol)
    clk = ensure_sim_clock_started()
    if hasattr(clk, "set_day"):
        clk.set_day(0)
    if hasattr(clk, "configure"):
        clk.configure(run_id=run_id)

    models_init.init_models()
    s1 = SessionLocal()
    inst_srv1 = InstrumentService(s1)
    inst_srv1.create(
        symbol=symbol,
        name=symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=500_000,
        initial_price=10.0,
        ipo_opened=True,
    )
    engine = MatchingEngine(
        symbol,
        create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0, settlement_cycle=1),
    )
    run_context = RunContext(run_id=run_id, run_type="simulation", scenario_name="tplus1-persisted", sim_day=0)
    osrv1 = OrderService(s1, engine, instrument_service=inst_srv1, run_context=run_context)
    acc_svc1 = AccountService(s1)
    seller = acc_svc1.get_or_create(f"SELLER_{symbol}", cash=100000.0)
    seller_pos = acc_svc1.get_position(seller, symbol)
    seller_pos.quantity = 100
    seller_pos.avg_price = 10.0
    buyer_id = f"BUYER_{symbol}"
    acc_svc1.get_or_create(buyer_id, cash=100000.0)
    s1.flush()

    sell_liquidity = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=100, account_id=seller.id)
    osrv1.place_order(sell_liquidity)
    buy_order = Order(symbol=symbol, side=OrderSide.BUY, price=10.0, quantity=100, account_id=buyer_id)
    buy_trades = osrv1.place_order(buy_order)
    assert buy_trades
    s1.commit()
    s1.close()

    assert RuntimeQueryService().get_available_sell_qty(account_id=buyer_id, symbol=symbol) == 0

    s2 = SessionLocal()
    try:
        inst_srv2 = InstrumentService(s2)
        osrv2 = OrderService(s2, engine, instrument_service=inst_srv2, run_context=run_context)
        same_day_sell = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=100, account_id=buyer_id)
        trades = osrv2.place_order(same_day_sell)

        assert trades == []
        assert same_day_sell.status == OrderStatus.REJECTED
    finally:
        s2.close()
        if hasattr(clk, "configure"):
            clk.configure(run_id="")


def test_same_day_buy_then_sell_allowed_for_t0_instrument():
    engine_registry.remove('T0X')
    models_init.init_models()
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    inst_srv.create(
        symbol='T0X',
        name='T0X',
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=0,
        total_shares=1_000_000,
        free_float_shares=500_000,
        initial_price=10.0,
        ipo_opened=True,
    )

    engine = MatchingEngine('T0X', create_instrument('T0X', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0, settlement_cycle=0))
    osrv = OrderService(s, engine, instrument_service=inst_srv)

    acc_svc = AccountService(s)
    acc = acc_svc.get_or_create('ACC_T0_RULE', cash=100000.0)
    pos = acc_svc.get_position(acc, 'T0X')
    pos.quantity = 100
    pos.avg_price = 10.0
    s.flush()
    osrv.risk.update_tplus(acc.id, 'T0X', OrderSide.BUY, 100)

    same_day_sell = Order(symbol='T0X', side=OrderSide.SELL, price=10.0, quantity=100, account_id='ACC_T0_RULE')
    trades = osrv.place_order(same_day_sell)

    # T0 场景下不应被 T+1 规则拒绝；至于是否即时成交，取决于当时簿内是否有对手单。
    assert same_day_sell.status in (OrderStatus.NEW, OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELED)
    assert same_day_sell.status != OrderStatus.REJECTED
    assert isinstance(trades, list)
    s.close()


def test_same_day_sell_allowed_for_model_on_t1_instrument():
    symbol = f"T1M{uuid.uuid4().hex[:6].upper()}"
    model_account = f"MODEL_T1_{uuid.uuid4().hex[:6].upper()}"
    engine_registry.remove(symbol)
    models_init.init_models()
    s = SessionLocal()
    try:
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
            initial_price=10.0,
            ipo_opened=True,
        )

        engine = MatchingEngine(
            symbol,
            create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0, settlement_cycle=1),
        )
        osrv = OrderService(s, engine, instrument_service=inst_srv)
        acc_svc = AccountService(s)
        acc = acc_svc.get_or_create(model_account, cash=100000.0)
        pos = acc_svc.get_position(acc, symbol)
        pos.quantity = 100
        pos.avg_price = 10.0
        s.flush()
        osrv.risk.update_tplus(acc.id, symbol, OrderSide.BUY, 100)

        same_day_sell = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=100, account_id=model_account)
        trades = osrv.place_order(same_day_sell)

        assert same_day_sell.status != OrderStatus.REJECTED
        assert same_day_sell.status in (OrderStatus.NEW, OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELED)
        assert isinstance(trades, list)
    finally:
        s.close()


def test_ipo_open_then_same_day_sell_is_blocked_for_t1_instrument():
    ipo_symbol = f"IPO{uuid.uuid4().hex[:6].upper()}"
    engine_registry.remove(ipo_symbol)
    models_init.init_models()
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    settings.IPO_CALL_AUCTION_SECONDS = 0.05
    settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS = 0.01

    inst_srv.create(
        symbol=ipo_symbol,
        name=ipo_symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=300_000,
        initial_price=15.0,
        ipo_opened=False,
    )

    engine = MatchingEngine(ipo_symbol, create_instrument(ipo_symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=15.0))
    osrv = OrderService(s, engine, instrument_service=inst_srv)

    # 走 IPO 集合竞价 -> 开盘链路，至少确认冷启动状态已转入连续竞价，
    # 再基于“当日买入已发生”的状态注入来验证 T+1 拒卖。
    buy_ipo = Order(symbol=ipo_symbol, side=OrderSide.BUY, price=16.0, quantity=100_000, account_id='ACC_IPO_BUYER')
    sell_ipo = Order(symbol=ipo_symbol, side=OrderSide.SELL, price=15.0, quantity=100_000, account_id='ACC_ISSUER')
    osrv.place_order(buy_ipo)
    osrv.place_order(sell_ipo)

    ipo_book = engine.get_book(ipo_symbol)
    engine._ipo_end_ts = time.time() - 0.001
    maybe_auto_open_ipo(engine, ipo_book)
    assert ipo_book.phase is Phase.CALL_AUCTION and getattr(engine, '_ipo_cleared', False)
    sleep(settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS + 0.02)
    maybe_auto_open_ipo(engine, ipo_book)
    assert ipo_book.phase is Phase.CONTINUOUS

    buyer_acc = osrv.accounts.get_or_create('ACC_IPO_BUYER', cash=100000.0)
    buyer_pos = osrv.accounts.get_position(buyer_acc, ipo_symbol)
    buyer_pos.quantity = max(buyer_pos.quantity, 100)
    buyer_pos.avg_price = 15.0
    s.flush()
    osrv.risk.update_tplus('ACC_IPO_BUYER', ipo_symbol, OrderSide.BUY, 100)
    assert osrv.risk.get_tplus('ACC_IPO_BUYER', ipo_symbol, OrderSide.BUY) > 0

    same_day_sell = Order(symbol=ipo_symbol, side=OrderSide.SELL, price=15.0, quantity=100, account_id='ACC_IPO_BUYER')
    trades = osrv.place_order(same_day_sell)

    assert trades == []
    assert same_day_sell.status == OrderStatus.REJECTED
    s.close()
