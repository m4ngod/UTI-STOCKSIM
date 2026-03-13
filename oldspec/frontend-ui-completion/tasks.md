# Tasks Document

(所有任务使用 Python 3.11 + PySide6；遵循分层：Service/Controller/PanelLogic/UI Adapter。每条任务 1~3 文件改动，互斥并行度高。含 _Prompt 供后续自动代理执行。)

## Legend
- Req: 关联需求 ID (R1~R25)
- Type: feat / refactor / test / doc
- Dep: 依赖前置任务编号 (以任务号列表表示)

---

- [x] 1. 创建 BasePanelLogic 抽象
  - Files: app/panels/base_logic.py (新建)
  - Content: 定义 attach(context), detach(), apply_settings(settings), get_view() 占位; 兼容现有面板可不继承
  - Req: R25
  - Dep: -
  - _Prompt: Role: Python Architect | Task: Create BasePanelLogic abstract class with lifecycle methods (attach, detach, apply_settings, get_view) ensuring backward compatibility; no existing panels must break | Restrictions: No Qt imports, pure logic only | Success: File added, mypy passes, existing panel imports unaffected_

- [x] 2. 主窗口 UI Shell 与 Dock 管理骨架
  - Files: app/ui/main_window.py (新建), app/ui/docking.py (新建)
  - Content: MainWindow 继承 QMainWindow; DockManager 提供 add_panel/ remove_panel/list_open; 不实现具体面板适配逻辑
  - Req: R20, R25
  - Dep: 1
  - _Prompt: Role: PySide6 Developer | Task: Implement MainWindow and DockManager skeleton (open/close panel via registry), minimal menu placeholder, no business logic | Restrictions: Avoid heavy logic, no layout persistence yet | Success: run_frontend(headless=False) creates window without errors_

- [x] 3. 布局持久化集成到主窗口
  - Files: app/ui/main_window.py (修改), app/ui/docking.py (修改)
  - Content: serialize_layout()/restore_layout() 与 LayoutPersistence 交互; 保存时机：closeEvent; 启动时加载
  - Req: R20
  - Dep: 2
  - _Prompt: Role: PySide6 Developer | Task: Integrate LayoutPersistence with MainWindow for dock/tab state persistence | Restrictions: Handle JSON decode errors gracefully (fallback default) | Success: Layout file updates after open/close panel actions_

