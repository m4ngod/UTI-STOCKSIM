# Tasks Document

- [x] T1 创建“新标的”对话框（R1-UI）
  - Files: app/panels/market/dialog.py (新增)、app/ui/notifications.py���复用）
  - 内容：新增 CreateInstrumentDialog，包含名称/代码/初始价格/总股本/流通股/市值；任意两项推导第三项（就地校验与错误提示）。
  - 目的：完成前端表单与推导逻辑，提交时调用控制器。
  - _Leverage: app/panels/agent_creation/dialog.py, app/ui/utils/formatters.py_
  - _Requirements: R1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 前端工程师（Qt/桌面UI） | Task: 在 app/panels/market/dialog.py 实现 CreateInstrumentDialog，含输入校验与三元推导；错误就地提示；提交调用控制器 | Restrictions: 不直接触服务层；严格沿用现有面板/对话框风格与i18n | _Leverage: app/panels/agent_creation/dialog.py, app/ui/utils/formatters.py | _Requirements: R1 | Success: 对话框可交互、两项输入可推导第三项、无阻塞错误、提交触发控制器调用_

- [x] T2 市场控制器新增创建标的（R1-Controller）
  - Files: app/controllers/market_controller.py（增量）
  - 内容：新增 create_instrument(name, symbol, price, float_shares, market_cap, total_shares)；参数校验、错误转换、事件广播 instrument-created。
  - 目的：统一标的创建入口，串联服务与事件。
  - _Leverage: app/services/market_data_service.py, app/event_bridge.py_
  - _Requirements: R1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 控制器工程师 | Task: 在 market_controller.py 实现 create_instrument，调用服务创建并通过 event_bridge 广播 instrument-created | Restrictions: 不做UI逻辑；参数必须再次校验与日志记录 | _Leverage: app/services/market_data_service.py, app/event_bridge.py | _Requirements: R1 | Success: 创建成功后列表可见且事件可被订阅方接收；失败路径有明确信息_

- [x] T3 推导��校验工具（R1-Utils）
  - Files: app/utils/validators.py（新增）
  - 内容：safe_float, safe_int, round_to_price_step, derive_third_value(flow_shares, mcap, price)。
  - 目的：提取通用推导与校验，供对话框与控制器复用。
  - _Leverage: app/utils/formatters.py_
  - _Requirements: R1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 平台工具工程师 | Task: 新增 validators.py，提供数值解析、价格步长取整与三元推导工具 | Restrictions: 纯函数������������含类��注解���边界处理、单元测���友好 | _Leverage: app/utils/formatters.py | _Requirements: R1 | Success: 工具函数覆盖边界用例并被 T1/T2 复用_

- [x] T4 批量创建散户弹窗（R2-UI）
  - Files: app/panels/agent_creation/dialog.py（增量）
  - 内容：新增批量创建入口：数量N(1-1000)、初始资金、初始策略、可选seed；显示进度与可取消按钮。
  - 目的：一次性批量创建多策略散户并提供过程�����。
  - _Leverage: 现有单个创建流程、app/ui/notifications.py_
  - _Requirements: R2_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 前端工程师 | Task: 在 agent_creation/dialog.py 增加批量创建UI与进度/取��� | Restrictions: 进���UI非阻塞；遵循既有样式；错误集中显示 | _Leverage: 现有创建逻辑, app/ui/notifications.py | _Requirements: R2 | Success: 可配置参数并启动批量创建，实时进度可见，可取消_

- [x] T5 控制器批量创建与取消（R2-Controller）
  - Files: app/controllers/agent_creation_controller.py（增量）
  - 内容：新增 batch_create_multi_strategy(count, capital, strategy, seed?) → progress stream；支持取消信号；汇总成功/失败计数。
  - 目的：承接 UI，串服务与事件，控制并发度。
  - _Leverage: app/services/agent_service.py, app/event_bridge.py_
  - _Requirements: R2, R3_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 控制器工程师 | Task: 在 agent_creation_controller 增加批量创建能力与取消；暴露进度回调/事件 | Restrictions: 控制并发、保证幂等、错误聚合 | _Leverage: app/services/agent_service.py, app/event_bridge.py | _Requirements: R2,R3 | Success: 大批量创建可完成且有明确统计，取消后及时停止_

