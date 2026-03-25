# Backend Phase-1 Plan

_Last updated: 2026-03-24_

## Goal

Build the minimum platform backend base for UTI-STOCKSIM.

Focus:
1. `RunContext` / `run_id`
2. `event_log`
3. `recovery`
4. `replay`
5. `account_equity_snapshots`

---

## Scope

In scope:
- runtime backend
- persistence models
- runtime tests
- minimal docs sync

Out of scope:
- GUI polish
- Market detail UI repair
- broad `OrderService` refactor
- PostgreSQL/Redis full migration
- model bridge phase 2/3

---

## Why first

Current backend is strong on trading semantics.
Current backend is weak on platform continuity.

Main gaps:
- no stable run identity
- incomplete event persistence
- recovery is still stub-like
- replay base is weak
- equity history is not first-class

Without these, later work will be fragile.

---

## Deliverables

### D1. Run identity
- add `RunContext`
- wire `run_id` into:
  - `orders`
  - `order_events`
  - `trades`
  - `ledgers`
- make `OrderService` and `AccountService` accept `run_context`

### D2. Event log base
- persist key runtime events into `event_log`
- define minimal event payload rules
- support batch or buffered write path

### D3. Recovery base
- replace stub-only recovery path
- recover from persisted state + event facts
- enter readonly mode on recovery failure
- publish clear recovery events

### D4. Replay base
- replay by time range and optional `run_id`
- support dry-run mode
- support state rebuild validation

### D5. Equity snapshots
- add `account_equity_snapshots`
- write snapshots at controlled points
- bind snapshots to `run_id`

---

## Target files

### Runtime services
- `services/order_service.py`
- `services/account_service.py`
- `services/recovery_service.py`
- `services/replay_service.py`
- `services/event_persistence_service.py`
- `services/run_context.py`  *(new)*
- `services/account_equity_snapshot_service.py`  *(new, if needed)*

### Persistence
- `persistence/models_order.py`
- `persistence/models_order_event.py`
- `persistence/models_trade.py`
- `persistence/models_ledger.py`
- `persistence/models_event_log.py`
- `persistence/models_account_equity_snapshot.py`  *(new)*
- related imports / migration helpers

### Tests
- `tests/test_run_context_wiring.py`  *(new)*
- `tests/test_event_log_persistence.py`  *(new)*
- `tests/test_recovery_flow.py`  *(new or expand)*
- `tests/test_replay_flow.py`  *(new or expand)*
- `tests/test_account_equity_snapshots.py`  *(new)*

---

## Execution order

## Step 1. `RunContext`

### Goal
Give every runtime fact a run identity.

### Work
- create `RunContext` dataclass
- add `run_context=None` to `OrderService`
- add `run_context=None` to `AccountService`
- add helper `_get_run_id()`
- write `run_id` on:
  - order persist
  - order event persist
  - trade persist
  - ledger persist

### Done when
- services work with and without `run_context`
- new records carry `run_id`
- old paths still run when `run_context is None`

### Risk
- old tests may assume constructors without new param
- ORM writes may miss one branch

---

## Step 2. `account_equity_snapshots`

### Goal
Make account equity history first-class.

### Work
- add snapshot model
- define minimal fields:
  - `run_id`
  - `account_id`
  - `sim_day`
  - `sim_dt`
  - `cash`
  - `frozen_cash`
  - `market_value`
  - `gross_exposure`
  - `net_exposure`
  - `equity`
  - `drawdown`
  - `borrowed_notional`
- add writer service or helper
- write on controlled lifecycle points:
  - post-trade settle
  - end-of-step / end-of-batch
  - optional recovery checkpoint

### Done when
- snapshots can be queried by `run_id` and account
- account history no longer depends on ad hoc rebuild

### Risk
- over-frequent writes
- unclear snapshot trigger policy

---

## Step 3. `event_log`

### Goal
Make event persistence useful for replay and audit.

### Work
- expand persistence beyond `ACCOUNT_UPDATED`
- persist at least:
  - `ORDER_ACCEPTED`
  - `ORDER_REJECTED`
  - `ORDER_FILLED`
  - `ORDER_PARTIALLY_FILLED`
  - `ORDER_CANCELED`
  - `TRADE`
  - `ACCOUNT_UPDATED`
  - `SNAPSHOT_UPDATED`
  - `IPO_OPENED`
  - `SIM_DAY`
- add payload shape rules
- add `run_id` into payload when available
- reduce debug prints
- add failure metrics

