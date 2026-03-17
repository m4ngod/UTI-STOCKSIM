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

## Outstanding work

- Add future notes if symbol-page creation or market-controller construction changes engine assumptions.
- Track any later work that changes engine registration, symbol routing, or multi-symbol ownership behavior.
