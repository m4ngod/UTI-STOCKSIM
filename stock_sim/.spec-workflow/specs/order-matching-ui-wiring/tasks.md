# order-matching-ui-wiring — Tasks

Status legend:
- [ ] Pending
- [-] In progress
- [x] Completed

Notes:
- Requirements reference: R1 OrdersPanel, R2 Market接线, R3 通知联动, R4 稳定性/节流/释放, R5 可测试性。
- Implement in small PR-sized steps. After finishing a task, update its status and run quick headless checks.

---

- [x] T1: 新增 OrdersPanel 逻辑（app/panels/orders/panel.py）
  - Create a pure logic panel maintaining a bounded deque of normalized lines and filters.
  - Methods: add_line(dict), set_symbol_filter(Optional[str]), set_type_filter(Optional[set[str]]), clear(), set_capacity(int), get_view().
  - Ensure headless-safe, no Qt dependency.
  - Files:
    - NEW app/panels/orders/panel.py
  - Implements: R1, R4, R5
  - _Prompt:
    Role: Python application engineer (UI logic)
    Task: Implement a headless-safe OrdersPanel at app/panels/orders/panel.py with a bounded deque (default capacity=1000), normalization, filters, and get_view(). Include thread-safety with a simple RLock. Export class OrdersPanel with the described API.
    Restrictions: No Qt imports; do not wire event_bus here; avoid heavy dependencies.
    _Leverage: Refer to app/panels/market/panel.py and app/ui/adapters/* patterns for style; use collections.deque and threading.RLock.
    _Requirements: R1, R4, R5
    Success: Tests or a tiny harness can create OrdersPanel, add lines of three types (Trade/OrderRejected/OrderCanceled), set filters, and get_view() reflects expected items with capacity trimming.
    Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.

- [x] T2: 新增 OrdersPanelAdapter（app/ui/adapters/orders_adapter.py）并订阅事件
  - Build a Qt-friendly adapter with headless fallbacks (stub widgets) mirroring existing adapters’ style.
  - UI: top filter controls (symbol input, type toggles), table with columns [ts,type,order_id,symbol,side,price,qty,status,reason]. Optional cancel button placeholder (no-op if service unavailable).
  - Subscribe topics via app.event_bridge.subscribe_topic: "Trade", "OrderRejected", "OrderCanceled". Normalize incoming payloads to OrdersPanel lines; push to logic; throttle refresh (100–200ms). Store unsubscribe callbacks and release in __del__.
  - Also publish ui.notification on rejected/canceled.
  - Files:
    - NEW app/ui/adapters/orders_adapter.py
  - Implements: R1, R2 (Trade ingestion for this panel), R3, R4, R5
  - _Prompt:
    Role: Python Qt adapter engineer
    Task: Implement OrdersPanelAdapter that binds to OrdersPanel logic, renders basic table and filters (with headless stubs), subscribes to Trade/OrderRejected/OrderCanceled using subscribe_topic, throttles refresh, and publishes ui.notification on rejected/canceled. Provide unsubscribe cleanup.
    Restrictions: Keep headless fallback consistent with other adapters; avoid blocking operations; do not directly query backends.
    _Leverage: app/ui/adapters/notifications_adapter.py, market_adapter.py, app/event_bridge.subscribe_topic, infra/event_bus.event_bus
    _Requirements: R1, R2, R3, R4, R5
    Success: In headless mode, invoking incoming event handlers updates adapter’s cached items via logic.get_view(); notifications are published for rejected/canceled; refresh is throttled.
    Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.

- [x] T3: 面板注册（app/panels/__init__.py）加入 orders & 工厂替换
  - Add "orders" to placeholders if missing; add a factory in register_ui_adapters() to replace_panel("orders", ...), creating OrdersPanel logic and binding OrdersPanelAdapter.
  - Files:
    - EDIT app/panels/__init__.py
  - Implements: R1, R4, R5
  - _Prompt:
    Role: Python application integrator
    Task: Wire an Orders panel into panel registry: add placeholder name and a factory in register_ui_adapters() that constructs OrdersPanel logic and returns OrdersPanelAdapter().bind(logic).
    Restrictions: Keep existing registrations untouched; handle import errors with try/except the same way as others.
    _Leverage: Existing register_ui_adapters() patterns for account/market/settings/clock/leaderboard.
    _Requirements: R1, R4
    Success: MainWindow menu shows “Orders”, and get_panel("orders") creates adapter-bound panel.
    Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.

- [x] T4: MarketPanel 逻辑补充 add_trade()
  - Add a public method add_trade(self, trade) forwarding to self._detail.add_trade(trade).
  - Files:
    - EDIT app/panels/market/panel.py
  - Implements: R2, R4
  - _Prompt:
    Role: Python application engineer (logic)
    Task: Add a simple add_trade method to MarketPanel that calls SymbolDetailPanel.add_trade(trade). Keep thread-safety consistent.
    Restrictions: Do not change existing behavior; minimal diff only.
    _Leverage: Current SymbolDetailPanel.add_trade implementation.
    _Requirements: R2, R4
    Success: When adapter calls MarketPanel.add_trade(trade), the trade is appended for the selected symbol and visible in get_view().
    Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.

- [x] T5: MarketPanelAdapter 订阅 Trade 与 FRONTEND_SNAPSHOT_BATCH_TOPIC 并节流刷新
  - Subscribe Trade: if payload.trade.symbol == selected symbol, call logic.add_trade(payload.trade or dict).
  - Subscribe FRONTEND_SNAPSHOT_BATCH_TOPIC: throttle-call self.refresh() every ~200ms.
  - Keep unsubscribe handlers and cleanup in __del__.
  - Files:
    - EDIT app/ui/adapters/market_adapter.py
  - Implements: R2, R4, R5
  - _Prompt:
    Role: Python Qt adapter engineer
    Task: Update MarketPanelAdapter to subscribe to Trade and FRONTEND_SNAPSHOT_BATCH_TOPIC using subscribe_topic, push trades for the selected symbol to logic.add_trade, and throttle UI refresh on batch snapshots; ensure unsubscribe cleanup.
    Restrictions: Keep existing behavior; avoid tight coupling with services; use the same headless stubs patterns.
    _Leverage: app/event_bridge.FRONTEND_SNAPSHOT_BATCH_TOPIC, subscribe_topic; existing MarketPanelAdapter style in _create_widget and __del__.
    _Requirements: R2, R4, R5
    Success: In headless tests, simulating Trade events increases trades for selected symbol; batch snapshot events trigger at most ~5 refreshes/sec.
    Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.

- [x] T6: 基础测试/验证（headless）
  - Add a minimal test or script (optional if existing test suite is heavy) to simulate events and assert logic/adapter state changes. If adding tests is intrusive, provide a minimal script under tests/frontend/integration or scripts/ to exercise orders wiring headlessly.
  - Files:
    - NEW tests/frontend/integration/test_orders_panel_wiring.py (or scripts/dev_check_orders_wiring.py)
  - Implements: R5
  - _Prompt:
    Role: Python test engineer
    Task: Create a small headless test to instantiate OrdersPanel & OrdersPanelAdapter, simulate event callbacks (Trade/OrderRejected/OrderCanceled) by directly calling adapter handlers or publishing on event_bus (if feasible in tests), then assert get_view() content and notifications publication. Also cover MarketAdapter trade pass-through when symbol is selected.
  - Restrictions: Keep tests fast and independent; skip if PySide6 unavailable; prefer event_bus.subscribe for capture.
  - _Leverage: tests/frontend patterns, infra.event_bus
  - _Requirements: R5
  - Success: Test passes locally (headless), verifying the wiring and basic behaviors.
  - Instructions: Implement the task for spec order-matching-ui-wiring, first run spec-workflow-guide to get the workflow guide then implement the task. Then mark this task as [-] when starting and [x] when finished.
