"""Executable migration checklist for storage evolution.

This module captures the recommended order for moving from the current
compatibility persistence stack toward the intended PostgreSQL + Redis layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


MigrationStatus = Literal["planned", "in_progress", "ready", "blocked"]


@dataclass(frozen=True, slots=True)
class MigrationStep:
    phase: int
    domain: str
    target_backend: str
    goal: str
    prerequisites: tuple[str, ...]
    deliverables: tuple[str, ...]
    acceptance: tuple[str, ...]
    status: MigrationStatus = "planned"


PERSISTENCE_MIGRATION_PLAN: tuple[MigrationStep, ...] = (
    MigrationStep(
        phase=1,
        domain="run-tracking",
        target_backend="postgresql",
        goal="Stabilize run identity semantics before backend replacement.",
        prerequisites=(
            "run_id means one full simulation session",
            "sim_day and sim_dt advance within a stable run_id",
            "RunContext remains explicit in runtime services",
        ),
        deliverables=(
            "Complete run_id propagation for newly persisted rows",
            "Normalize simulation_runs lifecycle transitions",
            "Keep current SQLite compatibility path working",
        ),
        acceptance=(
            "simulation_runs reflects current session state consistently",
            "No rotating run_id within one active simulation session",
        ),
        status="ready",
    ),
    MigrationStep(
        phase=2,
        domain="trading-facts",
        target_backend="postgresql",
        goal="Move order/trade/ledger persistence behind stable repositories first.",
        prerequisites=(
            "OrderService writes go through persistence collaborators",
            "AccountService ledger/equity writes go through persistence collaborators",
            "Replay/recovery still validate against current persisted facts",
        ),
        deliverables=(
            "Repository-backed writes for orders/order_events/trades/ledgers",
            "Migration-safe schema contract for trading fact tables",
            "Run-scoped integrity checks preserved",
        ),
        acceptance=(
            "Order/trade/ledger writes no longer require orchestration code changes when backend swaps",
            "Replay/recovery reports stay behaviorally unchanged",
        ),
        status="ready",
    ),
    MigrationStep(
        phase=3,
        domain="account-state",
        target_backend="postgresql",
        goal="Migrate current truth tables for account/instrument state to PostgreSQL authority.",
        prerequisites=(
            "trading-facts persistence boundary exists",
            "current truth semantics for accounts/positions/instruments are frozen",
            "agent bindings remain relational truth",
        ),
        deliverables=(
            "PostgreSQL-backed repositories for accounts/positions/agent_bindings/instruments",
            "Compatibility fallback kept for dev/demo SQLite mode",
            "Current runtime query services retargeted through repositories",
        ),
        acceptance=(
            "Current state reads/writes work without direct SessionLocal coupling in app-facing paths",
            "SQLite remains optional compatibility backend rather than primary authority",
        ),
        status="planned",
    ),
    MigrationStep(
        phase=4,
        domain="historical-market-facts",
        target_backend="postgresql",
        goal="Move persisted snapshots/bars to PostgreSQL without breaking replay or chart history.",
        prerequisites=(
            "run-scoped historical fact queries are isolated",
            "snapshot_listener/bar_aggregator stay on persisted relational facts",
            "detail chart history still loads from persisted bars",
        ),
        deliverables=(
            "Repository-backed snapshot/bar persistence",
            "Replay/recovery fact queries pointed at PostgreSQL",
            "Historical chart load path remains compatible",
        ),
        acceptance=(
            "Replay validation still sees the same facts by run_id",
            "Market detail history remains queryable after backend swap",
        ),
        status="planned",
    ),
    MigrationStep(
        phase=5,
        domain="event-log",
        target_backend="postgresql",
        goal="Keep event log as relational truth while preparing realtime delivery separation.",
        prerequisites=(
            "run_id propagation is stable",
            "event persistence remains append-oriented",
        ),
        deliverables=(
            "Repository-backed event log writer",
            "Replay loader pointed at abstracted event store",
        ),
        acceptance=(
            "ReplayService no longer depends directly on raw SQLAlchemy EventLog queries",
            "Event log stays authoritative for audit/replay",
        ),
        status="planned",
    ),
    MigrationStep(
        phase=6,
        domain="equity-snapshots",
        target_backend="postgresql",
        goal="Standardize equity snapshot timing before production backend migration.",
        prerequisites=(
            "account persistence collaborator exists",
            "snapshot write timing policy is agreed",
        ),
        deliverables=(
            "Documented minimum write policy",
            "Repository-backed equity snapshot writer",
            "Run-scoped snapshot query support",
        ),
        acceptance=(
            "Equity snapshots are written on settlement and risk events",
            "Leaderboard/reporting can depend on persisted equity snapshots",
        ),
        status="planned",
    ),
    MigrationStep(
        phase=7,
        domain="realtime-hot-state",
        target_backend="redis",
        goal="Introduce Redis only after relational truth boundaries are stable.",
        prerequisites=(
            "PostgreSQL authority exists for truth tables",
            "runtime query/write interfaces are stable",
            "no competing truth ownership between cache and relational store",
        ),
        deliverables=(
            "Redis-backed latest snapshot and latest bar cache",
            "Redis-backed leaderboard/clock hot state",
            "UI delivery paths pointed at cache while truth remains relational",
        ),
        acceptance=(
            "Realtime UI can be served from Redis without changing business truth semantics",
            "Cache loss does not destroy replay/recovery or authoritative facts",
        ),
        status="planned",
    ),
    MigrationStep(
        phase=8,
        domain="compatibility-dev-store",
        target_backend="sqlite",
        goal="Downgrade SQLite to compatibility-only mode after formal backends are live.",
        prerequisites=(
            "PostgreSQL truth path works",
            "Redis hot-state path works where needed",
            "dev/test/demo scenarios still need lightweight local mode",
        ),
        deliverables=(
            "SQLite compatibility profile for tests/demo/export",
            "No production/runtime assumptions tied to SQLite locking behavior",
        ),
        acceptance=(
            "Project can run in formal backend mode without SQLite assumptions",
            "SQLite remains useful for tests and demos only",
        ),
        status="planned",
    ),
)


def list_migration_steps() -> Sequence[MigrationStep]:
    return PERSISTENCE_MIGRATION_PLAN


def list_ready_steps() -> tuple[MigrationStep, ...]:
    return tuple(step for step in PERSISTENCE_MIGRATION_PLAN if step.status == "ready")


__all__ = [
    "MigrationStep",
    "PERSISTENCE_MIGRATION_PLAN",
    "list_migration_steps",
    "list_ready_steps",
]
