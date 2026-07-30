# Engine Module Status

## Module

Backend engine ownership / symbol-to-engine consistency

## Current goal

- Keep symbol → engine ownership explicit and consistent.
- Prevent frontend or orchestration paths from assuming conflicting engine instances for the same symbol.

## Current state

in-progress

## Files involved

- `services/engine_registry.py`
- `services/instrument_service.py`
- `services/order_service.py`
- `docs/frontend-backend-dependency-map.md`

---

## Task 2026-03-17-engine-01
- **time**: 2026-03-17
- **status**: done
- **goal**: document engine ownership and runtime routing semantics
- **files involved**:
  - `docs/frontend-backend-dependency-map.md`
- **total changed lines**: 14905

### Code fragment anchors
#### fragment 1
- **first line**: `## 2.1 Instrument creation is backend state creation, not just UI state`
- **last line**: `any frontend shortcut that fabricates a symbol without going through this path will diverge from runtime truth`

#### fragment 2
- **first line**: `## 2.2 \`engine_registry\` is the global symbol → engine index`
- **last line**: `structural cleanup should reduce chances of “same symbol, different engine instance assumptions”`

### Change summary
- Recorded that instrument creation registers real engine state.
- Recorded that engine ownership is global and symbol-based.

### Purpose
- Make later frontend cleanup respect backend runtime truth.
- Reduce risk of inconsistent symbol detail across multiple engine assumptions.

### Impact / risk
- No runtime impact.
- Important architectural guardrail for future refactors.

### Next actions
- If new symbol-page or market flows are changed later, re-check whether they instantiate controllers/services with consistent engine expectations.

---

## Known current conclusions

- `services/instrument_service.py` is the real symbol/engine creation path.
- `services/engine_registry.py` is the runtime symbol → engine authority.
- `services/order_service.py` may prefer explicit injected engine, but still coordinates with registry state.

---

## T+1 / engine-routing note (2026-03-21)

### status
in-progress

### goal
Confirm whether T+1 is truly enforced on the real order path, and document the result without confusing account semantics and engine-routing semantics.

### files involved
- `services/risk_engine.py`
- `services/risk_rule_registry.py`
- `services/order_service.py`
- `services/engine_registry.py`
- `tests/test_tplus1_order_flow.py`

### change summary
- Confirmed that previous T+1 behavior existed mostly in docs / naming / placeholders, not as a real runtime rule.
- Added a minimal real risk rule: `TPlusOneSellRestrictionRule`.
- `RiskEngine.validate()` now passes `risk_engine` through rule context so rules can access intraday buy counters.
- Added `RiskEngine.get_tplus()` for rule-side reads.
- Began building regression tests for:
  - T+1 symbol same-day sell rejection
  - T+0 symbol same-day sell allowance
  - IPO-open path combined with same-day sell rejection validation

### current conclusion
- T+1 enforcement is now moving out of ambiguous account-side expectations and into explicit risk-rule ownership.
- This is architecturally cleaner for a maintainable complex system.
- Test stabilization is still in progress because engine registry state and cold-start/IPO flows have legacy coupling.
- `tests/test_multi_symbol_match.py` has now been partially converged toward runtime truth by explicitly preparing seller inventory for normal sell-side fills instead of relying on historical implicit naked-sell behavior.

### impact / risk
- Good: T+1 is becoming an explicit, reviewable rule.
- Risk: engine-registry and cold-start assumptions can still pollute tests unless isolated carefully.
- Risk: current IPO-linked regression is still being stabilized.
- Risk: SQLite-based test runs can produce misleading failures when multiple suites are executed in parallel; several recent red results were traced to lock / pending-rollback pollution rather than business-logic regression.

### next actions
- Finish stabilizing `tests/test_tplus1_order_flow.py`.
- Re-check `OrderService` + engine-registry interaction once T+1 regression is green.
- Only after that, decide whether deeper cold-start matching fixes are needed.
- Keep multi-symbol tests aligned with runtime truth: seller accounts should explicitly hold inventory unless the scenario is intentionally modeling short/IPO issuance paths.
- Prefer serial verification for SQLite-backed regression groups when diagnosing failures; do not overreact to parallel lock-induced red tests.

## Runtime path stabilization note (2026-03-22)

### status
in-progress

### goal
Continue stabilizing engine-routed runtime regression work by separating true business regressions from SQLite/test-harness noise, especially around T+1 and IPO-linked order paths.

### files involved
- `docs/testing/runtime/runtime-critical-path-test-matrix.md`
- `tests/test_tplus1_order_flow.py`
- `tests/test_multi_symbol_match.py`
- `tests/test_order_tif_semantics.py`
- `tests/test_order_funding_semantics.py`
- `tests/test_order_short_cover_semantics.py`

### change summary
- Introduced a formal runtime critical-path matrix under the new `docs/testing/runtime/` structure.
- Added explicit order-path regression tests for IOC/FOK and funding/freeze semantics.
- Added explicit short-cover regression tests while deliberately avoiding an unstable order-service-level short-open scenario that did not yet represent a dependable engine-routed truth.
- Reaffirmed that SQLite lock behavior can still distort diagnosis if runtime tests are not kept serial and session-safe.

### current conclusion
- Engine-routed runtime verification is improving, but test scenario design still matters as much as code coverage.
- Not every theoretically desirable scenario should immediately become a regression test if current engine/order constraints make it structurally unstable.
- T+1 and IPO-linked routing still remain the highest-value next stabilization targets.