### Done when
- key runtime events enter `event_log`
- replay can rely on event facts
- event persistence no longer looks test-only

### Risk
- duplicate writes
- event bus ordering assumptions
- payload drift

---

## Step 4. `recovery`

### Goal
Recover to a trustworthy runtime state.

### Work
- define recovery inputs:
  - latest durable account state
  - positions
  - open orders
  - event log tail
  - snapshots/checkpoints
- implement recovery report
- validate consistency on startup/resume
- switch to readonly mode if recovery fails
- publish:
  - `RECOVERY_FAILED`
  - `RECOVERY_RESUMED`

### Done when
- recovery is not only a stub
- readonly mode has real meaning
- resume path is testable

### Risk
- source-of-truth ambiguity
- mismatch between order tables and event log

---

## Step 5. `replay`

### Goal
Rebuild and verify runtime history.

### Work
- replay by time range
- replay by optional `run_id`
- dry-run mode
- compare rebuilt state with persisted state
- output minimal replay report

### Done when
- a run can be replayed for audit/debug
- replay can support recovery validation

### Risk
- missing event coverage
- non-deterministic side effects

---

## Minimal design rules

1. Runtime truth stays in runtime services.
2. New docs stay short, direct, file-scoped.
3. New write paths must be optional-safe for old flows.
4. `run_context=None` must remain valid.
5. Event payloads should be versionable later.
6. Snapshot triggers should be explicit, not hidden in UI paths.

---

## Test strategy

### T1. Run context wiring
- service with `run_context`
- new rows contain `run_id`
- service without `run_context` still works

### T2. Event log
- key events are persisted
- payload contains expected fields
- persistence failure increments metrics, does not silently corrupt state

### T3. Recovery
- normal recovery resumes
- inconsistent state enters readonly mode
- recovery result is inspectable

### T4. Replay
- replay dry-run works
- replay can filter by `run_id`
- replay summary matches expected counts

### T5. Equity snapshots
- snapshot rows are created at defined points
- rows bind to account + `run_id`
- history query is stable

---

## Current implementation status

Done in current step:
- added `services/run_context.py`
- added `persistence/models_account_equity_snapshot.py`
- added `run_id` to `orders / order_events / trades / ledgers`
- wired `run_context` into `OrderService` and `AccountService`
- added basic equity snapshot write path in `AccountService`
- added `tests/test_run_context_wiring.py`
- expanded `event_log` model with `run_id / sim_day / sim_dt`
- changed event persistence to hook the event bus directly instead of one-topic subscription only
- added event persistence regression coverage for trade-event run/scoped sim-time writes

Done in current step:
- added recovery report base with persisted-count checks
- added readonly degrade path for simple trade/ledger mismatch detection
- added recovery regression coverage for resumed/degraded behavior

Done in current step:
- upgraded replay service with `run_id` filtering
- added replay filtering by `sim_day`
- added `dry_run_summary()` for replay planning / validation
- added replay + recovery integration coverage with run-scoped event loading

Done in current step:
- normalized key runtime event payloads to carry `run_id` / `symbol` more explicitly
- tightened recovery from global mismatch checks toward run-scoped inconsistency reporting
- added regression checks for event payload run-id persistence and run-scoped degraded recovery reporting

Done in current step:
- normalized `SIM_DAY`, `IPO_OPENED`, and `BAR_UPDATED` payloads with simulation-time metadata
- added a lightweight replay/recovery cross-check in integration coverage
- validated replay `sim_day` filtering against persisted run-scoped events

Done in current step:
- normalized `SNAPSHOT_UPDATED` payloads with simulation-time metadata on the listener path
- added event-log coverage for snapshot-event persistence
- extended replay/recovery integration coverage so run-scoped replay sees persisted snapshot events

Not done yet:
- snapshot trigger policy refinement
- richer recovery source selection and checkpoint restore
- replay validation against reconstructed persisted state
- broader payload normalization for remaining runtime event families like borrow-fee / liquidation / config-change

---

## Acceptance criteria

Phase 1 is complete when:
- `run_id` is written through core runtime facts
- `account_equity_snapshots` exists and is used
- `event_log` covers key runtime events
- `recovery_service` has real recovery behavior
- `replay_service` can rebuild a run in dry-run mode
- tests exist for each area

---

## Suggested follow-up after this phase

1. split `OrderService` boundaries
2. harden app-layer vs runtime-layer boundaries
3. move storage plan toward PostgreSQL-first + Redis hot-state
4. add packaged-app diagnostics and startup smoke
