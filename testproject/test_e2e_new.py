# python
# file: test_e2e_new.py
import os, json, traceback

os.environ.setdefault("DB_URL", "mysql+pymysql://root:yu20010402@127.0.0.1:3308/test_dataset?charset=utf8mb4")

from stock_sim.settings import settings
from stock_sim.persistence.models_init import init_models
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_trade import TradeORM
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.persistence.models_order_event import OrderEvent
from stock_sim.services.order_service import OrderService
from stock_sim.services.market_data_service import MarketDataService
from stock_sim.infra.unit_of_work import UnitOfWork
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.instruments import Stock
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce, OrderStatus
from stock_sim.core.auction_engine import AuctionMatchingEngine  # 新增

def assert_true(cond, msg, ctx):
    if not cond:
        ctx["errors"].append(msg)

def run():
    ctx = {"errors": [], "exception": None, "checks": {}}
    ev_counts = {"Trade":0,"OrderRejected":0,"OrderCanceled":0}
    def _ev_rec(topic, payload):
        ev_counts[topic] = ev_counts.get(topic,0)+1
    event_bus.subscribe("Trade", _ev_rec)
    event_bus.subscribe("OrderRejected", _ev_rec)
    event_bus.subscribe("OrderCanceled", _ev_rec)

    try:
        init_models()
        symbol = "E2E"
        engine = AuctionMatchingEngine(symbol,
                                       instrument=Stock(symbol, 0, 0, tick_size=0.01, lot_size=10, min_qty=10),
                                       enable_auction=settings.AUCTION_ENABLED,
                                       fast_mode=True)
        mkt = MarketDataService(engine)

        with UnitOfWork(SessionLocal) as uow:
            s = uow.session
            order_service = OrderService(s, engine)

            buyer_id = "ACC_E2E_BUY"
            seller_id = "ACC_E2E_SELL"
            buyer = s.get(Account, buyer_id) or Account(id=buyer_id, cash=settings.DEFAULT_CASH, frozen_cash=0)
            seller = s.get(Account, seller_id) or Account(id=seller_id, cash=settings.DEFAULT_CASH, frozen_cash=0)
            s.add(buyer); s.add(seller)
            if not any(p.symbol == symbol for p in seller.positions):
                s.add(Position(account_id=seller_id, symbol=symbol, quantity=5000, frozen_qty=0, avg_price=100.0))
            s.flush()

            # 0. 集合竞价阶段下单（快速模式立即 finalize）
            pre_buy = Order(symbol=symbol, side=OrderSide.BUY, price=100.00, quantity=200,
                            account_id=buyer_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            pre_sell = Order(symbol=symbol, side=OrderSide.SELL, price=99.90, quantity=150,
                             account_id=seller_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(pre_buy)
            order_service.place_order(pre_sell)
            # 立即结束集合竞价
            open_trades = engine.finalize_open(settings.AUCTION_DEFAULT_PREV_CLOSE)
            # 持久化成交 (集合竞价产生的 trades 需手动调用)
            if open_trades:
                order_service._after_trades(open_trades)  # 利用内部处理
            assert_true(all(t.price is not None for t in open_trades), "集合竞价成交缺价格", ctx)

            # 1. BUY 订单（连续竞价阶段），数量非整 lot 触发对齐：105 -> 100
            o_buy = Order(symbol=symbol, side=OrderSide.BUY, price=100.00, quantity=105,
                          account_id=buyer_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(o_buy)
            assert_true(o_buy.quantity == 100, "数量应被对齐为 100", ctx)
            assert_true(o_buy.status in (OrderStatus.NEW, OrderStatus.PARTIAL), "BUY 初始状态异常", ctx)

            # 2. 部分成交：先卖 40
            o_sell_part = Order(symbol=symbol, side=OrderSide.SELL, price=100.00, quantity=40,
                                account_id=seller_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            trades_part = order_service.place_order(o_sell_part)
            assert_true(len(trades_part) == 1, "部分成交应产生 1 笔 trade", ctx)
            assert_true(o_buy.filled == 40 and o_buy.remaining == 60, "BUY 部分成交数量不符", ctx)

            # 3. 再卖 60 完成
            o_sell_rest = Order(symbol=symbol, side=OrderSide.SELL, price=100.00, quantity=60,
                                account_id=seller_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            trades_rest = order_service.place_order(o_sell_rest)
            assert_true(o_buy.status == OrderStatus.FILLED, "BUY 应已完全成交", ctx)

            # 4. 卖空风控
            short_acc = s.get(Account, "ACC_SHORT") or Account(id="ACC_SHORT", cash=settings.DEFAULT_CASH, frozen_cash=0)
            s.add(short_acc); s.flush()
            o_short = Order(symbol=symbol, side=OrderSide.SELL, price=99.50, quantity=100,
                            account_id="ACC_SHORT", order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(o_short)
            assert_true(o_short.status == OrderStatus.REJECTED, "裸卖空应被拒绝", ctx)

            # 5. 资金不足
            low_acc = s.get(Account, "ACC_LOW") or Account(id="ACC_LOW", cash=1_000, frozen_cash=0)
            s.add(low_acc); s.flush()
            o_big = Order(symbol=symbol, side=OrderSide.BUY, price=100.0, quantity=10_000,
                          account_id="ACC_LOW", order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(o_big)
            assert_true(o_big.status == OrderStatus.REJECTED, "资金不足应拒绝", ctx)

            # 6. 费用/冻结释放
            buyer_db = s.get(Account, buyer_id)
            assert_true(buyer_db.frozen_cash < 1e-6, "买方冻结资金应释放为 0", ctx)
            led_buy = (s.query(Ledger)
                       .filter(Ledger.account_id == buyer_id, Ledger.side == "BUY")
                       .order_by(Ledger.id.asc()).all())
            assert_true(any(l.fee > 0 for l in led_buy), "买方流水缺少费用记录", ctx)

            # 7. 持仓
            pos_buy = next((p for p in buyer_db.positions if p.symbol == symbol), None)
            assert_true(pos_buy and pos_buy.quantity >= 100, "买方持仓应 >=100 (含集合竞价+连续成交)", ctx)

            seller_db = s.get(Account, seller_id)
            pos_sell = next((p for p in seller_db.positions if p.symbol == symbol), None)
            assert_true(pos_sell and pos_sell.quantity <= 5000 - 100, "卖方持仓应减少", ctx)

            # 8. 快照
            snap = mkt.snapshot(levels=5)
            d = snap.to_dict()
            assert_true(d["last_price"] is not None, "快照 last_price 为空", ctx)

            # 9. 持久化计数
            ctx["checks"]["orders_cnt"] = s.query(OrderORM).count()
            ctx["checks"]["trades_cnt"] = s.query(TradeORM).count()
            ctx["checks"]["ledgers_cnt"] = s.query(Ledger).count()
            ctx["checks"]["events_cnt"] = s.query(OrderEvent).count()

            # 10. 事件计数
            ctx["checks"]["events"] = ev_counts
            assert_true(ev_counts["Trade"] >= 2, "应至少有 2 笔成交事件(含集合竞价)", ctx)
            assert_true(ev_counts["OrderRejected"] >= 2, "应有 >=2 拒单事件", ctx)

            # 11. 指标
            from stock_sim.observability.metrics import metrics
            ctx["checks"]["metrics_orders_submitted"] = metrics.counters.get("orders_submitted", 0)
            assert_true(ctx["checks"]["metrics_orders_submitted"] >= 5, "提交订单计数不足", ctx)

            uow.commit()

    except Exception as e:
        ctx["exception"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))

    ctx["result"] = "PASS" if not ctx["errors"] and not ctx["exception"] else "FAIL"
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    if ctx["result"] == "FAIL":
        exit(1)

if __name__ == "__main__":
    run()