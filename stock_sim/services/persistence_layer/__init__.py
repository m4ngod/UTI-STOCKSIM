"""Stable package surface for persistence-boundary collaborators.

This package does not replace the current module layout yet. It provides a
clear import surface so future storage migration work can depend on one
coherent package instead of scattered service modules.
"""

from .readers import MARKET_READERS, RUNTIME_READERS, RUN_READERS
from .migration_plan import (
    PERSISTENCE_MIGRATION_PLAN,
    MigrationStep,
    list_migration_steps,
    list_ready_steps,
)
from .topology import (
    PERSISTENCE_DOMAINS,
    PersistenceDomain,
    get_persistence_domain,
    list_persistence_domains,
)
from .writers import ACCOUNT_WRITERS, ORDER_WRITERS, TRADE_WRITERS

__all__ = [
    "ACCOUNT_WRITERS",
    "MARKET_READERS",
    "MigrationStep",
    "ORDER_WRITERS",
    "PERSISTENCE_DOMAINS",
    "PERSISTENCE_MIGRATION_PLAN",
    "PersistenceDomain",
    "RUNTIME_READERS",
    "RUN_READERS",
    "TRADE_WRITERS",
    "get_persistence_domain",
    "list_migration_steps",
    "list_persistence_domains",
    "list_ready_steps",
]
