# Market Detail Module Status

## Module

Market detail page / symbol detail data contract

## Current goal

- Keep Market detail on an explicit multi-path contract instead of drifting back to ad hoc UI assembly.
- Treat the current convergence slice as a test-backed acceptance baseline.
- Leave only incremental UI and runtime-depth improvements for follow-up work.

## Current state

accepted

## Files involved

- `app/controllers/market_controller.py`
- `app/panels/market/panel.py`
- `app/ui/adapters/market_adapter.py`
- `app/services/market_data_service.py`
- `app/event_bridge.py`
- `services/market_data_service.py`
- `docs/frontend-backend-dependency-map.md`
- `docs/contracts/market/market-detail-contract.md`

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

## Field contract refinement (2026-03-20)

### `series`
- current source:
  - `app/services/market_data_service.py`
  - consumed by `app/panels/market/panel.py`
- responsibility:
  - symbol subscription intent
  - initial bars loading
  - bars cache reuse
  - indicator input data
- refresh model:
  - loaded on symbol selection / timeframe change
  - refreshed via app-layer market data service, not from backend snapshot merge
- current risk:
  - can diverge in freshness/semantics from snapshot/order-book path
- current code direction:
  - detail payload now exposes `series_meta` to mark this path as app-layer bars-cache-led rather than backend snapshot authority

### `snapshot`
- current source:
  - `app/controllers/market_controller.py` merged cache (`_snapshots`)
- upstream path:
  - backend snapshot events -> `app/event_bridge.py` batching -> frontend snapshot batch topic
- responsibility:
  - latest quote-like state for symbol detail and market list
- refresh model:
  - event-driven batch merge
- current risk:
  - depends on bridge/batch freshness rather than bars cache refresh timing
- current code direction:
  - detail payload now exposes `snapshot_meta` to mark this path as the current authoritative quote/order-book source in the detail view

### `order_book`
- current source:
  - snapshot-derived detail payload in `app/panels/market/panel.py`
- upstream nature:
  - backend matching-engine snapshot path
- responsibility:
  - display of current bid/ask ladder from latest merged snapshot
- refresh model:
  - updates only when snapshot path updates
- current risk:
  - appears stale if snapshot bridge lags even when other detail sections update

### `trades`
- current source:
  - local/event-fed ring buffer in `SymbolDetailPanel`
  - UI adapter subscribes to `Trade` and forwards matching-symbol payloads
- responsibility:
  - recent trade tape for current symbol
- refresh model:
  - event-driven append
- current risk:
  - symbol switching clears/reinitializes local buffer; not a backend authoritative history query
- current code direction:
  - detail payload now exposes `trades_meta` so downstream consumers know this is a local recent-tape view, not a backend historical query

### `holdings`
- current source:
  - optional app service helper if available
  - otherwise placeholder/fallback payload in panel logic
- responsibility:
  - auxiliary ownership/composition display only
- refresh model:
  - opportunistic / fallback-based
- current risk:
  - currently weakest contract in the detail view; may not represent real backend runtime ownership state
- current code direction:
  - return explicit non-authoritative metadata alongside the holdings payload so downstream UI/tests do not silently treat it as backend truth

## UI convergence note (2026-03-20)

- `app/ui/adapters/market_adapter.py` now consumes detail metadata (`series_meta`, `snapshot_meta`, `trades_meta`, `holdings_meta`) to make the detail page more honest about source/authority.
- `app/panels/market/panel.py` now emits `detail_health` so UI can distinguish missing/stale/degraded states instead of presenting all sections as equally fresh.
- Current minimal UI behavior:
  - snapshot label includes snapshot source + series source
  - snapshot label also includes lightweight health state (`ok` / `degraded`) plus per-section status
  - debug label includes trades/holdings status
  - holdings pie stays empty for explicit placeholder payloads instead of rendering fake composition slices

## Task 2026-03-22-market-detail-02
- **time**: 2026-03-22
- **status**: done
- **goal**: turn the working-draft Market detail contract into a stricter payload/UI/test contract with more explicit health and metadata semantics
- **files involved**:
  - `docs/contracts/market/market-detail-contract.md`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_detail_contract.py`
  - `tests/frontend/unit/test_market_detail_contract_extended.py`
- **total changed lines**: targeted contract hardening + test expansion

### Code fragment anchors
#### fragment 1
- **first line**: `# UTI-STOCKSIM Market Detail 数据契约`
- **last line**: `_文档状态：Market detail contract 初版完成_`

#### fragment 2
- **first line**: `        snapshot_meta = {`
- **last line**: `            "detail_health": detail_health,`

#### fragment 3
- **first line**: `        ob = detail.get('order_book') or None`
- **last line**: `                f"detail debug: mode={chart_mode} symbol={symbol} bars={bars_count} trades={trades_status} indicators={indicators_status} holdings={holdings_status}/{holdings_tag}"`

