# Traceability Matrix (platform-hardening)

Spec: platform-hardening  Task:24  Scope: 全部需求 (Req1..Req7)

目的: 建立 需求 -> 实施任务 -> 测试/脚本 覆盖的交叉映射，验证无缺口并辅助回归。若未来新增需求/任务/测试，须同步更新本表并保持“无孤儿需求 (无对应任务或测试)”与“无孤儿测试 (测试未指向任何需求)”。

## 汇总表
| Requirement | 标题 (简) | 关联任务 (Task ID: 摘要) | 覆盖测试 / 脚本 | 说明 / 备注 |
|-------------|-----------|--------------------------|-----------------|-------------|
| Req1 | 自适应快照与节流 | 1(接口/事件基座),2(AdaptiveSnapshot),10(Config 热更新),12(README 更新),17(风险+热更集成测),18(性能基准),21(清理重构),22(Rollout 计划), (隐含:1 已含 Req1) | test_adaptive_snapshot.py, test_risk_config_hot_reload.py, (性能: benchmark_adaptive_snapshot.py) | 覆盖节流阈值调整、热更新与文档/上线策略；性能脚本验证吞吐趋势 (非断言测试)。 |
| Req2 | 事件持久化与回放 | 1(接口基座),3(EventPersistenceService),4(ReplayService/CLI),13(CLI stocksimctl replay),15(回放+恢复集成测),18(性能基准 replay),19(EventLog 迁移),12(README),21,22 | test_event_persistence.py, test_replay_recovery_integration.py, (脚本: benchmark_replay.py) | 覆盖写入/批量/失败重试/回放一致性；性能脚本评估重放速度。 |
| Req3 | 卖空 & 借券经济 | 1(接口基座),6(BorrowFeeScheduler),7(ForcedLiquidationService),10(Config 热更新),13(CLI borrow-fee-run),16(集成: 卖空+费用+强平),12,21,22 | test_borrow_fee.py, test_short_borrow_liquidation.py | 涵盖借券费计提、防重复、强平触发及参数热更新。 |
| Req4 | 高精度风险控制 | 1(接口基座),7(强平服务 涉及敞口),8(RiskRuleRegistry+扩展),17(风险+热更),20(诊断文档错误码),12,21,22 | test_risk_rules.py, test_risk_config_hot_reload.py | 包括多规则注册、FOK 预检查、短库存、错误码文档化与热更新影响。 |
| Req5 | 可观测 & 健康 | 1(接口基座),3(持久化失败指标),9(MetricsExporter),10(热更新事件),13(CLI metrics),17(风险&配置观测),20(诊断指标文档),23(指标回归脚本),12,21,22 | test_event_persistence.py, test_risk_config_hot_reload.py, scripts/metrics_sanity_check.py | 指标收集/导出/失败告警；脚本补充回归检查；文档列出全部指标与事件。 |
| Req6 | 恢复与状态重建 | 1(接口基座),5(RecoveryService),13(CLI recover),15(回放+恢复集成),20(错误码/事件文档),12,21,22 | test_recovery.py, test_replay_recovery_integration.py | 覆盖成功/失败/只读模式与一致性校验；集成测试模拟崩溃与重放。 |
| Req7 | RL 融合+向量化 | 11(AccountAdapter+VectorizedEnv),18(向量化性能基准),12(README),21,22 | test_rl_vectorized.py, (脚本: benchmark_vectorized_env.py) | 覆盖真实账户数据接入、批量 step、吞吐验证；性能脚本观测并行加速。 |

## 需求覆盖完整性检查
- 总需求: 7; 上表均出现 => 100% 覆盖。
- 每个需求至少 1 个实现任务 & ≥1 测试/脚本; 均满足。
- 无任务标记的需求: 无。
- 无测试引用的需求: 无 (Req7 性能脚本+功能测试; Req5 有脚本+测试)。

## 测试 / 脚本指向性检查
| 测试 / 脚本 | 关联需求 | 说明 |
|-------------|----------|------|
| test_adaptive_snapshot.py | Req1 | 阈值动态与强制成交快照发布 |
| test_event_persistence.py | Req2, Req5 | 持久化成功/失败与指标增量 |
| test_recovery.py | Req6 | 基础恢复一致性校验 |
| test_replay_recovery_integration.py | Req2, Req6 | 端到端回放+崩溃恢复流 |
| test_borrow_fee.py | Req3 | 借券费用日切/防重复 |
| test_short_borrow_liquidation.py | Req3 | 费用+强平链路 (风险指标侧重另测) |
| test_risk_rules.py | Req4 | 多规则/拒绝路径覆盖 |
| test_risk_config_hot_reload.py | Req4, Req5, Req1 | 热更新对风险与节流/指标影响 |
| test_rl_vectorized.py | Req7 | 并行环境 step 输出一致性 |
| scripts/metrics_sanity_check.py | Req5 | 指标最小集合存在性断言 |
| benchmark_* (3 脚本) | Req1, Req2, Req7 | 性能与吞吐基线 (不做 pass/fail 断言) |