- [x] T6 列表适配器刷新（R2+B2-Adapter）
  - Files: app/ui/adapters/agents_adapter.py（增量）
  - 内容：订阅 agent-status-changed 与 创建结果事件；在无事���情���下退避轮询（默认2s, 指数退避）；刷新列表与排行榜。
  - 目的：确保 UI 与后端状态一致，覆盖事件与无事件两种路径。
  - _Leverage: app/ui/adapters/base_adapter.py（若有）, app/services/leaderboard_service.py_
  - _Requirements: R2, B2_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 前端适配器工程师 | Task: 在 agents_adapter 中集成事件订阅与兜底轮询，刷新UI | Restrictions: 避免过度刷新；加入节流/去抖 | _Leverage: leaderboard_service, 现有事件桥 | _Requirements: R2,B2 | Success: 状态变化≤500ms可见；无事件时轮询生效_

- [x] T7 统一配置/蒸馏接口（R3-Controller）
  - Files: app/controllers/agent_controller.py（增量）
  - 内容：新增 configure(agent_id, payload), distill(agent_id, payload)；返回任务ID/状态与错误。
  - 目的：统一控制入口，减少前端多处分支。
  - _Leverage: app/services/agent_service.py, app/services/metrics_exporter.py_
  - _Requirements: R3_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 控制器工程师 | Task: 在 agent_controller.py ��现 configure/distill 统一接口与日志 | Restrictions: 不引入UI依赖；保持函数纯粹与可测 | _Leverage: agent_service.py, metrics_exporter.py | _Requirements: R3 | Success: API 契约稳定，调用链清晰，失败有可读错误_

- [x] T8 i18n 实时切换与持久化（B1）
  - Files: app/i18n/loader.py（增量）, app/state/settings_store.py（增量）
  - 内容：提供 reload(locale) 与 get_current_locale；settings_store 持久化语言偏好并启动时优先加载。
  - 目的：切换语言即时生效且重启后保持。
  - _Leverage: app/ui/i18n_bind.py, app/ui/main_window.py, app/state/version_store.py_
  - _Requirements: B1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 国际化工程师 | Task: 在 loader 与 settings_store 中补齐 reload 与持久化；启动时应用偏好 | Restrictions: 不阻塞UI线��；失败回退到默认语言 | _Leverage: i18n_bind, settings_store 现有模式 | _Requirements: B1 | Success: 切换≤1s全局生效，重启后语言保持_

- [x] T9 Settings 控制器注入语言切换（B1-Controller）
  - Files: app/controllers/settings_controller.py（增量）
  - 内容：新��� set_language(locale)：settings_store.persist → i18n.reload → panels refresh。
  - 目的：在控制器层统一落地语言切换流程。
  - _Leverage: app/panels/shared/registry.py, app/ui/i18n_bind.py_
  - _Requirements: B1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 控制器工程师 | Task: 在 settings_controller 增加 set_language 并驱动全局刷新 | Restrictions: 面板刷新需最小范围触发；避免闪烁 | _Leverage: panels registry, i18n_bind | _Requirements: B1 | Success: 切换语言后所有面板标题/菜单即时更新_

- [x] T10 事件驱动与兜底轮询（B2-Infra/UI）
  - Files: app/event_bridge.py（增量）, app/ui/adapters/agents_adapter.py（同 T6）
  - 内容：在 event_bridge 中注册 agent-status-changed/instrument-created 订阅帮助方法；在 adapter 端实现回退轮询调度与退����策略。
  - 目��：统一事件接入点并在 UI 层可复用。
  - _Leverage: app/services/log_stream_service.py, app/utils/throttle.py_
  - _Requirements: B2_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 前端基础设施工程师 | Task: 扩展 event_bridge 与 adapter 的事件/轮询机制 | Restrictions: ���件监听需可取消；避免内存泄漏 | _Leverage: log_stream_service, throttle | _Requirements: B2 | Success: 事件路径稳定；无事件时轮询可靠且可停止_