#### fragment 4
- **first line**: `def test_detail_view_exposes_contract_metadata_and_placeholder_holdings():`
- **last line**: `    assert detail["order_book_meta"]["status"] == "available"`

#### fragment 5
- **first line**: `def test_detail_view_marks_holdings_placeholder_when_helper_missing():`
- **last line**: `    assert detail["detail_health"]["overall"] == "degraded"`

### Change summary
- Added a dedicated `docs/market-detail-contract.md` to formalize Market detail as a multi-path aggregated view rather than a single-source detail object.
- Hardened `SymbolDetailPanel.get_view()` so metadata shape is more uniform across sections.
- Added `order_book_meta` and `indicators_meta` to the payload.
- Expanded `detail_health` with `order_book_status`, `holdings_status`, and `indicators_status`.
- Updated the adapter so detail labels/debug output surface the richer contract state.
- Added/expanded unit tests covering placeholder holdings, available helper-backed holdings, stale series degradation, and indicators status consistency.

### Purpose
- Make the Market detail contract explicit enough to guide future UI fixes instead of relying on implicit assumptions.
- Reduce the chance that later work treats local buffers / placeholders / app-cache paths as backend-authoritative truth.
- Create a safer base for later K-line/detail debugging and adapter cleanup.

### Impact / risk
- Positive maintainability impact: the payload is more honest and better structured.
- Low runtime risk: changes are additive contract clarifications rather than large structural rewrites.
- Medium follow-up risk: any code assuming older, less explicit detail payload semantics may need minor adjustment later.

### Next actions
- Decide whether `order_book` should later expose its own stale/degraded semantics beyond snapshot presence.
- Consider surfacing a small user-facing non-authoritative hint for holdings/trades instead of leaving it only in debug/status text.

## Task 2026-04-22-market-detail-04
- **time**: 2026-04-22 22:56:20 +08:00
- **status**: done
- **goal**: finish the current Market detail convergence slice and turn it into a reusable acceptance baseline
- **files involved**:
  - `app/controllers/market_controller.py`
  - `app/services/market_data_service.py`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `docs/contracts/market/market-detail-contract.md`
  - `tests/frontend/unit/test_market_detail_contract.py`
  - `tests/frontend/unit/test_market_detail_contract_extended.py`
  - `tests/frontend/unit/test_market_detail_trades_contract.py`
  - `tests/frontend/unit/test_market_snapshot_detail_contract.py`
  - `tests/frontend/unit/test_market_detail_adapter_contract_labels.py`
  - `tests/frontend/unit/test_market_runtime_trade_series.py`
  - `tests/frontend/unit/test_market_detail_chart_geometry.py`
- **total changed lines**: approximately 2117 touched lines across the convergence batch, including 4 newly added Market detail regression tests

### Code fragment anchors
#### fragment 1
- **first line**: `    def get_detail_snapshot(self, symbol: str, *, stale_after_ms: int = _DETAIL_SNAPSHOT_STALE_MS) -> Dict[str, Any]:`
- **last line**: `        return {`

#### fragment 2
- **first line**: `    def request_detail(self, symbol: str, timeframe: Timeframe, *, ensure_loaded: bool = True, limit: Optional[int] = None) -> Dict[str, object]:`
- **last line**: `        return {`

#### fragment 3
- **first line**: `    def get_holdings_detail(self, symbol: str, limit: int = 8) -> Dict[str, object]:`
- **last line**: `        return {`

#### fragment 4
- **first line**: `    def get_trades_detail(self, symbol: str, limit: int = 20) -> Dict[str, object]:`
- **last line**: `        return {`

#### fragment 5
- **first line**: `    def _apply_series_info(self, series_info: Dict[str, Any]) -> None:`
- **last line**: `        self._last_loaded_ts = time.time()`

#### fragment 6
- **first line**: `    def _merge_trades(`
- **last line**: `        return merged[: max(int(limit), 1)]`

#### fragment 7
- **first line**: `    def get_view(self) -> Dict[str, Any]:`
- **last line**: `        return {`

#### fragment 8
- **first line**: `def _build_detail_snapshot_label_text(detail: Dict[str, Any], *, bars_count: int) -> str:`
- **last line**: `    return (`

#### fragment 9
- **first line**: `def _build_detail_debug_label_text(`
- **last line**: `    return (`

#### fragment 10
- **first line**: `def _build_order_book_rows(order_book: Any, *, depth: int = 5) -> List[tuple[str, str, str]]:`
- **last line**: `    return rendered`

#### fragment 11
- **first line**: `    def apply_detail(self, detail: Dict[str, Any]):`
- **last line**: `        # Trades（最多 10 条）保留原占位，不做强制要求`

