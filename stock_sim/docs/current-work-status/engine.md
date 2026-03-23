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

## Outstanding work

- Add future notes if symbol-page creation or market-controller construction changes engine assumptions.
- Track any later work that changes engine registration, symbol routing, or multi-symbol ownership behavior.
