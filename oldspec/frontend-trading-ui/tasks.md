# Tasks Document

说明：以下任务基于已批准 requirements (R1~R12) 与 design(修订版)。任务粒度控制在 1~3 文件改动；每条列出：文件/目录、目的、复用、覆盖需求、完成判定。执行阶段需严格按依赖顺序推进。若未特别说明，所有新代码置于 app/ 目录内。

## 约定
- DTO 放 app/core_dto/
- 控制器放 app/controllers/
- 面板放 app/panels/<panel_name>/
- 服务与适配层放 app/services/
- 注册表/工具放 app/utils/ 或专属子目录
- 安全校验放 app/security/
- 状态与存储放 app/state/
- 指标放 app/indicators/
- i18n 放 app/i18n/
- 测试放 tests/frontend/

---

- [x] 1. 创建核心 DTO 定义
  - Files: app/core_dto/account.py, snapshot.py, trade.py, agent.py, leaderboard.py, clock.py, versioning.py
  - Purpose: 定义 AccountDTO / PositionDTO / SnapshotDTO / TradeDTO / AgentMetaDTO / LeaderboardRowDTO / ClockStateDTO / AgentVersionDTO (与 design 一致)
  - Reuse: 后端事件字段 (README 第27节), design Data Models
  - Requirements: R1,R2,R3,R4,R5,R7,R8,R10
  - Done: mypy 通过 + 单元测试序列化通过

- [x] 2. 建立全局 AppState 与 SettingsState
  - Files: app/state/app_state.py, settings_state.py
  - Purpose: 维护当前账户/语言/主题/时钟/指标缓存 key 等；SettingsState 支持持久化加载
  - Requirements: R1,R2,R5,R6,R11
  - Done: 初始化/更新事件测试通过

- [x] 3. 事件桥基础骨架
  - Files: app/event_bridge.py
  - Purpose: 建立 EventBridge 类 (start/stop/on_event + 队列 + 定时 flush + Qt Signal 占位)
  - Reuse: infra/event_bus.EventBus
  - Requirements: R1,R2,R3,R4,R5 (低延迟刷新)
  - Done: 单元测试模拟 50 条 snapshot 合并批量输出 ≤2 flush

- [x] 4. EventBridge Redis 订阅与回退
  - Files: app/event_bridge.py (增量), app/services/redis_subscriber.py
  - Purpose: 支持 REDIS_ENABLED 时订阅频道，断线回退本地 EventBus
  - Requirements: R2,R3,R4,R5 性能与可靠性
  - Done: 集成测试模拟断线 fallback 标记 metrics.redis_fallback++

- [x] 5. Throttle & RingBuffer 工具
  - Files: app/utils/throttle.py, ring_buffer.py
  - Purpose: snapshot 批量节流 + 逐笔滚动窗口结构
  - Requirements: R2 性能, R1 稳定
  - Done: 单测吞吐 & 丢弃策略计数正确

- [x] 6. IndicatorRegistry & 基础指标
  - Files: app/indicators/registry.py, ma.py, macd.py, rsi.py
  - Purpose: 注册表 + calc 接口 + 结果缓存 key 生成
  - Requirements: R2 指标, 性能要求
  - Done: 单测 3 指标输出 shape 正确

- [x] 7. 指标线程池执行器
  - Files: app/indicators/executor.py
  - Purpose: QThreadPool/或 concurrent.futures 适配提交 + 主线程回调
  - Requirements: R2,R2 AC4 延迟≤150ms
  - Done: 模拟 5 symbols * 3 指标 计算并发 ≤ 200ms

- [x] 8. MarketDataService & BarsCache
  - Files: app/services/market_data_service.py, bars_cache.py
  - Purpose: 行情细节拉取、K线/分时缓存、detail 请求
  - Requirements: R2 AC2/3/4/5
  - Done: 集成测试 detail 请求 1s 内返回首帧

- [x] 9. AccountService 前端适配
  - Files: app/services/account_service.py
  - Purpose: 拉取账户/持仓 + 一致性校验(差异>0.5% 报警)
  - Requirements: R1 AC1/2/3
  - Done: Mock 后端差异检出测试

