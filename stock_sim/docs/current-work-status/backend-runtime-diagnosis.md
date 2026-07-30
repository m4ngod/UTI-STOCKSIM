## Backend Runtime Diagnosis (2026-03-26)

### status
done

### goal
Diagnose backend redundancy and layering drift after runtime introduction, then classify old paths into:
- keep and continue runtime convergence
- keep but split responsibilities
- safe-delete candidate after one more reference check

### files examined
- `services/order_service.py`
- `services/account_service.py`
- `services/instrument_service.py`
- `services/market_data_service.py`
- `services/market_data_query_service.py`
- `services/event_persistence_service.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `services/replay_service.py`
- `services/recovery_service.py`
- Deleted detached legacy files:
  - `services/order_dispatcher.py`
  - `services/snapshot_service.py`
  - `core/matching_engine_extended.py`
- `app/controllers/market_controller.py`
- `app/services/account_service.py`
- `app/services/market_data_service.py`
- `app/services/runtime_retail_agent.py`
- `app/ui/adapters/market_adapter.py`

### key findings
- `OrderService` remains the largest backend structural risk:
  - runtime monkeypatches `AccountService` at import time
  - mixes engine routing, run registration, settlement orchestration, fee/risk hooks
- `InstrumentService` still mixes:
  - instrument persistence CRUD
  - runtime engine bootstrap
  - IPO timer / initial snapshot side effects
- market data layering is still blurred:
  - `services/market_data_service.py` is runtime-engine read-side
  - `services/market_data_query_service.py` is persisted query-side
  - `core/ring_buffer.py` still depends on `TickDTO` from the query service
- `snapshot_service.py`, `order_dispatcher.py`, `core/matching_engine_extended.py` were detached from the current desktop/runtime main chain and have now been removed
- `run_context.py`, `simulation_run_service.py`, `event_persistence_service.py`, `snapshot_listener.py`, `bar_aggregator.py`, `replay_service.py`, `recovery_service.py` are aligned with the runtime direction and should be retained
- app/backend decoupling is still incomplete:
  - `market_controller`
  - app `account_service`
  - app `market_data_service`
  - `runtime_retail_agent`
  - `market_adapter`
  still contain direct runtime/persistence imports that should keep moving behind `RuntimeGateway`

### artifact
- Added root diagnosis document:
  - `backend_runtime_diagnosis_2026-03-26.md`

### next actions
- Split `OrderService` responsibilities before deleting detached legacy files.
- Split `InstrumentService` into CRUD and runtime-bootstrap responsibilities.
- Keep moving app-layer direct runtime imports into `RuntimeGateway`.
- Detached legacy files `snapshot_service.py`, `order_dispatcher.py`, and `core/matching_engine_extended.py` have now been deleted from the active tree.

### follow-up update 10
- Deleted three backend files that were confirmed to be outside the current frontend/runtime main chain:
  - `services/snapshot_service.py`
  - `services/order_dispatcher.py`
  - `core/matching_engine_extended.py`
- Verification scope before deletion:
  - no live code references from `app/`, `services/`, `core/`, `tests/`, or `scripts/`
  - remaining references were documentation-only
- Also updated the most visible structure/index docs to stop listing the removed files:
  - `docs/code-index.md`
  - `structure.md`

### follow-up update
- Took the first low-risk `OrderService` cleanup slice:
  - disabled the legacy import-time monkeypatch fallback for `AccountService`
  - switched `OrderService` to build its default `InstrumentService` from the current session instead of `instrument_service_factory()`
- This does not finish the `OrderService` split, but it removes one hidden lifetime issue and stops the old fallback path from silently mutating backend account semantics at import time.

### follow-up update 2
- Continued the `OrderService` cleanup by reducing `_get_engine()` duplication:
  - added small helpers for loading instrument DTOs, building temporary instrument views, syncing engine phase from instrument metadata, and registering missing symbol books on an injected engine
  - rewired `_get_engine()` and `_get_symbol_params()` to reuse those helpers instead of repeating the same DTO-to-view conversion and IPO phase sync logic in multiple branches
- This still leaves `OrderService` as an oversized orchestrator, but the engine-routing slice is now more local and easier to extract into a dedicated runtime resolver next.

### follow-up update 3
- Started the `InstrumentService` split by extracting runtime-side engine/bootstrap behavior into:
  - `services/instrument_runtime_service.py`
- `InstrumentService.create()` now hands runtime engine creation/bootstrap to that new service instead of owning the runtime bootstrap path directly.
- `InstrumentService.update()` now hands runtime metadata/snapshot sync to that new service instead of mutating engine metadata inline.
- The previous in-file runtime bootstrap block in `InstrumentService` is now effectively disabled and left as a temporary dead path for safe incremental migration.
- This means the service boundary is now clearer:
  - `InstrumentService`: instrument row CRUD / stamping / flush
  - `instrument_runtime_service`: engine registry / phase / reference snapshot / IPO timer / runtime metadata sync

### follow-up update 4
- Moved the app-side instrument creation path one step further behind the runtime boundary:
  - added `RuntimeGateway.create_instrument()`
  - updated `MarketController` to prefer `RuntimeGateway` for runtime instrument creation
  - updated `AppContext` so the shared `MarketController` receives the shared `RuntimeGateway`
- The old direct-runtime helper in `market_controller.py` is still retained as a fallback path for incremental safety, but the standard desktop path now routes through the gateway.

### follow-up update 5
- Finished the `MarketController` cleanup for instrument creation:
  - removed the old direct-runtime import block from `market_controller.py`
  - removed the `_register_runtime_instrument()` helper
  - removed the remaining dead fallback branch inside `create_instrument()`
  - updated the controller unit test to inject a fake `RuntimeGateway` instead of monkeypatching the removed helper
- Result: the market instrument-create path now has a single desktop app route:
  - `MarketController -> RuntimeGateway -> backend runtime services`

### follow-up update 6
- Moved more app-layer runtime reads behind `RuntimeGateway` on the standard desktop path:
  - added gateway read methods for:
    - account snapshot
    - retail holdings distribution
    - persisted bars
    - current sim day
  - updated app `AccountService` to prefer `RuntimeGateway` for runtime account reads
  - updated app `MarketDataService` to prefer `RuntimeGateway` for:
    - bars
    - holdings
    - current sim day in chart meta
  - updated `AppContext` so the shared desktop `AccountService` and `MarketDataService` receive the shared `RuntimeGateway`
- Legacy direct ORM fallback code still exists in those services for compatibility and older tests, but the shared desktop app path no longer depends on app services querying runtime ORM directly.

### follow-up update 7
- Removed the remaining app-layer legacy ORM fallback from the standard runtime read services:
  - `app/services/account_service.py`
    - removed direct `SessionLocal/RuntimeAccount/RuntimePosition` imports
    - removed the in-file `_runtime_fetcher()` ORM path
    - now always reads runtime account state through `RuntimeGateway.get_account_snapshot()`
    - keeps only:
      - runtime-gateway DTO mapping
      - optional synthetic fallback for explicit non-authoritative callers
      - empty-account zero-state fallback
  - `app/services/market_data_service.py`
    - removed direct `SessionLocal/Bar1m/Bar1h/Bar1d/RuntimePosition/AgentBinding/current_sim_day` imports
    - removed in-file ORM fallback for:
      - persisted bars
      - retail holdings distribution
      - current sim day chart metadata
    - now always reads those runtime-backed values through `RuntimeGateway`
- Result:
  - desktop app services no longer open runtime sessions or query runtime ORM models directly on their standard path
  - app/backend boundary is cleaner:
    - `Account UI -> AccountService -> RuntimeGateway -> backend`
    - `Market UI -> MarketDataService -> RuntimeGateway -> backend`

### follow-up update 8
- Continued app/runtime decoupling for runtime retail execution:
  - `app/services/runtime_retail_agent.py`
    - removed direct imports of:
      - `models_init`
      - `SessionLocal`
      - backend `AccountService`
      - `current_sim_day()`
      - `ensure_sim_clock_started()`
    - now reads:
      - market-clock running state through `RuntimeGateway.clock_snapshot()`
      - current `sim_day` through `RuntimeGateway.get_current_sim_day()`
      - available sell quantity through new `RuntimeGateway.get_available_sell_qty()`
    - removed the dead `_ensure_opening_inventory()` path and its unused `_seeded_symbols` state
  - `app/services/agent_service.py`
    - now injects the shared `RuntimeGateway` into each `RuntimeRetailAgent`
- Result:
  - the retail runtime executor no longer opens runtime sessions or manipulates backend account rows directly from the app layer
  - app-side retail execution now follows the same boundary rule as the rest of the desktop stack:
    - `RuntimeRetailAgent -> RuntimeGateway -> backend`

### follow-up update 9
- Reduced residual legacy coupling and duplication in `app/ui/adapters/market_adapter.py`:
  - removed the adapter-local fallback import of backend `current_sim_day()`
  - detail chart bounds now trust `chart_meta.current_sim_day` from the app/runtime data path instead of reaching back into backend clock helpers
  - normalized trade payload parsing behind a shared local helper so both:
    - `MarketPanelAdapter`
    - `SymbolDetailPanelAdapter`
    consume `Trade` / `TradeEvent` the same way
  - replaced duplicate trade-topic subscription blocks with one local helper
- Result:
  - market UI adapters now depend less on backend clock internals
  - event-consumption logic is flatter and easier to keep consistent while the runtime boundary continues to tighten

### follow-up update 10
- Cleaned stale structure documentation and tightened the instrument-create boundary:
  - `structure.md`
    - removed already-deleted file entries such as:
      - `agents/multi_strategy_retail.py`
      - `services/agent_meta_listener.py`
      - `services/ipo_grant_queue.py`
      - `services/ipo_listener.py`
      - `services/ipo_poller.py`
      - `services/strategy_supervisor.py`
      - `app/main.py`
  - instrument creation boundary
    - added `finalize_runtime_instrument_creation()` in `services/instrument_runtime_service.py`
    - added `InstrumentService.finalize_create()`
    - changed `RuntimeGateway.create_instrument()` to:
      - call backend `InstrumentService.create()`
      - commit
      - call backend `InstrumentService.finalize_create()`
- Result:
  - `RuntimeGateway` no longer directly imports or executes IPO retail distribution side effects for instrument creation
  - instrument-create side effects now live behind backend instrument/runtime services instead of app-layer gateway logic

### follow-up update 11
- Split the heaviest runtime read queries out of `app/runtime_gateway.py` into a backend-side read service:
  - added `services/runtime_query_service.py`
  - moved these query implementations behind that service:
    - account snapshot
    - available sell quantity
    - retail holdings distribution
    - persisted bars
    - leaderboard snapshots
    - account id listing
- `RuntimeGateway` now delegates those reads to `RuntimeQueryService` instead of owning the ORM/query assembly itself.
- Result:
  - `RuntimeGateway` remains the stable app boundary
  - backend read-side ORM logic now lives in a backend service again, instead of accreting inside the app gateway

### follow-up update 12
- Split the mutation/command side out of `app/runtime_gateway.py` as well:
  - added `services/runtime_command_service.py`
  - moved these write/command flows behind that service:
    - agent account bootstrap
    - instrument creation finalization path
    - submit order
    - cancel order
    - clock snapshot / start / pause / resume / stop / speed
    - pending IPO allocation trigger
- Also completed the read-side split by adding `list_agent_bindings()` to `services/runtime_query_service.py`.
- `RuntimeGateway` is now primarily a thin delegating boundary:
  - reads -> `RuntimeQueryService`
  - writes/commands -> `RuntimeCommandService`
- Result:
  - app-facing interface stayed stable
  - backend query and mutation details are no longer concentrated inside the gateway itself

### follow-up update 13
- Cleaned `services/instrument_service.py` down to the active CRUD + runtime-sync path:
  - removed the old unreachable inline runtime bootstrap block after `create()`
  - removed the legacy `instrument_service_factory()` helper that created its own `SessionLocal()`
  - rewrote the file into a smaller, explicit shape:
    - `create()` flushes and delegates runtime engine setup to `ensure_runtime_engine_for_instrument()`
    - `finalize_create()` delegates post-commit runtime side effects to `finalize_runtime_instrument_creation()`
    - `update()` delegates runtime metadata synchronization to `sync_runtime_instrument_meta()`
- Result:
  - `InstrumentService` no longer carries two competing instrument-bootstrap implementations
  - hidden session lifecycle creation was removed from the backend path

### follow-up update 14
- Reduced active legacy behavior in `services/order_service.py`:
  - removed the still-executing "default cash refill" compatibility branch that silently assigned `DEFAULT_CASH` when an account snapshot came back with zero cash
  - removed the disabled AccountService monkeypatch implementation body near the top of the file
- Result:
  - `OrderService` now trusts `AccountService` as the authoritative account implementation instead of masking account-state issues with compatibility shims
  - one more source of legacy runtime/account ambiguity is gone from the order path

### follow-up update 15
- Began flattening duplicated injected-engine routing logic inside `services/order_service.py`:
  - added `_resolve_injected_engine()` as a shared helper for the "reuse injected engine and sync registry" path
  - switched the secondary `if self.engine:` branch in `_get_engine()` to use that helper instead of repeating registration/sync logic inline
- Result:
  - one repeated engine-resolution branch is now centralized
  - `OrderService` engine routing is incrementally getting smaller without changing the public order path

### follow-up update 16
- Moved `sim_day` lookup behind the backend read-side service as well:
  - added `RuntimeQueryService.get_current_sim_day()`
  - changed `RuntimeGateway.get_current_sim_day()` to delegate to the query service instead of deriving it from `clock_snapshot()`
- Result:
  - `RuntimeGateway` became thinner again
  - the current simulation day is now treated as a backend read concern instead of app-layer clock post-processing

### follow-up update 17
- Simplified the account snapshot read path a little further:
  - changed `RuntimeQueryService.get_account_snapshot()` to resolve fallback `sim_day` internally

### follow-up update 18
- Took another focused `OrderService` split slice aimed at reducing backend orchestration weight without changing the runtime order API:
  - added `services/order_engine_router.py`
    - owns symbol -> engine resolution
    - owns injected-engine reuse / registry synchronization
    - owns symbol-parameter lookup delegation through `OrderInstrumentResolver`
  - added `services/order_trade_settlement_service.py`
    - owns post-match trade persistence
    - owns ORM fill-state updates for buy/sell orders
    - owns batch settlement orchestration through backend `AccountService`
    - owns buy-side price-improvement cash refunds and buy-fee overage refunds
    - owns external trade settlement bridging used by IPO open flows
- `services/order_service.py` now:
  - delegates engine routing to `OrderEngineRouter`
  - delegates post-trade persistence/settlement to `OrderTradeSettlementService`
  - keeps the top-level orchestration role for:
    - recovery/read-only guard
    - run registration
    - order normalization/basic validation
    - risk validation
    - freeze / TIF lifecycle decisions
- Also flattened some inline order-lifecycle helpers inside `OrderService`:
  - centralized reject-path publishing/metrics
  - centralized reservation release + proportional fee refund logic
  - centralized freeze-resource logic for fee freeze vs main freeze
- Result:
  - `OrderService` still coordinates the runtime order path, but engine routing and trade settlement are no longer embedded as long internal blocks
  - the remaining split candidates are now clearer:
    - pre-trade validation/freeze policy
    - cancel/release lifecycle policy

### follow-up update 19
- Split the pre-match policy block out of `services/order_service.py` into:
  - `services/order_pretrade_service.py`
- `OrderPreTradeService` now owns:
  - order normalization
  - basic validation
  - account lookup for pre-trade checks
  - risk validation
  - fee estimation / `est_fee` attachment
  - fee freeze + main freeze policy
  - reject-path persistence / event / metric publication
  - reservation release + proportional fee refund used by:
    - user cancel
    - auction unmatched cancel
    - IOC/FOK cleanup
- `OrderService.place_order()` now reads more like a top-level runtime flow:
  - recovery guard
  - run registration
  - pre-trade prepare
  - persist NEW
  - submit to engine
  - post-trade settlement
  - TIF finalize
- Result:
  - the order path is now materially clearer as three backend collaborators:
    - pre-trade policy
    - engine routing
    - post-trade settlement
  - the next natural split target, if needed, is no longer generic “make OrderService smaller”, but specifically:
    - cancel / cancel-event lifecycle policy

### follow-up update 20
- Split cancellation handling out of `services/order_service.py` into:
  - `services/order_cancel_service.py`
- `OrderCancelService` now owns:
  - user cancel path against the engine
  - persisted-order cancel cleanup
  - runtime-order cancel cleanup for IOC/FOK post-match cancellation
  - shared cancel event publication / logging
  - shared reservation release delegation through `OrderPreTradeService`
- `OrderService` now only decides that a cancellation should happen in these paths:
  - user `cancel(order_id)`
  - auction unmatched leftovers
  - IOC/FOK finalize branches
  and delegates the actual cleanup/lifecycle side effects to `OrderCancelService`
- Added a focused runtime regression:
  - `tests/test_order_cancel_semantics.py`
    - user cancel releases buy-side reservations
    - runtime order status is synchronized to `CANCELED`
- Result:
  - the runtime order path is now effectively separated into four backend collaborators:
    - pre-trade
    - cancellation
    - engine routing
    - post-trade settlement
  - `OrderService` is noticeably closer to a pure orchestration surface

### follow-up update 21
- Split the remaining non-order-entry side concerns out of `services/order_service.py` into:
  - `services/order_auction_reconciliation_service.py`
    - owns reconciliation of `auction_canceled_order_ids`
    - delegates the actual cancel cleanup to `OrderCancelService`
    - keeps the backward-compatible default-engine fallback when it is not yet in the registry
  - `services/order_maintenance_service.py`
    - owns `daily_reset()` behavior
    - resets day-level risk storage
    - clears T+1 runtime counters through `RiskEngine.reset_day_tplus(...)`
    - runs borrow-fee accrual scheduling
- Added a focused runtime regression:
  - `tests/test_order_daily_reset_semantics.py`
    - `daily_reset()` clears T+1 counters
- Result:
  - `OrderService` now mainly keeps:
    - recovery/read-only guard
    - run registration
    - orchestration sequencing across collaborators
    - local order-book/memory synchronization helpers
  - it is now substantially closer to a coordination facade than a mixed-responsibility service
  - removed the extra `current_sim_day` parameter passing from `RuntimeGateway.get_account_snapshot()`
- Result:
  - account snapshot assembly is now self-contained on the backend read side
  - the gateway no longer has to help build account DTO context for this query

### follow-up update 18
- Finished flattening the remaining duplicated injected-engine branch in `services/order_service.py`:
  - changed the primary `if self.engine and self.engine.symbol == symbol` branch in `_get_engine()` to reuse `_resolve_injected_engine()`
  - reduced `_get_engine()` to a simpler three-step decision flow:
    - preferred injected engine
    - existing engine from registry
    - create on demand
- Result:
  - injected-engine reconciliation now lives in one helper instead of two partially duplicated branches
  - `OrderService` engine routing is easier to reason about and safer to refactor further

### follow-up update 19
- Did a small cleanliness pass on `services/order_service.py` after the routing refactor:
  - removed the leftover top-of-file comment stubs from the old AccountService compatibility patch
- Result:
  - the file header now reflects active dependencies only
  - one more source of historical confusion is gone from the order path

### follow-up update 20
- Split instrument metadata/view resolution out of `services/order_service.py`:
  - added `services/order_instrument_resolver.py`
  - moved these responsibilities behind that helper:
    - loading instrument DTOs
    - building lightweight instrument views
    - syncing engine phase from instrument state
    - registering symbol metadata onto engines
    - resolving symbol params for order validation
  - updated `OrderService` to depend on `OrderInstrumentResolver` and removed the now-redundant local wrapper helpers
- Result:
  - `OrderService` is more focused on order orchestration and engine routing
  - instrument-query/assembly logic now lives in a dedicated backend service instead of being mixed through the order path

### follow-up update 21
- Started the first backend persistence-boundary extraction:
  - added `services/order_persistence_service.py`
    - owns `OrderORM` / `OrderEvent` create-update-write helpers used by `OrderService`
  - added `services/account_persistence_service.py`
    - owns `Ledger` / `AccountEquitySnapshot` write helpers used by `AccountService`
  - rewired:
    - `OrderService._persist_order()`
    - `OrderService._persist_state()`
    - `OrderService._persist_event()`
    - `AccountService._write_ledger()`
    - `AccountService.write_equity_snapshot()`
    to delegate ORM row creation/writes to those collaborators
- Result:
  - persistence writes are no longer embedded only as raw ORM construction inside service orchestration code
  - this is the first concrete step toward a replaceable persistence layer without breaking the current runtime

### follow-up update 22
- Extended the persistence-boundary extraction to trade row writes:
  - added `services/trade_persistence_service.py`
  - rewired both `TradeORM` write points in `services/order_service.py` to use that collaborator
  - removed direct `TradeORM` row construction from the order orchestration flow
- Result:
  - trade persistence is now isolated behind a dedicated backend writer helper
  - `OrderService` keeps less raw ORM knowledge while replay/recovery can continue using the same persisted tables unchanged

### follow-up update 23
- Started the shared persistence read-side extraction for replay/recovery:
  - added `services/run_persistence_query_service.py`
  - moved common run-scoped persisted-fact queries there:
    - per-run snapshot/bar/order/trade/ledger fact loading
    - full recovery row loading
    - distinct `run_id` collection from persisted tables
  - rewired:
    - `ReplayService.validate_against_persisted_facts()`
    - `RecoveryService._build_report()`
    to consume that shared query collaborator
- Result:
  - replay and recovery now share one backend persistence query source instead of duplicating low-level SQLAlchemy scans
  - the persistence boundary now exists on both write-side and read-side

### follow-up update 24
- Added a stable package-level entrypoint for persistence collaborators:
  - created `services/persistence_layer/`
  - grouped current collaborators into:
    - `readers.py`
    - `writers.py`
    - `topology.py`
    - package `__init__.py`
- Result:
  - migration-facing persistence code now has one coherent package surface
  - future PostgreSQL / Redis work can start from a stable import boundary without moving existing runtime files yet

### follow-up update 25
- Added an executable migration-order registry alongside the topology map:
  - created `services/persistence_layer/migration_plan.py`
  - registered per-phase steps for:
    - run tracking
    - trading facts
    - account state
    - historical market facts
    - event log
    - equity snapshots
    - realtime hot state
    - compatibility SQLite mode
  - re-exported that plan through `services/persistence_layer/__init__.py`
- Result:
  - storage migration order is now captured in code, not only in prose
  - future persistence work can key off explicit prerequisites and acceptance gates

### follow-up update 26
- Moved phase-1 run tracking from "planned/ready" into the actual desktop runtime path:
  - updated `services/runtime_command_service.py`
  - `Clock Start` now creates or resumes a stable desktop-session `run_id`
  - `Clock Resume` keeps the same active `run_id`
  - runtime orders/cancels now pass a `RunContext` into `OrderService`
  - active `run_id` is stamped onto registered runtime engines so snapshot/trade event paths can inherit the same session identity
  - `Clock Stop` now marks the active simulation run completed and clears the runtime clock's public `run_id`
  - added `tests/test_runtime_command_service_run_session.py` to lock this flow
- Result:
  - the desktop runtime now has one stable `run_id` per simulation session instead of leaving clock-driven sessions effectively anonymous
  - persisted order facts from the runtime command path can now join replay/recovery facts under the same run session

### follow-up update 27
- Continued `run_id` propagation from order facts into runtime historical-data paths:
  - updated `services/runtime_query_service.py`
    - added active-run awareness through the runtime clock
    - `get_bars()` now prefers bars from the current active `run_id` before falling back to unscoped history
  - updated `services/instrument_runtime_service.py`
    - runtime engines now inherit the active `run_id` when instruments are created or re-synced
    - engine book metadata and in-memory snapshots are stamped with the current session run id
  - updated `services/bar_aggregator.py`
    - minute/hour/day aggregation groups rows by `(symbol, run_id)` instead of only by symbol
    - `BAR_UPDATED` now keeps the grouped run identity through the aggregation path
  - added tests:
    - `tests/test_runtime_query_run_scoped_bars.py`
    - `tests/test_instrument_runtime_run_id_stamp.py`
- Result:
  - the active desktop session now has better separation between its own historical bars and unrelated persisted rows
  - runtime instruments created during an active session are less likely to emit anonymous snapshot/bar history

### follow-up update 28
- Fixed a destructive runtime bootstrap bug that was corrupting run-scoped history reads:
  - updated `persistence/models_init.py`
    - split non-destructive schema assurance into `ensure_models()`
    - kept `init_models()` as the explicit destructive reset path for tests and full re-init flows
  - updated active runtime services to use non-destructive schema assurance:
    - `services/runtime_query_service.py`
    - `services/runtime_command_service.py`
    - `services/ipo_retail_distribution.py`
- Validation:
  - `python -m pytest tests/test_runtime_query_run_scoped_bars.py tests/test_instrument_runtime_run_id_stamp.py tests/test_runtime_event_run_id_contract.py tests/test_snapshot_run_scoped_replay.py tests/test_bar_run_report_contract.py -q`
  - result: `8 passed`
- Result:
  - constructing runtime query/command services no longer wipes persisted SQLite rows mid-session
  - run-scoped bar/history tests now reflect the real runtime path instead of being invalidated by hidden schema resets

### follow-up update 29
- Added active-run awareness to replay/recovery reporting:
  - updated `services/run_persistence_query_service.py`
    - added `get_active_run_id()` based on the latest non-terminal `simulation_runs` row
  - updated `services/recovery_service.py`
    - recovery reports now expose `checks.active_run_id`
    - replay validation is ordered with the active run first when multiple runs are present
  - added `tests/test_recovery_active_run_priority.py`
- Validation:
  - `python -m pytest tests/test_runtime_query_run_scoped_bars.py tests/test_instrument_runtime_run_id_stamp.py tests/test_runtime_event_run_id_contract.py tests/test_snapshot_run_scoped_replay.py tests/test_bar_run_report_contract.py tests/test_recovery_active_run_priority.py -q`
  - result: `9 passed`
- Result:
  - backend run reports now have a stable notion of "current session" instead of treating all persisted runs as an unordered set
  - follow-up frontend work can key off the active run without guessing from mixed historical data

### follow-up update 30
- Reduced agent-list dependence on app-process memory:
  - updated `services/runtime_query_service.py`
    - `list_agent_bindings()` now returns parsed binding metadata
  - updated `app/services/agent_service.py`
    - `list_agents()`, `get()`, `control()`, and `update_params_version()` now hydrate from runtime `agent_bindings`
    - runtime-hydrated agent rows normalize type names back to desktop-facing values such as `Retail`
  - added `tests/frontend/unit/test_agent_service_runtime_authority.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_agent_service_runtime_gateway.py tests/frontend/unit/test_agent_service_runtime_authority.py tests/frontend/unit/test_agents_panel.py tests/frontend/unit/test_agent_creation_modal.py -q`
  - result: `8 passed`
- Result:
  - the desktop agent list can now recover persisted identities/strategies after restart instead of depending entirely on the current process memory
  - agent lifecycle is still not fully runtime-authoritative, but agent identity metadata is now materially closer to the backend source of truth

### follow-up update 31
- Extended the same agent-binding path to persist minimal live lifecycle state:
  - updated `services/runtime_command_service.py`
    - added `update_agent_binding_meta(...)`
    - bootstrap bindings now include baseline lifecycle metadata fields
  - updated `app/runtime_gateway.py`
    - exposed `update_agent_binding_meta(...)`
  - updated `app/services/agent_service.py`
    - runtime state changes and `params_version` updates now write back to runtime binding metadata
    - hydration now restores persisted `status / start_time / last_heartbeat / params_version`
  - expanded `tests/frontend/unit/test_agent_service_runtime_authority.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_agent_service_runtime_authority.py tests/frontend/unit/test_agent_service_runtime_gateway.py tests/frontend/unit/test_agents_panel.py tests/frontend/unit/test_agent_creation_modal.py -q`
  - result: `10 passed`
- Result:
  - agent identity and basic lifecycle state now survive desktop process restarts through runtime metadata
  - the remaining gap is no longer "agent list disappears", but "agent lifecycle history is stored in lightweight binding metadata instead of a dedicated runtime authority model"

### follow-up update 32
- Started consolidating frontend trade-event consumption onto one canonical topic:
  - updated `app/event_bridge.py`
    - added canonical `TRADE_EXECUTED_TOPIC = "trade.executed"`
    - `publish_trade_payload(...)` now emits the canonical topic while still broadcasting legacy `Trade / TradeEvent`
    - added `on_trade_executed(...)` helper with duplicate suppression for dual-bus compatibility mode
  - updated consumers:
    - `app/ui/adapters/orders_adapter.py`
    - `app/ui/adapters/market_adapter.py`
    to subscribe through the canonical helper instead of manually dual-subscribing to `Trade` and `TradeEvent`
  - expanded `tests/frontend/unit/test_event_bridge_trade_publish.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_event_bridge_trade_publish.py tests/frontend/unit/test_orders_panel_dedup.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_event_bridge.py -q`
  - result: `7 passed`
- Result:
  - the app-side trade refresh path now has one preferred event contract instead of requiring every consumer to subscribe to two legacy topics
  - legacy topics remain available for compatibility while the main desktop chain becomes easier to reason about

### follow-up update 33
- Extended the same contract-cleanup pattern to order and app-broadcast helpers:
  - updated `app/event_bridge.py`
    - added canonical helper hooks for:
      - `on_order_rejected(...)`
      - `on_order_canceled(...)`
      - `publish_agent_status_changed(...)`
      - `publish_instrument_created(...)`
    - introduced canonical names for order lifecycle topics while keeping legacy backend topic compatibility
  - updated consumers/publishers:
    - `app/ui/adapters/orders_adapter.py`
    - `app/services/agent_service.py`
    - `app/controllers/market_controller.py`
  - expanded `tests/frontend/unit/test_event_bridge_trade_publish.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_event_bridge_trade_publish.py tests/frontend/unit/test_orders_panel_dedup.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_event_bridge.py tests/frontend/unit/test_agent_service_runtime_authority.py -q`
  - result: `13 passed`
- Result:
  - more of the desktop event contract now flows through one app-facing bridge instead of ad hoc string-topic publishing in each caller
  - backend legacy topics remain usable, but new UI-side code has clearer subscription and publish entrypoints

### follow-up update 34
- Moved desktop leaderboard curves closer to runtime-authoritative history:
  - updated `services/runtime_query_service.py`
    - added `get_leaderboard_history(...)`
    - leaderboard history now resolves agent bindings to accounts and prefers `account_equity_snapshots` from the active `run_id`
  - updated `app/runtime_gateway.py`
    - exposed `get_leaderboard_history(...)`
  - updated `app/services/leaderboard_service.py`
    - added `get_agent_curves(...)`
    - runtime leaderboard curves now prefer persisted equity history and only fall back to synthetic placeholder curves when runtime history is absent
  - updated `app/controllers/leaderboard_controller.py`
    - added `get_curves(...)`
  - updated `app/panels/leaderboard/panel.py`
    - selected-agent view blocks now surface `curve_source`, `curve_authoritative`, and `active_run_id`
  - updated `app/ui/adapters/leaderboard_adapter.py`
    - rebuilt the adapter with a safe headless fallback path
    - export completion UI updates now marshal back to the UI thread instead of touching Qt widgets from a worker thread
  - added/updated tests:
    - `tests/frontend/unit/test_leaderboard_service_runtime_gateway.py`
    - `tests/frontend/unit/test_leaderboard_panel.py`
    - `tests/frontend/unit/test_leaderboard_export_concurrency.py`
    - `tests/frontend/unit/test_market_active_run_meta.py`
    - `tests/test_runtime_query_run_scoped_bars.py`
    - `tests/test_instrument_runtime_run_id_stamp.py`
    - `tests/test_runtime_event_run_id_contract.py`
    - `tests/test_snapshot_run_scoped_replay.py`
    - `tests/test_bar_run_report_contract.py`
    - `tests/test_recovery_active_run_priority.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_leaderboard_service_runtime_gateway.py tests/frontend/unit/test_leaderboard_panel.py tests/test_leaderboard_service.py tests/frontend/unit/test_leaderboard_export_concurrency.py tests/frontend/unit/test_market_active_run_meta.py tests/test_runtime_query_run_scoped_bars.py tests/test_instrument_runtime_run_id_stamp.py tests/test_runtime_event_run_id_contract.py tests/test_snapshot_run_scoped_replay.py tests/test_bar_run_report_contract.py tests/test_recovery_active_run_priority.py -q`
  - result: `23 passed`
- Result:
  - the leaderboard selected-detail curve path now has a runtime-authoritative source based on persisted account equity history
  - the desktop process no longer needs synthetic leaderboard curves to appear "complete" when runtime history exists
  - the leaderboard export path is no longer relying on unsafe background-thread UI updates

### follow-up update 35
- Started moving Account from a pure pull-only DTO view toward a runtime-backed store model:
  - added `app/services/account_runtime_store.py`
    - introduced `AccountRuntimeStore`
    - runtime account state can now be hydrated from either:
      - runtime snapshot queries via `RuntimeGateway`
      - live `AccountUpdated` event payloads
  - updated `app/services/account_service.py`
    - `load_account()` now prefers the runtime store/cache instead of querying runtime directly every time
    - runtime DTO conversion is shared with the store instead of living as private service-only glue
  - updated `app/event_bridge.py`
    - added canonical `ACCOUNT_UPDATED_TOPIC = "account.updated"`
    - added `on_account_updated(...)`
    - added `publish_account_updated(...)`
  - updated `app/ui/adapters/account_adapter.py`
    - switched Account panel subscriptions to the canonical account-update helper instead of hardcoding `"AccountUpdated"`
  - added tests:
    - `tests/frontend/unit/test_account_runtime_store.py`
    - expanded `tests/frontend/unit/test_event_bridge_trade_publish.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_account_runtime_store.py tests/frontend/unit/test_event_bridge_trade_publish.py tests/frontend/unit/test_account_panel.py tests/frontend/integration/test_account_panel_adapter_bridge.py tests/frontend/unit/test_account_contract.py -q`
  - result: `12 passed`
- Result:
  - desktop Account now has the beginnings of a real runtime store path instead of only reloading through a pull-only DTO service
  - live account payloads can update cached runtime account state before the next explicit panel reload
  - the event contract cleanup now also covers account updates, not only trade/order/instrument flows

### follow-up update 36
- Extended the same Account-store shift into the controller layer:
  - updated `app/services/account_service.py`
    - added `get_account(account_id=None, refresh=False)`
    - added `list_account_ids()`
    - service now exposes a stable way to read the latest runtime-backed account state instead of only the last DTO returned by `load_account()`
  - updated `app/controllers/account_controller.py`
    - `get_account()` now asks the service for the latest selected-account state
    - `refresh()` now prefers the service/store refresh path before falling back to a full reload
    - added `list_account_ids()`
  - added `tests/frontend/unit/test_account_controller_runtime_store.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_account_controller_runtime_store.py tests/frontend/unit/test_controllers_account_market.py tests/frontend/unit/test_account_panel.py tests/frontend/integration/test_account_panel_adapter_bridge.py tests/frontend/unit/test_account_runtime_store.py tests/frontend/unit/test_account_contract.py -q`
  - result: `13 passed`
- Result:
  - `AccountPanel.get_view()` is less tied to the controller's old "last loaded DTO" cache and can now track fresher runtime-backed state for the selected account
  - the controller boundary is now closer to a real account store façade instead of being only a one-shot load wrapper

### follow-up update 37
- Extended the canonical event-contract cleanup into account creation events:
  - updated `app/event_bridge.py`
    - added `ACCOUNT_CREATED_TOPIC = "account.created.canonical"`
    - added `on_account_created(...)`
    - added `publish_account_created(...)`
  - updated consumers:
    - `app/services/account_runtime_store.py`
    - `app/ui/adapters/account_adapter.py`
    so account creation subscriptions no longer hardcode only the legacy `"account.created"` string
  - updated publisher:
    - `app/services/agent_service.py`
    now emits account creation through the canonical helper while preserving legacy topic compatibility
  - expanded `tests/frontend/unit/test_event_bridge_trade_publish.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_event_bridge_trade_publish.py tests/frontend/unit/test_account_runtime_store.py tests/test_kline_and_account_events.py tests/frontend/unit/test_agent_service_runtime_authority.py -q`
  - result: `15 passed`
- Result:
  - account lifecycle event cleanup now covers both "created" and "updated" paths
  - desktop account consumers can keep moving toward canonical app-side contracts without breaking older backend/topic publishers

### follow-up update 38
- Fixed two live desktop consistency gaps behind "no orders shown / account panel looks wrong":
  - updated `app/event_bridge.py`
    - added canonical `ORDER_SUBMITTED_TOPIC = "order.submitted"`
    - added `on_order_submitted(...)`
    - added `publish_order_submitted(...)`
    - widened `on_trade_executed(...)` back to a deduped compatibility subscription across:
      - `trade.executed`
      - `Trade`
      - `TradeEvent`
    so new UI code can prefer the canonical contract without silently missing legacy runtime publishers
  - updated `app/services/trading_service.py`
    - submitted-order publishing now goes through `publish_order_submitted(...)`
  - updated `app/ui/adapters/orders_adapter.py`
    - Orders now subscribes to submitted-order events in addition to trade/reject/cancel
    - filter-button logic now correctly covers all four order lifecycle kinds
  - updated `app/panels/orders/panel.py`
    - normalized `OrderSubmitted` into the headless/UI-neutral order event stream
    - added lifecycle metadata for resting/submitted lines
  - updated `services/runtime_query_service.py`
    - `list_account_ids()` now prefers recent runtime `agent_bindings` order instead of plain account id sort
  - updated `app/ui/adapters/account_adapter.py`
    - Account prefill now auto-selects the newest runtime-discovered account rather than the last alphabetic account id
  - expanded tests:
    - `tests/frontend/unit/test_event_bridge_trade_publish.py`
    - `tests/frontend/unit/test_trading_service_runtime_gateway.py`
    - `tests/frontend/integration/test_orders_panel_wiring.py`
    - `tests/frontend/unit/test_orders_contract.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_event_bridge_trade_publish.py tests/frontend/unit/test_orders_contract.py tests/frontend/integration/test_orders_panel_wiring.py tests/frontend/unit/test_trading_service_runtime_gateway.py tests/frontend/unit/test_account_panel.py tests/frontend/integration/test_account_panel_adapter_bridge.py -q`
  - result: `16 passed`
- Result:
  - Orders no longer depends only on trade/reject/cancel to show activity; resting/submitted orders are now visible
  - legacy `Trade` publishers once again flow into canonical UI subscribers without duplicate callbacks
  - Account is less likely to open on a stale historical account when the runtime database already contains many older sessions

### follow-up update 39
- Did a small-scope backend convergence pass on the remaining runtime-sync helpers inside `services/order_service.py`:
  - added `services/order_runtime_sync_service.py`
    - owns locating a syncable `OrderBook` view from an engine-like object
    - owns synchronizing persisted order state back into:
      - in-memory runtime orders
      - optional engine-local order handles
      - optional order-book maps exposed by compatibility engines
    - owns calculating required buy-side frozen fee from active runtime orders
  - updated `services/order_service.py`
    - now delegates runtime sync concerns to `OrderRuntimeSyncService`
    - keeps `calc_required_frozen_fee()` as a thin facade method for compatibility
  - updated `docs/code-index.md`
  - added `tests/test_order_runtime_sync_service.py`
- Validation:
  - `python -m pytest tests/test_order_runtime_sync_service.py tests/test_order_daily_reset_semantics.py tests/test_order_cancel_semantics.py tests/test_order_tif_semantics.py tests/test_order_ioc_fee_semantics.py tests/test_order_funding_semantics.py tests/test_order_short_cover_semantics.py tests/test_tplus1_order_flow.py tests/test_ipo_settlement_bridge.py tests/test_release_minimal_runtime_chain.py tests/test_order_service_run_registration.py -q`
- Result:
  - `OrderService` now reads more consistently as a coordination facade instead of still carrying a hidden "runtime sync utility" role
  - the contract for syncing ORM order state back into runtime memory is now isolated enough to evolve independently of pre-trade/cancel/settlement work

### follow-up update 40
- Continued the Market detail convergence work so the desktop detail page stops rebuilding authority metadata locally:
  - updated `app/services/market_data_service.py`
    - `request_detail()` now returns canonical `series_meta` alongside the legacy flat compatibility fields
    - added `get_holdings_detail()` so holdings + holdings metadata come from one app-layer helper boundary
    - runtime trade-cache detail series is now marked authoritative when the detail view is driven by live trade appends
    - added compatibility fallback for older `get_retail_holdings(symbol)` overrides that do not accept `limit=...`
  - updated `app/panels/market/panel.py`
    - `SymbolDetailPanel` now stores and reuses service-owned `series_meta` / `chart_meta` instead of reconstructing them ad hoc
    - snapshot / order-book / trades / indicators / holdings metadata now flow through focused builder helpers
    - detail health now evaluates against the already-normalized block metadata instead of recomputing status from mixed local fields
  - updated `app/ui/adapters/market_adapter.py`
    - added a pure chart-geometry helper for candle rendering bounds
    - changed detail K-line rendering to use bar-index x coordinates and tight price bounds instead of `current_sim_day`-scaled x space and `0 -> history_high` y space
    - bottom-axis labels now reflect bar positions, which makes live intraday candles visually occupy the detail chart immediately
  - added / updated tests:
    - `tests/frontend/unit/test_market_runtime_trade_series.py`
    - `tests/frontend/unit/test_market_detail_chart_geometry.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_market_detail_contract.py tests/frontend/unit/test_market_detail_contract_extended.py tests/frontend/unit/test_market_detail_contract_overall_health.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_market_detail_chart_geometry.py tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py tests/frontend/integration/test_frontend_trading_closed_loop.py -q`
  - result: `13 passed`
- Result:
  - Market detail now has a more stable authority split:
    - `snapshot` / `snapshot_meta`: controller snapshot cache
    - `series` / `series_meta`: market data service contract
    - `trades` / `trades_meta`: local detail ring buffer
    - `holdings` / `holdings_meta`: app-layer holdings helper contract
  - runtime trades now produce detail-series metadata that stays aligned with the rendered chart path
  - the detail-page K-line viewport no longer compresses live candles into an almost invisible strip during trading

### follow-up update 41
- Continued the Market detail convergence pass by tightening the `trades` contract:
  - updated `services/runtime_query_service.py`
    - added `get_recent_trades(symbol, limit=...)`
    - recent trade rows now come from persisted `TradeORM` with active-run preference and recent-window fallback
  - updated `app/runtime_gateway.py`
    - exposed `get_recent_trades(...)` to the app layer
  - updated `app/services/market_data_service.py`
    - added `get_trades_detail()` as the app-layer detail boundary for `trades + trades_meta`
    - normalized runtime trade rows into a stable desktop-facing shape
  - updated `app/panels/market/panel.py`
    - detail view now merges:
      - runtime trade log
      - local event overlay
    - local `deque` is no longer the sole source of truth for the tape block
    - duplicate trade rows between runtime query and local overlay are deduped before rendering
  - updated docs:
    - `docs/contracts/market/market-detail-contract.md`
  - added / updated tests:
    - `tests/frontend/unit/test_market_detail_trades_contract.py`
    - `tests/frontend/unit/test_market_runtime_trade_series.py`
    - `tests/frontend/unit/test_market_detail_contract.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_market_detail_contract.py tests/frontend/unit/test_market_detail_contract_extended.py tests/frontend/unit/test_market_detail_contract_overall_health.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_market_detail_chart_geometry.py tests/frontend/unit/test_market_detail_trades_contract.py tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py tests/frontend/integration/test_frontend_trading_closed_loop.py -q`
  - result: `15 passed`
- Result:
  - `trades_meta` now describes a more honest boundary:
    - `runtime-trade-log`
    - `runtime-trade-log+local-overlay`
    - `local-symbol-detail-ring-buffer` only as a degraded fallback
  - detail tape remains immediately responsive to live trade events without pretending the page-local event buffer is the full trade-history source

### follow-up update 42
- Continued the Market detail convergence work by formalizing snapshot/order-book freshness semantics:
  - updated `app/controllers/market_controller.py`
    - added `get_detail_snapshot(symbol, stale_after_ms=...)`
    - controller now owns:
      - `snapshot`
      - `snapshot_meta`
      - `order_book`
      - `order_book_meta`
    - freshness is now explicit:
      - `snapshot_meta.freshness_model = snapshot-ts-age`
      - `order_book_meta.freshness_model = inherit-snapshot-age`
      - `order_book_meta.derived_from = snapshot`
  - updated `app/panels/market/panel.py`
    - `SymbolDetailPanel` now delegates snapshot/order-book detail block assembly to the controller when available
    - panel keeps only a small compatibility fallback for lightweight test doubles without the new controller helper
  - updated docs:
    - `docs/contracts/market/market-detail-contract.md`
  - added / updated tests:
    - `tests/frontend/unit/test_market_snapshot_detail_contract.py`
    - `tests/frontend/unit/test_market_detail_contract.py`
    - `tests/frontend/unit/test_market_detail_contract_extended.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_market_detail_contract.py tests/frontend/unit/test_market_detail_contract_extended.py tests/frontend/unit/test_market_detail_contract_overall_health.py tests/frontend/unit/test_market_snapshot_detail_contract.py tests/frontend/unit/test_market_detail_trades_contract.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_market_detail_chart_geometry.py tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py tests/frontend/integration/test_frontend_trading_closed_loop.py -q`
  - result: `16 passed`
- Result:
  - snapshot freshness is no longer a panel-local heuristic
  - order-book freshness now explicitly inherits snapshot freshness instead of silently shadowing it
  - Market detail core blocks now have clearer ownership:
    - `series`: market data service
    - `snapshot/order_book`: market controller snapshot cache contract
    - `trades`: runtime trade log + local overlay

### follow-up update 43
- Did a small UI-side convergence pass so the detail adapter stops re-inventing status semantics already present in the Market detail contract:
  - updated `app/ui/adapters/market_adapter.py`
    - added focused helpers for:
      - snapshot summary label text
      - debug label text
      - empty-chart fallback text
    - `SymbolDetailAdapter.apply_detail()` now reads contract fields through those helpers instead of rebuilding status strings inline
    - debug output now reflects contract metadata more directly, including:
      - `series_meta.source`
      - `snapshot_meta.freshness_model`
      - `order_book_meta.freshness_model`
  - added tests:
    - `tests/frontend/unit/test_market_detail_adapter_contract_labels.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_market_detail_adapter_contract_labels.py tests/frontend/unit/test_market_adapter_no_trade_buttons.py tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py tests/frontend/unit/test_market_detail_contract.py tests/frontend/unit/test_market_detail_contract_extended.py tests/frontend/unit/test_market_detail_contract_overall_health.py tests/frontend/unit/test_market_snapshot_detail_contract.py tests/frontend/unit/test_market_detail_trades_contract.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_market_detail_chart_geometry.py tests/frontend/integration/test_frontend_trading_closed_loop.py -q`
  - result: `20 passed`
- Result:
  - adapter status/debug text is now a thinner presentation layer over the detail contract instead of another hidden source of freshness/status rules
  - future Market detail contract changes should require fewer UI-side edits because the text rendering path is more centralized

### follow-up update 44
- Continued the Market detail adapter cleanup by splitting the remaining small renderers out of `apply_detail()`:
  - updated `app/ui/adapters/market_adapter.py`
    - added helper render builders for:
      - symbol label text
      - rendered bar count
      - order-book table rows
    - added `_apply_order_book_table(...)` so table painting is separate from order-book row derivation
    - `SymbolDetailAdapter.apply_detail()` now reads more like orchestration over small UI render helpers
  - expanded tests:
    - `tests/frontend/unit/test_market_detail_adapter_contract_labels.py`
- Validation:
  - `python -m pytest tests/frontend/unit/test_market_detail_adapter_contract_labels.py tests/frontend/unit/test_market_adapter_no_trade_buttons.py tests/frontend/unit/test_market_adapter_snapshot_batch_bridge.py tests/frontend/unit/test_market_detail_contract.py tests/frontend/unit/test_market_detail_contract_extended.py tests/frontend/unit/test_market_detail_contract_overall_health.py tests/frontend/unit/test_market_snapshot_detail_contract.py tests/frontend/unit/test_market_detail_trades_contract.py tests/frontend/unit/test_market_runtime_trade_series.py tests/frontend/unit/test_market_detail_chart_geometry.py tests/frontend/integration/test_frontend_trading_closed_loop.py -q`
  - result: `22 passed`
- Result:
  - the detail adapter has less inline branching and fewer mixed responsibilities
  - label rendering, chart empty-state text, and order-book row shaping now have clearer unit-level coverage
