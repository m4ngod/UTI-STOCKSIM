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

## Frontend ↔ Runtime semantic gap (2026-03-20)

### Frontend account path today
- `app/services/account_service.py`
  - fetcher-oriented
  - can use synthetic data
  - returns `AccountDTO`
- `app/controllers/account_controller.py`
  - caches the latest `AccountDTO`
- `app/panels/account/panel.py`
  - renders summary + positions
  - currently emphasizes:
    - `cash`
    - `equity`
    - `utilization`
    - `realized_pnl`
    - `unrealized_pnl`
    - per-position `quantity`, `avg_price`, `borrowed_qty`, `pnl_unreal`

### Backend runtime semantics today
- `services/account_service.py`
  - owns real freeze/release/settlement semantics
  - tracks:
    - `cash`
    - `frozen_cash`
    - `frozen_fee`
    - `frozen_qty`
    - `borrowed_qty`
- `services/order_service.py`
  - coordinates:
    - fee pre-freeze
    - main notional/position freeze
    - partial/final release
    - fill settlement
    - IOC/FOK residual refund / cancellation handling

### Current semantic gap
The frontend account panel is still largely DTO-led and summary-oriented, while the backend order/account path is lifecycle-oriented.

That means the current UI can show a reasonable account snapshot while still under-expressing important runtime states such as:
- buy-side fee pre-freeze
- buy-side frozen cash before final cost refund
- sell-side frozen quantity before fill/cancel
- short-side borrowed quantity transitions during sell and buy-to-cover

### Why this matters
If this gap is not narrowed, the released UI may look "mostly correct" while failing to explain:
- why available cash changed before final fill
- why account cash/equity appears inconsistent during active orders
- why a position can have borrow/short semantics not obvious from summary fields
- why order lifecycle events and account summary do not visually line up

## Contract convergence note (2026-03-21)

- `app/panels/account/panel.py` has started surfacing the semantic gap explicitly in its view contract.
- Current code direction:
  - account summary now includes `frozen_cash`
  - account summary now includes `account_meta`
  - position rows now include `frozen_qty`
  - position rows now include `position_meta` with lightweight exposure-state hints
- This is still DTO-led, but it makes the gap to runtime lifecycle semantics visible instead of implicit.

## Orders alignment note (2026-03-21)

- `app/panels/orders/panel.py` has started surfacing lifecycle semantics in its normalized lines.
- Current code direction:
  - each order/event line now exposes `lifecycle_stage`
  - each order/event line now exposes `line_meta`
- This does not yet make Orders authoritative runtime state, but it improves semantic alignment with Account freeze/release behavior.

## Recommended next actions

1. Define whether the account panel stays DTO-led for now or starts surfacing selected runtime freeze fields.
2. Treat the following runtime fields as first-class contract candidates for UI alignment:
   - `frozen_cash`
   - `frozen_fee`
   - `frozen_qty`
   - `borrowed_qty`
3. Align Orders + Account views around lifecycle semantics instead of treating them as separate independent summaries.

## Runtime repair note (2026-03-21)

### status
in-progress

### goal
Stabilize backend `services/account_service.py` so freeze / release / settle semantics are usable as a trustworthy runtime base before broader refactor work continues.

### files involved
- `services/account_service.py`
- `services/order_service.py`
- `tests/test_account_service_semantics.py`
- `tests/test_borrow_fee.py`
- `tests/test_short_borrow_liquidation.py`
- `tests/test_tplus1_order_flow.py`

### change summary
- Repaired `services/account_service.py` so SELL freeze no longer mutates `position.quantity` during freeze stage.
- Restored batch settlement behavior for BUY / SELL legs.
- Added ledger writes for BUY / SELL settlement paths.
- Added richer `ACCOUNT_UPDATED` payload construction.
- Added dedicated semantic tests for:
  - sell freeze behavior
  - short-cover transition
  - short opening transition
  - fee / frozen cash settlement behavior

### current conclusion
- Backend account semantics are in better shape than the previously reconstructed minimal version.
- The account service now behaves more like a real runtime owner instead of a temporary stub.
- T+1 is not being enforced by account freezing itself; it is now being pushed toward explicit risk-rule enforcement.

