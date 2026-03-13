# test_smoke.py
import os
import traceback

# 1. 提前设定测试数据库 (避免与生产冲突)
os.environ.setdefault("DB_URL", "mysql+pymysql://root:yu20010402@127.0.0.1:3308/test_dataset?charset=utf8mb4")  # 覆盖 settings.assembled_db_url()

# 2. 导入项目模块
from stock_sim.settings import settings
from stock_sim.persistence.models_init import init_models
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_trade import TradeORM
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.persistence.models_order_event import OrderEvent

from stock_sim.core.instruments import Stock
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce, OrderStatus
from stock_sim.core.matching_engine import MatchingEngine

from stock_sim.services.order_service import OrderService
from stock_sim.infra.unit_of_work import UnitOfWork

# 3. 校验
required = [
    "MAX_SINGLE_ORDER_NOTIONAL",
    "MAX_POSITION_RATIO",
    "RISK_DISABLE_SHORT",
    "MAX_DAILY_VOLUME_RATIO",
]
missing = [k for k in required if not hasattr(settings, k)]
assert not missing, f"settings 缺失字段: {missing}"

def assert_true(cond, msg, ctx):
    if not cond:
        ctx["errors"].append(msg)

def smoke_test():
    ctx = {"errors": [], "checks": {}, "exception": None}

    try:
        # 4. 初始化模型
        init_models()

        symbol = "SMOKE"
        engine = MatchingEngine(symbol, instrument=Stock(symbol, 0, 0, tick_size=0.01, lot_size=10, min_qty=10))

        with UnitOfWork(SessionLocal) as uow:
            s = uow.session
            order_service = OrderService(s, engine)

            # 5. 预置账户与卖方持仓
            buyer_id = "ACC_BUY"
            seller_id = "ACC_SELL"

            buyer = s.get(Account, buyer_id)
            if not buyer:
                buyer = Account(id=buyer_id, cash=settings.DEFAULT_CASH, frozen_cash=0)
                s.add(buyer)

            seller = s.get(Account, seller_id)
            if not seller:
                seller = Account(id=seller_id, cash=settings.DEFAULT_CASH, frozen_cash=0)
                s.add(seller)
                # 卖方给定库存 (避免风控拒绝)
                pos = Position(account_id=seller_id, symbol=symbol,
                               quantity=10_000, frozen_qty=0, avg_price=100.0)
                s.add(pos)

            s.flush()

            # 6. 下买单（先挂买单，成为账簿中等待撮合）
            buy_order = Order(symbol=symbol, side=OrderSide.BUY,
                              price=100.00, quantity=1000,
                              account_id=buyer_id,
                              order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(buy_order)

            # 校验买单挂出后状态
            assert_true(buy_order.status in (OrderStatus.NEW, OrderStatus.PARTIAL),
                        "买单初始状态应为 NEW/PARTIAL", ctx)

            # 7. 下卖单（价格相同，应立即撮合）
            sell_order = Order(symbol=symbol, side=OrderSide.SELL,
                               price=100.00, quantity=1000,
                               account_id=seller_id,
                               order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            trades = order_service.place_order(sell_order)

            # 8. 刷新 ORM
            s.flush()

            # 9. 校验撮合结果
            buy_db = s.get(OrderORM, buy_order.order_id)
            sell_db = s.get(OrderORM, sell_order.order_id)

            ctx["checks"]["trade_count"] = len(trades)
            assert_true(len(trades) == 1, "应产生 1 笔成交", ctx)

            assert_true(buy_db and buy_db.status == OrderStatus.FILLED,
                        "买单应 FILLED", ctx)
            assert_true(sell_db and sell_db.status == OrderStatus.FILLED,
                        "卖单应 FILLED", ctx)
            assert_true(buy_db.filled == 1000 and sell_db.filled == 1000,
                        "买卖单 filled 数量应为 1000", ctx)

            # 10. 资金与持仓
            buyer_after = s.get(Account, buyer_id)
            seller_after = s.get(Account, seller_id)
            buyer_pos = next((p for p in buyer_after.positions if p.symbol == symbol), None)
            seller_pos = next((p for p in seller_after.positions if p.symbol == symbol), None)

            assert_true(buyer_pos and buyer_pos.quantity >= 1000,
                        "买方应新增持仓 >=1000", ctx)
            assert_true(seller_pos and seller_pos.quantity <= 9000,
                        "卖方持仓应减少到 <=9000", ctx)

            # 冻结资金应释放 (买方冻结现金应减少)
            assert_true(buyer_after.frozen_cash <= settings.DEFAULT_CASH * 0.01,
                        "买方冻结资金应接近 0", ctx)

            # 11. 持久化记录数量
            orders_cnt = s.query(OrderORM).count()
            trades_cnt = s.query(TradeORM).count()
            ledgers_cnt = s.query(Ledger).count()
            events_cnt = s.query(OrderEvent).count()

            ctx["checks"].update({
                "orders_in_db": orders_cnt,
                "trades_in_db": trades_cnt,
                "ledgers_in_db": ledgers_cnt,
                "order_events_in_db": events_cnt,
                "buyer_cash": buyer_after.cash,
                "buyer_frozen_cash": buyer_after.frozen_cash,
                "seller_cash": seller_after.cash,
            })

            assert_true(trades_cnt == 1, "DB 中应只有 1 笔成交记录", ctx)
            assert_true(orders_cnt == 2, "DB 中应有 2 条订单记录", ctx)
            assert_true(ledgers_cnt == 2, "应有 2 条资金流水 (买/卖)", ctx)
            assert_true(events_cnt >= 4, "订单事件应 >=4 (NEW, NEW, FILL, FILL 等)", ctx)

            # 12. （可选）尝试触发价格修改逻辑，暴露潜在缺失方法
            modify_error = None
            try:
                # 若 engine 暴露 order_book
                ob = engine.order_book
                if hasattr(ob, "modify_price"):
                    ob.modify_price(buy_order.order_id, 101.0)
            except Exception as e:
                modify_error = repr(e)
            ctx["checks"]["modify_price_error"] = modify_error

            # 13. 提交事务
            uow.commit()

    except Exception as e:
        ctx["exception"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))

    # 汇总
    ctx["result"] = "PASS" if not ctx["errors"] and not ctx.get("exception") else "FAIL"
    return ctx

if __name__ == "__main__":
    import json
    res = smoke_test()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res["result"] == "FAIL":
        exit(1)