#### fragment 12
- **first line**: `def test_detail_view_exposes_contract_metadata_and_placeholder_holdings():`
- **last line**: `    assert detail["detail_health"]["overall"] == "degraded"`

#### fragment 13
- **first line**: `def test_detail_view_prefers_runtime_trade_log_contract():`
- **last line**: `    assert detail["trades_meta"]["status"] == "available"`

#### fragment 14
- **first line**: `def test_market_controller_exposes_snapshot_and_order_book_detail_contract():`
- **last line**: `    assert detail["order_book_meta"]["derived_from"] == "snapshot"`

#### fragment 15
- **first line**: `def test_detail_snapshot_label_text_uses_contract_status_and_age():`
- **last line**: `    assert "snap_age_ms=18000" in text`

### Change summary
- Moved `snapshot / snapshot_meta / order_book / order_book_meta` freshness semantics behind `MarketController.get_detail_snapshot(...)`.
- Promoted `series_meta`, `trades_meta`, and `holdings_meta` into explicit app-layer detail contracts instead of panel-local reconstruction.
- Changed the trades block from a page-local recent tape to a runtime-trade-log baseline plus local overlay model with dedupe.
- Fixed detail K-line visibility by switching chart geometry to bar-index x coordinates and a tight price-domain viewport.
- Split the adapter into smaller render helpers for:
  - snapshot summary text
  - debug text
  - chart empty-state text
  - symbol label text
  - order-book row shaping
- Added regression coverage for:
  - detail contract shape
  - runtime trades contract
  - snapshot freshness contract
  - adapter label rendering
  - chart geometry

### Purpose
- Create a stable acceptance baseline for the detail page before any larger visual or UX redesign.
- Make ownership of each core block obvious enough that future work can change one path without silently regressing another.
- Reduce the chance that the adapter or panel becomes a hidden second contract layer.

### Impact / risk
- Positive architectural impact:
  - core Market detail sections now have clearer ownership boundaries
  - UI text/status rendering is thinner and easier to reason about
- Positive verification impact:
  - the current convergence slice is backed by targeted regressions instead of only manual GUI checking
- Residual risk:
  - the detail page is still an aggregated multi-path view rather than a single backend detail query
  - real desktop visual acceptance still benefits from periodic click-through verification when chart or adapter behavior changes
  - trades remain a recent-window contract, not a full history browser

### Next actions
- Add one small real-GUI verification pass focused on:
  - live candle appearance
  - stale snapshot wording
  - order-book table updates
- Decide whether holdings should stay helper-scoped or graduate to a runtime-authoritative detail query.
- If the page is considered stable, shift effort from further decomposition to UX cleanup and user-facing hints for non-authoritative blocks.

