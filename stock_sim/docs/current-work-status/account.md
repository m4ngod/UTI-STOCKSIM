# Account Module Status

## Module

Account data path / account semantics between frontend app layer and backend runtime layer

## Current goal

- Keep clear distinction between frontend app-layer account DTO service and backend runtime account service.
- Preserve awareness of freeze/refund/settlement semantics while planning UI cleanup.

## Current state

in-progress

## Files involved

- `app/services/account_service.py`
- `app/controllers/account_controller.py`
- `app/panels/account/panel.py`
- `services/account_service.py`
- `services/order_service.py`
- `docs/frontend-backend-dependency-map.md`

---

## Task 2026-03-17-account-01
- **time**: 2026-03-17
- **status**: done
- **goal**: document the split between frontend account DTO flow and backend runtime settlement semantics
- **files involved**:
  - `docs/frontend-backend-dependency-map.md`
- **total changed lines**: 14905

### Code fragment anchors
#### fragment 1
- **first line**: `## 2.4 \`AccountService\` carries real freeze/settlement semantics`
- **last line**: `any frontend model simplification that drops frozen state risks making the UI look wrong even if backend is correct`

#### fragment 2
- **first line**: `## 3.5 Account frontend is currently app-layer synthetic/cache oriented`
- **last line**: `if future work wants stronger real-time account correctness, the app-layer service likely needs a closer adapter to backend/runtime events`

### Change summary
- Recorded that backend account service carries real trading semantics.
- Recorded that frontend account service is currently DTO/fetcher-oriented and not the same thing.

### Purpose
- Prevent future cleanup from conflating app-layer DTO views with backend runtime truth.
- Keep frozen-state semantics visible in architecture decisions.

### Impact / risk
- No runtime impact.
- Important when later improving account UI correctness.

### Next actions
- If account UI moves closer to real backend state later, document the migration path and required fields explicitly.

---

## Known current conclusions

- Backend `services/account_service.py` owns freeze/release/settlement semantics.
- Backend `services/order_service.py` depends on those semantics during order lifecycle.
- Frontend `app/services/account_service.py` is a different layer that currently returns DTO snapshots and can use a synthetic fetcher.

---

## Outstanding work

- Define whether the account panel will remain DTO-led for now or later be connected more tightly to runtime events/state.
- If that migration happens, record required fields such as:
  - `frozen_cash`
  - `frozen_fee`
  - `frozen_qty`
  - `borrowed_qty`
