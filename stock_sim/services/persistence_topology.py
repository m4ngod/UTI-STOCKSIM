from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


StorageTarget = Literal["postgresql", "redis", "sqlite"]
TruthRole = Literal["authoritative", "hot-cache", "compatibility"]


@dataclass(frozen=True, slots=True)
class PersistenceDomain:
    name: str
    truth_role: TruthRole
    target_backend: StorageTarget
    current_backend: StorageTarget
    current_tables: tuple[str, ...]
    current_services: tuple[str, ...]
    notes: str


PERSISTENCE_DOMAINS: tuple[PersistenceDomain, ...] = (
    PersistenceDomain(
        name="run-tracking",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("simulation_runs",),
        current_services=(
            "services/simulation_run_service.py",
            "services/run_context.py",
            "services/sim_clock.py",
        ),
        notes="One run_id should represent one full simulation session.",
    ),
    PersistenceDomain(
        name="trading-facts",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("orders", "order_events", "trades", "ledgers"),
        current_services=(
            "services/order_service.py",
            "services/order_persistence_service.py",
            "services/trade_persistence_service.py",
            "services/account_service.py",
            "services/account_persistence_service.py",
        ),
        notes="Core order/trade/ledger facts should migrate as a unit, not piecemeal.",
    ),
    PersistenceDomain(
        name="account-state",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("accounts", "positions", "agent_bindings", "instruments"),
        current_services=(
            "services/account_service.py",
            "services/agent_binding_service.py",
            "services/instrument_service.py",
            "services/instrument_runtime_service.py",
            "services/runtime_query_service.py",
            "services/runtime_command_service.py",
        ),
        notes="These tables are current truth on a temporary backend, not disposable legacy data.",
    ),
    PersistenceDomain(
        name="historical-market-facts",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("snapshots_1s", "bars_1m", "bars_1h", "bars_1d"),
        current_services=(
            "services/snapshot_listener.py",
            "services/bar_aggregator.py",
            "services/run_persistence_query_service.py",
            "services/replay_service.py",
            "services/recovery_service.py",
        ),
        notes="Persisted history must remain queryable for replay/recovery even after realtime cache is introduced.",
    ),
    PersistenceDomain(
        name="event-log",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("event_log",),
        current_services=(
            "services/event_persistence_service.py",
            "services/replay_service.py",
            "services/recovery_service.py",
        ),
        notes="Event log stays relational truth even if delivery later uses Redis streams/pubsub.",
    ),
    PersistenceDomain(
        name="equity-snapshots",
        truth_role="authoritative",
        target_backend="postgresql",
        current_backend="postgresql",
        current_tables=("account_equity_snapshots",),
        current_services=(
            "services/account_service.py",
            "services/account_persistence_service.py",
        ),
        notes="Write timing should be standardized before backend migration.",
    ),
    PersistenceDomain(
        name="realtime-hot-state",
        truth_role="hot-cache",
        target_backend="redis",
        current_backend="postgresql",
        current_tables=(),
        current_services=(
            "services/runtime_query_service.py",
            "services/market_data_query_service.py",
            "services/snapshot_listener.py",
            "services/bar_aggregator.py",
            "app/event_bridge.py",
        ),
        notes="Hot state is still served from the relational runtime path; Redis should be introduced only after PostgreSQL truth boundaries are stable.",
    ),
    PersistenceDomain(
        name="compatibility-dev-store",
        truth_role="compatibility",
        target_backend="sqlite",
        current_backend="sqlite",
        current_tables=(
            "accounts",
            "positions",
            "orders",
            "order_events",
            "trades",
            "ledgers",
            "event_log",
            "snapshots_1s",
            "bars_1m",
            "bars_1h",
            "bars_1d",
            "simulation_runs",
            "account_equity_snapshots",
        ),
        current_services=(
            "persistence/models_imports.py",
            "persistence/models_init.py",
        ),
        notes="SQLite remains an explicit compatibility backend for tests/dev diagnostics, not the default runtime store.",
    ),
)


def list_persistence_domains() -> Sequence[PersistenceDomain]:
    return PERSISTENCE_DOMAINS


def get_persistence_domain(name: str) -> PersistenceDomain | None:
    normalized = str(name or "").strip().lower()
    for domain in PERSISTENCE_DOMAINS:
        if domain.name == normalized:
            return domain
    return None


__all__ = [
    "PersistenceDomain",
    "PERSISTENCE_DOMAINS",
    "list_persistence_domains",
    "get_persistence_domain",
]