## Task 2026-04-22-market-detail-05
- **time**: 2026-04-22 23:34:00 +08:00
- **status**: done
- **goal**: finish the real-GUI acceptance loop by making the detail K-line visibly render in the desktop widget instead of relying on pyqtgraph behavior that looked blank in practice
- **files involved**:
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_detail_chart_geometry.py`
  - `artifacts/market_detail_gui_validation/live_chart_qt_canvas_full.png`
  - `artifacts/market_detail_gui_validation/live_chart_qt_canvas_chart.png`
  - `artifacts/market_detail_gui_validation/qt_canvas_acceptance_report.json`
- **total changed lines**: small targeted rendering/verification follow-up

### Change summary
- Replaced the detail-page live chart primary render path with a lightweight Qt painter canvas instead of relying on pyqtgraph items that existed logically but were visually close to blank in real desktop grabs.
- Kept the existing detail contract intact:
  - `series`
  - `series_meta`
  - `snapshot`
  - `snapshot_meta`
  - `order_book`
  - `order_book_meta`
- Rendered:
  - candle wicks and bodies
  - close-price overlay line and markers
  - reference-price guide line
  - compact axis/grid framing
- Added a regression test that verifies the chart widget paints vivid series pixels instead of regressing back to an “empty black panel with labels only” state.
- Saved real-widget acceptance artifacts showing the chart now renders visibly in the detail page.

### Purpose
- Close the main remaining UX gap in Market detail after the data-contract convergence work.
- Stop the desktop app from presenting a logically healthy detail contract with a visually untrustworthy chart region.

### Impact / risk
- Positive:
  - live detail K-line is now visibly present in desktop rendering
  - chart rendering is no longer dependent on pyqtgraph behavior that was fragile in this environment
  - regression protection now covers visual paint output, not only data contract shape
- Residual risk:
  - the new canvas is intentionally simple and favors reliability over advanced pan/zoom interactions
  - if richer chart interactivity is reintroduced later, it should be treated as a separate feature rather than folded back into this acceptance fix

### Verification
- Targeted regressions passed:
  - `tests/frontend/unit/test_market_detail_chart_geometry.py`
  - `tests/frontend/unit/test_market_detail_adapter_contract_labels.py`
  - `tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py`
  - `tests/frontend/integration/test_frontend_trading_closed_loop.py`
- Real-widget acceptance artifacts now show:
  - live chart visibly rendered
  - snapshot/debug labels still aligned with the detail contract
  - order-book table still present below the chart

### Next actions
- Treat current Market detail as stable enough for normal feature work.
- If desired, do a later UX-only pass for chart styling, hover info, or interaction affordances without reopening contract ownership.

## Task 2026-03-26-market-detail-03
- **time**: 2026-03-26
- **status**: done
- **goal**: repair the real frontend/runtime live-market path so backend trades can reach Market panel snapshot state
- **files involved**:
  - `app/event_bridge.py`
  - `app/headless.py`
  - `setup_frontend_entry.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_event_bridge.py`
  - `tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py`
- **total changed lines**: targeted bridge/startup/adapter wiring repair

### Code fragment anchors
#### fragment 1
- **first line**: `BACKEND_RUNTIME_SNAPSHOT_TOPIC = "SnapshotUpdated"`
- **last line**: `def stop_frontend_bridge() -> None:`

#### fragment 2
- **first line**: `start_frontend_bridge()`
- **last line**: `return HeadlessMainWindow()`

#### fragment 3
- **first line**: `start_frontend_bridge()`
- **last line**: `app.aboutToQuit.connect(stop_frontend_bridge)`

#### fragment 4
- **first line**: `def _on_batch(_topic: str, payload: Dict[str, Any]):`
- **last line**: `self._cancel_batch = subscribe_topic(FRONTEND_SNAPSHOT_BATCH_TOPIC, _on_batch, async_mode=False)`

### Change summary
- Confirmed the user-visible symptom was not just "retail has no trades"; backend trades could already occur and `Orders` could receive them.
- Found two missing live-data links:
  - GUI/headless startup did not automatically start the frontend `EventBridge`.
  - `MarketPanelAdapter` reacted to `frontend.snapshot.batch` by refreshing only, without first merging the batch into `MarketController`.
- Rebuilt `app/event_bridge.py` so it:
  - subscribes to both app/runtime event buses
  - normalizes runtime `SnapshotUpdated` payloads into frontend snapshot DTO shape
  - exposes singleton startup helpers for frontend entry ownership

## Task 2026-03-26-market-detail-04
- **time**: 2026-03-26
- **status**: done
- **goal**: reduce Market vs Orders divergence caused by duplicate trade display, and let real runtime trades draw at least one honest K-line in detail view
- **files involved**:
  - `app/services/bars_cache.py`
  - `app/services/market_data_service.py`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `app/panels/orders/panel.py`
  - `app/ui/adapters/orders_adapter.py`
  - `tests/frontend/unit/test_orders_panel_dedup.py`
  - `tests/frontend/unit/test_market_runtime_trade_series.py`
- **total changed lines**: medium targeted frontend/runtime convergence fix

### Change summary
- Added recent-event deduping to the Orders panel so the same runtime trade event no longer appears twice when both app/runtime event paths deliver equivalent payloads.
- Added runtime-trade-backed bar construction in `app/services/market_data_service.py` so real desktop trades can materialize into a minimal local OHLC series without waiting for the later persistence/aggregator path.
- Updated `SymbolDetailPanel.add_trade()` to:
  - deduplicate the local trade tape
  - feed trades into the runtime-trade bar cache
  - refresh the detail view immediately
- Updated detail-page adapters so dedicated `symbol:*` pages also subscribe to live trade and snapshot batch events rather than staying static after first open.
- Moved Market and Orders refresh paths onto the UI thread to reduce cross-thread repaint risk.

### Purpose
- Make the on-screen Market/Orders relationship more honest by removing duplicate trade presentation noise.
- Ensure that once runtime trades exist, detail page K-line rendering has a non-placeholder data source and can draw the current bar.

### Impact / risk
- Positive: detail page now has a direct “runtime trade -> local bar” fallback path for live desktop simulations.
- Positive: dedicated detail pages should no longer stay frozen while other panels continue updating.
- Risk: this is still an app-layer live-bar cache, not yet the long-term authoritative persistence/replay bar pipeline.

### Remaining known gaps after this fix
- `MarketDataService` still defaults to a synthetic fetcher for historical bars when no real backend fetcher is injected.
- `holdings` in detail remains an auxiliary/partly placeholder contract rather than a fully runtime-authoritative ownership view.
- runtime `bar_aggregator.py` / `snapshot_listener.py` are still not part of the standard desktop startup chain, so durable history/replay semantics are not yet the same thing as the live detail cache.
- Updated startup paths to auto-start the bridge before panels are used.
- Updated `MarketPanelAdapter` batch handling so `merge_batch()` happens before UI refresh.
- Added regression tests for runtime snapshot normalization and Market batch-to-controller merge.

### Purpose
- Make Market panel reflect real backend runtime activity instead of staying visually stale while the engine is already trading.
- Prevent future regressions where startup succeeds but the live market feed is structurally disconnected from the desktop UI.

### Verification
- `tests/frontend/unit/test_event_bridge.py`: passed
- `tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py`: passed
- Targeted smoke evidence before final adapter fix:
  - engine trade count > 0
  - orders panel count > 0
  - market snapshot still missing
- That evidence directly matched the repaired `MarketPanelAdapter` merge gap.

### Additional verification note (2026-03-26)
- A later logic-level smoke test using the real frontend `MarketController.create_instrument()` path confirmed:
  - payload now includes `runtime_registered=True`
  - the created symbol exists in runtime `engine_registry`
  - six GUI-created retail agents can produce real trades on that symbol
- This identified an additional root cause behind the user-visible “create instrument but nothing ever trades” symptom:
  - the previous frontend create flow only created app-layer/watchlist state
  - it did not persist/register a real runtime instrument
- `app/controllers/market_controller.py` now bridges GUI create into runtime `services.instrument_service.InstrumentService.create(...)` and currently assumes:
  - `settlement_cycle = 1`
  - `ipo_opened = True`
- This assumption is intentional for the current desktop workflow so a newly created GUI symbol can enter continuous trading immediately instead of silently remaining detached or stuck in an un-driven IPO phase.

### Impact / risk
- Positive runtime impact: live market snapshot path is now structurally connected.
- Low-to-medium risk: startup now owns a process-level bridge singleton, so later work should avoid creating duplicate ad-hoc bridges in normal GUI flow.

### Next actions
- Re-run a full manual GUI smoke test on desktop:
  - create instrument
  - create/start retail
  - confirm Market watchlist last price and detail snapshot/order-book move in sync with Orders
- If needed, then tighten symbol-detail trade tape refresh semantics separately from snapshot flow.
- Use the hardened contract as the reference point for diagnosing real GUI detail/K-line problems.

## Task 2026-03-25-market-detail-03
- **time**: 2026-03-25
- **status**: done
- **goal**: restore double-click opening of dedicated symbol detail pages in the real GUI workspace
- **files involved**:
  - `app/ui/adapters/market_adapter.py`
  - `app/ui/ui_refresh.py`
  - `app/panels/market/panel.py`
- **change summary**:
  - Re-enabled the Market watchlist double-click path to call `open_symbol_page(...)` after local selection refresh, instead of intentionally suppressing dedicated page opening.
  - Passed through the current Market controller / service pair so dynamic symbol pages reuse the same app-layer runtime context instead of fabricating a disconnected detail source.
  - Preserved local in-panel detail refresh first, then opened or focused the dynamic workspace page such as `symbol:001`.
  - Verified offscreen that opening `symbol:001` now registers a dedicated workspace page successfully.
- **purpose**:
  - Remove the current GUI mismatch where the inline detail region refreshed but the user-facing dedicated detail page never appeared.
  - Bring real GUI behavior back into line with the dynamic symbol-page design already present in the codebase.
- **impact / risk**:
  - Positive: double-click now behaves like an actual “open detail page” action again.
  - Positive: dynamic symbol pages are no longer dead code in the main Market interaction path.
  - Risk: if later work changes Market controller / service lifetime assumptions, symbol-page reuse should be rechecked against engine/runtime consistency.
- **next actions**:
  - Run a live GUI smoke check on create-instrument -> double-click -> symbol page -> back navigation.
  - If symbol pages later gain editable controls, document whether they should stay shared-context or become isolated page controllers.

## Task 2026-03-25-market-detail-04
- **time**: 2026-03-25
- **status**: done
- **goal**: stop the Market/detail UI from drawing default synthetic fallback bars as if they were real K-line data before any real market activity exists
- **files involved**:
  - `app/services/market_data_service.py`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_detail_contract.py`