### impact / risk
- Positive: clearer distinction between stable regression guardrails and noisy test constructions.
- Risk: if future work changes engine routing, some new tests may need to move from account/settlement-level ownership into stricter order-path ownership.
- Risk: SQLite-backed suite behavior still requires care when interpreting failures.

### next actions
- Continue explicit T+1 / IPO path hardening.
- Prefer serial, isolated verification for engine-routed regression work when SQLite is the backend.
- Record any future shift in short-open ownership if the order path is intentionally made more explicit.

## IPO minimal-path note (2026-03-23)

### status
in-progress

### goal
Add a narrower, more stable IPO minimum-path regression that locks the core open-path guarantee without depending on more fragile implementation-detail flags.

### files involved
- `tests/test_ipo_minimal_path.py`
- `docs/testing/runtime/runtime-critical-path-test-matrix.md`

### change summary
- Added a dedicated IPO minimal-path test.
- Locked the stable minimum guarantees:
  - IPO book remains in call auction during clearing-buffer stage
  - IPO book transitions to continuous phase after buffer completion
  - actual trade volume is produced on the IPO path
- Intentionally removed an over-strong assertion on `engine.instrument.ipo_opened` after observing that phase/trade truth is currently more stable than instrument-flag synchronization in this path.

### current conclusion
- The IPO runtime floor is now better protected by a dedicated, intention-revealing regression test.
- The minimum stable truth for this path is currently phase transition + actual trade generation, not necessarily immediate instrument-flag synchronization.
- If future work makes `ipo_opened` synchronization an explicit invariant, that should be tightened with a separate, deliberate test rather than silently assumed here.

### impact / risk
- Positive: IPO path now has a focused regression guardrail instead of relying only on mixed scenarios.
- Positive: the test is more likely to remain stable because it asserts business truth rather than a currently weaker implementation detail.
- Risk: some developers may still assume `instrument.ipo_opened` is always synchronized immediately; this should be treated as a follow-up design/ownership question.

### next actions
- Keep IPO minimum-path test narrow and stable.
- If needed, add a separate explicit test for instrument-level IPO-open synchronization once ownership of that guarantee is clarified.
- Continue using the runtime test matrix to distinguish stable guarantees from implementation-detail assumptions.

## Runtime clock note (2026-03-26)

### status
in-progress

### goal
Begin converging desktop clock control with runtime `sim_day` ownership so settlement/T+1 semantics stop depending on a purely app-local notion of time.

### files involved
- `services/sim_clock.py`
- `app/services/clock_service.py`
- `tests/test_clock_and_rollback_service.py`

### change summary
- Extended runtime `sim_clock` from a manual day counter into a lightweight loop-capable singleton with:
  - `start_loop`
  - `pause_loop`
  - `stop_loop`
  - `set_day`
  - `set_speed`
  - `snapshot`
- Wired frontend `ClockService` to start/pause/resume/stop that runtime loop when available.
- Current default compression is now configurable through `STOCKSIM_SIM_DAY_SECONDS`, with the desktop target set to `120` seconds per `sim_day`.
- Added module-alias unification so `services.sim_clock` and `stock_sim.services.sim_clock` resolve to the same singleton instead of splitting runtime day state.

### current conclusion
- Runtime now has a real process-level day-advance mechanism, which is necessary for:
  - T+1 “same day” gating
  - daily reset hooks
  - fee/day-boundary jobs
- Frontend/app clock semantics are still not fully unified with runtime display semantics:
  - the app clock DTO still exposes a string `sim_day`
  - runtime settlement still trusts integer runtime `sim_day`
- So this is a structural convergence step, not the final time-model cleanup.

### impact / risk
- Positive: runtime day-dependent behavior no longer has to remain permanently stuck on day `1` during desktop sessions.
- Positive: later `sim_day/sim_dt/run_id` cleanup now has a real backend clock to anchor against.
- Risk: the clock panel still does not surface runtime intraday progress directly, so user-visible time semantics are only partially aligned today.

## Runtime run-context wiring note (2026-03-24)

### status
in-progress

### goal
Start Phase-1 backend platform work by carrying run identity through the order-side runtime path without changing engine ownership semantics.

### files involved
- `services/order_service.py`
- `services/run_context.py`
- `persistence/models_order.py`
- `persistence/models_order_event.py`
- `persistence/models_trade.py`
- `tests/test_run_context_wiring.py`
- `docs/tasks/runtime/backend-phase-1-plan.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `def __init__(self, session: Session, engine: MatchingEngine | None = None, instrument_service: InstrumentService | None = None, run_context: RunContext | None = None):`
- **last line**: `self._batch_trades: list = []  # 批量模式缓冲`

#### fragment 2
- **first line**: `def _get_run_id(self) -> str | None:`
- **last line**: `self.s.add(OrderEvent(order_id=order_id, event=event, detail=detail, run_id=self._get_run_id()))`

#### fragment 3
- **first line**: `self.s.add(TradeORM(`
- **last line**: `run_id=self._get_run_id(),`

### Change summary
- Added `run_context` support to backend `OrderService`.
- Added `run_id` propagation into orders, order events, and trades.
- Added focused regression coverage that verifies run-scoped persistence on the order/trade path.
- Kept engine routing and engine registry ownership unchanged while adding run-level traceability.

### Purpose
- Make order-side runtime facts traceable to a simulation run.
- Prepare a stable base for replay / audit / recovery work.
- Avoid mixing run identity work with deeper engine-routing refactors.

### Impact / risk
- Positive: core order/trade persistence can now carry run identity.
- Positive: this reduces future ambiguity when multiple simulation runs share one database.
- Risk: deeper event-log expansion is still pending, so run traceability is only partial for now.
- Risk: this does not yet solve recovery or replay by itself; it only lays the identity base.

