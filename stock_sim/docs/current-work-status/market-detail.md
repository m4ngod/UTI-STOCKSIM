# Market Detail Module Status

## Module

Market detail page / symbol detail data contract

## Current goal

- Clarify the real data contract of Market detail.
- Separate structural UI issues from data-source inconsistency.
- Prepare for later K-line / detail-page fixes on the real GUI.

## Current state

in-progress

## Files involved

- `app/controllers/market_controller.py`
- `app/panels/market/panel.py`
- `app/ui/adapters/market_adapter.py`
- `app/services/market_data_service.py`
- `app/event_bridge.py`
- `services/market_data_service.py`
- `docs/frontend-backend-dependency-map.md`

---

## Task 2026-03-17-market-detail-01
- **time**: 2026-03-17
- **status**: done
- **goal**: document the current split data paths behind Market detail
- **files involved**:
  - `docs/frontend-backend-dependency-map.md`
- **total changed lines**: 14905

### Code fragment anchors
#### fragment 1
- **first line**: `## 2.5 Backend market snapshot path is different from frontend bars/K-line path`
- **last line**: `This is deeper than file duplication. Even if window structure is unified, Market detail may still feel inconsistent unless these data contracts are clarified.`

#### fragment 2
- **first line**: `## 3.3 \`MarketPanel\`/\`SymbolDetailPanel\` are logic panels with split data dependencies`
- **last line**: `So “detail page correctness” must be checked field by field, not page by page.`

### Change summary
- Recorded that Market detail is currently composed from multiple sources rather than one unified contract.
- Explicitly separated snapshot/order-book path from bars/K-line path.

### Purpose
- Avoid mistaking a structural MainWindow issue for a pure data issue.
- Provide a stable reference for future detail-page fixes.

### Impact / risk
- No runtime risk.
- Strongly affects how later debugging should be prioritized.

### Next actions
- Write a more explicit per-field contract for:
  - `series`
  - `snapshot`
  - `order_book`
  - `trades`
  - `holdings`

---

## Known current contract (working draft)

- `series`:
  - current source: `app/services/market_data_service.py`
  - nature: app-layer bars cache / fetcher path
- `snapshot`:
  - current source: `app/controllers/market_controller.py` merged snapshot cache
  - upstream nature: backend/event snapshot path
- `order_book`:
  - current source: snapshot-derived data shown through detail view
- `trades`:
  - current source: local/event-fed trade buffer in detail logic
- `holdings`:
  - current source: mixed / partially optional / may still fallback to placeholder behavior

---

## Outstanding work

- Confirm whether K-line should remain app-cache-led or move closer to backend-query-led.
- Record exact refresh/update responsibilities for each field.
- After that, use the contract to diagnose the real GUI K-line/detail problem more safely.