- [x] 10. AgentService & LogStreamService
  - Files: app/services/agent_service.py, log_stream_service.py
  - Purpose: 列表/控制/批量创建(仅零售)/日志分页拉取
  - Requirements: R3 AC1/2/3/4 + 批量限制修订
  - Done: 业务错误 AGENT_BATCH_UNSUPPORTED 单测

- [x] 11. LeaderboardService 适配
  - Files: app/services/leaderboard_service.py
  - Purpose: 时间窗口参数构造、指标拉取、缓存命中统计
  - Requirements: R4 AC1/2/3/4/5/6
  - Done: 排序稳定性 & rank_delta 计算单测

- [x] 12. ClockService & RollbackService 接口层
  - Files: app/services/clock_service.py, rollback_service.py
  - Purpose: 启停/暂停/加载 simday + 回滚一致性校验
  - Requirements: R5 AC1/2/3/4/5/6
  - Done: 回滚失败回退测试

- [x] 13. ExportService
  - Files: app/services/export_service.py
  - Purpose: 导出 CSV/Excel (依赖 pandas 可选) + snapshot_id 绑定
  - Requirements: R10 AC1/2/3/4
  - Done: 单测生成文件含元数据行

- [x] 14. ScriptValidator + ASTRuleRegistry
  - Files: app/security/ast_rules.py, script_validator.py
  - Purpose: AST 解析 + 白名单 import + 禁止危险属性
  - Requirements: R7 AC2/3, R9 全部
  - Done: 危险 import 拦截 & 大文件拒绝测试

- [x] 15. VersionStore
  - Files: app/state/version_store.py
  - Purpose: JSON 持久化智能体参数版本链 (rollback_of 支持)
  - Requirements: R8 AC2/3/4/5/6
  - Done: 回滚生成 v+1 单测

- [x] 16. SettingsStore & LayoutPersistence
  - Files: app/state/settings_store.py, layout_persistence.py
  - Purpose: 语言/主题/刷新频率/告警阈值/布局 JSON 持久化
  - Requirements: R6 AC1/2/3/4/5/6, R11
  - Done: 切换语言触发回调测试

- [x] 17. 国际化加载器
  - Files: app/i18n/loader.py, zh_CN.json, en_US.json (示例键)
  - Purpose: lazy 翻译函数 + missing key 计数
  - Requirements: R11 AC1/2, R6 AC1
  - Done: 缺失 key 记录 metrics.i18n_missing++

- [x] 18. 通用格式化与本地化工具
  - Files: app/utils/formatters.py
  - Purpose: 金额/数字/日期本地化输出
  - Requirements: R11 AC2, R1 汇总展示
  - Done: 单测千分位/精度可配置

- [x] 19. 告警与通知去抖
  - Files: app/utils/alerts.py
  - Purpose: 资金/回撤/心跳阈值监控 + 60s 去抖
  - Requirements: R6 AC6, R3 AC7
  - Done: 时间窗口内多次触发仅一次通知

- [x] 20. Controllers 实现 (AccountController/MarketController)
  - Files: app/controllers/account_controller.py, market_controller.py
  - Purpose: 合并增量/分页/过滤/指标请求
  - Requirements: R1,R2
  - Done: 行情 1000 snapshot/s 压测 P95 合并帧 ≤120ms

- [x] 21. Controllers (AgentController/AgentConfigController/AgentCreationController)
  - Files: app/controllers/agent_controller.py, agent_config_controller.py, agent_creation_controller.py
  - Purpose: 列表/控制/批量(零售)/日志/版本/热更新/回滚/脚本校验
  - Requirements: R3,R7,R8,R9
  - Done: 批量非零售拒绝测试通过

- [x] 22. Controllers (LeaderboardController, ClockController, SettingsController)
  - Files: app/controllers/leaderboard_controller.py, clock_controller.py, settings_controller.py
  - Purpose: 排名刷新/Δ 排名/导出；时钟启停读档；设置热更新
  - Requirements: R4,R5,R6,R10
  - Done: 回滚后再次启动事件继续流

