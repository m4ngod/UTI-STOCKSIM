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
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.ipo_service import maybe_auto_open_ipo
from stock_sim.services.snapshot_listener import SnapshotPersistenceListener
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, Phase, EventType
from app.controllers.market_controller import MarketController
from app.services.market_data_service import MarketDataService
from app.controllers.account_controller import AccountController
from app.services.account_service import AccountService as AppAccountService
from app.panels.market.panel import MarketPanel
from app.panels.account.panel import AccountPanel
from infra.event_bus import event_bus
from stock_sim.settings import settings


symbol = f"DBG{uuid.uuid4().hex[:6].upper()}"
buyer_id = f"ACC_BUY_{uuid.uuid4().hex[:6].upper()}"
seller_id = f"ACC_SELL_{uuid.uuid4().hex[:6].upper()}"

print('start', symbol, flush=True)
engine_registry.remove(symbol)
models_init.init_models()
s = SessionLocal()
snap_listener = SnapshotPersistenceListener(session_factory=lambda: s)
market_ctrl = MarketController(MarketDataService())
account_panel = AccountPanel(AccountController(AppAccountService()))
market_panel = MarketPanel(market_ctrl, MarketDataService())
settings.IPO_CALL_AUCTION_SECONDS = 0.01
settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS = 0.0


def on_snapshot(_topic: str, payload: dict):
    print('on_snapshot', type(payload), flush=True)
    if not isinstance(payload, dict):
        return
    market_ctrl.merge_batch([payload])


event_bus.subscribe(EventType.SNAPSHOT_UPDATED, on_snapshot)

try:
    print('create_instrument', flush=True)
    inst_srv = InstrumentService(s)
    inst_payload = inst_srv.create(
        symbol=symbol,
        name=symbol,
        tick_size=0.01,
        lot_size=100,
        min_qty=100,
        settlement_cycle=1,
        total_shares=1_000_000,
        free_float_shares=300_000,
        initial_price=10.0,
        ipo_opened=False,
    )
    print('inst_payload', getattr(inst_payload, 'symbol', None), flush=True)

    print('create_engine_services', flush=True)
    engine = MatchingEngine(symbol, create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0))
    osrv = OrderService(s, engine, instrument_service=inst_srv)
    acc_svc = AccountService(s)

    print('create_accounts', flush=True)
    buyer = acc_svc.get_or_create(buyer_id, cash=1_000_000.0)
    seller = acc_svc.get_or_create(seller_id, cash=100_000.0)
    seller_pos = acc_svc.get_position(seller, symbol)
    seller_pos.quantity = 100_000
    seller_pos.avg_price = 10.0
    s.flush()

    print('place_orders', flush=True)
    buy_order = Order(symbol=symbol, side=OrderSide.BUY, price=10.2, quantity=100_000, account_id=buyer_id)
    sell_order = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=100_000, account_id=seller_id)
    osrv.place_order(buy_order)
    osrv.place_order(sell_order)
    print('orders_placed', flush=True)

    ipo_book = engine.get_book(symbol)
    print('phase_after_orders', ipo_book.phase, flush=True)
    engine._ipo_end_ts = 0.0
    print('maybe_auto_open_ipo_1', flush=True)
    maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv._after_trades)
    print('maybe_auto_open_ipo_2', flush=True)
    maybe_auto_open_ipo(engine, ipo_book, settle_trades_callback=osrv._after_trades)
    print('phase_after_ipo', ipo_book.phase, 'trades', sum(t.quantity for t in ipo_book.trades), flush=True)
    from stock_sim.persistence.models_order import OrderORM
    buy_orm = s.get(OrderORM, buy_order.order_id)
    sell_orm = s.get(OrderORM, sell_order.order_id)
    print('buy_orm', {'id': getattr(buy_orm, 'id', None), 'filled': getattr(buy_orm, 'filled', None), 'status': getattr(getattr(buy_orm, 'status', None), 'name', getattr(buy_orm, 'status', None)), 'qty': getattr(buy_orm, 'quantity', None)}, flush=True)
    print('sell_orm', {'id': getattr(sell_orm, 'id', None), 'filled': getattr(sell_orm, 'filled', None), 'status': getattr(getattr(sell_orm, 'status', None), 'name', getattr(sell_orm, 'status', None)), 'qty': getattr(sell_orm, 'quantity', None)}, flush=True)

    raw_snap = engine.get_book(symbol).snapshot.to_dict()
    listener_payload = {
        'symbol': symbol,
        'snapshot': {
            'symbol': symbol,
            'last': raw_snap.get('last'),
            'vol': raw_snap.get('volume'),
            'turnover': raw_snap.get('turnover'),
            'bid1': (raw_snap.get('bid_levels') or [(None, None)])[0][0],
            'bid1_qty': (raw_snap.get('bid_levels') or [(None, None)])[0][1],
            'ask1': (raw_snap.get('ask_levels') or [(None, None)])[0][0],
            'ask1_qty': (raw_snap.get('ask_levels') or [(None, None)])[0][1],
        },
    }
    front_snap = {
        'symbol': symbol,
        'last': float(raw_snap.get('last') or 0.0),
        'bid_levels': list(raw_snap.get('bid_levels') or []),
        'ask_levels': list(raw_snap.get('ask_levels') or []),
        'volume': int(raw_snap.get('volume') or 0),
        'turnover': float(raw_snap.get('turnover') or 0.0),
        'ts': int(time.time() * 1000),
        'snapshot_id': f'release-{symbol.lower()}',
    }
    print('snapshot_persist', flush=True)
    snap_listener._on_snapshot(EventType.SNAPSHOT_UPDATED.value, listener_payload)
    print('snapshot_merge', flush=True)
    market_ctrl.merge_batch([front_snap])
    print('snapshot_done', flush=True)

    print('account_view', flush=True)
    account_panel.switch_account(buyer_id)
    account_view = account_panel.get_view()
    print('account_view_done', account_view.get('account', {}).get('account_id'), flush=True)
    print('account_positions', account_view.get('positions', {}).get('items'), flush=True)
    buyer_runtime_pos = acc_svc.get_position(buyer, symbol)
    print('runtime_buyer_position', {'symbol': buyer_runtime_pos.symbol, 'qty': buyer_runtime_pos.quantity, 'frozen_qty': buyer_runtime_pos.frozen_qty, 'borrowed_qty': buyer_runtime_pos.borrowed_qty, 'avg_price': buyer_runtime_pos.avg_price}, flush=True)

    print('market_detail', flush=True)
    market_panel.add_symbol(symbol)
    market_panel.select_symbol(symbol)
    detail_view = market_panel.detail_view()
    print('market_detail_done', detail_view.get('symbol'), detail_view.get('detail_health'), flush=True)
finally:
    event_bus.unsubscribe(EventType.SNAPSHOT_UPDATED, on_snapshot)
    try:
        engine_registry.remove(symbol)
    except Exception:
        pass
    s.close()
    print('done', flush=True)
