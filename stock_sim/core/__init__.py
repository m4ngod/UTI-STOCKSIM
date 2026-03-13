"""
Core modules for stock_sim (lazy / fault-tolerant exports).
避免在仅需 const 时强制加载撮合 / 订单等重型依赖。
"""
try:
    from .instruments import Stock  # type: ignore
except Exception:
    Stock = None  # type: ignore
try:
    from .order import Order, OrderSide  # type: ignore
except Exception:
    Order = None  # type: ignore
    from .const import OrderSide  # fallback only side
try:
    from .market_data import MarketSnapshot  # type: ignore
except Exception:
    MarketSnapshot = None  # type: ignore
try:
    from .matching_engine import MatchingEngine  # type: ignore
except Exception:
    MatchingEngine = None  # type: ignore

__all__ = [
    name for name, val in dict(Stock=Stock, Order=Order, OrderSide=OrderSide,
                               MarketSnapshot=MarketSnapshot, MatchingEngine=MatchingEngine).items() if val is not None
]

