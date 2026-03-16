# Frontend ↔ Backend Dependency Map

_Last updated: 2026-03-17_

This note documents how the current frontend is wired to backend/runtime state in `stock_sim`, with special focus on the Market/Account flows and the `app.main.py` vs `app/ui/main_window.py` consolidation work.

The purpose is twofold:

1. help future frontend cleanup avoid breaking real backend semantics;
2. record the backend/runtime model the frontend is actually depending on.

---

## 1. High-level architecture

There are **two different layers** in this project that are easy to confuse:

- **Backend/runtime layer** under `stock_sim/services`, `stock_sim/core`, `stock_sim/persistence`
- **Frontend app layer** under `stock_sim/app/...`

The frontend app layer is not talking to a single unified backend adapter today. Instead, different UI features depend on different sources of truth:

- order lifecycle / account freeze-settle semantics -> backend `services/order_service.py`, `services/account_service.py`
- symbol/engine existence -> backend `services/instrument_service.py`, `services/engine_registry.py`
- top-of-book / snapshot / latest price -> backend engine snapshot path
- K-line bars / indicators -> frontend `app/services/market_data_service.py` cache path
- UI panel opening/layout -> frontend `app/ui/main_window.py` + panel registry

That split is the main reason why frontend structural cleanup must be done carefully.

---

## 2. Backend runtime sources of truth

## 2.1 Instrument creation is backend state creation, not just UI state

Relevant file:

- `stock_sim/services/instrument_service.py`

When a symbol is created, the backend service does more than write a row:

- persists an `Instrument`
- creates a `Stock`/instrument object
- creates or registers a `MatchingEngine`
- stores it in global `engine_registry`
- sets the initial phase (`CALL_AUCTION` or `CONTINUOUS`) from `ipo_opened`
- may seed initial snapshot display values from `initial_price`

Implication for frontend:

- Market "create instrument" is a real backend mutation
- symbol detail pages must assume the symbol is bound to a real engine, not only to a local watchlist row
- any frontend shortcut that fabricates a symbol without going through this path will diverge from runtime truth

---

## 2.2 `engine_registry` is the global symbol → engine index

Relevant file:

- `stock_sim/services/engine_registry.py`

This registry provides the process-wide mapping from symbol to `MatchingEngine`.

Important points:

- `get(symbol)` returns the authoritative engine if already registered
- `get_or_create(symbol)` lazily constructs one if missing
- metadata like `name`, `market_cap`, `initial_price` may also be attached

Implication for frontend and orchestration:

- if two frontend code paths accidentally instantiate services/controllers with different engine references, the UI may show inconsistent detail for the same symbol
- structural cleanup should reduce chances of “same symbol, different engine instance assumptions”

---

## 2.3 `OrderService` is the real order lifecycle orchestrator

Relevant file:

- `stock_sim/services/order_service.py`

`OrderService.place_order()` is the real transaction orchestrator. It currently does all of the following:

1. recovery / readonly guard
2. call-auction unmatched cleanup
3. resolve engine by symbol
4. normalize price/quantity from instrument params
5. basic validation
6. risk validation
7. estimate fees
8. freeze fee for buys
9. freeze main cash/position
10. persist initial order state
11. submit into matching engine
12. process trades and batch settlement
13. IOC/FOK residual release/refund
14. persist final/rest state and emit events/metrics

This means the truth of an order is distributed but coordinated here across:

- DB order rows
- in-memory order cache
- matching engine state
- account balances / frozen balances / positions
- emitted events

Frontend implication:

- Orders panel, Account panel, Market detail, and any execution-related UI cannot assume one isolated source is sufficient
- a frontend refactor must preserve the connection between order state, account freeze state, and symbol engine state

---

## 2.4 `AccountService` carries real freeze/settlement semantics

Relevant file:

- `stock_sim/services/account_service.py`

Although labeled simplified/reconstructed, the backend `AccountService` is still semantically important.

It owns:

- account creation/load
- position creation/load
- fee freezing / refunding
- cash freezing / release
- sell-side quantity freezing
- batch settlement of trades
- short/borrowed quantity transitions

Important runtime semantics:

### BUY side

- fee may be pre-frozen in `frozen_fee`
- notional may be frozen in `frozen_cash`
- actual trade cost consumes frozen cash
- excess is refunded later by `OrderService`

### SELL side

- quantity is frozen via `frozen_qty`
- insufficient inventory may create short exposure
- `borrowed_qty` matters

Frontend implication:

- Account/Position UI must not treat `cash` and `quantity` as the only meaningful state
- frozen fields are part of normal order lifecycle, not debug-only data
- any frontend model simplification that drops frozen state risks making the UI look wrong even if backend is correct

---

## 2.5 Backend market snapshot path is different from frontend bars/K-line path

This is one of the most important findings.

### Backend snapshot authority

Relevant file:

- `stock_sim/services/market_data_service.py`

This backend service:

- prefers engine `get_snapshot(levels)`
- otherwise falls back to `engine.snapshot`
- rebuilds bids/asks from the actual order book
- backfills last trade / last price if needed
- applies `sanity_fill()`

