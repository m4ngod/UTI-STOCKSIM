import time
import pytest

from stock_sim.core.order import Order, OrderSide
from stock_sim.core.order_book import OrderBook

def test_price_time_priority():
    """
    同价不同时间 → FIFO
    """
    book = OrderBook("000001.SZ")

    o1 = Order("000001.SZ", OrderSide.BUY, 10.00, 100)
    time.sleep(0.001)  # 保证时间先后
    o2 = Order("000001.SZ", OrderSide.BUY, 10.00, 200)

    book.add_order(o1)
    book.add_order(o2)

    dq = book._bids[10.00]
    assert dq[0].order_id == o1.order_id        # 队首应是 o1
    assert dq[1].order_id == o2.order_id        # 第二个是 o2

def test_price_priority():
    """
    不同价格 → 价格优先
    """
    book = OrderBook("000001.SZ")

    low = Order("000001.SZ", OrderSide.BUY, 9.90, 100)
    high = Order("000001.SZ", OrderSide.BUY, 10.00, 100)
    book.add_order(low)
    book.add_order(high)

    best = book.best_bid("000001.SZ")
    assert best.price == 10.00                  # 高价优先
    assert best.order_id == high.order_id

def test_cross_side_price_priority():
    """
    卖方同理：低价优先
    """
    book = OrderBook("000001.SZ")

    high = Order("000001.SZ", OrderSide.SELL, 10.10, 100)
    low = Order("000001.SZ", OrderSide.SELL, 10.00, 100)

    book.add_order(high)
    book.add_order(low)

    best = book.best_ask("000001.SZ")
    assert best.price == 10.00
    assert best.order_id == low.order_id
