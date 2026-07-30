# Data Architecture Review

_Last updated: 2026-03-28_

## Scope

This review compares the intended storage design in `docs/data/` against the
current runtime/backend implementation.

Reviewed inputs:

- `docs/data/data-layering-design.md`
- `docs/data/data-layering-table-plan.md`
- `docs/data/run-context-design.md`
- `docs/data/simulation-runs-design.md`
- `docs/data/account-equity-snapshots-design.md`

Reviewed code paths:

- `services/order_service.py`
- `services/account_service.py`
- `services/simulation_run_service.py`
- `services/runtime_query_service.py`
- `services/runtime_command_service.py`
- `services/event_persistence_service.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `services/recovery_service.py`
- `services/replay_service.py`
- `services/sim_clock.py`

## Overall Judgment

The direction in `docs/data/` is correct.

The project should keep:

- PostgreSQL as the future authoritative business store
- Redis as the future hot/cache/realtime layer
- SQLite as the current dev/test/demo compatibility layer

The main issue is not design direction. The main issue is migration sequencing.

Right now the project still depends on the existing SQLAlchemy + local database
persistence chain for:

- orders / order events / trades / ledgers
- accounts / positions / agent bindings / instruments
- snapshots / bars
- replay / recovery
- simulation runs
- account equity snapshots

So the current persistence layer is not deletable yet. It is still load-bearing.

## What Is Already Good

These parts of the design are already strong and should be preserved:

- Clear three-layer split: PostgreSQL / Redis / SQLite
- `RunContext` as the explicit runtime identity carrier
- `simulation_runs` as the anchor for run isolation
- `account_equity_snapshots` as a dedicated historical table instead of deriving everything from current account state
- Treating bars and snapshots differently from hot UI state
- Keeping replay/recovery tied to persisted facts rather than only in-memory state

## Recommended Optimizations

### 1. Add a migration stage model to the design docs

The design docs describe the target architecture well, but they do not separate:

- target-state architecture
- transition-state architecture

That distinction is needed now.

Recommended explicit stages:

- Stage A: current compatibility mode
  - SQLite remains the active runtime store
  - `run_id` may still be nullable in some tables
  - replay/recovery keep reading the current SQLAlchemy models
- Stage B: persistence abstraction mode
  - runtime code writes through a persistence gateway/repository boundary
  - storage backend becomes swappable without rewriting order/account logic
- Stage C: PostgreSQL authority mode
  - PostgreSQL becomes the authoritative store for business truth
  - SQLite remains only for tests/demo/export packages
- Stage D: Redis realtime mode
  - latest snapshot / latest bars / leaderboard / clock hot state move to Redis-backed delivery paths

Without these stages, the design can encourage premature deletion of the current store.

### 2. Define which existing tables are “temporary but authoritative”

Some current tables are temporary in technology choice, but authoritative in business semantics.

That should be stated explicitly for:

- `accounts`
- `positions`
- `orders`
- `order_events`
- `trades`
- `ledgers`
- `agent_bindings`
- `instruments`
- `simulation_runs`
- `account_equity_snapshots`

These are not legacy junk. They are current truth tables living on a temporary backend.

That means:

- schema meaning should be stabilized now
- storage backend can change later
- semantics should not be rewritten casually during migration

### 3. Make `run_id` rollout rules explicit

Current code already wires `run_id` into many models and services, but many columns remain nullable.

That is the right transition choice today.

The docs should explicitly state:

- Phase 1: `run_id` nullable for compatibility
- Phase 2: all newly created runtime rows should have `run_id`
- Phase 3: selected tables become `NOT NULL` for `run_id` in PostgreSQL mode

Suggested priority order:

1. `simulation_runs`
2. `orders`
3. `order_events`
4. `trades`
5. `ledgers`
6. `event_log`
7. `snapshots_1s`
8. `bars_*`
9. `account_equity_snapshots`

### 4. Separate “current state” and “historical fact” more sharply

The docs already move in this direction, but it should be stated as a hard rule:

- current-state tables:
  - `accounts`
  - `positions`
- immutable or append-heavy fact tables:
  - `orders`
  - `order_events`
  - `trades`
  - `ledgers`
  - `event_log`
  - `account_equity_snapshots`
  - `snapshots_1s`
  - `bars_*`

This matters because replay/recovery should trust fact tables more than reconstructed current state.

### 5. Add a persistence boundary before backend migration

This is the most important architectural optimization.

Before replacing SQLite with PostgreSQL/Redis in earnest, the backend should gain a dedicated persistence boundary for write/read operations.

Otherwise migration will require touching:

- `OrderService`
- `AccountService`
- replay/recovery
- snapshot/bar writers
- runtime query services

all at once.

Suggested boundary shape:

- write-side repositories / command persistence services
- read-side query services

This matches the direction already started with:

- `RuntimeCommandService`
- `RuntimeQueryService`
- `OrderInstrumentResolver`

The same idea should be applied one layer lower for persistence.

### 6. Delay Redis until truth boundaries are stable

Redis is in the right target architecture, but should not be introduced as a primary migration step.

Why:

- current truth ownership is still being clarified
- replay/recovery still rely on relational persisted facts
- introducing Redis too early risks creating two competing truths

Recommended order:

1. stabilize relational truth boundaries
2. stabilize `run_id` propagation
3. stabilize persistence interfaces
4. then add Redis as hot cache / delivery layer

### 7. Tighten `simulation_runs` semantics

The current docs are broadly right, but should be more explicit about one point:

- one `run_id` should identify one full simulation session
- it should not rotate during one running session
- `sim_day` advances within a `run_id`
- `sim_dt` advances within a `run_id`

That rule is already consistent with the recent runtime cleanup direction and should be written as non-negotiable semantics.

### 8. Make `account_equity_snapshots` write timing concrete

This table design is good, but the design docs should specify an initial minimum write policy.

Recommended minimum policy:

- write on end of settlement batch for touched accounts
- write on risk/liquidation events
- write on run end
- optionally write on daily close

Without a minimum write policy, the table design stays correct but operationally vague.

## What Should Not Be Deleted Yet

The following current persistence chain should not be removed now:

- SQLAlchemy models in `persistence/`
- `SessionLocal`
- `simulation_run_service.py`
- `event_persistence_service.py`
- `snapshot_listener.py`
- `bar_aggregator.py`
- `recovery_service.py`
- `replay_service.py`
- `account_service.py` persistence writes
- `order_service.py` persistence writes

Reason:

They are still required for runtime continuity, replay, recovery, and chart/history support.

## Safe Near-Term Strategy

The safe near-term strategy is:

1. Keep current persistence as the compatibility backend
2. Continue shrinking backend service responsibilities into clearer layers
3. Introduce persistence interfaces/repositories
4. Make `run_id` propagation complete
5. Migrate truth tables to PostgreSQL
6. Add Redis for hot realtime state
7. Downgrade SQLite to test/demo/export-only usage

## Bottom Line

The `docs/data` direction does not need a conceptual rewrite.

What it needs is stronger migration discipline:

- add transition stages
- mark current truth tables explicitly
- do not delete the current persistence backbone yet
- introduce a lower persistence boundary before swapping storage backends

That path keeps the project running while still converging toward the intended formal data architecture.

## Code Landing

To avoid leaving the migration plan only in prose, the current storage-domain map has also been landed in code:

- `services/persistence_topology.py`

That module groups current persistence responsibilities into migration domains such as:

- `run-tracking`
- `trading-facts`
- `account-state`
- `historical-market-facts`
- `event-log`
- `equity-snapshots`
- `realtime-hot-state`
- `compatibility-dev-store`

This is not a runtime backend switch yet. It is a code-side registry so future PostgreSQL / Redis migration work can hang off one explicit topology instead of being rediscovered from scattered services.

In addition, there is now a stable package-level persistence entrypoint:

- `services/persistence_layer/`

That package currently re-exports:

- read-side collaborators
- write-side collaborators
- topology metadata

So the migration path is no longer only “documented”; it also has a concrete code boundary to grow behind.

There is now also an executable migration checklist in code:

- `services/persistence_layer/migration_plan.py`

That module records:

- migration phases
- per-domain target backend
- prerequisites
- deliverables
- acceptance conditions

So the project now has both:

- a topology map
- an ordered migration plan