### impact / risk
- Good: runtime account semantics are less corrupt and easier to reason about.
- Risk: some older tests or flows may still rely on implicit historical behavior from the simplified account service.
- Risk: full realized PnL / stricter margin semantics are still not fully modeled.

### next actions
- Keep `services/account_service.py` stable while T+1 and order-lifecycle validation are completed.
- Do not re-introduce buy-fill-as-frozen-qty coupling blindly; prefer explicit rule ownership for T+1.

## Runtime regression hardening note (2026-03-22)

### status
in-progress

### goal
Add explicit runtime regression tests around order-funding, freeze/release, and short-cover semantics so future cleanup does not rely only on indirect or account-service-only coverage.

### files involved
- `docs/testing/runtime/runtime-critical-path-test-matrix.md`
- `tests/test_order_tif_semantics.py`
- `tests/test_order_funding_semantics.py`
- `tests/test_order_short_cover_semantics.py`
- `services/order_service.py`
- `services/account_service.py`

### change summary
- Added a dedicated runtime critical-path test matrix document under the new `docs/testing/runtime/` structure.
- Added explicit IOC/FOK lifecycle tests.
- Added explicit BUY-side price-improvement refund coverage.
- Added explicit SELL freeze semantics coverage from the order-service path.
- Added explicit short-cover edge tests for:
  - full cover back to flat
  - partial cover remaining short
- Chose not to force an unstable order-service-level “short open” test where current runtime constraints made the scenario unreliable; existing account-service settlement tests remain the authoritative short-open guardrail for now.

### current conclusion
- The runtime floor is stronger than before because several critical paths are now protected by direct, intention-revealing tests instead of only indirect historical coverage.
- Account semantics and order lifecycle semantics are starting to share a more explicit regression perimeter.
- The project should continue preferring stable semantic guardrails over brittle scenario inflation.

### impact / risk
- Positive: core runtime behavior is becoming safer to refactor.
- Positive: freeze/refund/cover behavior is no longer relying only on code reading and memory.
- Risk: SQLite-backed tests can still produce misleading failures if sessions are not closed carefully or if scenarios are constructed in lock-heavy ways.
- Risk: short-open behavior is still split across different semantic layers (order path vs settlement path), so future changes should document which layer owns which guarantee.

### next actions
- Continue with T+1 and IPO explicit-path hardening.
- Keep account-service-level short-open tests as the current stable source of truth until the order-service-level short-open path is intentionally clarified.
- If short-open semantics are later tightened or relaxed at the order path, record the ownership change explicitly in docs and tests.

## Account / Orders semantic convergence note (2026-03-23)

### status
in-progress

### goal
Make the frontend Account / Orders experience more honest about runtime lifecycle semantics without prematurely forcing the app-layer account service to become a live runtime-state mirror.

### files involved
- `app/panels/account/panel.py`
- `app/ui/adapters/account_adapter.py`
- `app/panels/orders/panel.py`
- `tests/frontend/unit/test_account_contract.py`
- `tests/frontend/unit/test_orders_contract.py`

### change summary
- Account summary contract now explicitly includes `frozen_fee` alongside `frozen_cash`.
- Account summary metadata now exposes `runtime_fields_emphasized = ['frozen_cash', 'frozen_fee']`.
- Account adapter summary row now surfaces `frozen_cash` and `frozen_fee` directly.
- Account adapter now shows a semantic-gap summary line so the account view is more explicit about being summary-oriented rather than a perfect runtime lifecycle mirror.
- Account table columns now surface `frozen_qty`, `borrowed_qty`, and `exposure_state` in addition to the older quantity/PnL fields.
- Orders line metadata now exposes:
  - `lifecycle_summary`
  - `account_semantic_hint`
  - `account_effect_summary`
- This makes Orders less like a raw event stream and more like a lifecycle/account-impact explanation surface.

### current conclusion
- The frontend account path remains DTO-led, but it now surfaces more of the runtime semantics users actually need to understand active orders and short/frozen states.
- Orders and Account are beginning to form a semantic closure at the frontend contract level, even though adapter-level integration still has a flaky headless/integration test path.
- Current best strategy is to keep strengthening logic/contract expressiveness first, then return to unstable adapter integration behavior later.

