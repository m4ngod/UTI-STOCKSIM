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
- Use the hardened contract as the reference point for diagnosing real GUI detail/K-line problems.

## Outstanding work

- Confirm whether K-line should remain app-cache-led or move closer to backend-query-led.
- Record exact refresh/update responsibilities for each field.
- If needed, add clearer end-user-facing wording beyond debug/status labels for non-authoritative fields.
- After that, use the contract to diagnose the real GUI K-line/detail problem more safely.
