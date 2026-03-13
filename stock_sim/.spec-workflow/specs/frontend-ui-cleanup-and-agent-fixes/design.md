# Design: Frontend UI Cleanup and Agent Fixes

Spec: frontend-ui-cleanup-and-agent-fixes

## Context and Findings
Codebase scan highlights:
- Settings-related modules exist and are registered:
  - Panels: `app/panels/settings/panel.py` (class SettingsPanel)
  - UI: `app/ui/adapters/settings_adapter.py`, `app/controllers/settings_controller.py`
  - State/Bridge: `app/state/settings_state.py`, `app/state/settings_store.py`, `app/ui/settings_sync.py`, `app/bridge/settings_clock.py`
- i18n and theme:
  - i18n binding at `app/ui/i18n_bind.py`; tests import `app.i18n.*`
- Panels and registry:
  - Panel Registry in `app/panels/registry.py`; placeholder panel helper in `app/panels/__init__.py`
  - Market panel and symbol detail already exist: `app/panels/market/panel.py` defines `SymbolDetailPanel` and `MarketPanel`
  - Market adapter wires double-click: `app/ui/adapters/market_adapter.py` connects `itemDoubleClicked` (line ~382)
- Account panel:
  - UI adapter `app/ui/adapters/account_adapter.py`; service/controller: `app/services/account_service.py`, `app/controllers/account_controller.py`
- Agents UI:
  - Adapter `app/ui/adapters/agents_adapter.py` (Start button handling present)

## Design Overview
Deliver five changes while minimizing regressions:
1) Remove Settings panel and language switching; set default language zh_CN at app init
2) Account panel: add account/agent dropdown and filtered orders view
3) Fix batch start of multi-strategy retail agents (start all selected, update statuses)
4) Replace placeholder UI/methods in touched modules
5) Enable market symbol double-click to open detail subpage (daily K-line + L2 top5)

## Detailed Design

### 1. Remove Settings panel and enforce default language
- Deregistration/removal:
  - Remove registration of SettingsPanel from `app/panels/registry.py` (and any menu/docking references in `app/ui/main_window.py`)
  - Delete or keep module but no-op export. Safer path: keep `SettingsPanel` file but remove from registry and menu to avoid import errors. Mark for deletion after tests updated.
- Keep SettingsSync minimal:
  - `app/ui/settings_sync.py` will only push initial defaults on startup (theme, language) and ignore runtime language changes.
- Default language:
  - Initialize `zh_CN` language in i18n loader (likely `app/i18n/loader.py`) or via `app/ui/i18n_bind.py` on app bootstrap before panels render.
  - Remove any Settings controller wiring that toggles language.
- Update tests:
  - Adjust `tests/test_panel_i18n_titles.py` to not require dynamic switching; keep missing/fallback tests intact.
  - Update `tests/test_panels_e2e_view_models.py` expected core panel list to remove `settings`.

### 2. Account panel: dropdown selector and orders filtering
- UI adapter `app/ui/adapters/account_adapter.py`:
  - Add a top-left dropdown (QComboBox) to list “agents and multi-strategy retail accounts”.
  - On selection change, emit a signal to controller to load orders for selected account_id.
  - Render orders table (reuse `OrdersPanelAdapter` if integrated or keep internal table).
- Controller `app/controllers/account_controller.py`:
  - Add `load_accounts()` to provide list with fields: id, name, type (agent|multi-retail), status.
  - Add `load_orders(account_id, page=1, page_size=100)` that calls service.
- Service `app/services/account_service.py`:
  - Implement `list_accounts()` by querying registry of agents and retail strategies.
  - Implement `get_orders_by_account(account_id, offset/limit)` via infra repository or in-memory store.
- DTO `app/core_dto/account.py`:
  - Ensure DTO supports both agent-backed and retail multi-strategy accounts; include stable identifier.

### 3. Fix batch Start for multi-strategy retail agents
- UI adapter `app/ui/adapters/agents_adapter.py`:
  - Start handler should query selected rows (selectionModel.selectedRows()) and iterate over each.
  - For each selected, call controller/service start and update row status to RUNNING upon success (or show error per item).
  - Ensure non-blocking UI: use QThreadPool/QRunnable or async tasks if infrastructure exists; else sequential with spinner.
- Controller/Service:
  - Ensure `start_agent(agent_id)` is idempotent and returns status; expose `start_agents(list[agent_id])` for batch.
  - Handle multi-strategy retail agent factory if applicable.
- Tests:
  - Add unit test covering batch start: create 3 agents, invoke start, assert all RUNNING.

### 4. Replace placeholder UI/methods
- Identify placeholders in touched modules:
  - `app/panels/__init__.py` has `_PlaceholderPanel` — replace usages in registry for our panels (market/account) if any.
  - `app/ui/adapters/market_adapter.py` shows stub methods like `setStartAngle(self, *_) : pass` at ~97; replace only if part of market symbol visualization (ensure no dead UI).
- Remove `pass`/TODO placeholders where they block the user stories; add minimal functional implementations.

### 5. Market symbol double-click opens detail subpage
- Adapter `app/ui/adapters/market_adapter.py`:
  - Ensure `itemDoubleClicked` handler calls a controller method with `symbol`.
- Controller `app/controllers/market_controller.py`:
  - Implement `open_symbol_detail(symbol)` that asks registry to open `SymbolDetailPanel` with the symbol context.
- Panel `app/panels/market/panel.py`:
  - Ensure `SymbolDetailPanel` renders Daily K-line and L2 five-level book:
    - Use `app/indicators` for K-line (or fallback to matplotlib/pyqtgraph if minimal needed).
    - Use `app/services/market_data_service.py` for OHLC daily and current order book (top5 levels).
  - Wire close/back to return to market list without losing state.

## Data Flow
- Accounts/orders:
  - events: selectionChanged -> controller.load_orders -> service.get_orders_by_account -> adapter.render_orders
- Agents batch start:
  - startClicked -> selectedIds -> controller.start_agents(ids) -> service.start_agent(id) loop -> adapter.updateRowStatus
- Market dblclick:
  - symbolDblClick -> controller.open_symbol_detail(symbol) -> registry.open(SymbolDetailPanel, props) -> panel fetches data via market_data_service

## Risks & Mitigations
- Removing Settings references may break startup: guard imports, deregister cleanly, keep module but unused initially.
- i18n tests expecting language switch: update tests to assert default zh_CN and no toggle.
- Data volume for orders: add basic pagination params to service/controller.

## Migration/Compatibility
- Panel registry: remove Settings from default layout; if serialized layouts reference it, add fallback to skip missing panel.
- Config: default theme light; language zh_CN; no UI toggle.

## Acceptance Tests Mapping
- AC1: No settings panel; zh_CN by default → verify startup and titles.
- AC2: Account dropdown + orders filter → unit test on controller + a small integration.
- AC3: Batch start for multi-strategy agents → unit test verifying all started.
- AC4: No placeholders in touched modules → grep-based check + tests run.
- AC5: Market dblclick opens detail → simulate dblclick signal and assert panel opened and renders charts.

## Implementation Notes
- Keep public APIs stable; prefer adding new methods over breaking changes.
- Keep imports lazy where possible to avoid circular deps.
- Update docs: `docs/frontend_dev_guide.md` for panel list and navigation.

