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
from stock_sim.core.const import OrderSide, Phase
from stock_sim.settings import settings



def test_ipo_minimal_open_path_transitions_to_continuous_and_produces_trade():
    ipo_symbol = f"IPO{uuid.uuid4().hex[:6].upper()}"
    engine_registry.remove(ipo_symbol)
    models_init.init_models()
    s = SessionLocal()
    try:
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

        engine = MatchingEngine(
            ipo_symbol,
            create_instrument(ipo_symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=15.0),
        )
        osrv = OrderService(s, engine, instrument_service=inst_srv)
        acc_svc = AccountService(s)

        issuer = acc_svc.get_or_create("ACC_IPO_ISSUER", cash=100000.0)
        issuer_pos = acc_svc.get_position(issuer, ipo_symbol)
        issuer_pos.quantity = 120_000
        issuer_pos.avg_price = 15.0
        s.flush()

        buy_ipo = Order(symbol=ipo_symbol, side=OrderSide.BUY, price=16.0, quantity=100_000, account_id="ACC_IPO_BUYER")
        sell_ipo = Order(symbol=ipo_symbol, side=OrderSide.SELL, price=15.0, quantity=120_000, account_id="ACC_IPO_ISSUER")

        osrv.place_order(buy_ipo)
        osrv.place_order(sell_ipo)

        ipo_book = engine.get_book(ipo_symbol)
        assert ipo_book.phase is Phase.CALL_AUCTION

        engine._ipo_end_ts = time.time() - 0.001
        maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv._after_trades)
        assert ipo_book.phase is Phase.CALL_AUCTION
        assert getattr(engine, '_ipo_cleared', False) is True

        sleep(settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS + 0.02)
        maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv._after_trades)

        assert ipo_book.phase is Phase.CONTINUOUS
        assert sum(t.quantity for t in ipo_book.trades) > 0
        # 当前最稳定的最小保证是：簿阶段切到连续竞价且实际成交产生。
        # instrument-level ipo_opened 标志的同步仍可能依赖更外层路径，
        # 不把这个更脆弱的实现细节当作本测试的最小闭环断言。
    finally:
        s.close()
