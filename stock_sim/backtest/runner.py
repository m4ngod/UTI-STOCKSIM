# file: backtest/runner.py
# python
from datetime import datetime, timedelta
from stock_sim.infra.unit_of_work import UnitOfWork
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.order_service import OrderService
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import Stock
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce
from stock_sim.simulation.market_clock import MarketClock
from stock_sim.infra.event_bus import event_bus
from stock_sim.observability.struct_logger import logger
from stock_sim.observability.metrics import metrics

class BacktestRunner:
    def __init__(self, symbol: str):
        self.engine = MatchingEngine(symbol, instrument=Stock(symbol, 0, 0))
        self.clock = MarketClock(
            start=datetime(2024, 1, 1, 9, 30),
            end=datetime(2024, 1, 1, 10, 0),
            step=timedelta(seconds=1)
        )

    def run(self):
        with UnitOfWork(SessionLocal) as uow:
            order_service = OrderService(uow.session, self.engine)
            self.clock.on_tick(lambda ts: self._on_tick(ts, order_service))
            self.clock.run()
            uow.commit()
        logger.log("backtest_done", trades=len(self.engine.trades),
                   orders=metrics.counters.get("orders_submitted", 0))

    def _on_tick(self, ts, order_service: OrderService):
        # 简易策略：每 5s 下买单
        if ts.second % 5 == 0:
            o = Order(symbol=self.engine.symbol, side=OrderSide.BUY,
                      price=100.0, quantity=100, account_id="BT_ACC",
                      order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            order_service.place_order(o)
        event_bus.publish("Tick", {"ts": ts.isoformat()})