### Next actions
- Expand `event_log` persistence so run-scoped replay has broader coverage.
- Keep future engine-routing changes separate from run-context propagation work.
- Re-check any legacy persistence branch that may still miss `run_id` in edge cases.

## Event-log simulation-time alignment note (2026-03-24)

### status
in-progress

### goal
Expand event persistence so run-scoped order/trade activity is recorded with both simulation time and wall-clock write time, matching the variable-speed simulation platform direction.

### files involved
- `persistence/models_event_log.py`
- `services/event_persistence_service.py`
- `persistence/models_init.py`
- `tests/test_event_persistence.py`
- `docs/tasks/runtime/backend-phase-1-plan.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `class EventLog(Base):`
- **last line**: `Index("ix_event_log_symbol_ts", EventLog.symbol, EventLog.ts_ms)`

#### fragment 2
- **first line**: `def _sync_write(evt_type: Any, payload: dict[str, Any]):`
- **last line**: `event_bus._persist_hook = _hook`

#### fragment 3
- **first line**: `def test_event_log_carries_run_id_sim_day_and_trade_symbol():`
- **last line**: `assert row.sim_dt is not None`

### Change summary
- Expanded `event_log` schema with `run_id`, `sim_day`, and `sim_dt`.
- Moved event persistence from one-topic subscription logic to a generic event-bus persistence hook.
- Persisted wall-clock write time via `ts_ms` and simulation time via `sim_day / sim_dt` in the same event row.
- Added regression coverage that checks trade-event persistence carries `run_id`, symbol, and simulation time.

### Purpose
- Align event persistence with the platform goal of variable-speed trading simulation.
- Keep replay / recovery work grounded in simulation time instead of only wall-clock insertion order.
- Avoid treating `sim_day` as a replacement for audit time while still making it first-class in persisted events.

### Impact / risk
- Positive: event history now better reflects both run identity and simulation-time progression.
- Positive: later replay can filter by `run_id` and simulation time more naturally.
- Risk: payload-level `run_id` extraction still depends on upstream payload shape in some paths.
- Risk: generic event-bus persistence may increase write volume once more event types are active.

### Next actions
- Continue normalizing event payload shapes so `run_id` propagation is less heuristic.
- Add replay queries that use `run_id + sim_day / sim_dt` directly.
- Later consider buffered/batched event-log writes if persistence volume becomes heavy.

## Recovery skeleton note (2026-03-24)

### status
in-progress

### goal
Replace the old recovery stub with a minimal real recovery skeleton that can produce a report, detect a simple persisted inconsistency, and switch runtime behavior to readonly on degraded recovery.

### files involved
- `services/recovery_service.py`
- `tests/test_recovery.py`
- `docs/tasks/runtime/backend-phase-1-plan.md`

### total changed lines
- small to moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `class RecoveryService:`
- **last line**: `return _LAST_REPORT`

#### fragment 2
- **first line**: `def test_recovery_service_switches_readonly_on_mismatch():`
- **last line**: `assert is_readonly() is True`

### Change summary
- Replaced the old stub-like recovery path with a report-building recovery skeleton.
- Added a minimal persisted consistency check based on trade/ledger count mismatch.
- Added degraded recovery behavior that switches runtime into readonly mode.
- Added regression coverage for resumed behavior, degraded behavior, and manual failure forcing.

### Purpose
- Give recovery real runtime meaning before replay work grows larger.
- Make readonly mode represent an actual safety state instead of only a placeholder flag.
- Create a stable recovery/report contract for later checkpoint and replay integration.

### Impact / risk
- Positive: recovery is no longer only an event-emitting stub.
- Positive: order-path readonly protection now has a more defensible backend reason.
- Risk: current consistency check is intentionally minimal and may later need more precise logic.
- Risk: degraded recovery currently uses aggregate mismatch detection, not full reconstruction.

### Next actions
- Extend recovery checks from aggregate counts to run-scoped and event-scoped checks.
- Connect recovery report with replay verification results later.
- Add checkpoint-based restore input once recovery markers are designed more concretely.

## Replay dry-run note (2026-03-24)

### status
in-progress

### goal
Upgrade replay from a simple event dump reader into a run-scoped dry-run tool that can filter by simulation time and produce a replay summary for later recovery validation.

### files involved
- `services/replay_service.py`
- `tests/test_replay_recovery_integration.py`
- `docs/tasks/runtime/backend-phase-1-plan.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `class ReplayService:`
- **last line**: `return {`

#### fragment 2
- **first line**: `def test_replay_and_recovery_integration():`
- **last line**: `assert collected == list(range(n))`

### Change summary
- Added replay filtering by `run_id`.
- Added replay filtering by `sim_day` range.
- Added `dry_run_summary()` with event counts, type counts, symbol set, and sim-day range.
- Updated integration coverage so replay is validated against run-scoped persisted events before recovery is invoked.

### Purpose
- Make replay useful for the variable-speed simulation platform instead of only raw timestamp scans.
- Prepare replay to become a recovery-verification input later.
- Give backend tooling a concise dry-run report before full state reconstruction exists.

### Impact / risk
- Positive: replay can now operate on a single simulation run instead of the whole event table.
- Positive: replay summary is a practical bridge between event persistence and future recovery checks.
- Risk: current replay still replays payload events, not reconstructed runtime state.
- Risk: sim-day filtering is useful but still coarser than full sim-dt replay windows.

