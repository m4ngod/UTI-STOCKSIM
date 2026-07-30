"""Write-side persistence collaborators grouped by domain."""

from __future__ import annotations

from stock_sim.services.account_persistence_service import AccountPersistenceService
from stock_sim.services.order_persistence_service import OrderPersistenceService
from stock_sim.services.trade_persistence_service import TradePersistenceService

ORDER_WRITERS = {
    "orders": OrderPersistenceService,
}

TRADE_WRITERS = {
    "trades": TradePersistenceService,
}

ACCOUNT_WRITERS = {
    "accounts": AccountPersistenceService,
}

__all__ = [
    "ACCOUNT_WRITERS",
    "ORDER_WRITERS",
    "TRADE_WRITERS",
]