- [x] 4. SettingsSync + ThemeManager + I18nManager 框架
  - Files: app/ui/settings_sync.py (新), app/ui/theme.py (新), app/ui/i18n_bind.py (新)
  - Content: 订阅 SettingsStore.on_any → 触发主题(qss 读取 QSS/*.qss) & 语言刷新
  - Req: R6, R21
  - Dep: 2
  - _Prompt: Role: Python UI Engineer | Task: Implement SettingsSync to listen store changes and apply theme/i18n across registered widgets | Restrictions: Non-blocking (<50ms), catch file IO errors | Success: Changing language/theme updates a sample registered widget text/style_

- [x] 5. PanelAdapter 接口定义
  - Files: app/ui/adapters/base_adapter.py (新)
  - Content: class PanelAdapter: bind(logic), widget(), refresh(), apply_settings(settings)
  - Req: R25
  - Dep: 1
  - _Prompt: Role: PySide6 Developer | Task: Define a generic PanelAdapter base to bridge logic panels and QWidget | Restrictions: No business logic; minimal methods only | Success: Base adapter importable with no runtime side effects_

- [x] 6. AccountPanelAdapter 实现
  - Files: app/ui/adapters/account_adapter.py (新)
  - Content: 显示账户摘要 + QTableView 持仓; 高亮 highlight 行; refresh() 从 logic.get_view()
  - Req: R1
  - Dep: 5
  - _Prompt: Role: PySide6 Developer | Task: Implement AccountPanelAdapter with summary labels + table using model diff updates; highlight rows with pnl_ratio threshold | Restrictions: No blocking operations; keep repaint scope minimal | Success: Demo load shows account rows, highlight boolean reflected_

- [x] 7. MarketPanelAdapter + SymbolDetailAdapter
  - Files: app/ui/adapters/market_adapter.py (新)
  - Content: 左侧自选列表(QListView)、右侧 K 线占位(Plot placeholder)、盘口与 L2 占位表格; select symbol 触发 detail refresh
  - Req: R2, R12, R13, R14 (部分框架)
  - Dep: 5, 11 (L2 ring buffer), 15 (indicator executor 扩展)
  - _Prompt: Role: PySide6 Developer | Task: Implement market adapters with watchlist UI, detail views placeholders (bars, order book, trades) | Restrictions: No heavy plotting (placeholder widget), watchlist events must not block UI | Success: Selecting symbol updates detail snapshot fields_

- [x] 8. AgentsPanelAdapter + LogsViewer
  - Files: app/ui/adapters/agents_adapter.py (新), app/ui/adapters/agents_log.py (新)
  - Content: 列表 + 控制按钮(start/pause/stop) + 批量创建进度条 + tail 日志窗口
  - Req: R3, R18, R17 (UI 部分)
  - Dep: 5
  - _Prompt: Role: PySide6 Developer | Task: Implement agent list with control buttons and embedded log tail pane; refresh stale heartbeat coloring | Restrictions: Actions must call controller/service only via logic | Success: Start/Pause/Stop update status cell visually_

- [x] 9. LeaderboardPanelAdapter
  - Files: app/ui/adapters/leaderboard_adapter.py (新)
  - Content: 窗口下拉(window)、排序按钮、表格、曲线合成结果简单 matplotlib 或占位折线
  - Req: R4, R10 (UI 基础)
  - Dep: 5
  - _Prompt: Role: PySide6 Developer | Task: Implement leaderboard adapter with sorting and selection curve display placeholder | Restrictions: Use cached rows; no blocking export call (run in thread) | Success: Selecting row updates curve panel_

- [x] 10. ClockPanelAdapter
  - Files: app/ui/adapters/clock_adapter.py (新)
  - Content: 启动/暂停/恢复/停止/速度 spinbox/创建 checkpoint/回滚按钮 列表显示
  - Req: R5, R15 (UI 部分)
  - Dep: 5, 19 (speed sync)
  - _Prompt: Role: PySide6 Developer | Task: Implement clock controls adapter wired to controller; include checkpoint table and rollback button | Restrictions: Disable rollback while running action executes | Success: Creating checkpoint updates table within one refresh cycle_

- [x] 11. L2RingBuffer 与 TickAggregator
  - Files: app/l2/ring_buffer.py (新), app/l2/aggregator.py (新)
  - Content: RingBuffer(capacity=5000), append_tick(), get_recent(); aggregator 接收 TickEvent 合并
  - Req: R12, R22
  - Dep: -
  - _Prompt: Role: Python Performance Engineer | Task: Implement O(1) ring buffer for ticks and simple aggregator; include unit tests for overflow order | Restrictions: No external deps; thread-safe with RLock | Success: Tests confirm capacity clamp & order preservation_

- [x] 12. Watchlist 持久化
  - Files: app/panels/market/panel.py (修改), app/state/watchlist_store.py (新)
  - Content: 添加 store.load()/save(); add/remove 时持久化
  - Req: R14
  - Dep: 7 (适配前亦可实现)
  - _Prompt: Role: Python Developer | Task: Add persistent watchlist store with JSON path and integrate into MarketPanel add/remove | Restrictions: Avoid write amplification (debounce) | Success: Restart restores symbols list_

- [x] 13. 指标执行器扩展 (MA/MACD)
  - Files: app/indicators/executor.py (修改), app/indicators/builtin/ma.py (新), app/indicators/builtin/macd.py (新)
  - Content: 线程池 futures + invalidate(symbol); 计算结果缓存
  - Req: R13, R22
  - Dep: -
  - _Prompt: Role: Quant Python Developer | Task: Implement MA & MACD computations using numpy/pandas; add async executor with caching & invalidation | Restrictions: Fallback if pandas missing (graceful) | Success: Market detail view shows indicator arrays after compute_

- [x] 14. MarketDetail 指标 & 逐笔整合
  - Files: app/panels/market/panel.py (修改)
  - Content: detail_view 增加 indicators dict & trades list from ring buffer
  - Req: R12, R13
  - Dep: 11, 13
  - _Prompt: Role: Python Developer | Task: Extend SymbolDetailPanel to include indicators/trades fields using executor & ring buffer | Restrictions: Keep get_view pure (no blocking) | Success: get_view() returns indicators & trades keys_

- [x] 15. NotificationCenter
  - Files: app/notification/center.py (新), app/notification/dto.py (新)
  - Content: push/list_recent/mark_read/on_new; 内存固定长度 1000; 事件类型枚举
  - Req: R11, R16, R23, R24
  - Dep: -
  - _Prompt: Role: Python Backend Engineer | Task: Implement in-memory notification center with observer callbacks; add thread safety | Restrictions: No Qt dependency | Success: Unit tests push 1100 items keep latest 1000_

- [x] 16. 阈值告警 → 通知集成
  - Files: app/panels/account/panel.py (修改)
  - Content: highlight 触发时若新出现高亮新增通知 (type=ALERT)
  - Req: R11, R1
  - Dep: 15
  - _Prompt: Role: Python Developer | Task: Emit notification when a position becomes highlighted; suppress duplicates per symbol per session | Restrictions: Lightweight O(1) per row | Success: Test verifies single notification per symbol highlight_

- [x] 17. 心跳超时通知
  - Files: app/panels/agents/panel.py (修改)
  - Content: stale 状态触发通知
  - Req: R11, R3
  - Dep: 15
  - _Prompt: Role: Python Developer | Task: Add notification when agent first transitions to heartbeat stale | Restrictions: Debounce repeats | Success: Unit test triggers once despite multiple get_view calls_

- [x] 18. 脚本校验失败通知
  - Files: app/panels/agent_config/panel.py (修改)
  - Content: add_version 返回 False 且 last_error/violations 时 push 通知
  - Req: R11, R23, R8
  - Dep: 15
  - _Prompt: Role: Python Developer | Task: Emit notification on script validation failure with code summary | Restrictions: No duplicate for identical error consecutively | Success: Test triggers notification with correct code field_

- [x] 19. PlaybackSpeed 联动 ClockService
  - Files: app/controllers/clock_controller.py (修改), app/panels/settings/panel.py (必要时), app/ui/settings_sync.py (修改)
  - Content: settings playback_speed 改变调用 controller.set_speed
  - Req: R6, R15
  - Dep: 4, 10
  - _Prompt: Role: Python Developer | Task: Wire playback speed changes from settings to clock controller set_speed | Restrictions: Ignore invalid (<=0) values, notify WARNING | Success: Changing speed updates ClockPanel state within cycle_

- [x] 20. CheckpointVerifier
  - Files: app/rollback/verify.py (新), app/panels/clock/panel.py (修改)
  - Content: rollback 后调用 verify -> Notification (ALERT if issues)
  - Req: R16
  - Dep: 15
  - _Prompt: Role: Python Developer | Task: Implement verification comparing snapshot summaries of account/equity/agents count | Restrictions: Time <50ms typical; skip heavy diffs | Success: Artificial mismatch test triggers ALERT_

- [x] 21. ExportService xlsx 扩展
  - Files: app/services/export_service.py (修改)
  - Content: openpyxl 可选导出 meta sheet + data sheet
  - Req: R10
  - Dep: -
  - _Prompt: Role: Python Developer | Task: Add XLSX export path with meta sheet; fallback if openpyxl missing | Restrictions: Do not break CSV path | Success: Export returns .xlsx path and file exists in test_

- [x] 22. LeaderboardAdapter 导出异步
  - Files: app/ui/adapters/leaderboard_adapter.py (修改)
  - Content: 按钮点击 -> 线程执行 export -> 完成通知
  - Req: R4, R10, R11
  - Dep: 9, 21, 15
  - _Prompt: Role: PySide6 Developer | Task: Add async export button dispatching thread, show notification on success/failure | Restrictions: Prevent concurrent exports | Success: Second click disabled while running_

- [x] 23. TemplateStore & 应用模板 API
  - Files: app/templates/store.py (新), app/panels/agent_config/panel.py (修改), app/panels/agents/panel.py (必要修改)
  - Content: save/list/load/delete; agent_config 增加 apply_template(name)
  - Req: R9
  - Dep: 8, 18
  - _Prompt: Role: Python Developer | Task: Implement strategy template persistence JSON store and integrate apply_template | Restrictions: Validate name unique; atomic write | Success: Applying template increments params_version_

- [x] 24. Redis EventBridge 集成扩展
  - Files: app/event_bridge.py (修改), app/services/redis_subscriber.py (必要) 
  - Content: enable_redis(url) 建立订阅线程；指标 redis_fallback
  - Req: R19
  - Dep: -
  - _Prompt: Role: Python Backend Engineer | Task: Extend EventBridge to optionally use Redis pub/sub for events with graceful fallback | Restrictions: Thread safe shutdown; no busy loop | Success: Simulated redis unavailable triggers fallback metric_

- [x] 25. PerformanceMonitor
  - Files: app/observability/perf_monitor.py (新), app/ui/main_window.py (修改)
  - Content: context manager record_phase(); 主窗口定时 flush -> metrics
  - Req: R22, R24
  - Dep: 2
  - _Prompt: Role: Python Performance Engineer | Task: Add PerformanceMonitor to measure UI freeze sections and flush metrics periodically | Restrictions: Overhead <1% | Success: Test wraps dummy block and records metric name_

- [x] 26. 指标超时与取消
  - Files: app/indicators/executor.py (修改)
  - Content: Future timeout(1s) -> cancel + metrics.indicator_timeout
  - Req: R13, R22, R24
  - Dep: 13
  - _Prompt: Role: Python Developer | Task: Add timeout logic to indicator futures and record metrics on cancellation | Restrictions: Non-blocking join; skip partial results | Success: Simulated sleep indicator triggers timeout metric_

- [x] 27. MarketPanel 增量刷新节流
  - Files: app/controllers/market_controller.py (修改) (若存在 on_events), app/panels/market/panel.py (修改)
  - Content: 合并 snapshot 批次 ≤200ms 刷新; 控制刷新频率 5~10Hz
  - Req: R2, R22
  - Dep: 11
  - _Prompt: Role: Python Developer | Task: Implement throttled incremental updates for snapshots using time bucketing | Restrictions: No more than 10 refresh/sec | Success: Test simulating 50 events/second results in <=10 logic refresh calls_

- [x] 28. Undo/Redo 设置适配器联动
  - Files: app/ui/adapters/settings_adapter.py (新)
  - Content: 显示设置表单 + undo/redo 按钮
  - Req: R6
  - Dep: 5
  - _Prompt: Role: PySide6 Developer | Task: Implement SettingsPanelAdapter with undo/redo and transaction batch update UI | Restrictions: Ensure recent_changes reflected promptly | Success: Changing fields then undo reverts values_

- [x] 29. 通知中心 UI (NotificationWidget)
  - Files: app/ui/notification_widget.py (新), app/ui/main_window.py (修改)
  - Content: 列表视图 + 过滤(INFO/WARN/ERROR/ALERT) + 标记已读
  - Req: R11
  - Dep: 15
  - _Prompt: Role: PySide6 Developer | Task: Implement notification dock widget showing latest notifications with filter buttons | Restrictions: Keep model max 500 displayed | Success: Pushing notifications updates UI list_

- [x] 30. Agent Creation Dialog
  - Files: app/ui/dialogs/agent_creation_dialog.py (新)
  - Content: 输入 agent_type / initial_cash / strategies / count; 校验不支持类型
  - Req: R7, R17
  - Dep: 8
  - _Prompt: Role: PySide6 Developer | Task: Implement modal dialog for agent creation supporting batch and strategy list | Restrictions: Validate numeric ranges; show error label on unsupported | Success: Batch create triggers progress in AgentsPanel_

- [x] 31. AgentConfigPanelAdapter + 脚本编辑区
  - Files: app/ui/adapters/agent_config_adapter.py (新)
  - Content: 版本列表 + 添加版本(JSON diff + 可选脚本文本) + 回滚按钮 + violations 展示
  - Req: R8, R23, R9 (应用模板入口)
  - Dep: 5, 23, 18
  - _Prompt: Role: PySide6 Developer | Task: Implement adapter for agent config with script input editor and violations display | Restrictions: Large script (>200KB) reject with warning | Success: Adding bad script shows violations list_

- [x] 32. CheckpointVerifier 单元测试
  - Files: tests/frontend/unit/test_checkpoint_verifier.py (新)
  - Content: 构造模拟摘要 -> 验证 mismatch 检测
  - Req: R16
  - Dep: 20
  - _Prompt: Role: Python Test Engineer | Task: Write unit tests for VerificationReport generation (match & mismatch cases) | Restrictions: No real services; use fakes | Success: Both cases pass with expected issues length_

- [x] 33. L2RingBuffer & Aggregator 测试
  - Files: tests/frontend/unit/test_l2_ring_buffer.py (新)
  - Content: 容量溢出、顺序、并发 append 粗测
  - Req: R12
  - Dep: 11
  - _Prompt: Role: Python Test Engineer | Task: Test ring buffer overflow and concurrency safety | Restrictions: Avoid sleep; simulate threads with join | Success: Order maintained and size capped_

- [x] 34. IndicatorExecutor 测试
  - Files: tests/frontend/unit/test_indicator_executor.py (新)
  - Content: MA/MACD 正常 & 超时模拟
  - Req: R13, R22
  - Dep: 13, 26
  - _Prompt: Role: Python Test Engineer | Task: Test indicator computations and timeout path with monkeypatch | Restrictions: Deterministic data | Success: Timeout metric increment asserted_

- [x] 35. NotificationCenter 测试
  - Files: tests/frontend/unit/test_notification_center.py (新)
  - Content: push裁剪/mark_read/observer
  - Req: R11
  - Dep: 15
  - _Prompt: Role: Python Test Engineer | Task: Validate notification center ring behavior, read status, observer callback | Restrictions: No threading complexity needed | Success: Observer fired correct count_

- [x] 36. Watchlist 持久化测试
  - Files: tests/frontend/unit/test_watchlist_store.py (新)
  - Content: 添加/重启恢复/损坏文件恢复默认
  - Req: R14
  - Dep: 12
  - _Prompt: Role: Python Test Engineer | Task: Test watchlist load/save and corrupted file fallback | Restrictions: Use tmp path | Success: Corrupt file triggers default list_

- [x] 37. Export XLSX 测试
  - Files: tests/frontend/unit/test_export_xlsx.py (新)
  - Content: meta sheet 存在/无 openpyxl fallback
  - Req: R10
  - Dep: 21
  - _Prompt: Role: Python Test Engineer | Task: Test XLSX export with meta and simulate missing dependency fallback | Restrictions: Skip if module truly absent | Success: File exists or fallback path used_

- [x] 38. AgentsPanel Stale & Notification 测试
  - Files: tests/frontend/unit/test_agents_stale_notify.py (新)
  - Content: 心跳变 stale 触发单次通知
  - Req: R3, R11
  - Dep: 17
  - _Prompt: Role: Python Test Engineer | Task: Simulate agent heartbeat aging to trigger notification once | Restrictions: Use manual timestamp override | Success: Only one notification generated_

- [x] 39. AccountPanel Highlight Notification 测试
  - Files: tests/frontend/unit/test_account_highlight_notify.py (新)
  - Content: 盈亏超阈值 -> 通知
  - Req: R1, R11
  - Dep: 16
  - _Prompt: Role: Python Test Engineer | Task: Test position highlight pushes single notification | Restrictions: Use fake positions list | Success: Notification list size ==1_

- [x] 40. PlaybackSpeed 联动测试
  - Files: tests/frontend/unit/test_playback_speed_sync.py (新)
  - Content: Settings 更改 speed -> controller.set_speed 被调用
  - Req: R15
  - Dep: 19
  - _Prompt: Role: Python Test Engineer | Task: Test speed change results in controller update, invalid value ignored | Restrictions: Mock controller | Success: Valid speed calls once; invalid skipped_

- [x] 41. 集成测试：快照节流
  - Files: tests/frontend/integration/test_market_throttle.py (新)
  - Content: 频繁事件 -> 刷新次数 ≤10Hz
  - Req: R2, R22
  - Dep: 27
  - _Prompt: Role: Python Integration Tester | Task: Simulate high-rate snapshot events, assert throttled refresh count | Restrictions: Fake time or accelerate | Success: Refresh count within bounds_

- [x] 42. 集成测试：回滚+校验
  - Files: tests/frontend/integration/test_rollback_verify.py (新)
  - Content: rollback -> verification report -> 通知
  - Req: R16
  - Dep: 20, 32
  - _Prompt: Role: Python Integration Tester | Task: Simulate rollback with mismatch to assert ALERT notification | Restrictions: Fake controllers | Success: Notification includes 'ALERT' type_

- [x] 43. 集成测试：指标异步
  - Files: tests/frontend/integration/test_indicator_async.py (新)
  - Content: 请求指标 -> 异步完成后 detail 包含结果
  - Req: R13
  - Dep: 13, 14
  - _Prompt: Role: Python Integration Tester | Task: Test indicator future resolves and updates detail view model | Restrictions: Use deterministic small bars | Success: indicators key present_

- [x] 44. 集成测试：模板应用
  - Files: tests/frontend/integration/test_template_apply.py (新)
  - Content: 保存模板 -> 应用 -> params_version 增长
  - Req: R9
  - Dep: 23
  - _Prompt: Role: Python Integration Tester | Task: Test template save and apply increments params_version | Restrictions: Mock service where needed | Success: version incremented by 1_

- [x] 45. E2E (headless) 启动与多面板
  - Files: tests/frontend/e2e/test_startup_panels.py (新)
  - Content: run_frontend(headless=True) open panels programmatic -> 验证 get_view 非空
  - Req: R1,R2,R3,R4,R5,R6
  - Dep: 6,7,8,9,10,28
  - _Prompt: Role: Python E2E Tester | Task: Headless open all panels and assert core view models structure | Restrictions: No Qt event loop block; use timers minimal | Success: All panels open and return expected keys_

- [x] 46. E2E 语言/主题切换
  - Files: tests/frontend/e2e/test_language_theme.py (新)
  - Content: 修改 language/theme -> UI 属性变化(模拟 adapter 属性)
  - Req: R6, R21
  - Dep: 4, 28
  - _Prompt: Role: Python E2E Tester | Task: Test language/theme change triggers adapter apply_settings | Restrictions: Use dummy adapter capturing calls | Success: apply_settings invoked with new values_

- [x] 47. E2E 排行榜导出
  - Files: tests/frontend/e2e/test_leaderboard_export.py (新)
  - Content: 触发导出 -> 文件存在
  - Req: R4, R10
  - Dep: 22, 21
  - _Prompt: Role: Python E2E Tester | Task: Test export action produces file (csv + optional xlsx) | Restrictions: Temp directory usage | Success: Files created with >0 bytes_

- [x] 48. E2E 回滚与通知
  - Files: tests/frontend/e2e/test_rollback_notification.py (新)
  - Content: 模拟 mismatch -> ALERT 通知 UI 列表项
  - Req: R16, R11
  - Dep: 20, 29, 32
  - _Prompt: Role: Python E2E Tester | Task: Full flow rollback invoking verifier producing notification displayed | Restrictions: Headless mode; stub controllers | Success: NotificationWidget lists ALERT_

- [x] 49. 观测性统一慢操作装饰器
  - Files: app/utils/slow_op.py (新), 各需要位置引用(最小) 
  - Content: 装饰器记录耗时>阈值 metrics.{name}_slow
  - Req: R24
  - Dep: 24 (部分 metrics), 25
  - _Prompt: Role: Python Developer | Task: Implement slow_op decorator to measure function elapsed and inc metric if > threshold | Restrictions: Overhead minimal (<5µs call) | Success: Test triggers slow metric increment_

- [x] 50. 文档更新：frontend_dev_guide.md 扩充
  - Files: docs/frontend_dev_guide.md (修改)
  - Content: 新增 UI 适配层、NotificationCenter、指标执行器、L2 缓存章节
  - Req: R25, R12, R13, R11
  - Dep: 6,7,11,13,15
  - _Prompt: Role: Technical Writer | Task: Update dev guide documenting new architecture components and usage patterns | Restrictions: Keep sections concise; add sequence diagram if needed | Success: Guide includes new sections headings_

---
合计 50 任务，覆盖 R1~R25 功能与非功能需求；测试层级：Unit(32~40,33,34,35,36,37,38,39,40)、Integration(41~44)、E2E(45~48)。观察性与性能相关任务：25,26,27,49。通知与告警相关：15,16,17,18,20,22,29,48。模板与脚本：23,31,44。