### impact / risk
- Positive: account view is more useful for a trading-simulation platform, not just a generic portfolio summary.
- Positive: orders view now better explains likely account impact of order events.
- Low to medium risk: adapter/UI layouts may need later visual refinement as more semantic fields are surfaced.
- Known unresolved risk: `tests/frontend/integration/test_orders_panel_wiring.py::test_orders_panel_adapter_headless_flow` still behaves like an unstable adapter/event-loop path and should not be treated as the blocker for logic-layer semantic improvements.

### next actions
- Decide whether to continue enhancing Orders logic summaries before returning to flaky adapter wiring.
- Later revisit `OrdersPanelAdapter` integration timing/refresh behavior separately from semantic contract work.
- Keep Account / Orders improvements focused on user understanding of freeze / release / short lifecycle effects.

## Runtime run-context / equity-snapshot note (2026-03-24)

### status
in-progress

### goal
Start Phase-1 backend platform work by making account-side runtime facts traceable to a run and by making account equity history a first-class persisted fact.

### files involved
- `services/account_service.py`
- `services/run_context.py`
- `persistence/models_account_equity_snapshot.py`
- `persistence/models_ledger.py`
- `tests/test_run_context_wiring.py`
- `docs/tasks/runtime/backend-phase-1-plan.md`

### total changed lines
- moderate focused change set

### Code fragment anchors
#### fragment 1
- **first line**: `class AccountService:`
- **last line**: `self.run_context = run_context`

#### fragment 2
- **first line**: `def _get_run_id(self) -> str | None:`
- **last line**: `self.s.add(snap)`

#### fragment 3
- **first line**: `class AccountEquitySnapshot(Base):`
- **last line**: `__all__ = ["AccountEquitySnapshot"]`

### Change summary
- Added `run_context` support to backend `AccountService`.
- Added `run_id` propagation into ledger writes.
- Added persisted `account_equity_snapshots` model.
- Added a basic account equity snapshot writer and wired it after trade settlement.
- Added focused regression coverage for run-context wiring and equity snapshot persistence.

### Purpose
- Make account-side runtime history attributable to a simulation run.
- Stop treating equity history as an implicit future feature.
- Build the minimum persistence base for later replay / recovery / analysis work.

### Impact / risk
- Positive: account and ledger facts now have a path toward run-scoped traceability.
- Positive: post-trade account history is starting to become queryable instead of purely reconstructed.
- Risk: snapshot trigger policy is still minimal and may later need throttling or batching.
- Risk: current drawdown field is placeholder-level and not yet a full analytics truth.

### Next actions
- Expand snapshot trigger policy beyond the first post-trade path.
- Later separate snapshot writing into a dedicated service if account service becomes too crowded.
- Keep account-side run-context wiring aligned with replay / recovery design.

## Task 2026-03-25-account-06
- **time**: 2026-03-25
- **status**: done
- **goal**: repair real-GUI mounting for Account and Orders so workspace pages are backed by actual Qt widgets instead of headless placeholders
- **files involved**:
  - `app/ui/adapters/account_adapter.py`
  - `app/ui/adapters/orders_adapter.py`
  - `app/ui/main_window.py`
- **change summary**:
  - Replaced the previous headless-only `AccountPanelAdapter` widget path with a dual-mode adapter that creates a real `QWidget` tree when `STOCKSIM_ENABLE_REAL_UI=1`.
  - Restored a real `QComboBox` / summary labels / positions table composition for the Account page while preserving headless-safe fallbacks for tests.
  - Replaced the previous headless-only `OrdersPanelAdapter` root with a real `QWidget` composition for GUI mode, including filter controls and the orders table.
  - Verified offscreen that `MainWindow.open_panel("account")` and `MainWindow.open_panel("orders")` now mount successfully and appear in workspace page state.
- **purpose**:
  - Remove the current GUI blocker where Account / Orders were registered but could not be mounted into the real workspace stack.
  - Keep headless/integration paths intact without forcing GUI dependencies into non-UI runs.