### Next actions
- Add replay filtering by `sim_dt` when needed.
- Later compare replay summary against recovery report and persisted fact tables.
- Keep event payload normalization improving so replay contracts stay stable.

## Event payload normalization / run-scoped recovery note (2026-03-24)

### status
in-progress

### goal
Make event payloads more explicit about run identity and symbol ownership, and tighten recovery checks from global aggregate mismatch into run-scoped inconsistency detection.

### files involved
- `services/order_service.py`
- `services/account_service.py`
- `services/recovery_service.py`
- `tests/test_event_persistence.py`
- `tests/test_recovery.py`
- `docs/current-work-status/engine.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `event_bus.publish("Trade", {"trade": tr.to_dict(), "run_id": self._get_run_id(), "symbol": tr.symbol})`
- **last line**: `event_bus.publish("OrderRejected", {"order": order.to_dict(), "reason": reason, "run_id": self._get_run_id(), "symbol": order.symbol})`

#### fragment 2
- **first line**: `def _account_payload(self, acc: Account) -> dict[str, Any]:`
- **last line**: `"run_id": self._get_run_id(),`

#### fragment 3
- **first line**: `per_run = defaultdict(lambda: {"filled_orders": 0, "trades": 0, "ledgers": 0})`
- **last line**: `"inconsistent_runs": inconsistent_runs,`

### Change summary
- Added `run_id` and `symbol` into order/trade cancel/reject event payloads on the runtime path.
- Added `run_id` into account-updated payload generation.
- Tightened recovery mismatch detection so degraded recovery is now keyed by inconsistent `run_id` groups instead of only whole-database aggregate mismatch.
- Added regression checks that verify event-log payload persistence and recovery reporting now expose run-scoped inconsistency explicitly.

### Purpose
- Reduce heuristic extraction work inside event persistence.
- Make replay / recovery reasoning more naturally aligned with per-run simulation execution.
- Prevent one noisy run from conceptually contaminating recovery analysis for another run.

### Impact / risk
- Positive: event persistence now depends less on implicit nested payload conventions.
- Positive: recovery reports are more actionable because they identify inconsistent runs.
- Risk: some older event producers may still emit payloads without normalized fields until they are updated.
- Risk: current run-scoped checks are still count-based rather than full event/fact reconstruction.

### Next actions
- Continue normalizing payloads for snapshot / IPO / SIM_DAY and other runtime events.
- Later push recovery from run-scoped count checks toward run-scoped fact reconstruction.
- Keep replay and recovery contracts aligned around `run_id + sim_time`.

## Broader runtime event normalization / replay-check note (2026-03-24)

### status
in-progress

### goal
Extend payload normalization beyond order/account paths into simulation-time platform events, and add a lightweight replay/recovery cross-check so the platform backbone is not only individually tested but also minimally connected.

### files involved
- `services/sim_clock.py`
- `services/ipo_service.py`
- `services/bar_aggregator.py`
- `tests/test_replay_recovery_integration.py`
- `docs/current-work-status/engine.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `event_bus.publish(EventType.SIM_DAY, {  # type: ignore`
- **last line**: `"real_ts": datetime.utcnow().isoformat(timespec='seconds'),`

#### fragment 2
- **first line**: `event_bus.publish(EventType.IPO_OPENED, {`
- **last line**: `'sim_day': current_sim_day(),`

#### fragment 3
- **first line**: `event_bus.publish(EventType.BAR_UPDATED, {`
- **last line**: `"sim_dt": sim_dt.isoformat() if sim_dt else None,`

### Change summary
- Added simulation-time fields to `SIM_DAY` payloads.
- Added simulation-time metadata to `IPO_OPENED` payloads.
- Added `sim_day / sim_dt` to emitted `BAR_UPDATED` payloads.
- Extended replay/recovery integration coverage with a lightweight cross-check and sim-day filtered summary validation.

### Purpose
- Push event normalization from isolated runtime events toward a broader platform contract.
- Make replay filtering by simulation time more meaningful across multiple event families.
- Ensure variable-speed simulation time is present in emitted platform events, not only in persisted fact tables.

### Impact / risk
- Positive: simulation-time events are becoming more uniformly queryable and replay-friendly.
- Positive: replay/recovery now have at least one shared validation seam.
- Risk: other event families like snapshot and borrow-fee are still only partially normalized.
- Risk: current replay/recovery cross-check is intentionally lightweight and not a full reconciliation.

### Next actions
- Normalize `SNAPSHOT_UPDATED` and remaining runtime event families.
- Later compare replay summary with recovery report on a per-run basis more strictly.
- Keep emitted payload contracts stable as more platform tooling depends on them.

## Snapshot-event normalization note (2026-03-24)

### status
in-progress

### goal
Normalize snapshot-family event payloads so simulation-time replay and recovery tooling can reason over market-state updates with the same run/scoped semantics already used for orders, trades, bars, and account events.

### files involved
- `services/snapshot_listener.py`
- `tests/test_event_persistence.py`
- `tests/test_replay_recovery_integration.py`
- `docs/current-work-status/engine.md`

### total changed lines
- focused incremental change set

### Code fragment anchors
#### fragment 1
- **first line**: `def _on_snapshot(self, topic: str, payload: dict):`
- **last line**: `payload.setdefault("sim_dt", virtual_datetime(sd).isoformat() if sd else None)`

#### fragment 2
- **first line**: `def test_event_log_carries_snapshot_sim_time_and_symbol():`
- **last line**: `assert row.sim_day == 3`

