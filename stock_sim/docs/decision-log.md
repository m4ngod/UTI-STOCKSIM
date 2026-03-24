# Decision Log

## 2026-03-17 - MainWindow unification before larger GUI fixes

Decision:
- Prioritize MainWindow structural unification and compatibility-layer shrinkage before broad GUI/K-line fixes.

Why:
- The project currently has both structural duplication (`app/main.py` vs `app/ui/main_window.py`) and semantic split (Market detail uses multiple data paths).
- Fixing GUI symptoms first would risk papering over architecture problems.

Implication:
- Continue moving structural ownership to `app/ui/main_window.py`.
- Keep `app/main.py` only as a temporary wrapper during migration.

## 2026-03-17 - Module status notes should not use line numbers

Decision:
- Module work-status notes will not record line numbers.
- They will record first/last code lines for each modified fragment, plus total changed line count.

Why:
- Line numbers drift and become brittle.
- Code anchors are more durable for future continuation.

Implication:
- All module notes under `docs/current-work-status/` should follow the anchor-based format.

## 2026-03-22 - Future runtime storage should move to PostgreSQL + Redis layering

Decision:
- SQLite should remain a development / test / demo backend, not the long-term primary runtime store.
- PostgreSQL is the recommended authoritative business database.
- Redis is the recommended hot-state / real-time cache layer.

Why:
- The target system is evolving toward hundreds of retail traders, multiple agents, dynamic simulation speed, and long-lived historical analysis.
- SQLite lock behavior is already creating misleading failures in heavier runtime-style regression work.
- A layered model better separates authoritative data, high-frequency transient state, and development ergonomics.

Implication:
- New storage-facing design work should assume PostgreSQL compatibility first.
- High-frequency UI/runtime state should prefer Redis or cache/event paths instead of overloading the primary relational store.
- `docs/data/data-layering-design.md` is now the baseline storage architecture note for future work.
- `docs/data/data-layering-table-plan.md` is now the concrete table-level mapping note for future schema evolution.
- `docs/data/simulation-runs-design.md` is now the first concrete new-table design draft under that storage plan.
- `docs/data/account-equity-snapshots-design.md` is now the matching equity-history table design draft under the same storage plan.
- `docs/data/run-id-wiring-plan.md` is now the migration blueprint for attaching run-level identity to existing fact/history tables.
- `docs/data/run-context-design.md` is now the runtime bridge design for how that run-level identity should flow through services.
- `docs/data/minimal-run-context-integration-plan.md` is now the first implementation-focused bridge from storage/runtime design into a constrained code-change plan.
- `docs/data/run-context-design.md` is now the runtime-context design note that explains how run identity should flow through services.

## 2026-03-23 - Headless compatibility should live outside `app.main`

Decision:
- `app.headless` is now the intended owner of headless frontend compatibility behavior.
- `app.main` should continue shrinking toward a thin legacy GUI/entry wrapper rather than owning headless behavior.
- The `_DEFAULT_PRELOAD` compatibility alias in `app.main` should be retired rather than kept indefinitely.

Why:
- Headless test and e2e paths were still giving `app.main` too many reasons to remain a structural dependency.
- Headless mode semantically means "no GUI event loop", not "placeholder-only frontend".
- Keeping preload aliases and headless ownership in `app.main` would slow or blur final compatibility retirement.

Implication:
- Headless tests and headless e2e flows should prefer `app.headless.run_headless_frontend()`.
- `run_headless_frontend()` should still try to register UI adapters so headless flows can exercise logic-backed panels when possible.
- Remaining direct external `app.main` imports should be treated as compatibility exceptions and reduced toward entry-only usage.

## 2026-03-23 - Product/app entry should be localized in `setup_frontend_entry.py`

Decision:
- `setup_frontend_entry.py` should be treated as the product-facing frontend entry surface for future application packaging/distribution.
- GUI startup should be owned locally in `setup_frontend_entry.py` using the real `MainWindow`, not delegated back into `app.main`.
- `app.main` should no longer be required by external project code for normal startup paths.

Why:
- A packaged application should have a clear, honest startup path rather than a product entry that secretly routes through a historical compatibility wrapper.
- Keeping GUI fallback logic in `app.main` would blur release ownership and complicate future packaging/debugging work.
- By this point the project has already converged enough that the packaged entry can depend directly on `app.ui.main_window` and `app.headless`.

Implication:
- Future packaging or distribution work should target `setup_frontend_entry.py` (or a direct successor of the same role) as the canonical app entry.
- `app.main` entered deletion-staging once product entry and headless ownership moved away from it.
- On 2026-03-24, dependency verification confirmed no internal project code still imported it, so the file was deleted rather than kept as a compatibility wrapper.

## 2026-03-23 - Frontend Account / Orders should explain runtime lifecycle effects, not just display DTO/event data

Decision:
- The frontend Account view should remain DTO-led for now, but it must explicitly surface runtime-relevant fields such as `frozen_cash`, `frozen_fee`, `frozen_qty`, and `borrowed_qty`.
- The frontend Orders view should evolve from a raw event list toward a lifecycle/account-impact explanation surface.
- Flaky adapter/integration behavior should be treated as a separate UI/adapter problem, not as a reason to keep semantic contracts weak.

Why:
- A trading simulation platform cannot rely on generic portfolio-summary UI semantics without misleading the user about active order state.
- The backend runtime already carries richer freeze/release/short semantics than the older frontend expression path exposed.
- Strengthening logic/contract semantics first is safer than overfitting UI adapter timing behavior.

Implication:
- Account summary and position views should continue emphasizing runtime-significant fields.
- Orders lines should carry lifecycle summaries and account-effect hints that later adapters can render more clearly.
- Integration-level adapter instability should not block semantic contract convergence work.

## 2026-03-24 - Bar-family recovery severity should distinguish primary vs derived runtime market facts

Decision:
- `bars_1m` should be treated as the primary persisted bar-health layer because it is the nearest stable derivative of snapshot/runtime market facts.
- `bars_1h` and `bars_1d` should remain separately reported, but initially only as warning-level derived layers rather than degraded recovery gates.

Why:
- Treating all bar timeframes as equally severe would over-penalize higher-level aggregation drift.
- Ignoring `1h / 1d` entirely would make bar-family health too opaque.
- Separating primary-vs-derived severity keeps recovery honest without making it brittle.

Implication:
- Replay/run reports should expose `bars_1m / 1h / 1d` separately.
- Recovery may degrade when snapshots exist but `bars_1m` are missing for a run.
- Recovery should report missing `1h / 1d` bars as warnings, not full degraded failure.

## 2026-03-23 - Layout persistence should converge toward workspace-page state before any deep refactor

Decision:
- Layout persistence should stop treating old dock/panel-open state as the primary application-state truth.
- The first phase of convergence should persist primary workspace pages and the active non-symbol page, while excluding dynamic symbol-detail pages from auto-restore.
- Symbol detail should be treated as a workspace-page concept first, and only later evaluated for persistence policy.

Why:
- The frontend has already moved toward a workspace-page mental model, so persisting raw dock-open state would encode stale structure into future behavior.
- Dynamic symbol pages still have evolving lifecycle semantics; restoring them blindly would likely create confusing startup state.
- A deeper layout persistence rewrite should only happen after semantic boundaries are corrected.

Implication:
- Future layout work should build on workspace-page semantics, not on historical panel-open assumptions.
- `DockManager` should be treated increasingly as a supporting layer rather than the canonical app-state owner.
- The long-term question is no longer just how to save layout, but what the product considers part of a restorable workspace session.