- [x] 23. MainWindow & Panel 注册机制
  - Files: app/main.py, app/panels/__init__.py, app/panels/registry.py
  - Purpose: register_panel(name, factory, lifecycle hooks)
  - Requirements: 基础支撑全部 (R1-R12)
  - Done: 启动无异常 + 面板懒加载成功

- [x] 24. AccountPanel
  - Files: app/panels/account/panel.py (+ 子组件)
  - Purpose: 资金/持仓/分页/过滤/阈值高亮
  - Requirements: R1
  - Done: 切换账户 300ms 内渲染

- [x] 25. MarketPanel & SymbolDetailPanel
  - Files: app/panels/market/panel.py, symbol_detail.py
  - Purpose: 自选列表/双击详情/K线/盘口/L2/逐笔滚动
  - Requirements: R2
  - Done: 逐笔窗口 5000 行保持 ≥30FPS

- [x] 26. AgentsPanel
  - Files: app/panels/agents/panel.py
  - Purpose: 列表/控制按钮/批量创建(零售)/心跳高亮
  - Requirements: R3 (修订批量限制)
  - Done: Batch 进度显示 & 心跳超时高亮

- [x] 27. LeaderboardPanel
  - Files: app/panels/leaderboard/panel.py
  - Purpose: 排序/窗口切换/收益&回撤曲线/导出
  - Requirements: R4,R10
  - Done: 窗口切换 800ms 内完成

- [x] 28. ClockPanel (启停读档)
  - Files: app/panels/clock/panel.py
  - Purpose: 启动/暂停/停止/读档选择 simday & 进度
  - Requirements: R5
  - Done: 回滚后 equity 差异 ≤0.01%

- [x] 29. SettingsPanel
  - Files: app/panels/settings/panel.py
  - Purpose: 语言/主题/刷新频率/告警阈值/布局/倍速
  - Requirements: R6,R11
  - Done: 语言切换 300ms 内生效

- [x] 30. AgentConfigPanel & AgentCreationDialog
  - Files: app/panels/agent_config/panel.py, app/panels/agent_creation/dialog.py
  - Purpose: 参数列表/热更新/版本回滚/脚本上传
  - Requirements: R7,R8,R9
  - Done: 回滚生成新版本号 & AST 校验失败阻断

- [x] 31. 导出统一按钮与快照绑定
  - Files: app/panels/shared/export_button.py
  - Purpose: 封装 ExportService 调用 + snapshot_id 注入
  - Requirements: R10
  - Done: 导出内容顺序与当前表一致

- [x] 32. 国际化接入所有面板
  - Files: 修改各 panel.py 加载翻译 keys
  - Purpose: 文本全部走 i18n loader
  - Requirements: R11
  - Done: 统计缺失 key=0 (初始)

- [x] 33. 可访问性 & 快捷键
  - Files: app/utils/shortcuts.py, 面板增量
  - Purpose: 全局面板切换/表格键盘滚动/高对比主题变量
  - Requirements: R12 AC1/2/3/4
  - Done: 快捷键循环切换面板测试

- [x] 34. Metrics & Structured Logging 集成
  - Files: app/utils/metrics_adapter.py, 日志注入 main.py
  - Purpose: 记录渲染延迟/丢弃事件/指标计算耗时/缺失翻译等
  - Requirements: 非功能 Observability, R1-R12 追踪
  - Done: 关键指标数值 >0 时输出到 struct.log

- [x] 35. 错误与告警 UI 统一组件
  - Files: app/panels/shared/notifications.py
  - Purpose: toast/对话框/高亮统一
  - Requirements: R1,R3,R5,R6,R7,R9,R10
  - Done: 模拟 5 类错误均正常展示

- [x] 36. 安全脚本节流 & 上传频率限制
  - Files: app/security/rate_limiter.py (整合脚本验证)
  - Purpose: 每策略名 1h >3 次拒绝
  - Requirements: R9 AC4
  - Done: 单测触发节流

- [x] 37. 批量创建智能体权限/类型校验
  - Files: agent_controller.py (增量)
  - Purpose: 限定 Retail/MultiStrategyRetail
  - Requirements: 设计修订范围
  - Done: 测试对 PPO 类型返回错误