## 潜在后续增强 (非缺口)
1. Req5: 增加针对 MetricsExporter 输出格式(JSON & Prom) 的专门单元测试以锁定序列化结构。
2. Req6: 添加故障注入 (部分缺失事件) 测试以验证 RECOVERY_FAILED 分支。
3. Req3/Req4: 可添加组合测试 (高杠杆 -> 风险拒绝 vs 强平) 以检验优先级。
4. Req7: 增加 RL checkpoint 签名广播 (AgentMetaUpdate) 的显式测试。

## 追溯更新流程
- 新增需求: 添加至 requirements.md -> design.md 中说明 -> tasks.md 创建任务 -> 在本表新增行 -> 编写测试。
- 任务调整/拆分: 更新 tasks.md 与本表任务列，保持需求映射稳定。
- 测试新增/移除: 更新“测试 / 脚本指向性检查”表，确认不引入孤儿测试。
- 发布前 Gate: 所有需求行 “关联任务” 与 “覆盖测试” 不得为空；版本标签附上本文件 SHA。

---
最后更新: {最后更新时间将由提交时间确定}

---

# Traceability Matrix (frontend-trading-ui)
Spec: frontend-trading-ui  Scope: R1..R12 (功能) + NFR (性能/安全/可维护性/可扩展性)

目的: 映射前端规格的业务/非功能需求 → 实施任务(Tasks 文档编号) → 控制器/面板/服务组件 + 测试层级(Unit/Integration/E2E/脚本)。确保无孤儿需求/孤儿测试，并支持回归与影响评估。

## 汇总表 (功能需求 R1-R12)
| Requirement | 标题 (简) | 关联任务 (核心子集) | 控制器 / 面板 / 服务 | 覆盖测试 (示例) | 说明 / 备注 |
|-------------|-----------|---------------------|----------------------|----------------|-------------|
| R1 | 账户面板 | 1,2,3,9,20,24,31,34,35,41,42 | AccountController / AccountPanel / AccountService / ExportButton / Notifications | test_account_panel.py, test_controllers_account_market.py, test_export_service_equity_consistency.py, test_alerts.py, test_notifications.py, test_export_button.py, test_state.py | 实时刷新/分页/阈值告警/导出一致性 (<0.01%) |
| R2 | 行情面板 | 3,4,5,6,7,8,20,25,40,41,42 | MarketController / MarketPanel / MarketDataService / IndicatorRegistry / Executor / EventBridge | test_market_panel.py, test_indicators.py, test_event_bridge.py, test_event_bridge_redis.py, test_controllers_account_market.py, test_utils_tools.py | 批量节流 ≤100ms, 指标计算 ≤150ms, 逐笔滚动 30FPS |
| R3 | 智能体面板 | 1,3,10,21,26,33,34,36,37,41,43 | AgentController / AgentsPanel / AgentService / LogStreamService / RateLimiter | test_agents_panel.py, test_agent_controller_batch.py, test_controllers_agents.py, test_agent_creation_dialog.py, test_rate_limiter.py | 批量仅零售类型 / 心跳高亮 / 日志流 / 控制指令 ≤1s |
| R4 | 排行榜 | 1,11,22,27,31,34,41,42 | LeaderboardController / LeaderboardPanel / LeaderboardService / ExportButton | test_leaderboard_panel.py, test_export_service.py, test_export_button.py | 排序稳定 / Δ 排名 / 导出含元数据 / 800ms 切换窗口 |
| R5 | 时钟 & 回滚 | 2,12,22,28,34,39,41,42 | ClockController / ClockPanel / ClockService / RollbackService | test_clock_panel.py, test_rollback_consistency.py, test_event_flow.py | 启停/暂停/回滚一致性 (净值差异≤0.01%) & 再启动续流 |
| R6 | 设置面板 | 2,16,22,29,33,34,41,44,45* | SettingsController / SettingsPanel / SettingsStore / LayoutPersistence / Shortcuts | test_settings_panel.py, test_settings_store.py, test_shortcuts_accessibility.py, test_panel_registry_main.py | 语言/主题/刷新频率热生效 / 布局持久化 / 告警配置 |
| R7 | 智能体创建 | 10,21,30,34,41,43 | AgentCreationController / AgentCreationDialog / ScriptValidator / AgentService | test_agent_creation_dialog.py, test_script_validator.py | AST 校验 / 模板保存 / 创建 ≤2s 出现 |
| R8 | 参数版本 | 15,21,30,34,41,43 | AgentConfigController / AgentConfigPanel / VersionStore | test_agent_config_panel.py, test_version_store.py | 回滚生成新版本 (rollback_of) / 分页列表 |
| R9 | 脚本安全 | 14,21,30,34,36,41,43 | ScriptValidator / ASTRuleRegistry / RateLimiter / AgentCreationDialog | test_script_validator.py, test_rate_limiter.py | 危险 import 拦截 / 大文件 / 频率限制 |
| R10 | 导出一致性 | 13,22,27,31,34,38,41,42,44 | ExportService / ExportButton / AccountController / LeaderboardController | test_export_service.py, test_export_button.py, test_export_service_equity_consistency.py | snapshot_id 绑定 / 失败无空文件 |
| R11 | 国际化 | 16,17,18,29,32,34,41,44,45* | i18n Loader / SettingsPanel / Formatters / 全部 Panels | test_i18n_loader.py, test_panel_i18n_titles.py, test_formatters.py, test_settings_panel.py | 语言切换 300ms / 金额本地化 / 缺失 key 计数 |
| R12 | 可访问性 | 16,29,33,34,41,44,45* | Shortcuts / 高对比主题变量 / Panels | test_shortcuts_accessibility.py, test_settings_panel.py, test_market_panel.py | 快捷键循环 / 高对比度 / 焦点导航 |

