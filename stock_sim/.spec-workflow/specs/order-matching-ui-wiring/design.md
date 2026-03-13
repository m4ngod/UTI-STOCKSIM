# order-matching-ui-wiring — Design

Scope recap:
- 将撮合/委托链路接到 UI：新增 Orders 面板；Market 面板订阅成交与快照批；拒单/取消转通知。

Architecture
- Event sources (backend):
  - services/order_service.py publishes topics: "Trade", "OrderRejected", "OrderCanceled".
  - app/event_bridge.py defines FRONTEND_SNAPSHOT_BATCH_TOPIC ("frontend.snapshot.batch") and helper subscribe_topic.
- UI integration pattern:
  - 按现有约定，订阅放在 UI 适配器层（参考 notifications_adapter, market_adapter 的 instrument-created 订阅）。
  - 逻辑层（Panel）维护内存态与视图构造（get_view），不直接耦合事件总线。

Components
1) OrdersPanel (logic) — app/panels/orders/panel.py
   - State:
     - deque events (capacity=N=1000，可配置)
     - filters: symbol: Optional[str], types: Optional[set[str]]
   - API:
     - add_line(line: dict)
     - set_symbol_filter(str|None), set_type_filter(set|None)
     - clear(), capacity(n)
     - get_view() -> { "items": [...], "filters": {...}, "capacity": N }
   - Line schema (normalized):
     - { ts:int(ms), type:str in {Trade, OrderRejected, OrderCanceled}, order_id?:str, symbol?:str, side?:str, price?:float, qty?:int, status?:str, reason?:str }
   - Behavior:
     - append -> trim to capacity
     - filter in get_view (by symbol and type)

2) OrdersPanelAdapter — app/ui/adapters/orders_adapter.py
   - Widget:
     - Top filter row: symbol input + type toggles (Trade/Rejected/Canceled)
     - Table QTableWidget(cols: ts, type, order_id, symbol, side, price, qty, status, reason)
     - Cancel button (if row has order_id) -> 调用逻辑挂钩或直接事件发布（占位，不强依赖服务）
   - Event subscriptions:
     - subscribe_topic("Trade", on_trade)
     - subscribe_topic("OrderRejected", on_rejected) -> 同时 publish('ui.notification', level=error, code=ORDER_REJECTED, message=...)
     - subscribe_topic("OrderCanceled", on_canceled) -> 同时 publish('ui.notification', level=warning, code=ORDER_CANCELED, message=...)
   - Throttle:
     - 100–200ms 合并刷新（批量到达时只触发一次 UI 刷新）
   - Lifecycle:
     - 记录取消函数；__del__/销毁时取消订阅。

3) MarketPanelAdapter wiring update
   - Subscribe:
     - subscribe_topic("Trade", on_trade): 如果 trade.symbol == 当前选中 symbol => 调用逻辑层新增方法 add_trade(trade)
     - subscribe_topic(FRONTEND_SNAPSHOT_BATCH_TOPIC, on_batch): 节流调用 self.refresh()（<=每200ms 一次）
   - Logic update (MarketPanel logic):
     - 新增 def add_trade(self, trade: TradeDTO|dict): self._detail.add_trade(trade)
   - Lifecycle:
     - 保存取消订阅句柄；__del__ 释放。

4) Panel registration
   - 更新 app/panels/__init__.py：
     - 在 _PLACEHOLDER_NAMES 中加入 "orders"，使之默认可见。
     - 在 register_ui_adapters() 中新增 Orders 面板工厂：
       - logic: app.panels.orders.panel.OrdersPanel
       - adapter: app.ui.adapters.orders_adapter.OrdersPanelAdapter
       - 使用 replace_panel("orders", factory, title="Orders", meta={"i18n_key": "panel.orders"})

5) Notifications wiring
   - 在 OrdersPanelAdapter 的 on_rejected/on_canceled 中，发布 'ui.notification'：{'level','code','message'}
   - NotificationsPanelAdapter 已订阅该主题，无需改动。

Data contracts
- Input events:
  - Trade: { 'trade': {symbol, price, quantity, buy_order_id, sell_order_id, ... , ts?} }
  - OrderRejected: { 'order': {... minimal fields ...}, 'reason': str }
  - OrderCanceled: { 'order_id': str, 'reason': str }
- Orders line mapping:
  - Trade: ts: trade.ts or now_ms; type:'Trade'; order_id: buy_order_id|sell_order_id? (留空或显示 buy/sell 对)
  - Rejected: ts: now_ms; type:'OrderRejected'; order_id: order.id; symbol: order.symbol; side: order.side; price, qty, status: 'REJECTED'; reason
  - Canceled: ts: now_ms; type:'OrderCanceled'; order_id; reason

Performance & thread-safety
- 适配器订阅回调内仅入缓冲并触发节流刷新。
- OrdersPanel 内部使用 deque；MarketPanel 内部 SymbolDetailPanel 已使用 RingBuffer。

Error handling
- 回调中任何异常捕获并忽略，同时 metrics.inc(...)（若可用）。
- 缺失字段容忍：用 None/缺省值填充，不阻塞。

File plan (to be created/edited)
- NEW app/panels/orders/panel.py — OrdersPanel logic
- NEW app/ui/adapters/orders_adapter.py — Orders UI adapter + subscriptions + notifications publishing
- EDIT app/panels/__init__.py — 注册占位与适配器工厂（加入 orders）
- EDIT app/panels/market/panel.py — 添加 public add_trade(self, trade)
- EDIT app/ui/adapters/market_adapter.py — 订阅 Trade 和 FRONTEND_SNAPSHOT_BATCH_TOPIC + 节流 + 释放订阅

Test plan
- Unit (headless):
  - 创建 OrdersPanel + OrdersPanelAdapter（在 headless stub 控件下）;
  - 手动调用回调模拟发布三类事件 -> get_view() 包含对应记录；超容量时丢弃最早记录。
  - 触发 rejected/canceled 回调 -> 检查 event_bus 中 ui.notification 被消费（可通过订阅测试 handler 计数）。
  - MarketAdapter：调用 on_trade(trade for selected symbol) -> MarketPanel.get_view()['trades'] 数量增加；发布 FRONTEND_SNAPSHOT_BATCH_TOPIC -> 观察节流刷新次数（可暴露计数器或通过方法桩）。

Risks / mitigations
- 事件量较大：采用节流+固定容量；若后续需要更大吞吐，考虑使用批量 append API 与批处理渲染。
- 依赖字段不稳定：映射时尽量兜底，避免 keyError。