- [x] 38. 导出数据一致性 snapshot_id 绑定实现
  - Files: export_service.py (增量)
  - Purpose: 同一次导出统一 snapshot_id 深拷贝
  - Requirements: R10 AC1/2/3
  - Done: 测试账户与导出净值差异 <0.01%

- [x] 39. 回滚一致性校验逻辑
  - Files: rollback_service.py (增量)
  - Purpose: 回滚后账户/持仓/智能体状态对比基准
  - Requirements: R5 AC3/4
  - Done: 不一致触发恢复与提示

- [x] 40. 性能基准脚本 (前端)
  - Files: scripts/benchmark_frontend_event_flow.py
  - Purpose: 模拟 1000 snapshot/s + 账户/代理事件混合衡量延迟
  - Requirements: 性能 NFR
  - Done: 输出延迟统计并写日志

- [x] 41. 单元测试集合 (DTO/工具/指标/安全/控制器)
  - Files: tests/frontend/unit/test_*.py
  - Purpose: 覆盖核心纯逻辑
  - Requirements: 全部功能基础
  - Done: 覆盖率报告≥目标(后续设阈值)

- [x] 42. 集成测试：事件流 → 控制器 → 面板 mock
  - Files: tests/frontend/integration/test_event_flow.py
  - Purpose: 验证账户/行情/排行榜/回滚链路
  - Requirements: R1-R5,R10
  - Done: P95 UI 延迟 <250ms (mock 时间)

- [x] 43. 集成测试：批量零售/版本回滚/脚本上传
  - Files: tests/frontend/integration/test_agents_flow.py
  - Purpose: 覆盖 R3,R7,R8,R9
  - Done: 全流程成功 & 错误场景覆盖

- [x] 44. E2E 测试：多面板用户旅程
  - Files: tests/frontend/e2e/test_full_journey.py
  - Purpose: 启动→创建零售批量→指标开关→回滚→导出
  - Requirements: 全部
  - Done: 断言关键 UI 状态

- [x] 45. E2E 测试：语言/主题切换 & 可访问性
  - Files: tests/frontend/e2e/test_i18n_accessibility.py
  - Purpose: R6,R11,R12
  - Done: 快捷键 & 语言切换断言

- [x] 46. 打包与启动脚本
  - Files: app/__init__.py, setup_frontend_entry.py (或 main.py 增量)
  - Purpose: 统一入口 run_frontend() 便于后续 PyInstaller
  - Requirements: 部署可运行
  - Done: 手动运行展示主窗口

- [x] 47. 文档补充 (开发指南 + 面板注册说明)
  - Files: docs/frontend_dev_guide.md
  - Purpose: 便于新贡献者快速上手
  - Requirements: 可维护性 NFR
  - Done: 包含架构图/扩展步骤/测试说明

- [x] 48. 追踪矩阵更新
  - Files: docs/traceability_matrix.md (增量章节 FE)
  - Purpose: 映射 R1-R12 → 控制器/面板/测试
  - Requirements: 可追踪性
  - Done: 表格生成

- [x] 49. Metrics 仪表补充导出
  - Files: app/utils/metrics_adapter.py (增量)
  - Purpose: 增加 dump_metrics() 供后期可视化
  - Requirements: Observability
  - Done: 调用返回 JSON

- [x] 50. 风险 & 未来 Hook 占位注释
  - Files: 各 controller 顶部 docstring
  - Purpose: 标注未来 RL stats / Kafka hook TODO
  - Requirements: 设计未来扩展
  - Done: docstring 含 TODO

---
依赖顺序指引 (概括)：1-2 → 3-5 → 6-8 → 9-19 (服务+工具) → 20-22 (控制器) → 23 (主窗口注册) → 24-31 (面板) → 32-38 (横切特性) → 39-40 (一致性/性能) → 41-45 (测试) → 46-50 (打包与文档)。

质量门槛：
- mypy 基线通过 (新增模块 type hints ≥95% 定义)
- 单元+集成+E2E 三层测试
- P95 事件到渲染延迟 <250ms (Mock 及基准脚本)
- 批量创建仅零售类型约束覆盖
- 导出数据净值差异 <0.01%

完成判定：全部复选框勾选 + 追踪矩阵更新 + 性能基准脚本输出合格。