- [x] T11 单元测试：推导、语言、控制器（R1/B1/R2）
  - Files: tests/frontend/unit/test_create_instrument_dialog.py（新增）, tests/frontend/unit/test_i18n_loader_reload.py（新增）, tests/frontend/unit/test_agent_creation_controller_batch.py（新增）
  - 内容：覆盖三元推导边界；i18n reload 成功/失败与回退；批量创建并发/取消与统计。
  - 目的：关键逻辑单测保障。
  - _Leverage: tests/conftest.py, 既有fixtures_
  - _Requirements: R1, B1, R2_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: QA 工程师 | Task: 补充上述单测覆盖关键边界与失败路径 | Restrictions: 保持测试独�����稳定；���免真实外部依赖 | _Leverage: 现有fixtures与工具 | _Requirements: R1,B1,R2 | Success: 单测通过且覆盖新增关键路径_

- [x] T12 集成测试：状态刷新与批量创建（R2/B2）
  - Files: tests/frontend/integration/test_agent_status_refresh.py（新增）, tests/frontend/integration/test_batch_create_agents.py（新增）
  - ���容：模��事件/���到���件；���证≤500ms ��新；验证进度/取消与列表/排行榜刷新。
  - 目的：端到端验证事件与兜底一致性。
  - _Leverage: tests/frontend/integration/ 现有测试模式_
  - _Requirements: R2, B2_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 集成测试工程师 | Task: 编写集成用例覆盖事件与轮询两路径 | Restrictions: 控制时间依赖；使用假时钟/定时器桩 | _Leverage: 现有集成测试基建 | _Requirements: R2,B2 | Success: 用例稳��通过并��在CI运行_

- [x] T13 端到端测试：创建标的与批量散户（R1/R2/B1）
  - Files: tests/frontend/e2e/test_create_instrument_and_batch_agents.py（新增）
  - 内容：用户路径：创建标的→加入关注→批量创建散户→列表与排行榜可见→切换语言生效。
  - 目的：验证主路径体验。
  - _Leverage: tests/frontend/e2e 既有脚手架_
  - _Requirements: R1, R2, B1_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: E2E 自动化工程师 | Task: 编写端到端脚本覆盖核心用户旅程 | Restrictions: 使用稳定选择器；避免易碎等待；提供截图/日志 | _Leverage: 现有E2E脚手架 | _Requirements: R1,R2,B1 | Success: 脚本在CI稳定运行并产出报告_

- [x] T14 文档与指标埋点（横切）
  - Files: docs/traceability_matrix.md（增量）, observability/metrics.py（增量）
  - 内容：在可追溯矩阵关联 R1/R2/R3/B1/B2 的测试/用例；新增指标：状态刷新延迟P95、创建成功率、语言切换耗时。
  - 目的：增强可观察性与可追溯性。
  - _Leverage: docs/rollout_plan.md, observability/performance_monitor.py_
  - _Requirements: All_
  - _Prompt: Implement the task for spec frontend-enhancements-bugfixes, first run spec-workflow-guide to get the workflow guide then implement the task: Role: 文档与可观测性工程师 | Task: 补充可追溯矩阵并埋点性能指标 | Restrictions: 不影响热路径性能；指标命名遵循现有规范 | _Leverage: performance_monitor.py | _Requirements: All | Success: 文档更新并提交；新指标可在本地验证采集_


备注：
- 开始执行任一任务前，请在本文件将相应条目由 [ ] 改为 [-]；完成后改为 [x] 并提交。
- 任务应尽量保证单任务改动文件不超过 3 个，必要时拆分。
