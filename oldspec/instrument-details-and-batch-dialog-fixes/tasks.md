# Tasks: instrument-details-and-batch-dialog-fixes

- [x] T1: Fix AgentsPanelAdapter missing _open_batch_dialog and wire to AgentCreationModal
  - Files: app/ui/adapters/agents_adapter.py, app/ui/agent_creation_modal.py (read-only)
  - Implements: R1, AC1
  - _Prompt:
    Role: PySide6 UI developer.
    Task: Add _open_batch_dialog() to AgentsPanelAdapter. Use Qt dialog if available with inputs: count (int), agent_type (combo from BATCH_ALLOWED_TYPES), name_prefix (str), strategies (multiline, optional). Validate via AgentCreationModal.submit, then close and refresh. If PySide6 not available, call logic.start_batch_create with defaults. Ensure no AttributeError and progress label updates via existing refresh.
    Restrictions: Minimal API changes; headless fallback must not crash.
    _Leverage: app/ui/agent_creation_modal.py, app/panels/agents/panel.py
    _Requirements: R1
    Success: Clicking "Batch Create…" opens or triggers batch; no exception; get_errors clean.

- [x] T2: Instrument list double-click opens symbol details; enhance details with L2 top5, daily K chart (zoom/pan), holdings pie
  - Files: app/ui/adapters/market_adapter.py, app/panels/market/panel.py
  - Implements: R2-R5, AC2
  - _Prompt:
    Role: PySide6 + pyqtgraph UI developer.
    Task: In MarketPanelAdapter, connect itemDoubleClicked to _handle_select. Extend SymbolDetailAdapter: add K chart using pyqtgraph GraphicsLayoutWidget; draw simple candlesticks from series open/high/low/close with pan/zoom enabled; add order book table already exists; add holdings pie chart using QGraphicsEllipseItem segments within a dedicated widget; fallback to labels when Qt/pyqtgraph unavailable. Update apply_detail to populate charts with new data; support empty data gracefully.
    Restrictions: No new heavy deps; use existing pyqtgraph. Keep headless stubs safe.
    _Leverage: series/order_book from MarketPanel.detail_view(); pyproject lists pyqtgraph.
    _Requirements: R2-R5
    Success: Double-click selects symbol; charts render when data present; no crashes; get_errors clean.

- [x] T3: Create Instrument dialog triad live-derivation with priority rules
  - Files: app/ui/adapters/market_adapter.py (dialog UI only)
  - Implements: R6-R9, AC3
  - _Prompt:
    Role: UI logic developer.
    Task: In _open_create_dialog(), add per-field textChanged handlers that record last_changed and auto-clear the derived field to enforce exactly one empty: if last_changed in {float_shares, market_cap} -> clear price; if last_changed == price -> clear float_shares. Then call cid.set_fields() and refresh preview via cid.get_view(). Show derived.field/value in UI. Prevent recursive updates via a guard flag.
    Restrictions: Do not modify derive_third_value; all logic in adapter.
    _Leverage: CreateInstrumentDialog.get_view/derive info.
    _Requirements: R6-R9
    Success: Example 25 + 5 -> market_cap shows 12.5 (亿元示例仅为文案说明)；changing price clears float_shares and recomputes; invalid inputs show errors; get_errors clean.

- [x] T4: Expose holdings data in MarketPanel.detail_view (optional minimal)
  - Files: app/panels/market/panel.py
  - Implements: partial R5
  - _Prompt:
    Role: Backend panel developer.
    Task: Add optional 'holdings' field to detail_view() with structure { labels: list[str], pct: list[float] }. If a service exists to compute multi-strategy retail aggregated holdings, call it; else return placeholder. UI must handle None.
    Restrictions: Do not introduce new services; keep as placeholder if not available.
    _Leverage: Existing MarketDataService/AgentService if present; else None.
    _Requirements: R5
    Success: detail_view() returns dict with 'holdings' key; UI renders pie or empty state.
