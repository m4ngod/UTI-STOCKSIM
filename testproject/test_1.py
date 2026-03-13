from pathlib import Path
import sys
import os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
print(sys.path)

from stock_sim.core import Stock, MatchingEngine
from stock_sim.api import LocalAPI
from stock_sim.core.order import Order, OrderSide

stock = Stock("TEST", 1_000_000, 800_000)

# 关键改动：把 stock.ticker 传进去即可
engine = MatchingEngine(stock.ticker)
api = LocalAPI(engine)

# 关键改动：订单的 symbol 用 "TEST"，用关键字参数可以避免顺序混淆
order1 = Order("TEST", OrderSide.BUY, 10.0, 1000, "A1", order_id="A1")
order2 = Order("TEST", OrderSide.SELL, 9.9, 1000, "A1", order_id="A2")

api.send_order(order1)
api.send_order(order2)

print(engine.trades)
print(engine.snapshot.last_price)