*45: 当前进行中 (E2E i18n & A11y) 尚未全部断言完成；矩阵预留。

## 非功能 (NFR) 追踪摘录
| NFR 类别 | 关键目标 | 关联任务 | 指标/验证 | 覆盖测试/脚本 |
|----------|----------|----------|-----------|---------------|
| 性能 | 行情 P95 合并≤120ms / 指标 ≤150ms / UI 延迟 P95 <250ms | 3,4,5,6,7,20,25,40,42 | metrics: snapshot_batch_latency, indicator_latency_ms, ui_render_latency_ms | scripts/benchmark_frontend_event_flow.py, test_event_bridge.py |
| 可靠性 | Redis 回退 / 回滚一致性 | 4,12,22,28,39 | redis_fallback, rollback_consistency_flag | test_event_bridge_redis.py, test_rollback_consistency.py |
| 可维护性 | 模块分层 & DTO 统一 | 1,2,20-22,23,47,48 | mypy 基线 & 目录结构一致性 | test_dto.py, test_panel_registry_main.py |
| 可扩展性 | 指标/脚本/面板注册表 | 6,14,23,30,32,33 | registry_size(indicators), script_validation_time | test_indicators.py, test_script_validator.py |
| 可观测性 | Metrics & 结构化日志 | 34,40,49* | metrics 输出 & struct.log 关键字段 | test_metrics_adapter.py |
| 安全 | AST + Rate Limit | 14,36 | script_reject_total, rate_limit_triggered | test_script_validator.py, test_rate_limiter.py |

*49: 即将实现 dump_metrics()，本矩阵预留。

## 测试 / 脚本指向性检查
| 测试 / 脚本 | 关联需求 | 说明 |
|-------------|----------|------|
| test_account_panel.py | R1 | 账户刷新/分页/阈值高亮 |
| test_controllers_account_market.py | R1,R2 | 控制器聚合与��照合并 |
| test_market_panel.py | R2,R12 | 行情列表/详情 & 可访问性基础 |
| test_indicators.py | R2,NFR-性能 | 指标计算正确 & 延迟统计 |
| test_event_bridge.py | R1,R2,NFR-性能 | 批量 flush / 节流行为 |
| test_event_bridge_redis.py | R2,NFR-可靠性 | Redis 断线回退 |
| test_agents_panel.py | R3 | 列表/控制/心跳高亮 |
| test_agent_controller_batch.py | R3 | 批量零售限制 & 进度 |
| test_agent_creation_dialog.py | R3,R7 | 创建流程 / 表单默认值 |
| test_agent_config_panel.py | R8 | 版本列表 / 回滚逻辑 |
| test_agent_creation_dialog.py | R7,R9 | AST 触发/错误提示 |
| test_script_validator.py | R7,R9 | 白名单/危险导入/大小限制 |
| test_rate_limiter.py | R9 | 上传频率限制触发 |
| test_leaderboard_panel.py | R4 | 排名/排序/窗口切换 |
| test_export_service.py | R4,R10 | 排行榜导出含元信息 |
| test_export_button.py | R1,R4,R10 | snapshot_id 绑定/顺序一致 |
| test_export_service_equity_consistency.py | R1,R10 | 账户��值一致性 <0.01% |
| test_clock_panel.py | R5 | 启停/暂停/状态切换 |
| test_rollback_consistency.py | R5 | 回滚一致性校验 |
| test_settings_panel.py | R6,R11 | 语言/主题/刷新频率生效 |
| test_settings_store.py | R6 | 持久化与读取 |
| test_shortcuts_accessibility.py | R12 | 全局快捷键循环与焦点 |
| test_panel_registry_main.py | R11,R12,NFR-可维护性 | 面板注册与标题 i18n |
| test_i18n_loader.py | R11 | 翻译缺失计数 |
| test_panel_i18n_titles.py | R11 | 标题 key 全覆盖 |
| test_formatters.py | R11 | 数字/金额本地化 |
| test_alerts.py | R1,R6 | 资金/心跳阈值去抖 |
| test_notifications.py | R1,R3,R5,R7,R9,R10 | 统一通知组件多类型 |
| test_version_store.py | R8 | 版本链 & rollback_of |
| test_metrics_adapter.py | NFR-可观测性 | 指标记录正确 |
| test_utils_tools.py | R2 | RingBuffer/节流工具 |
| test_state.py | R1,R6 | AppState/SettingsState 更新 |
| test_dto.py | R1-R5,R7-R10 | DTO 结构与序列化 |
| test_export_service_equity_consistency.py | R1,R10 | 导出净值一致性重复标注 |
| test_shortcuts_accessibility.py | R12 | (重复) 可访问性主���盖 |
| tests/frontend/integration/test_event_flow.py | R1-R5,R10 | 事件流端到端延迟 |
| tests/frontend/integration/test_agents_flow.py | R3,R7,R8,R9 | 批量/版本/脚本上传链路 |
| tests/frontend/e2e/test_full_journey.py | R1-R12 | 完整用户旅程 |
| tests/frontend/e2e/test_i18n_accessibility.py* | R6,R11,R12 | 语言/主题/快捷键 (进行中) |
| scripts/benchmark_frontend_event_flow.py | NFR-性能 | 延迟与吞吐统计 (无断言) |