- **change summary**:
  - Marked the default `MarketDataService()` fallback series as placeholder metadata when bars come from the implicit synthetic fetcher.
  - Propagated that placeholder flag through `SymbolDetailPanel.get_view()` into `series_meta`.
  - Updated the Market/detail adapter so placeholder series are treated as “no real data” for rendering: chart is cleared, visible `bars` count stays `0`, and debug text now says `series_ui=placeholder`.
  - Kept the synthetic payload itself available for non-UI tests and debugging instead of deleting the fallback mechanism outright.
  - Added a contract assertion that the default detail path exposes `series_meta.placeholder = True`.
- **purpose**:
  - Prevent the UI from misleading users with example K-lines before any real bars / trades / runtime market history exist.
  - Make the frontend honest without destabilizing existing test scaffolding that still benefits from deterministic fallback bars.
- **impact / risk**:
  - Positive: single-clicking a newly created instrument in Market no longer shows fake K-line drawings by default.
  - Positive: detail labels/debug output now distinguish placeholder series from real renderable bars.
  - Risk: the payload still contains synthetic bars internally, so future UI code must continue honoring the placeholder metadata instead of rendering blindly.
- **next actions**:
  - Do one live GUI smoke check on a newly created instrument to confirm the chart region stays empty until real bars exist.
  - If the product later gets a real historical-bar source, switch placeholder detection from “default synthetic fetcher” to explicit runtime source semantics.

