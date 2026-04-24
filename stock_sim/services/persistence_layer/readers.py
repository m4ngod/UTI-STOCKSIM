"""Read-side persistence collaborators grouped by domain."""

from __future__ import annotations

from stock_sim.services.market_data_query_service import MarketDataQueryService
from stock_sim.services.run_persistence_query_service import RunPersistenceQueryService
from stock_sim.services.runtime_query_service import RuntimeQueryService

RUN_READERS = {
    "run_facts": RunPersistenceQueryService,
}

RUNTIME_READERS = {
    "runtime_state": RuntimeQueryService,
}

MARKET_READERS = {
    "market_history": MarketDataQueryService,
}

__all__ = [
    "MARKET_READERS",
    "RUNTIME_READERS",
    "RUN_READERS",
]
