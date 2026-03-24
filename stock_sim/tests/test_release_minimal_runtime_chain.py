from __future__ import annotations

import uuid

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_trade import TradeORM
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_snapshot import Snapshot1s
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


def test_release_minimal_runtime_chain_from_instrument_to_account_and_market_view():
    symbol = f"RLS{uuid.uuid4().hex[:6].upper()}"
    buyer_id = f"ACC_BUY_{uuid.uuid4().hex[:6].upper()}"
    seller_id = f"ACC_SELL_{uuid.uuid4().hex[:6].upper()}"

    engine_registry.remove(symbol)
    models_init.init_models()
    s = SessionLocal()
    snap_listener = SnapshotPersistenceListener()
    market_ctrl = MarketController(MarketDataService())
    account_panel = AccountPanel(AccountController(AppAccountService()))
    market_panel = MarketPanel(market_ctrl, MarketDataService())

    settings.IPO_CALL_AUCTION_SECONDS = 0.01
    settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS = 0.0

    def on_snapshot(_topic: str, payload: dict):
        if not isinstance(payload, dict):
            return
        market_ctrl.merge_batch([payload])

    event_bus.subscribe(EventType.SNAPSHOT_UPDATED, on_snapshot)

    try:
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
        assert getattr(inst_payload, "symbol", None) == symbol

        engine = MatchingEngine(
            symbol,
            create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0),
        )
        osrv = OrderService(s, engine, instrument_service=inst_srv)
        acc_svc = AccountService(s)

        buyer = acc_svc.get_or_create(buyer_id, cash=1_000_000.0)
        seller = acc_svc.get_or_create(seller_id, cash=100_000.0)
        seller_pos = acc_svc.get_position(seller, symbol)
        seller_pos.quantity = 100_000
        seller_pos.avg_price = 10.0
        s.flush()

        buy_order = Order(symbol=symbol, side=OrderSide.BUY, price=10.2, quantity=100_000, account_id=buyer_id)
        sell_order = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=100_000, account_id=seller_id)

        osrv.place_order(buy_order)
        osrv.place_order(sell_order)

        ipo_book = engine.get_book(symbol)
        assert ipo_book.phase is Phase.CALL_AUCTION

        engine._ipo_end_ts = 0.0
        maybe_auto_open_ipo(engine, ipo_book)
        maybe_auto_open_ipo(engine, ipo_book)

        assert ipo_book.phase is Phase.CONTINUOUS
        assert sum(t.quantity for t in ipo_book.trades) == 100_000

        snap = engine.get_book(symbol).snapshot.to_dict()
        snap_listener._on_snapshot(EventType.SNAPSHOT_UPDATED.value, snap)
        market_ctrl.merge_batch([snap])

        order_rows = s.query(OrderORM).filter(OrderORM.symbol == symbol).all()
        trade_rows = s.query(TradeORM).filter(TradeORM.symbol == symbol).all()
        snapshot_rows = s.query(Snapshot1s).filter(Snapshot1s.symbol == symbol).all()

        assert len(order_rows) >= 2
        assert len(trade_rows) >= 1
        assert len(snapshot_rows) >= 1

        account_panel.switch_account(buyer_id)
        account_view = account_panel.get_view()
        account = account_view["account"]
        assert account["account_id"] == buyer_id
        assert float(account["cash"]) < 1_000_000.0
        assert "frozen_cash" in account
        assert "frozen_fee" in account

        positions = account_view["positions"]["items"]
        target_positions = [p for p in positions if p.get("symbol") == symbol]
        assert target_positions
        assert float(target_positions[0].get("quantity") or 0) >= 100_000

        market_list = market_ctrl.list_snapshots()
        assert any(getattr(item, "symbol", None) == symbol for item in market_list["items"])

        market_panel.add_symbol(symbol)
        market_panel.select_symbol(symbol)
        detail_view = market_panel.detail_view()
        assert detail_view["symbol"] == symbol
        assert detail_view["snapshot"] is not None
        assert detail_view["order_book"] is not None
        assert detail_view["detail_health"]["overall"] in {"ok", "degraded"}
    finally:
        event_bus.unsubscribe(EventType.SNAPSHOT_UPDATED, on_snapshot)
        try:
            engine_registry.remove(symbol)
        except Exception:
            pass
        s.close()
