# Backend Phase-1 Progress And Next Backlog

_Last updated: 2026-03-24_

## Phase-1 goal

Build the minimum backend platform base for:
- run identity
- event persistence
- recovery
- replay
- equity history

---

## What is done

### 1. Run identity
Done:
- `services/run_context.py`
- `run_id` wired into:
  - `orders`
  - `order_events`
  - `trades`
  - `ledgers`
- `OrderService` accepts `run_context`
- `AccountService` accepts `run_context`

### 2. Equity history
Done:
- `persistence/models_account_equity_snapshot.py`
- basic equity snapshot write path in `AccountService`
- snapshots bind to `run_id`

### 3. Event log base
Done:
- `event_log` now stores:
  - `run_id`
  - `sim_day`
  - `sim_dt`
  - `ts_ms`
- `event_persistence_service` moved to generic event-bus persistence hook
- key payload normalization started across runtime paths

### 4. Recovery base
Done:
- `recovery_service` is no longer stub-only
- recovery returns report
- readonly degrade path exists
- simple consistency checks exist
- run-scoped inconsistency reporting exists

### 5. Replay base
Done:
- replay supports `run_id`
- replay supports `sim_day` filter
- replay supports `dry_run_summary()`
- replay/recovery have minimal integration coverage

---

## What is only partially done

### A. Event payload normalization
Partial:
- order/account/trade payloads improved
- `SIM_DAY`, `IPO_OPENED`, `BAR_UPDATED` improved
- snapshot family only partially converged

### B. Recovery quality
Partial:
- current checks are count-based
- not yet full fact reconstruction
- not yet checkpoint-based

### C. Replay quality
Partial:
- replay is event-based, not state-rebuild-based
- not yet validating rebuilt state vs persisted facts
- `sim_dt` filtering exists for datetime and ISO-string bounds; richer rebuilt-state validation is still pending

### D. Equity snapshot policy
Partial:
- write path exists
- trigger policy still minimal
- batching/throttling not designed yet

---

## Current backend judgment

### Stronger now
- backend platform traceability
- run-scoped persistence
- event-time model
- recovery safety posture
- replay visibility

### Still weaker
- snapshot-event family completeness
- strict recovery correctness
- full replay verification
- event payload consistency across all runtime families

---

## Phase-2 candidate backlog

## P0

### BL-201 snapshot family convergence
Goal:
- finish `SNAPSHOT_UPDATED` contract normalization
- clarify snapshot event vs persisted snapshot row ownership
- add stable snapshot replay checks

Files likely:
- `services/snapshot_listener.py`
- `services/market_data_service.py`
- snapshot-related tests
- snapshot docs/contracts

### BL-202 recovery precision upgrade
Goal:
- move from count mismatch to fact-level checks
- compare orders / trades / ledgers / event_log more precisely by `run_id`
- prepare checkpoint-based restore input

Files likely:
- `services/recovery_service.py`
- `services/replay_service.py`
- recovery/replay tests

### BL-203 replay verification upgrade
Goal:
- keep `sim_dt` filtering covered and extend it into operator-facing validation
- compare replay summary against persisted facts
- add run-level verification report

Files likely:
- `services/replay_service.py`
- replay tests
- docs/tasks/runtime/*

---

## P1

### BL-204 remaining event-family normalization
Goal:
- normalize payloads for:
  - `BORROW_FEE_ACCRUED`
  - `LIQUIDATION_TRIGGERED`
  - `CONFIG_CHANGED`
  - snapshot-adjacent market events

### BL-205 equity snapshot trigger policy
Goal:
- define when snapshots are written
- reduce over-write risk
- decide batch/throttle strategy

### BL-206 recovery markers / checkpoints
Goal:
- introduce explicit recovery markers
- make recovery input less implicit

---

## P2

### BL-207 replay + recovery operator tooling
Goal:
- CLI/report output for run inspection
- concise run health summary
- easier operator debugging

### BL-208 simulation-runs table integration
Goal:
- connect `RunContext` / event_log / replay / recovery to `simulation_runs`
- make run lifecycle more explicit in persistence

---

## Recommended immediate next step

Best next move:
- finish snapshot family convergence first
- then upgrade recovery/replay precision together

Reason:
- snapshot events are the clearest remaining hole in the event platform layer
- replay and recovery will become much more useful once snapshot events are cleaner

---

## Keep / avoid

Keep:
- short docs
- run-scoped thinking
- simulation-time vs wall-clock separation
- test-first stabilization for platform paths

Avoid:
- large refactor of `OrderService` during this phase
- mixing GUI fixes into backend platform work
- pretending snapshot event chain is fully solved before tests are stable
