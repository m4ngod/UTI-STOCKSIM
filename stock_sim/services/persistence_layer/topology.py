"""Re-export the current persistence topology map from one stable package."""

from __future__ import annotations

from stock_sim.services.persistence_topology import (
    PERSISTENCE_DOMAINS,
    PersistenceDomain,
    get_persistence_domain,
    list_persistence_domains,
)

__all__ = [
    "PERSISTENCE_DOMAINS",
    "PersistenceDomain",
    "get_persistence_domain",
    "list_persistence_domains",
]