So for these concepts, the authority is the backend matching engine snapshot:

- best bid / ask
- order book levels
- last price
- recent snapshot state

### Frontend bars/K-line authority

Relevant file:

- `stock_sim/app/services/market_data_service.py`

This frontend-side service is a cache/orchestration layer for:

- symbol subscription intent
- initial bars loading
- local bars cache
- realtime append
- indicator inputs

It can also fall back to a synthetic fetcher.

### Consequence

The project currently has **two data worlds** in Market detail:

- snapshot/order-book/latest quote world
- bars/K-line/indicator world

They are not naturally unified today.

This is deeper than file duplication. Even if window structure is unified, Market detail may still feel inconsistent unless these data contracts are clarified.

---

## 3. Frontend app-layer wiring

## 3.1 EventBridge is the bridge for snapshot batching

Relevant file:

- `stock_sim/app/event_bridge.py`

EventBridge responsibilities:

- subscribes to backend snapshot topic
- batches snapshots into `frontend.snapshot.batch`
- can emit via Qt signal and/or local event bus
- supports redis fallback to local event bus

Frontend implication:

- the Market UI list is not supposed to render every backend snapshot individually
- it depends on a batched front-end-friendly topic
- over-refreshing the UI bypassing this batching would regress performance and semantics

---

## 3.2 `app.controllers.market_controller` merges snapshot state, but bars come from app service

Relevant file:

- `stock_sim/app/controllers/market_controller.py`

This controller currently owns:

- snapshot merge cache (`_snapshots`)
- snapshot listing/filter/sort/page
- indicator submission
- frontend-side instrument creation validation/triad derivation

Its K-line dependency is **not** backend engine snapshot; it depends on:

- `app.services.market_data_service.MarketDataService`

So the controller is already bridging two different models:

- snapshot DTO cache
- bars cache/data service

Implication:

- when debugging Market detail, verify separately whether the failure is in snapshot flow or bars flow
- a UI-only refactor may not fix data inconsistency by itself

---

## 3.3 `MarketPanel`/`SymbolDetailPanel` are logic panels with split data dependencies

Relevant file:

- `stock_sim/app/panels/market/panel.py`

`MarketPanel` logic:

- owns watchlist
- uses `MarketController.list_snapshots()` for list rendering
- delegates selected symbol detail to `SymbolDetailPanel`

`SymbolDetailPanel` logic:

- loads symbol/timeframe through app market data service
- reads snapshot through `MarketController.get_snapshot()`
- keeps trades ring buffer locally
- schedules indicators from bars cache
- provides a combined `detail_view()`

Important consequence:

`detail_view()` mixes data from different origins:

- `series` -> app bars cache path
- `snapshot` -> controller snapshot cache path
- `order_book` -> snapshot-derived
- `trades` -> local ring buffer / event-fed
- `holdings` -> partially optional/placeholder

So “detail page correctness” must be checked field by field, not page by page.

---

## 3.4 `MarketPanelAdapter` depends on UI bridge and batched events

Relevant file:

- `stock_sim/app/ui/adapters/market_adapter.py`

The adapter:

- renders watchlist and symbol detail
- subscribes to `frontend.snapshot.batch`
- subscribes to `Trade`
- subscribes to `instrument-created`
- uses `ui_refresh.open_symbol_page()` for dynamic symbol detail pages

Implication:

- the adapter assumes `ui_refresh` knows the active main window
- dynamic symbol pages depend on panel registry + main window open path being consistent
- duplicated main window structures increase the chance that dynamic pages open in one structure while the rest of the app uses another

---

## 3.5 Account frontend is currently app-layer synthetic/cache oriented

Relevant files:

- `stock_sim/app/services/account_service.py`
- `stock_sim/app/controllers/account_controller.py`
- `stock_sim/app/panels/account/panel.py`

Important distinction:

The frontend app-layer `AccountService` is **not** the same as backend `stock_sim/services/account_service.py`.

Current app-layer account service:

- is fetcher-based
- defaults to a synthetic deterministic fetcher
- performs consistency checks between local and remote snapshots
- returns `AccountDTO`

Current app-layer AccountPanel:

- shows account summary and positions
- applies highlight logic based on drawdown threshold
- works on DTOs, not on backend ORM/account state directly

Implication:

- account panel cleanup must distinguish between app DTO model and backend runtime model
- if future work wants stronger real-time account correctness, the app-layer service likely needs a closer adapter to backend/runtime events

---

## 4. MainWindow duplication problem: what is structural vs what is semantic

## 4.1 Structural duplication

Relevant files:

- `stock_sim/app/main.py`
- `stock_sim/app/ui/main_window.py`

The intended cleanup direction is:

- `app/ui/main_window.py` = **single real window structure**
- `app/main.py` = compatibility/export layer only

Why this is necessary:

- panel opening should have one structural path
- menu/layout/docking should have one structural path
- dynamic symbol pages should target one main window host
- tests may still require compatibility shims, but those should not become a second UI implementation

