# file: simulation/random_liquidity_provider.py
# python
import random, uuid
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce

class RandomLiquidityProvider:
    def __init__(self, symbol: str, account_id: str | None = None):
        self.symbol = symbol
        self.account_id = account_id or f"LP_{uuid.uuid4().hex[:6]}"

    def generate_quotes(self, mid: float, spread: float = 0.02, depth: int = 3):
        orders = []
        for i in range(1, depth + 1):
            px_b = round(mid - spread * i, 2)
            px_a = round(mid + spread * i, 2)
            qty = random.randint(100, 500)
            orders.append(Order(symbol=self.symbol, side=OrderSide.BUY,
                                price=px_b, quantity=qty, account_id=self.account_id,
                                order_type=OrderType.LIMIT, tif=TimeInForce.GFD))
            orders.append(Order(symbol=self.symbol, side=OrderSide.SELL,
                                price=px_a, quantity=qty, account_id=self.account_id,
                                order_type=OrderType.LIMIT, tif=TimeInForce.GFD))
        return orders