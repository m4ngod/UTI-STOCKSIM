from types import SimpleNamespace

from stock_sim.core.const import OrderSide, OrderStatus
from stock_sim.core.order import Order
from stock_sim.core.order_book import OrderBook
from stock_sim.services.order_runtime_sync_service import OrderRuntimeSyncService


class _FakeEngine:
    def __init__(self, order_book, engine_order):
        self.order_book = order_book
        self._engine_order = engine_order

    def get_order(self, order_id: str):
        if self._engine_order.order_id == order_id:
            return self._engine_order
        return None


def test_sync_order_state_updates_mem_engine_and_book_views():
    mem_order = Order(
        symbol="SYNC1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        account_id="ACC_SYNC",
    )
    engine_order = Order(
        symbol="SYNC1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        account_id="ACC_SYNC",
        order_id=mem_order.order_id,
    )
    book_order = Order(
        symbol="SYNC1",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        account_id="ACC_SYNC",
        order_id=mem_order.order_id,
    )
    order_book = OrderBook(symbol="SYNC1")
    order_book.order_map = {mem_order.order_id: book_order}
    engine = _FakeEngine(order_book, engine_order)
    orm_order = SimpleNamespace(
        filled=100,
        status=OrderStatus.FILLED,
        price=9.95,
    )

    sync = OrderRuntimeSyncService(mem_orders={mem_order.order_id: mem_order})
    sync.sync_order_state(mem_order.order_id, orm_order, engine)

    assert mem_order.status == OrderStatus.FILLED
    assert mem_order.filled == 100
    assert mem_order.price == 9.95
    assert engine_order.status == OrderStatus.FILLED
    assert engine_order.filled == 100
    assert book_order.status == OrderStatus.FILLED
    assert book_order.filled == 100


def test_calc_required_frozen_fee_aggregates_active_buy_orders_only():
    active_new = Order(
        symbol="SYNC2",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        account_id="ACC_FEE",
    )
    active_new.attach_meta(est_fee=12.0)

    active_partial = Order(
        symbol="SYNC3",
        side=OrderSide.BUY,
        price=20.0,
        quantity=200,
        account_id="ACC_FEE",
    )
    active_partial.attach_meta(est_fee=18.0)
    active_partial.filled = 50
    active_partial.status = OrderStatus.PARTIAL

    inactive_sell = Order(
        symbol="SYNC4",
        side=OrderSide.SELL,
        price=30.0,
        quantity=100,
        account_id="ACC_FEE",
    )
    inactive_sell.attach_meta(est_fee=99.0)

    canceled_buy = Order(
        symbol="SYNC5",
        side=OrderSide.BUY,
        price=40.0,
        quantity=100,
        account_id="ACC_FEE",
    )
    canceled_buy.attach_meta(est_fee=5.0)
    canceled_buy.status = OrderStatus.CANCELED

    sync = OrderRuntimeSyncService(
        mem_orders={
            active_new.order_id: active_new,
            active_partial.order_id: active_partial,
            inactive_sell.order_id: inactive_sell,
            canceled_buy.order_id: canceled_buy,
        }
    )

    required = sync.calc_required_frozen_fee()

    assert required == {"ACC_FEE": 25.5}
