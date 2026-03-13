from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order import Order, OrderSide, OrderStatus

def test_full_fill():
    """
    两张相同数量、可成交的对手单应全部成交并被标记 FILLED。
    """
    engine = MatchingEngine("000001.SZ")
    buy = Order("000001.SZ", OrderSide.BUY, 10.00, 1000)
    sell = Order("000001.SZ", OrderSide.SELL, 10.00, 1000)

    t1 = engine.submit_order(buy)
    assert t1 == []  # 先挂买单不发生成交
    t2 = engine.submit_order(sell)

    # 产生 1 条成交
    assert len(t2) == 1
    trade = t2[0]
    assert trade.price == 10.00
    assert trade.quantity == 1000

    # 订单状态
    assert buy.status is OrderStatus.FILLED
    assert sell.status is OrderStatus.FILLED

    # 快照更新
    assert engine.snapshot.last_price == 10.00
    assert engine.snapshot.last_quantity == 1000

def test_partial_fill():
    """
    对手单数量不足 → 部分成交。
    """
    engine = MatchingEngine("000001.SZ")
    sell_big = Order("000001.SZ", OrderSide.SELL, 10.00, 1500)
    buy_small = Order("000001.SZ", OrderSide.BUY, 10.00, 1000)

    engine.submit_order(sell_big)                   # 先挂大卖单
    trades = engine.submit_order(buy_small)         # 买单吃掉 1,000

    assert len(trades) == 1
    trade = trades[0]
    assert trade.quantity == 1000
    assert sell_big.remaining == 500
    assert sell_big.status.name == "PARTIALLY_FILLED"
    assert buy_small.status.name == "FILLED"

    # 订单簿中应剩余 500 股卖单
    best_ask = engine.order_book.best_ask("000001.SZ")
    assert best_ask.remaining == 500
    assert best_ask.price == 10.00

def test_no_fill():
    """
    买价 < 卖价 时不成交
    """
    engine = MatchingEngine("000001.SZ")
    buy = Order("000001.SZ", OrderSide.BUY, 9.90, 1000)
    sell = Order("000001.SZ", OrderSide.SELL, 10.00, 1000)

    t1 = engine.submit_order(buy)
    t2 = engine.submit_order(sell)

    # 均无成交
    assert t1 == []
    assert t2 == []

    assert engine.order_book.best_bid("000001.SZ").price == 9.90
    assert engine.order_book.best_ask("000001.SZ").price == 10.00
