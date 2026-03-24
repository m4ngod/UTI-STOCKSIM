from __future__ import annotations

import time
import uuid

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.account_service import AccountService as RuntimeAccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide
from stock_sim.services.order_service import OrderService

from app.controllers.market_controller import MarketController
from app.controllers.account_controller import AccountController
from app.controllers.trading_controller import TradingController
from app.services.market_data_service import MarketDataService
from app.services.account_service import AccountService as AppAccountService
from app.services.trading_service import TradingService
from app.panels.market.panel import MarketPanel
from app.panels.account.panel import AccountPanel
from app.panels.orders.panel import OrdersPanel
from app.ui.adapters.market_adapter import MarketPanelAdapter
from app.ui.adapters.orders_adapter import OrdersPanelAdapter


def test_frontend_trading_closed_loop_market_order_account_orders():
    print('closed-loop:enter', flush=True)
    symbol = f"CL{uuid.uuid4().hex[:6].upper()}"
    buyer_id = f"ACC_BUY_{uuid.uuid4().hex[:6].upper()}"
    seller_id = f"ACC_SELL_{uuid.uuid4().hex[:6].upper()}"

    engine_registry.remove(symbol)
    models_init.init_models()
    s = SessionLocal()
    try:
        print('closed-loop:session-ready', flush=True)
        inst_srv = InstrumentService(s)
        dto = inst_srv.create(
            symbol=symbol,
            name=symbol,
            tick_size=0.01,
            lot_size=100,
            min_qty=100,
            settlement_cycle=1,
            total_shares=1_000_000,
            free_float_shares=300_000,
            initial_price=10.0,
            ipo_opened=True,
        )
        assert getattr(dto, "symbol", None) == symbol
        s.commit()

        print('closed-loop:instrument-created', flush=True)
        engine = MatchingEngine(
            symbol,
            create_instrument(symbol, tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0),
        )
        engine_registry.register(symbol, engine, overwrite=True)

        print('closed-loop:engine-ready', flush=True)
        runtime_acc = RuntimeAccountService(s)
        buyer = runtime_acc.get_or_create(buyer_id, cash=1_000_000.0)
        seller = runtime_acc.get_or_create(seller_id, cash=100_000.0)
        seller_pos = runtime_acc.get_position(seller, symbol)
        seller_pos.quantity = 10_000
        seller_pos.avg_price = 10.0
        s.flush()

        # 先挂一个卖单，等前端 buy 去吃它
        print('closed-loop:accounts-ready', flush=True)
        runtime_order = OrderService(s, engine=engine, instrument_service=inst_srv)
        resting_sell = Order(symbol=symbol, side=OrderSide.SELL, price=10.0, quantity=1000, account_id=seller_id)
        runtime_order.place_order(resting_sell)
        s.commit()

        print('closed-loop:resting-sell-ready', flush=True)
        market_svc = MarketDataService()
        market_ctl = MarketController(market_svc)
        print('closed-loop:market-service-ready', flush=True)
        market_panel = MarketPanel(market_ctl, market_svc)
        print('closed-loop:market-panel-ready', flush=True)
        market_panel.add_symbol(symbol)
        print('closed-loop:market-add-symbol-done', flush=True)
        market_panel.select_symbol(symbol)
        print('closed-loop:market-select-symbol-done', flush=True)
        from infra.event_bus import event_bus as app_event_bus
        try:
            from stock_sim.infra.event_bus import event_bus as runtime_event_bus
        except Exception:
            runtime_event_bus = app_event_bus
        seen_topics = []
        def _rec(topic, payload):
            seen_topics.append((topic, payload))
            print('closed-loop:event', topic, type(payload).__name__, flush=True)
        app_event_bus.subscribe('Trade', _rec, async_mode=False)
        runtime_event_bus.subscribe('Trade', _rec, async_mode=False)
        app_event_bus.subscribe('TradeEvent', _rec, async_mode=False)
        runtime_event_bus.subscribe('TradeEvent', _rec, async_mode=False)

        orders_logic = OrdersPanel(capacity=20)
        print('closed-loop:orders-logic-ready', flush=True)
        orders_adapter = OrdersPanelAdapter().bind(orders_logic)
        print('closed-loop:orders-adapter-bound', flush=True)
        _ = orders_adapter.widget()
        print('closed-loop:orders-widget-ready', flush=True)

        print('closed-loop:panels-ready', flush=True)
        trading_ctl = TradingController(TradingService())
        submit = trading_ctl.submit_order(symbol=symbol, side="buy", price=10.0, qty=1000, account_id=buyer_id)
        print('closed-loop:submit-done', submit, flush=True)

        assert submit["ok"] is True
        assert submit["status"] in {"PARTIAL", "FILLED", "NEW"}
        assert submit["trade_count"] >= 1

        # Account 面板刷新后应能看到持仓
        print('closed-loop:before-account-view', flush=True)
        account_panel = AccountPanel(AccountController(AppAccountService()))
        account_panel.switch_account(buyer_id)
        account_view = account_panel.get_view()
        positions = account_view["positions"]["items"]
        assert any(p["symbol"] == symbol and p["quantity"] >= 1000 for p in positions)

        # Orders 面板应收到 Trade 事件
        deadline = time.perf_counter() + 0.8
        seen_trade = False
        while time.perf_counter() < deadline:
            items = orders_adapter.get_items()
            print('closed-loop:orders-items', items, flush=True)
            if any((it.get("type") == "Trade" and it.get("symbol") == symbol) for it in items):
                seen_trade = True
                break
            time.sleep(0.02)
        assert seen_trade, "orders panel did not receive trade event"

        # Market detail 应收到成交逐笔
        deadline = time.perf_counter() + 0.8
        seen_detail_trade = False
        while time.perf_counter() < deadline:
            detail = market_panel.detail_view()
            trades = detail.get("trades") or []
            if any(t.get("symbol") == symbol for t in trades if isinstance(t, dict)):
                seen_detail_trade = True
                break
            time.sleep(0.02)
        assert seen_detail_trade, "market detail did not receive trade passthrough"
    finally:
        s.close()
        try:
            engine_registry.remove(symbol)
        except Exception:
            pass
