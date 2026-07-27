"""
Stock Simulator Package
"""
print(__package__,__name__)
from pathlib import Path
from typing import Any
from .core.order import Order
from .core.const import OrderType, OrderSide, TimeInForce
from .core.market_data import MarketSnapshot
from .core.matching_engine import MatchingEngine
from .core.instruments import Stock
#from agents.base_agent import
#from storage.serializer import save_data, load_data

__all__ = [
    "Stock",
    "MatchingEngine",
    "Order",
    "OrderSide",
    "Account",
    "MarketSnapshot",
]

PACKAGE_ROOT = Path(__file__).parent
__version__ = "0.0.1"


def __getattr__(name: str) -> Any:
    """Load persistence symbols only when callers explicitly request them."""

    if name == "Account":
        from .persistence.models_account import Account

        return Account
    if name == "init_models":
        from .persistence.models_init import init_models

        return init_models
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
