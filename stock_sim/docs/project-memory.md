# Project Memory

## Stable conclusions

- `app/ui/main_window.py` is the intended single real frontend window structure.
- `app/main.py` is being reduced to a temporary compatibility/entry wrapper and should eventually be removable.
- Market detail currently combines multiple data paths rather than one unified source:
  - snapshot/order book path
  - bars/K-line path
  - trades path
  - holdings path
- Instrument creation is a real backend mutation that creates/registers engine state.
- `services/order_service.py` is the real order lifecycle orchestrator.
- Backend account freeze/refund/settlement semantics matter; frontend simplification must not ignore them.

## Current long-term refactor direction

1. unify MainWindow ownership in `app/ui/main_window.py`
2. shrink and retire `app/main.py`
3. document and stabilize Market detail field contracts
4. lock key user flows with regression tests
5. keep docs synchronized while structural cleanup advances
6. only then push larger GUI/K-line fixes with confidence

## 2026-03-20 route update

A formal convergence roadmap is now recorded in `docs/rollout_plan.md`.
Current execution order:

1. structure convergence
2. data-contract convergence
3. responsibility-boundary convergence
4. critical-path regression coverage
5. documentation / naming convergence

## 2026-03-22 storage route update

A formal storage-layer recommendation is now recorded in `docs/data/data-layering-design.md`.
A table-level storage mapping is now recorded in `docs/data/data-layering-table-plan.md`.
Current recommended direction:

1. PostgreSQL as the authoritative runtime business store
2. Redis as the hot-state / real-time cache layer
3. SQLite retained for dev/test/demo only
4. dynamic history should be split into current-state tables, snapshot tables, and event/history tables
5. instrument trading semantics such as `settlement_cycle` must follow explicit configured truth, not symbol-guess defaults
6. future storage work should use the table-plan document as the concrete migration blueprint
7. `simulation_runs` design is now recorded in `docs/data/simulation-runs-design.md` as the first concrete new-table draft
8. `account_equity_snapshots` design is now recorded in `docs/data/account-equity-snapshots-design.md` as the matching equity-history table draft
9. `run_id` wiring / migration strategy is now recorded in `docs/data/run-id-wiring-plan.md` as the concrete bridge from new run-level tables to existing runtime fact tables
10. `RunContext` runtime bridge design is now recorded in `docs/data/run-context-design.md` as the execution-time companion to the run_id storage plan
11. the first concrete implementation bridge is now recorded in `docs/data/minimal-run-context-integration-plan.md`, focusing on orders / trades / ledgers / order_events as the minimum viable run_id path
10. `RunContext` is now recorded in `docs/data/run-context-design.md` as the runtime bridge that should carry run identity through services

## 2026-03-23 compatibility convergence update

- `app.headless` is now the dedicated owner of headless frontend compatibility behavior.
- `HeadlessMainWindow` no longer lives in `app.main`.
- headless tests and headless e2e flows now prefer `app.headless.run_headless_frontend()`.
- `run_headless_frontend()` now attempts `register_ui_adapters()` before falling back to placeholders, preserving the meaning of headless as "no GUI event loop" rather than "logicless mode".
- `_DEFAULT_PRELOAD` has been retired from `app.main`; preload ownership now lives with `app.ui.main_window.DEFAULT_PRELOAD_PANELS`.
- `setup_frontend_entry.py` has now absorbed product-facing GUI startup locally and no longer imports `app.main` as a GUI fallback.
- dependency verification confirmed no internal project code still imports `app.main`; it has now been deleted, leaving `setup_frontend_entry.py` as the product-facing GUI entry and `app.headless` as the dedicated headless surface.
- Backend run-scoped platform work now also covers market-state derivative layers: snapshot rows carry `run_id`, bar models (`bars_1m / 1h / 1d`) carry `run_id`, replay/run-report expose bar-family persisted facts, and recovery treats missing `bars_1m` as a severe gap while treating missing `1h / 1d` bars as warning-level gaps.

## 2026-03-23 account-orders semantic convergence update

- The frontend account contract now explicitly emphasizes `frozen_cash` and `frozen_fee` as runtime-significant summary fields.
- The account adapter now surfaces `frozen_cash`, `frozen_fee`, `frozen_qty`, `borrowed_qty`, and `exposure_state` more directly instead of burying them behind a generic summary view.
- Orders lines now carry lifecycle/account-impact semantics (`lifecycle_summary`, `account_semantic_hint`, `account_effect_summary`) so the frontend can explain what order events likely mean for account state.
- Current working strategy: strengthen Account / Orders logic contracts first, then return later to unstable adapter-level integration timing issues.

## 2026-03-23 workspace/layout semantic convergence update

- Symbol detail is now treated more explicitly as a workspace-page concept rather than a dynamic panel remnant.
- `MainWindow` now tracks the last active non-symbol page to stabilize detail-page return behavior.
- Re-opening an existing workspace page now re-activates that page instead of merely returning the old object.
- Layout persistence has started converging away from raw dock/panel-open state and toward primary workspace-page state.
- Current first-phase persistence policy: restore main workspace pages and `active_page`, but do not auto-restore dynamic `symbol:*` pages yet.
