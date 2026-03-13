# order-matching-ui-wiring — Requirements

Purpose: 将“订单撮合/委托链路”与其他关键后端事件接线到 UI，提供可视化与交互能力，确保核心撮合、成交、委托拒单/取消等状态在 UI 实时可见。

Context (as-is):
- 后端事件来源：
  - services/order_service.py 发布事件：
    - "Trade"（成交） payload: {"trade": tr_dict}
    - "OrderCanceled"（订单取消） payload: {"order_id", "reason"}
    - "OrderRejected"（下单拒绝） payload: {"order": order_dict, "reason"}
  - snapshot 由 EventBridge 聚合后通过 FRONTEND_SNAPSHOT_BATCH_TOPIC 广播，但 MarketPanel 当前未订阅；SymbolDetailPanel 支持 add_trade(...)，但缺少事件接线。
- UI 现状：
  - 已有面板：account, market, agents, leaderboard, clock, settings；未发现“订单/撮合”面板。
  - notifications 仅订阅 'ui.notification'，未自动把拒单/取消转化为通知。

In-scope Requirements:
- R1 OrdersPanel（订单/撮合看板，最小可用版）：
  - R1.1 实时表格（增量流式）：显示订单相关事件/快照行，字段至少包含：ts、type(OrderRejected/OrderCanceled/Trade)、order_id、symbol、side、price、qty、status、reason（若有）。
  - R1.2 过滤/切片：按 symbol、type 过滤（至少支持复选 type 过滤）。
  - R1.3 取消操作（可选，若服务可用）：选中含 order_id 的行，触发取消（调用可用的 cancel API；若不可用则置灰）。
  - R1.4 保留最近 N 条（默认 1000，防内存膨胀）。
  - R1.5 Headless 降级可用（无 PySide6 环境不报错）。
- R2 Market接线：
  - R2.1 订阅 Trade，将本标的成交推送给 SymbolDetailPanel.add_trade。
  - R2.2 订阅 FRONTEND_SNAPSHOT_BATCH_TOPIC，触发轻量 refresh（节流）。
- R3 通知联动：
  - R3.1 将 OrderRejected/OrderCanceled 转换为 'ui.notification'，级别：
    - Rejected -> level=error, code=ORDER_REJECTED
    - Canceled -> level=warning, code=ORDER_CANCELED
  - R3.2 NotificationsPanel 可实时看到这些通知。
- R4 性能与稳定性：
  - R4.1 所有 UI 刷新需通过节流（>=100-200ms）
  - R4.2 订阅均提供取消钩子，避免泄漏；MainWindow 关闭/面板销毁时释放。
- R5 可测试性：
  - R5.1 在无 Qt 环境下，事件触发后 get_view() 可反映缓存中的数据变化（便于单测）。

Out of scope (本阶段不做)：
- 完整订单生命周期重放、复杂排序/分页；
- 历史回放与图形化订单簿可视化；
- 高级风控联动与可视指标。

Acceptance Criteria:
- A1 启动前端后，Panels 菜单出现“Orders”。
- A2 向 event_bus 依次发布 OrderRejected、OrderCanceled、Trade 事件后：
  - OrdersPanel 表格新增记录，字段正确映射，超过容量自动丢弃最早记录。
  - NotificationsPanel 出现对应等级通知。
- A3 发布 FRONTEND_SNAPSHOT_BATCH_TOPIC 后，MarketPanel 小于 200ms 的节流刷新生效；订阅 Trade 能在选中 symbol 的详情中看到成交条目计数增长（或最近列表增加）。
- A4 关闭主窗口或销毁 OrdersPanel 时，订阅被释放，不再响应事件。

Non-functional:
- N1 线程安全：事件处理内采用最小加锁或无锁结构（ring buffer 或 deque），UI 刷新统一投递主线程或在 headless 直接调用。
- N2 错误隔离：异常吞吐记录 metrics，不影响主流程。