---

## 4.2 Semantic inconsistency is a different layer of problem

Even after MainWindow duplication is removed, the Market detail page can still be inconsistent because:

- snapshot data and bars data come from different pipelines
- trades and holdings are yet another dependency path

So the cleanup order should be:

1. reduce structural duplication (single real MainWindow)
2. document the data contract for each detail field
3. only then refactor/optimize panel logic or adapters

---

## 5. Recommended safe refactor boundary

## Safe to consolidate now

- `app.main.run_frontend()` as entry/export layer only
- `app.ui.main_window.MainWindow` as sole structural owner
- panel registry opening path
- compatibility shims for legacy tests only

## Must be treated carefully

- anything in Market detail that mixes snapshot and bars
- any code path that creates its own controller/service bundle for symbol pages
- account displays that ignore frozen state semantics if switched to real backend data later
- any frontend workflow that creates symbols or orders without following backend services

---

## 6. Checklist for future frontend changes

Before changing Market/Account/Orders UI, verify:

### Market
- Is the field sourced from backend snapshot or app bars cache?
- Does the symbol already exist in backend `engine_registry`?
- Is this page refreshing from batched snapshots or direct event spam?

### Orders
- Does the UI reflect order state only, or also the freeze/refund lifecycle?
- Are IOC/FOK cancellations and residual refunds visible/derivable?

### Account
- Is the display based on app synthetic DTO service or real backend state?
- If moving toward real backend state, are `frozen_cash`, `frozen_fee`, `frozen_qty`, `borrowed_qty` accounted for?

### Window/panel structure
- Is panel opening going through the single real main window?
- Is `ui_refresh.register_main_window()` still the unique bridge root?
- Are dynamic symbol pages registered/opened through the same panel host as normal panels?

---

## 7. Current conclusion

The frontend inconsistency problem is **not only** that `app/main.py` and `app/ui/main_window.py` overlap.

There are two separate issues:

1. **Structural duplication**: two overlapping main-window/container responsibilities
2. **Semantic split**: Market detail is composed from multiple non-unified data pipelines

The structural duplication should still be fixed.
But the Market-detail/K-line class of bugs will only be fully understood when each field is traced back to its real source of truth.

---

## 8. Suggested next steps

1. finish shrinking `app.main.py` into a compatibility shell over `app.ui.main_window.MainWindow`
2. define a documented contract for Market detail fields:
   - `series`
   - `snapshot`
   - `order_book`
   - `trades`
   - `holdings`
3. decide whether K-line should remain app-cache-led or become backend-query-led
4. only after that, continue GUI-level debugging of the real `python` window

---

## 9. Compatibility retirement roadmap

The project goal is not to keep compatibility shims forever. Files like `app/main.py` should eventually be removable.

### Phase 1: compatibility shell only

Target:

- `app/ui/main_window.py` owns all real window structure
- `app/main.py` keeps only:
  - `run_frontend()`
  - `MainWindow` export alias or thin subclass
  - minimal legacy helpers needed by still-unmigrated tests/entrypoints

Rules:

- no new real UI behavior should be added to `app/main.py`
- no docking/menu/layout ownership should remain there
- compatibility helpers must be clearly marked temporary

### Phase 2: dependency migration

Migrate all real callers away from old surfaces:

- startup entry scripts
- tests importing `app.main.MainWindow`
- dynamic panel opening flows assuming old wrapper behavior
- any adapter logic depending on compatibility-only attributes

Success signal:

- most frontend tests import/use `app.ui.main_window.MainWindow` directly
- `run_frontend()` becomes a thin entry wrapper, not a structural module

### Phase 3: deletion readiness review

Before deleting `app/main.py`, confirm:

- no runtime import path still requires it
- no docs recommend it as the structural entrypoint
- compatibility-only attributes are gone from tests
- GUI startup still works through the real entry path

### Phase 4: remove deprecated files

When the above conditions hold:

- delete `app/main.py`
- delete any duplicate compatibility-only helpers that exist solely because of it
- update docs/tests/entrypoints in the same change set

Guiding principle:

> Compatibility files are scaffolding, not architecture.

---

## References

Backend/runtime:

- `stock_sim/services/instrument_service.py`
- `stock_sim/services/engine_registry.py`
- `stock_sim/services/order_service.py`
- `stock_sim/services/account_service.py`
- `stock_sim/services/market_data_service.py`
- `stock_sim/services/snapshot_service.py`

Frontend/app:

- `stock_sim/app/event_bridge.py`
- `stock_sim/app/services/market_data_service.py`
- `stock_sim/app/controllers/market_controller.py`
- `stock_sim/app/panels/market/panel.py`
- `stock_sim/app/ui/adapters/market_adapter.py`
- `stock_sim/app/ui/ui_refresh.py`
- `stock_sim/app/ui/main_window.py`
- `stock_sim/app/services/account_service.py`
- `stock_sim/app/controllers/account_controller.py`
- `stock_sim/app/panels/account/panel.py`
- `stock_sim/app/main.py`