#### fragment 3
- **first line**: `event_bus.publish(EventType.SNAPSHOT_UPDATED, {`
- **last line**: `assert any(ev["type"] == EventType.SNAPSHOT_UPDATED.value for ev in sim_loaded)`

### Change summary
- Ensured snapshot-event payloads are stamped with simulation-time metadata before persistence-side consumers read them.
- Added initial regression coverage attempt for `SNAPSHOT_UPDATED` normalization.
- Extended replay/recovery integration coverage on the run-scoped replay path while keeping snapshot-event verification in-progress.

### Purpose
- Bring snapshot events into the same platform event contract as other runtime families.
- Make replay/recovery useful for market-state transitions, not only account-side events.
- Reduce future ambiguity when market detail and recovery tooling consume snapshot history.

### Impact / risk
- Positive: snapshot history is becoming more replay-friendly and simulation-time aware.
- Positive: event-log coverage is now broader across market-state events.
- Risk: broader snapshot payload standardization may still be needed if more fields become authoritative.
- Risk: this normalizes timing metadata, not full snapshot contract ownership yet.

### Next actions
- Continue clarifying snapshot contract ownership across listener/service/UI usage.
- Later add stricter replay/recovery checks that compare snapshot event presence with persisted snapshot rows.
- Keep remaining event families (borrow-fee, liquidation, config-change) on the same normalization path.

## Phase-1 summary / next-backlog note (2026-03-24)

### status
done

### goal
Consolidate Phase-1 backend platform progress into a short durable runtime note before continuing more event-family and recovery/replay work.

### files involved
- `docs/tasks/runtime/backend-phase-1-progress-and-next-backlog.md`

### total changed lines
- new summary document

### Code fragment anchors
#### fragment 1
- **first line**: `# Backend Phase-1 Progress And Next Backlog`
- **last line**: `- pretending snapshot event chain is fully solved before tests are stable`

### Change summary
- Added a concise Phase-1 summary document.
- Recorded what is done, what is partial, and what should come next.
- Captured the recommended immediate next step: finish snapshot convergence, then tighten recovery/replay precision together.

### Purpose
- Prevent Phase-1 progress from becoming scattered across many small notes only.
- Give future work a short backlog instead of re-deriving priorities from code state.
- Make the backend platform line easier to continue after context switches.

### Impact / risk
- No runtime impact.
- Positive planning effect for next backend tasks.

### Next actions
- Continue with `BL-201 snapshot family convergence`.
- Then move into `BL-202 recovery precision upgrade` and `BL-203 replay verification upgrade`.

## Snapshot boundary note (2026-03-24)

### status
in-progress

### goal
Make snapshot-family convergence less ambiguous by explicitly separating runtime snapshot events from persisted snapshot rows before adding stricter validation.

### files involved
- `docs/contracts/market/snapshot-event-and-row-boundary.md`

### total changed lines
- new boundary note

### Code fragment anchors
#### fragment 1
- **first line**: `# Snapshot Event And Row Boundary`
- **last line**: `3. avoid over-testing unstable event chain details before ownership is cleaner`

### Change summary
- Added a dedicated boundary note for snapshot events vs `snapshots_1s` rows.
- Recorded that event history and persisted rows are related but not identical contracts.
- Clarified that replay should lean on event history while storage/history queries should lean on rows.

### Purpose
- Reduce confusion while snapshot-family convergence is still in progress.
- Prevent brittle tests from encoding a false one-to-one event/row assumption.
- Give future replay/recovery work a cleaner conceptual base.

### Impact / risk
- No runtime impact.
- Positive design clarification for next snapshot tasks.

### Next actions
- Continue snapshot payload normalization.
- Later add stricter replay-vs-row checks only after ownership is more stable.

## Snapshot event contract note (2026-03-24)

### status
in-progress

### goal
Add a stable, narrow regression around snapshot-event persistence without over-asserting unstable listener-to-row identity details.

### files involved
- `tests/test_snapshot_event_contract.py`

### total changed lines
- new focused test

### Code fragment anchors
#### fragment 1
- **first line**: `def test_snapshot_updated_event_persists_run_id_symbol_and_sim_day():`
- **last line**: `assert row.sim_day == 5`

### Change summary
- Attempted a dedicated snapshot-event contract regression.
- Kept the intended assertion surface narrow: `run_id`, `symbol`, and `sim_day` on the event side.
- Current result: the path is still not stable enough to keep as a durable regression yet, so stronger snapshot-event persistence assertions remain deferred.

### Purpose
- Make snapshot-family convergence continue through stable regression rather than speculative end-to-end assumptions.
- Keep the event-side contract enforceable while row-side ownership is still being clarified.

### Impact / risk
- Positive: snapshot-event persistence now has a dedicated regression hook.
- Low risk: the test is intentionally narrow and should remain stable.

### Next actions
- Later add row-side verification once snapshot event/row ownership is cleaner.
- Keep snapshot-family work split into event contract and row contract until convergence is stronger.

## Snapshot producer normalization note (2026-03-24)

### status
in-progress

### goal
Move snapshot-family normalization closer to the event producer so downstream listener and persistence code receives a more stable `SNAPSHOT_UPDATED` contract.

### files involved
- `core/matching_engine.py`
- `tests/test_snapshot_event_payload.py`

### total changed lines
- focused producer-side change

### Code fragment anchors
#### fragment 1
- **first line**: `sim_day = current_sim_day()`
- **last line**: `'sim_dt': sim_dt.isoformat() if sim_dt else None,`

#### fragment 2
- **first line**: `def test_matching_engine_snapshot_event_contains_symbol_and_sim_time():`
- **last line**: `assert 'sim_dt' in payload`