## Outstanding work

- Confirm whether K-line should remain app-cache-led or move closer to backend-query-led.
- Record exact refresh/update responsibilities for each field.
- If needed, add clearer end-user-facing wording beyond debug/status labels for non-authoritative fields.
- After that, use the contract to diagnose the real GUI K-line/detail problem more safely.

## Task 2026-03-26-market-detail-06
- **time**: 2026-03-26
- **status**: done
- **goal**: replace the temporary fixed-slot K-line view with a more realistic time-axis chart and fix the nearly invisible single-bar rendering bug
- **files involved**:
  - `app/ui/adapters/market_adapter.py`
  - `app/services/market_data_service.py`
  - `tests/frontend/unit/test_market_runtime_trade_series.py`
- **change summary**:
  - switched the chart bottom axis from synthetic slot indexes to real bar timestamps
  - attached a `DateAxisItem` so the x-axis now represents time instead of debug slots
  - changed candlestick body width to scale with the actual bar interval
  - restored y-axis behavior to visible-bar high/low auto framing rather than fixed limit-band framing
  - kept a lightweight reference-price guide line, but removed the temporary hard lock to the limit range
- **purpose**:
  - make the chart behave closer to normal trading software
  - ensure that one or a few live bars are still clearly visible
- **impact / risk**:
  - Positive: the previous “red pixel / empty chart” symptom is materially reduced
  - Positive: the chart is now much closer to the user mental model of a real K-line
  - Risk: until historical runtime bars are fully wired in, the left edge still reflects currently loaded history rather than a guaranteed IPO-day-origin history

