from __future__ import annotations

import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

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
from stock_sim.core.const import OrderSide
from stock_sim.settings import settings
from app.services.account_service import AccountService as AppAccountService
from app.controllers.account_controller import AccountController
from app.panels.account.panel import AccountPanel

symbol = f"VIS{uuid.uuid4().hex[:6].upper()}"
buyer_id = f"ACC_BUY_{uuid.uuid4().hex[:6].upper()}"
seller_id = f"ACC_SELL_{uuid.uuid4().hex[:6].upper()}"

engine_registry.remove(symbol)
models_init.init_models()
s = SessionLocal()
try:
    settings.IPO_CALL_AUCTION_SECONDS = 0.01
    settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS = 0.0

    inst_srv = InstrumentService(s)
    inst_srv.create(
        symbol=symbol,
        name=symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=300_000,
        initial_price=15.0,
        ipo_opened=False,
    )

    engine = MatchingEngine(symbol, create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=15.0))
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)

    buyer = acc_svc.get_or_create(buyer_id, cash=2_000_000.0)
    seller = acc_svc.get_or_create(seller_id, cash=100_000.0)
    seller_pos = acc_svc.get_position(seller, symbol)
    seller_pos.quantity = 120_000
    seller_pos.avg_price = 15.0
    s.flush()

    buy_ipo = Order(symbol=symbol, side=OrderSide.BUY, price=16.0, quantity=100_000, account_id=buyer_id)
    sell_ipo = Order(symbol=symbol, side=OrderSide.SELL, price=15.0, quantity=120_000, account_id=seller_id)
    osrv.place_order(buy_ipo)
    osrv.place_order(sell_ipo)

    ipo_book = engine.get_book(symbol)
    engine._ipo_end_ts = time.time() - 0.001
    maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv.settle_external_trades)
    maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv.settle_external_trades)

    s.commit()

    buyer_pos = acc_svc.get_position(buyer, symbol)
    print('runtime_position', {'symbol': buyer_pos.symbol, 'qty': buyer_pos.quantity, 'avg': buyer_pos.avg_price}, flush=True)

    app_svc = AppAccountService()
    dto = app_svc.load_account(buyer_id)
    print('app_service_positions', [p.model_dump() for p in dto.positions], flush=True)

    ctl = AccountController(app_svc)
    panel = AccountPanel(ctl)
    panel.switch_account(buyer_id)
    view = panel.get_view()
    print('panel_view_account', view.get('account'), flush=True)
    print('panel_view_positions', view.get('positions', {}).get('items'), flush=True)
finally:
    s.close()