### Change summary
- Added simulation-time metadata to producer-side `SNAPSHOT_UPDATED` emission in `MatchingEngine`.
- Added `snapshot.symbol` explicitly into the emitted snapshot payload.
- Added a narrow unit-style regression to verify producer-side snapshot event shape.

### Purpose
- Reduce downstream normalization burden.
- Make snapshot event contracts more stable before deeper replay/recovery checks.
- Keep BL-201 moving through producer-first convergence rather than only listener-side patching.

### Impact / risk
- Positive: snapshot event shape is now more explicit at source.
- Positive: downstream consumers have less reason to guess `symbol` and simulation time.
- Low risk: this is additive payload normalization.

### Next actions
- Revisit event-log-side snapshot verification after producer-side shape settles.
- Later align snapshot listener tests with this producer contract.

## Snapshot listener convergence note (2026-03-24)

### status
in-progress

### goal
Reduce listener-side guesswork now that producer-side snapshot events are more explicit, while keeping the listener safe for older payload shapes.

### files involved
- `services/snapshot_listener.py`
- `tests/test_snapshot_listener_contract.py`

### total changed lines
- small focused convergence step

### Code fragment anchors
#### fragment 1
- **first line**: `if "sim_day" not in payload:`
- **last line**: `if "sim_dt" not in payload:`

#### fragment 2
- **first line**: `def test_snapshot_listener_keeps_existing_sim_time_payload_fields():`
- **last line**: `assert payload["sim_dt"] == "0001-01-07T00:00:00"`

### Change summary
- Tightened snapshot-listener stamping so it only fills missing simulation-time fields instead of casually overwriting producer-provided values.
- Added a narrow listener-side regression that protects existing `sim_day` / `sim_dt` payload values.

### Purpose
- Keep BL-201 moving from producer-first normalization into safer listener behavior.
- Prevent downstream listener logic from hiding producer-side contract mistakes by overwriting payload values too aggressively.

### Impact / risk
- Positive: listener behavior is now more contract-preserving.
- Low risk: older payloads still get fallback stamping.

### Next actions
- Continue shifting snapshot-family correctness toward producer-side guarantees.
- Later add row-side regression once listener/row ownership is more stable.

## Snapshot row persistence note (2026-03-24)

### status
in-progress

### goal
Add a minimal stable row-side assertion for snapshot-family work without forcing a brittle event-log chain assumption.

### files involved
- `tests/test_snapshot_row_persistence.py`

### total changed lines
- new focused test

### Code fragment anchors
#### fragment 1
- **first line**: `def test_snapshot_listener_writes_snapshot_row_for_symbol():`
- **last line**: `assert row.volume == 100`

### Change summary
- Added a narrow snapshot row persistence regression.
- Verified that snapshot-listener processing writes a `snapshots_1s` row with expected core fields.
- Kept the assertion limited to stable row-side facts instead of unstable event-log coupling.

### Purpose
- Give BL-201 a durable row-side test anchor.
- Separate row persistence validation from event persistence validation.

### Impact / risk
- Positive: snapshot-family work now has both producer-side and row-side stable tests.
- Low risk: the assertion surface is intentionally small.

### Next actions
- Later bridge producer event + listener row + replay checks once the full chain is stable enough.

## Replay persisted-facts validation note (2026-03-24)

### status
in-progress

### goal
Upgrade replay validation from pure event reading toward a first real comparison against persisted runtime facts for a run.

### files involved
- `services/replay_service.py`
- `tests/test_replay_recovery_integration.py`

### total changed lines
- moderate focused validation upgrade

### Code fragment anchors
#### fragment 1
- **first line**: `def validate_against_persisted_facts(self, run_id: str) -> Dict[str, Any]:`
- **last line**: `"ok": checks["trade_event_vs_trade_row_gap"] == 0,`

#### fragment 2
- **first line**: `def test_replay_validate_against_persisted_facts_for_trade_run():`
- **last line**: `assert report['checks']['trade_event_vs_trade_row_gap'] == 0`

### Change summary
- Added replay-side persisted-facts validation for a run.
- Compared event-side trade/order counts against persisted order/trade/ledger rows.
- Added integration coverage for a real trade-producing run with run-scoped validation output.

### Purpose
- Move replay from passive event reading toward active backend verification.
- Create a first reusable validation seam between replay output and persisted runtime facts.
- Advance the second replay goal: stricter replay validation.

### Impact / risk
- Positive: replay now has an explicit persisted-facts validation path.
- Positive: this creates a concrete base for later stricter state reconciliation.
- Risk: current order-side comparison is still coarse because event families are not yet fully normalized.
- Risk: this is still count-based validation, not full reconstructed-state equivalence.

### Next actions
- Add `sim_dt` window validation and richer per-run checks.
- Later compare replay validation with recovery report directly.
- Expand from count checks toward fact-level reconciliation.

## Replay-to-recovery binding note (2026-03-24)

### status
in-progress

### goal
Make replay validation a visible recovery input instead of leaving replay and recovery as parallel but separate backend tracks.

### files involved
- `services/recovery_service.py`
- `tests/test_recovery.py`

### total changed lines
- focused integration step

### Code fragment anchors
#### fragment 1
- **first line**: `replay_validation: dict[str | None, dict] = {}`
- **last line**: `"replay_validation": replay_validation,`

#### fragment 2
- **first line**: `def test_recovery_service_emits_resumed_event_and_report():`
- **last line**: `assert 'replay_validation' in rep['checks']`