- **impact / risk**:
  - Positive: default workspace preload can now include Account and Orders again without `QStackedWidget.addWidget(...)` type errors.
  - Positive: panel registration and actual visible workspace state are aligned more honestly.
  - Risk: Account combo event-driven switching is now active in GUI mode and should be rechecked later against real multi-account creation flows.
- **next actions**:
  - Re-run a live GUI smoke check covering account creation, account switching, and order-event table updates.
  - If future adapter work changes runtime-mode ownership again, keep the GUI branch and headless branch explicit instead of silently returning fake widget objects.

## Outstanding work

- Define whether the account panel will remain DTO-led for now or later be connected more tightly to runtime events/state.
- If that migration happens, record required fields such as:
  - `frozen_cash`
  - `frozen_fee`
  - `frozen_qty`
  - `borrowed_qty`
- Decide when to revisit the unstable `OrdersPanelAdapter` headless/integration path as a dedicated adapter problem rather than part of semantic contract convergence.

## Task 2026-03-26-account-07
- **time**: 2026-03-26
- **status**: done
- **goal**: make desktop Account panel default to runtime-backed account data instead of silently falling back to synthetic placeholder accounts when runtime lookup misses
- **files involved**:
  - `app/services/account_service.py`
  - `app/panels/account/panel.py`
  - `app/panels/__init__.py`
- **change summary**:
  - Added an explicit `allow_synthetic_fallback` switch to the app-layer `AccountService`.
  - Wired desktop panel registration to instantiate `AccountService(allow_synthetic_fallback=False)`.
  - Added an empty runtime DTO fallback so the GUI shows an honest zero-state account instead of fabricated synthetic holdings when runtime has no record yet.
  - Propagated panel metadata so desktop Account summaries/positions now mark themselves as runtime-authoritative when synthetic fallback is disabled.
- **purpose**:
  - Stop desktop Account from presenting made-up balances or positions as if they were real runtime state.
  - Preserve the previous synthetic default only for tests and isolated non-runtime paths.
- **impact / risk**:
  - Positive: Account panel is now much more honest in the real desktop app.
  - Positive: runtime-vs-synthetic semantics are explicit instead of being hidden behind constructor defaults.
  - Risk: empty runtime accounts now surface more often during early bootstrap, so UX polish may later want a clearer first-run message.
## Account runtime discovery note (2026-03-26)

### status
done

### goal
修复 Account 面板在“先创建 retail / 后打开 Account 面板”场景下看不到任何账户与持仓的问题。

### files involved
- `app/ui/adapters/account_adapter.py`

### change summary
- Account 面板现在会在创建时主动从 runtime `accounts` 表补发现已有账户，而不再只依赖面板打开后的增量事件。
- 新增对 `AccountUpdated` 的订阅；当前选中账户收到 runtime 更新后会自动刷新。
- `account.created` 到达时会直接切换并加载对应账户，避免只把账号塞进下拉框但视图仍为空。

### impact / risk
- Positive: Account 面板不再要求“必须先打开再创建账户”才能看到数据。
- Risk: 当前默认选择的是 runtime 发现到的最后一个账户；后续若要更明确，可再加“最近活跃账户”策略。
## Task 2026-04-08-account-08
- **time**: 2026-04-08
- **status**: done
- **goal**: move desktop Account one step closer to a runtime-backed store instead of treating it as a purely pull-based DTO view
- **files involved**:
  - `app/services/account_runtime_store.py`
  - `app/services/account_service.py`
  - `app/event_bridge.py`
  - `app/ui/adapters/account_adapter.py`
  - `tests/frontend/unit/test_account_runtime_store.py`
  - `tests/frontend/unit/test_event_bridge_trade_publish.py`
- **change summary**:
  - added a lightweight `AccountRuntimeStore` that can cache runtime account state from both:
    - `RuntimeGateway.get_account_snapshot(...)`
    - live `AccountUpdated` event payloads
  - `AccountService.load_account()` now prefers the runtime store/cache path before falling back to synthetic data
  - introduced canonical account event helpers in `app.event_bridge` so app-side code can subscribe to account updates without hardcoding only the legacy backend topic string
  - Account adapter now consumes the canonical account-update helper rather than directly subscribing only to `"AccountUpdated"`