* 进行中或待完善测试：对可访问性 (Tab 顺序) 与主题对比度阈值后续补充断言。

## 覆盖完整性检查
- 功能需求 (R1-R12) 均出现在汇总表且有 ≥1 任务 + ≥1 测试。
- 非功能目标均有至少 1 个指标或脚本/测试支撑；dump_metrics() (Task49) 预留。
- 无孤儿测试：所有列出的测试均映射 ≥1 需求或 NFR。
- 进行中项：E2E i18n & A11y (Task45) 尚需补充对高对比度比值与 Tab 顺序断言。

## 潜在后续增强 (非缺口)
1. R2: 增加虚拟列表 (大于 500 symbols) 性能测试脚本。
2. R11: CI 钩子增加未翻译 key 阈值 fail 条件。
3. R12: 自动化对比度检测 (截图 + 采样) 工具脚本。
4. NFR-可靠性: 注入 Redis 闪断抖动场景扩展测试。
5. 导出流程: 增加错误注入 (IO 失败) 测试验证“无空文件”分支。

## 追溯更新流程 (前端)
- 新需求: 更新 requirements/design → 新建任务 → 本表新增行。
- 任务变更: 同步 tasks.md 与“关联任务”列，保持需求指向最新实现。
- 新测试: 添加到“测试指向性”表，若未对齐需求需创建/标注需求或删除测试。
- 发布前 Gate: R1-R12 行均满足 “关联任务不为空 & 覆盖测试不为空”。

最后更新: {提交时间自动记录}

## 新增指标（Spec: frontend-enhancements-bugfixes）
为加强端到端可观测性，新增以下不影响热路径的轻量级指标（命名遵循现有规范，均写入内存聚合，必要时由 exporter 统一导出）：

- ui_refresh_latency_ms
  - 含义：事件到 UI 刷新的延迟（ms，P95 用于观察 UI 端可见性）。
  - 产生方：app/ui/adapters/agents_adapter.py 在节流执行 _do_refresh 前记录。
  - 使用：NFR-性能 观察 UI P95 延迟（目标 < 250ms）。
- agent_create_success / agent_create_failed
  - 含义：批量创建智能体的成功与失败计数（可用 success/(success+failed) 计算成功率）。
  - 产生方：app/controllers/agent_creation_controller.py 在分块完成回调 _on_chunk_done。
  - 使用：R7/R3 质量回归与 CI 指标看板，验证创建质量与异常占比。
- language_switch_ms
  - 含义：语言切换耗时（ms），记录 SettingsPanel.set_language 实际调用耗时。
  - 产生方：app/panels/settings/panel.py set_language。
  - 使用：B1 体验监控（目标：切换≤1s，警戒>300ms）。

验证与采集：
- 本地脚本 scripts/metrics_smoke_new_indicators.py 可在无 GUI 环境触发上述三类指标并输出示例统计（见脚本内说明）。
- 指标导出沿用现有 MetricsAdapter/Exporter，不做热路径 IO；单次 add_timing/inc 为常数时间与低锁开销。

最后更新：{由提交时间确定}