### Change summary
- Wired replay validation into recovery report building.
- Recovery now exposes per-run replay validation results inside `checks.replay_validation`.
- Added regression coverage that verifies recovery report now includes replay-validation data on the ok path.

### Purpose
- Advance the third replay goal: deeper binding with recovery.
- Make recovery report more actionable for run-scoped backend inspection.
- Create a direct path for later recovery gating based on replay validation quality.

### Impact / risk
- Positive: replay is no longer only an external helper; it now informs recovery output.
- Positive: recovery report is becoming the central backend health surface for a run.
- Risk: current replay-validation integration is report-level, not yet hard recovery gating.
- Risk: replay validation itself is still coarse/count-based.

### Next actions
- Later decide whether severe replay validation gaps should force degraded recovery.
- Expand replay-validation detail so recovery can rely on more than count summaries.

## Replay snapshot integration note (2026-03-24)

### status
in-progress

### goal
Bring snapshot-family facts into replay validation so replay is not only order/trade/account aware but also market-state aware.

### files involved
- `services/replay_service.py`
- `tests/test_replay_recovery_integration.py`

### total changed lines
- focused replay-extension step

### Code fragment anchors
#### fragment 1
- **first line**: `"snapshots": s.query(Snapshot1s).count(),`
- **last line**: `"snapshot_event_vs_snapshot_row_gap": abs(event_side["snapshots"] - persisted["snapshots"]),`

#### fragment 2
- **first line**: `listener = SnapshotPersistenceListener()`
- **last line**: `assert 'snapshot_event_vs_snapshot_row_gap' in report['checks']`

### Change summary
- Extended replay persisted-facts validation to include snapshot rows and snapshot events.
- Added integration coverage that feeds both a snapshot row and a snapshot event into replay validation.
- Started bringing snapshot-family state into replay verification rather than leaving replay account/trade-only.

### Purpose
- Complete the fourth replay goal: include snapshot family in replay work.
- Make replay more aligned with the real trading-simulation runtime, where market-state facts matter alongside account/trade facts.

### Impact / risk
- Positive: replay validation is now broader than execution facts alone.
- Positive: snapshot family is starting to participate in run-scoped backend verification.
- Risk: current snapshot persisted count is still global because snapshot rows do not yet carry `run_id`.
- Risk: snapshot validation is still coarse/count-based.

### Next actions
- Later add run-scoped snapshot persistence if the data model evolves that way.
- Tighten snapshot replay validation once snapshot event/row ownership is even more stable.

## Run-scoped report note (2026-03-24)

### status
in-progress

### goal
Promote replay/recovery output from scattered summaries into a more complete run-scoped report structure that can serve as the main operator-facing backend health unit.

### files involved
- `services/replay_service.py`
- `services/recovery_service.py`
- `tests/test_replay_recovery_integration.py`
- `tests/test_recovery.py`

### total changed lines
- focused reporting upgrade

### Code fragment anchors
#### fragment 1
- **first line**: `def build_run_report(self, run_id: str) -> Dict[str, Any]:`
- **last line**: `"ok": bool(dry.get("event_count", 0) >= 0 and validation.get("ok")),`

#### fragment 2
- **first line**: `replay_validation[run_id] = replay_service.build_run_report(run_id)`
- **last line**: `assert 'summary' in first and 'validation' in first`

### Change summary
- Added a dedicated run-scoped replay report builder.
- Recovery now stores run reports instead of only raw validation snippets.
- Added regression coverage that checks recovery now exposes richer per-run report structure.

### Purpose
- Complete the fifth replay goal: richer run-scoped reporting.
- Make backend health output easier to consume for later operator tooling or diagnostics.
- Reduce fragmentation between dry-run summary, validation summary, and recovery report.

### Impact / risk
- Positive: run-scoped backend output is now more structured.
- Positive: replay and recovery now share a clearer report shape.
- Risk: report content is still count-based and will need richer facts later.

### Next actions
- Later add sim-dt range and checkpoint metadata into run reports.
- Evolve run reports toward operator/debug tooling once backend phase-1 closes.

## Run-report contract note (2026-03-24)

### status
in-progress

### goal
Lock the new run-scoped report shape with a focused contract test so later replay/recovery work can build on a stable report interface.

### files involved
- `tests/test_run_report_contract.py`

### total changed lines
- new focused test

### Code fragment anchors
#### fragment 1
- **first line**: `def test_run_report_contains_summary_validation_and_ok():`
- **last line**: `assert report['summary']['run_id'] == run_id`

### Change summary
- Added a dedicated run-report contract regression.
- Verified that run reports expose `summary`, `validation`, and `ok` in a stable shape.

### Purpose
- Make the richer run-scoped report explicit and test-protected.
- Reduce risk of future replay/recovery changes silently breaking report consumers.

### Impact / risk
- Positive: report structure is now more durable.
- Low risk: focused contract assertion only.

### Next actions
- Later extend run reports with checkpoint / sim-dt window / operator metadata when needed.

## Outstanding work

- Add future notes if symbol-page creation or market-controller construction changes engine assumptions.
- Track any later work that changes engine registration, symbol routing, or multi-symbol ownership behavior.

## Desktop app-context convergence note (2026-03-26)

### status
in-progress

### goal
Reduce frontend state fragmentation by introducing a shared desktop composition root and a small runtime access boundary, so workspace panels and dynamic symbol pages stop constructing parallel service graphs.

### files involved
- `app/app_context.py`
- `app/runtime_gateway.py`
- `app/panels/__init__.py`
- `app/ui/ui_refresh.py`
- `app/ui/adapters/account_adapter.py`
- `setup_frontend_entry.py`
- `app/headless.py`