- **impact / risk**:
  - Positive: Account is less dependent on manual reloads and direct query-only semantics
  - Positive: app-side account state is now closer to the same runtime event flow used by the backend
  - Risk: this is still a lightweight store layered on top of DTOs, not yet a full dedicated runtime authority model for every account lifecycle detail

## Task 2026-04-08-account-09
- **time**: 2026-04-08
- **status**: done
- **goal**: make the Account controller read through the runtime-backed store path instead of holding on to a stale one-shot DTO cache
- **files involved**:
  - `app/services/account_service.py`
  - `app/controllers/account_controller.py`
  - `tests/frontend/unit/test_account_controller_runtime_store.py`
- **change summary**:
  - `AccountService` now exposes `get_account(...)` and `list_account_ids()`
  - `AccountController.get_account()` now asks the service for the latest selected-account state before returning its cached DTO
  - `AccountController.refresh()` now prefers the service/store refresh path instead of always doing a full reload roundtrip
- **impact / risk**:
  - Positive: the selected account view can track fresher runtime-backed state with less dependence on explicit full reloads
  - Positive: controller semantics now align better with the new `AccountRuntimeStore`
  - Risk: the controller is still DTO-facing and not yet a full reactive store façade for every account lifecycle event

## Task 2026-04-09-account-10
- **time**: 2026-04-09
- **status**: done
- **goal**: unify the account creation event path so Account consumers no longer depend only on the legacy `"account.created"` topic string
- **files involved**:
  - `app/event_bridge.py`
  - `app/services/account_runtime_store.py`
  - `app/ui/adapters/account_adapter.py`
  - `app/services/agent_service.py`
  - `tests/frontend/unit/test_event_bridge_trade_publish.py`
- **change summary**:
  - added canonical account-created helpers in `app.event_bridge`
  - account runtime store and account adapter now subscribe through the canonical helper
  - agent creation now publishes account-created payloads through the same helper while keeping legacy topic compatibility
- **impact / risk**:
  - Positive: account event semantics are cleaner and more aligned with the same contract-cleanup work already done for trade/order/instrument updates
  - Positive: future Account UI/store work can depend on a stable app-side hook instead of mixing raw topic strings everywhere
  - Risk: canonical account-created semantics still wrap the old payload shape; a richer dedicated account lifecycle contract may still be useful later

## Task 2026-04-09-account-11
- **time**: 2026-04-09
- **status**: done
- **goal**: fix the two most likely causes behind "Account panel looks abnormal after creating/starting retail" in the live desktop flow
- **files involved**:
  - `services/runtime_query_service.py`
  - `app/ui/adapters/account_adapter.py`
- **change summary**:
  - `RuntimeQueryService.list_account_ids()` now prefers runtime `agent_bindings` ordered by recent `updated_at/created_at` before appending any remaining raw account ids
  - `AccountPanelAdapter._prefill_accounts()` now treats the runtime list as newest-first and auto-selects the first discovered current-session account instead of the alphabetically last account in the whole database
- **impact / risk**:
  - Positive: opening Account after older historical sessions no longer tends to land on a stale unrelated account
  - Positive: the Account panel is more likely to show the retail accounts created in the current runtime session without manual combo-box switching
  - Risk: this is still a heuristic based on recent bindings, not yet a fully explicit "active session accounts" query model

## Task 2026-04-09-account-12
- **time**: 2026-04-09
- **status**: done
- **goal**: make the Account summary area read like a real desktop account grid instead of a vertical stack of raw labels
- **files involved**:
  - `app/ui/adapters/account_adapter.py`
- **change summary**:
  - replaced the visible Account summary stack with a dedicated two-column summary table
  - added per-field formatting for money and utilization so runtime values are easier to read in the GUI
  - kept the semantic-gap note below the table so the panel still explains that account/order lifecycle semantics may be richer than the summary block
- **impact / risk**:
  - Positive: the Account panel is easier to scan during live trading and debugging
  - Positive: large cash/equity values and utilization now render in a more desktop-friendly way
  - Risk: this is still a summary block, not a full ledger/account-exposure workspace yet