## Task 2026-03-26-market-detail-05
- **time**: 2026-03-26
- **status**: done
- **goal**: make live detail K-line visible and stable during runtime trading instead of auto-scaling into a jumping point-like artifact
- **files involved**:
  - `app/services/market_data_service.py`
  - `app/controllers/market_controller.py`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_runtime_trade_series.py`
- **change summary**:
  - Switched detail default timeframe to `1m` so live trading opens on an intraday bar path instead of the coarsest day bar by default.
  - Added symbol chart metadata at the app market-data layer:
    - `reference_price`
    - `price_step`
    - `limit_pct`
    - `limit_up`
    - `limit_down`
    - per-timeframe trading-slot count
  - Registered newly created GUI instruments with chart reference metadata at creation time.
  - Updated the detail adapter to render with:
    - fixed trading-slot x range
    - fixed y range from price-limit band
    - reference / upper-limit / lower-limit horizontal guide lines
  - Kept the current live-bar source as runtime-trade-fed app cache, but removed the previous “auto-scale to a fast-moving pixel” behavior.
- **purpose**:
  - Make the detail K-line behave more like a real Chinese stock-market intraday chart, where the y-axis is anchored by the day limit band instead of being re-fit on every tiny tick.
  - Ensure the first live bar is actually visible to the user instead of collapsing into a red point.
- **impact / risk**:
- Positive: chart readability is much better for low-trade / cold-start symbols.
- Positive: the detail page now has a stable visual frame even when only one live bar exists.
- Risk: this is still not the final authoritative historical-K pipeline; it is a live desktop rendering stabilization over the current runtime-trade cache.

## Task 2026-03-26-market-detail-07
- **time**: 2026-03-26
- **status**: done
- **goal**: connect remaining Market-detail helper paths to runtime data and bring snapshot/bar support services into the standard desktop startup chain
- **files involved**:
  - `app/services/market_data_service.py`
  - `app/panels/market/panel.py`
  - `app/panels/__init__.py`
  - `app/runtime_bootstrap.py`
  - `setup_frontend_entry.py`
  - `app/headless.py`
  - `services/bar_aggregator.py`
- **change summary**:
  - Added runtime bar loading to `MarketDataService.load_initial(...)` before synthetic fallback, so detail pages can consume persisted 1m/1h/1d bars when available.
  - Added an opt-in runtime holdings helper and wired the real desktop Market panel to enable it, while leaving default test instances on the previous placeholder path.
  - Added a dedicated frontend/runtime bootstrap helper that starts `snapshot_listener` and `bar_aggregator` as part of normal GUI/headless startup.
  - Rebuilt `bar_aggregator.py` into a working OHLCV upsert path so persisted history can be generated from `snapshots_1s` instead of depending on broken placeholder variables.
- **purpose**:
  - Reduce the remaining gap between Market/detail UI and the actual runtime persistence layer.
  - Make detail history and holdings progressively more authoritative without breaking existing test scaffolding.
- **impact / risk**:
- Positive: desktop startup now actually activates the persistence sidecars needed for historical Market/detail data.
- Positive: holdings can now come from runtime positions instead of staying a permanent placeholder in the real GUI.
- Risk: 5m/15m bars still fall back to app-side aggregation/fallback because only 1m/1h/1d persisted tables are currently wired here.

## Task 2026-03-26-market-detail-08
- **time**: 2026-03-26
- **status**: done
- **goal**: switch K-line x-axis from real timestamps to bounded `sim_day` coordinates and remove the unused holdings pie-chart path from real rendering
- **files involved**:
  - `app/ui/adapters/market_adapter.py`
  - `app/services/market_data_service.py`
- **change summary**:
  - chart rendering now places candles on a `sim_day`-normalized axis instead of a wall-clock axis
  - zoom/pan limits are bounded to `x >= 0`, `x <= current_sim_day + 1`, `y >= 0`, `y <= history_high`
  - the old holdings pie path is disabled from the real render path so Market/detail no longer spends UI work on an unused visualization
- **impact / risk**:
  - Positive: the first visible bar is much easier to render/read in simulation coordinates
  - Positive: the chart can no longer drift into meaningless negative/overscrolled ranges
  - Risk: there is still dead helper code around the old pie renderer that can be removed in a later cleanup pass
## Chart clamp note (2026-03-26)

### status
done

### goal
把 K 线图的平移/缩放边界从“软 limits”收紧为真正不能越界的硬边界。

### files involved
- `app/ui/adapters/market_adapter.py`

### change summary
- 新增受限 `ViewBox`，对鼠标拖拽与滚轮缩放后的视图范围做二次钳制。
- 横轴最左侧不再允许小于 `sim_day0`，右侧不允许超过当前图表右边界。
- 纵轴最低不再允许小于 `0`，最高不允许超过当前历史最高价边界。

### impact / risk
- Positive: 视图行为更符合模拟交易软件预期，不再能无限拖到无效区域。
- Risk: 若后续横轴从“当前缓存 bars”切换到“完整 IPO 历史范围”，需要同步更新边界来源。
## Task 2026-04-05-market-detail-09
- **time**: 2026-04-05
- **status**: done
- **goal**: expose active runtime session identity to Market/detail so frontend history views can tell which `run_id` they are reading
- **files involved**:
  - `app/runtime_gateway.py`
  - `app/services/market_data_service.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_active_run_meta.py`
- **change summary**:
  - added `RuntimeGateway.get_current_run_id()`
  - `MarketDataService` chart metadata now includes `active_run_id` and `history_scope`
  - Market detail debug text now surfaces the current history scope and active run id
- **impact / risk**:
  - Positive: frontend K-line/detail diagnostics can now distinguish current-session history from mixed persisted history during debugging
  - Positive: follow-up UI work can explicitly key chart/history state off the active run without re-querying backend reports
  - Risk: current history scope still reflects the active runtime session identity, not a full user-selectable historical run filter yet

## Task 2026-04-05-market-detail-10
- **time**: 2026-04-05
- **status**: done
- **goal**: stop the desktop app from silently mixing synthetic bars into runtime Market/detail history
- **files involved**:
  - `app/services/market_data_service.py`
  - `app/app_context.py`
  - `tests/frontend/unit/test_market_runtime_only_mode.py`
- **change summary**:
  - `MarketDataService` now supports `allow_synthetic_fallback`
  - the shared desktop `AppContext` instantiates Market data in runtime-only mode
  - when runtime bars are missing in desktop mode, detail now stays empty instead of auto-filling synthetic bars
- **impact / risk**:
- Positive: desktop K-line/history semantics are more honest, which is important for a full simulation platform
- Positive: debugging "why is this chart moving" is easier because empty runtime history no longer becomes fake bars
- Risk: users will now see empty history sooner if runtime bar persistence is not producing data, which makes remaining backend gaps more visible

## Instrument issuance UX note (2026-04-09)

### status
done

### goal
Reduce accidental creation of "cold-start impossible" instruments in the desktop GUI by making the create-instrument dialog start from more realistic issuance defaults.

### files involved
- `app/ui/adapters/market_adapter.py`

### change summary
- the desktop create-instrument dialog now prefills:
  - `float_shares = 1,000,000`
  - `market_cap = 10,000,000`
  leaving price as the derived field
- the preview area now emits warnings when derived float shares are extremely small, especially the pathological `1-share` IPO case

### impact / risk
- Positive: quick-created symbols are much less likely to end up with `free_float_shares = 1`, which previously made IPO retail distribution and cold-start liquidity look broken even when the code path was working
- Positive: users get earlier feedback when the chosen issuance parameters are too small for a meaningful simulated market
- Risk: these are UI defaults and warnings, not hard backend validation; intentionally tiny instruments are still allowed

## Task 2026-04-21-market-detail-11
- **time**: 2026-04-21
- **status**: done
- **goal**: harden Market detail so chart/snapshot state reflects the actual runtime data path instead of optimistic inferred labels
- **files involved**:
  - `app/services/market_data_service.py`
  - `services/runtime_query_service.py`
  - `app/panels/market/panel.py`
  - `app/ui/adapters/market_adapter.py`
  - `tests/frontend/unit/test_market_runtime_only_mode.py`
  - `tests/frontend/unit/test_market_active_run_meta.py`
  - `tests/frontend/unit/test_market_detail_contract_extended.py`
- **change summary**:
  - `RuntimeQueryService.get_bars(...)` now tags returned rows with the resolved history scope so app-layer chart metadata can distinguish:
    - active-run bars
    - unscoped fallback bars
  - `MarketDataService` now records per-series path metadata instead of collapsing chart history into ambiguous labels such as `runtime-persisted-or-empty`
  - chart/detail payload now distinguishes:
    - `history_scope_requested`
    - `history_scope_resolved`
    - `series_source`
    - runtime-backed vs non-runtime-backed series paths
  - synthetic fallback history is now surfaced explicitly as placeholder/non-authoritative chart data
  - runtime-empty history is now surfaced explicitly instead of being grouped together with runtime-persisted history
  - snapshot/order-book contract now marks stale snapshot state based on snapshot age instead of only `available/missing`
  - detail overall health now degrades when the chart path is only a placeholder even if snapshot/order-book are present
- **impact / risk**:
  - Positive: Market detail is more honest about whether the user is seeing active-run history, unscoped historical fallback, synthetic placeholder bars, or no runtime history at all
  - Positive: snapshot freshness problems are now visible in contract/UI status instead of silently reading as healthy market state
  - Risk: some existing debug expectations/tests needed to move from inferred `active-run` history labels to resolved history labels

## Task 2026-04-25-market-detail-12
- **time**: 2026-04-25
- **status**: done
- **goal**: recover Market detail K-line bars from runtime trade history when persisted runtime bars are missing or delayed
- **files involved**:
  - `app/services/market_data_service.py`
  - `tests/frontend/unit/test_market_runtime_only_mode.py`
- **change summary**:
  - Added a runtime trade-log OHLCV fallback inside `MarketDataService.load_initial(...)`.
  - When persisted runtime bars are empty, the service now queries recent runtime trades for the selected symbol and aggregates them into timeframe buckets before considering the history path missing.
  - The recovered series is marked as `source = runtime-trade-log-bars`, authoritative, runtime-backed, and resolved to `history_scope_resolved = runtime-trade-log`.
  - Kept desktop runtime-only behavior honest: if both persisted bars and trade log are empty, the UI still shows `K: no runtime history` instead of drawing synthetic bars.
  - Added a regression proving that trade-only runtime history produces visible bar data and does not overwrite the source metadata with `runtime-empty`.
- **purpose**:
  - Fix the user-visible state where the Market panel could show many executions while the K-line chart still stayed empty with `K: no runtime history`.
  - Bridge the practical gap between live trades already persisted in `TradeORM` and bar sidecar persistence that may not have produced rows yet.
- **impact / risk**:
  - Positive: Market/detail now has a second authoritative runtime path for chart recovery during active simulation.
  - Positive: the fix preserves the earlier decision to hide synthetic placeholder bars in the real desktop app.
  - Risk: this is still a recent-window reconstruction, not a replacement for the durable bar persistence pipeline.
- **verification**:
  - `tests/frontend/unit/test_market_runtime_only_mode.py`
  - `tests/frontend/unit/test_market_active_run_meta.py`
  - `tests/frontend/unit/test_market_detail_adapter_contract_labels.py`
  - `tests/test_runtime_query_run_scoped_bars.py`
  - `tests/test_release_minimal_runtime_chain.py`
  - `tests/test_kline_and_account_events.py`