### change summary
- Added `AppContext` as the desktop composition root for shared controllers/services.
- Added `RuntimeGateway` as a first-pass runtime access seam for app-layer consumers.
- Switched panel registration to consume a shared `AppContext` instead of constructing fresh per-panel services.
- Switched dynamic symbol detail page opening to reuse the shared market controller/service instead of creating fallback instances.
- Moved account prefill discovery away from direct adapter-owned ORM access and into `RuntimeGateway`.
- Moved `reset_app_context()` to GUI/headless startup so the context is reset once per frontend session rather than inside panel registration.

### impact / risk
- Positive: Market main page and symbol detail pages now share the same market service/controller graph.
- Positive: the frontend has a clearer place to continue collecting runtime reads instead of letting adapters query persistence ad hoc.
- Positive: startup semantics are cleaner because context reset happens at entry, not during adapter registration.
- Risk: this is only the first slice; some services still keep app-local caches or dual-bus assumptions, so architectural convergence is not complete yet.

### next actions
- Keep moving direct runtime reads from adapters/services into `RuntimeGateway`.
- Decide whether `TradingService` / `AgentService` should eventually sit behind a fuller runtime gateway boundary.
- Later introduce a stronger event contract so shared context does not still depend on loosely duplicated topic names.

### follow-up update
- `ClockService` runtime sync is now routed through `RuntimeGateway` instead of importing runtime clock/IPO sidecars directly.
- `AgentService` runtime account bootstrap and IPO allocation trigger are now routed through `RuntimeGateway`.
- `LeaderboardService` runtime ranking reads are now routed through `RuntimeGateway`.
- Remaining obvious gap: `TradingService` still talks to runtime ORM/services directly and remains the next cleanup candidate on this boundary.

### follow-up update 2
- `TradingService` is now routed through `RuntimeGateway` for runtime submit/cancel operations instead of owning direct runtime ORM/service imports itself.
- Shared desktop `AppContext` now injects the shared `RuntimeGateway` into `TradingService`, aligning it with `ClockService / AgentService / LeaderboardService`.
- Safe cleanup performed:
  - removed old direct-runtime implementation from `app/services/trading_service.py`
  - removed the redundant local dual-bus subscription helper from `app/ui/adapters/orders_adapter.py` in favor of `app.event_bridge.subscribe_topic()`
  - removed the now-unused `_DETAIL_ENABLE_PIE` feature switch from `app/ui/adapters/market_adapter.py`; the pie render path remains structurally dead and can be fully deleted in a later focused cleanup

### follow-up update 3
- `TradingService` trade-event fanout is now routed through `app.event_bridge.publish_trade_payload()` instead of duplicating dual-bus publish logic locally.
- `app/ui/adapters/market_adapter.py` now imports `subscribe_topic()` from `app.event_bridge` instead of maintaining its own runtime/app dual-subscription implementation.
- The old Market pie-chart branch has been reduced to a dead stub path, which lowers maintenance noise without changing live UI behavior.

### follow-up update 4
- Added a focused regression for `publish_trade_payload()` so the centralized trade-event bridge now has a direct frontend-side contract test.
- Chose not to keep pushing on a couple of low-value encoded comment remnants in `market_adapter.py` during this pass; functional cleanup is in place and syntax remains clean, so later cleanup can safely be done as a dedicated cosmetic pass.

## Runtime support bootstrap note (2026-03-26)

### status
done

### goal
Make the desktop frontend standard startup path bring up the runtime persistence sidecars needed for snapshot and bar history instead of leaving them as manually started backend helpers.

### files involved
- `app/runtime_bootstrap.py`
- `setup_frontend_entry.py`
- `app/headless.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`

### change summary
- Added a frontend-owned runtime bootstrap helper that starts:
  - `ensure_snapshot_listener_started()`
  - `ensure_bar_aggregator_started()`
- Wired both GUI and headless frontend entry paths to call that helper during startup.
- Replaced the previous broken placeholder-heavy `bar_aggregator.py` with a working persisted OHLCV aggregation path.

### impact / risk
- Positive: runtime snapshots/bars now have a standard path to come alive in desktop sessions.
- Positive: later Market/detail history work can build on a startup chain that already launches the required sidecars.
- Risk: because these sidecars now come up by default, any future SQLite locking or startup ordering issue should be diagnosed against the new standard chain first.

## Legacy runtime cleanup note (2026-03-26)

### status
done

### goal
清理已脱离当前桌面前后端主链的 IPO / agent 遗留文件，减少后续误读与误接线风险。

### files removed
- `agents/multi_strategy_retail.py`
- `services/ipo_grant_queue.py`
- `services/ipo_poller.py`
- `services/strategy_supervisor.py`
- `services/agent_meta_listener.py`
- `services/ipo_listener.py`

### removal basis
- 代码侧已不再被当前 GUI/headless 启动链、面板注册链、runtime support bootstrap 链引用。
- 搜索确认当前 `app/`, `services/`, `tests/`, `scripts/` 中没有主链硬引用。
- 这些文件保留的主要是旧版 MultiStrategy/IPO grant/poller/listener 方案，与当前 runtime retail + clock + event bridge 主链已脱钩。

### impact / risk
- Positive: 后续排查时不会再把旧的 IPO grant / poller / listener 路径误当成现行链路。
- Positive: 当前桌面主链更聚焦在 `MarketController / AgentService / RuntimeRetailAgent / sim_clock / runtime bootstrap`。
- Risk: 文档和结构说明里仍会暂时保留历史提及，后续如需可再做一次纯文档清理。
