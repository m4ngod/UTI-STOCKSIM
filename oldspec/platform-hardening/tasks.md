# Tasks Document

(标记说明: Req#=需求编号, Comp#=组件)

- [x] 1. 建立核心接口与事件类型扩展 (Req1/Req2/Req4/Req6 综合)
  - File: infra/interfaces.py (新增)
  - 内容: 定义 IEventSink, IReplaySource, IRiskRule, IRecoveryStrategy, IConfigHotReloadListener
  - 扩展 core/const.py: 新增事件类型 SNAPSHOT_POLICY_CHANGED, PERSISTENCE_DEGRADED, RECOVERY_FAILED, RECOVERY_RESUMED, RISK_RESET, BORROW_FEE_ACCRUED, LIQUIDATION_TRIGGERED, CONFIG_CHANGED
  - 目的: 统一后续模块依赖契约
  - Requirements: 1,2,3,4,5,6

- [x] 2. AdaptiveSnapshotPolicyManager 实现 (Req1)
  - File: services/adaptive_snapshot_service.py (新增)
  - 内容: 类 + 每 symbol 速率统计 (滑动窗口 deque timestamp), 动态阈值计算, maybe_adjust 发布事件
  - 在 MatchingEngine 中添加可选 hook 注入 (minimal: 若文件 core/matching_engine.py 存在 add_adaptive_policy_manager 方法)
  - Requirements: 1

- [x] 3. EventPersistenceService 与 ORM (Req2/Req5)
  - File: persistence/models_event_log.py (新增)
  - File: services/event_persistence_service.py (新增)
  - 修改 persistence/models_init.py 引入新模型
  - 内容: event_log 表模型 + 批量 flush (队列 + 封顶 256) + 重试逻辑
  - Requirements: 2,5

- [x] 4. Replay 工具与服务 (Req2)
  - File: services/replay_service.py (新增)
  - File: scripts/replay.py (新增 CLI)
  - 功能: load_events(start,end)->yield, dry-run 重建簿与账户, 输出报告
  - Requirements: 2

- [x] 5. RecoveryService (Req6)
  - File: services/recovery_service.py (新增)
  - 内容: recover() 读取 orders/positions/snapshots；缺失时使用事件回放；校验一致性；失败发布 RECOVERY_FAILED
  - Requirements: 6

- [x] 6. 借券费用计提 BorrowFeeScheduler (Req3)
  - File: services/borrow_fee_scheduler.py (新增)
  - 修改 services/account_service.py 增加调用 hook (日切或手动 run)
  - Ledger: 使用 extra_json.kind='BORROW_FEE'
  - Requirements: 3

- [x] 7. 强平 ForcedLiquidationService (Req3/Req4)
  - File: services/forced_liquidation_service.py (新增)
  - 内容: evaluate_accounts()->生成强平订单列表；提交 OrderService
  - Requirements: 3,4

- [x] 8. RiskRuleRegistry + 扩展 RiskEngine (Req4)
  - File: services/risk_rule_registry.py (新增)
  - 修改 services/risk_engine.py：支持 register(rule) & evaluate 聚合返回
  - 添加示例规则: MaxGrossExposureRule, FOKPreCheckRule, ShortInventoryRule
  - Requirements: 4

- [x] 9. MetricsExporter (Req5)
  - File: services/metrics_exporter.py (新增)
  - 暴露接口 collect()->str；整合 observability/metrics.py
  - 指标: order_latency_hist, event_queue_size, persistence_failures_total, snapshot_threshold, risk_reject_total, crash_counter
  - Requirements: 5

- [x] 10. ConfigHotReloader (Req1/Req3/Req5)
  - File: services/config_hot_reload.py (新增)
  - 内容: apply(patch)->validate->更新 settings 子集->发布 CONFIG_CHANGED
  - Requirements: 1,3,5

- [x] 11. RL AccountAdapter + VectorizedEnvWrapper (Req7)
  - File: rl/account_adapter.py (新增)
  - File: rl/vectorized_env.py (新增)
  - 修改 rl/trading_env.py 接口以支持注入 adapter & vectorized wrapper
  - Requirements: 7

- [x] 12. 更新 README 章节 (自适应节流 / 事件持久化 / 恢复 / 借券费率 / 风险扩展 / RL 向量化) (所有)
  - File: README.md (修改)
  - Requirements: 1..7

- [x] 13. CLI 工具 stocksimctl (Req2/Req5/Req6)
  - File: scripts/stocksimctl.py (新增)
  - 子命令: replay, recover, metrics, risk-diagnose, borrow-fee-run
  - Requirements: 2,5,6,3

- [x] 14. 测试 - 单元 (核心组件) (Req1..7)
  - Files: tests/test_adaptive_snapshot.py, test_event_persistence.py, test_recovery.py, test_borrow_fee.py, test_risk_rules.py, test_rl_vectorized.py (新增)
  - 内容: 针对各核心逻辑的 happy + edge
  - Requirements: all

- [x] 15. 集成测试 - 回放与恢复 (Req2/Req6)
  - File: tests/test_replay_recovery_integration.py (新增)
  - 场景: 生成事件→回放→校验→模拟崩溃→恢复。
  - Requirements: 2,6

- [x] 16. 集成测试 - 卖空与借券费用 + 强平 (Req3)
  - File: tests/test_short_borrow_liquidation.py (新增)
  - Requirements: 3

- [x] 17. 集成测试 - 风险规则与配置热更新 (Req4/Req5/Req1)
  - File: tests/test_risk_config_hot_reload.py (新增)
  - Requirements: 4,5,1

- [x] 18. 性能基准脚本 (Req1/Req2/Req7)
  - File: scripts/benchmark_adaptive_snapshot.py, benchmark_replay.py, benchmark_vectorized_env.py (新增)
  - Requirements: 1,2,7

- [x] 19. 数据模型迁移 SQL 附录 (EventLog) (Req2)
  - File: persistence/migrations/001_event_log.sql (新增)
  - 内容: 创建 event_log 表 (含索引)；可选 checkpoint 表
  - Requirements: 2

- [x] 20. 错误码与指标文档 (Req5/Req4/Req6)
  - File: docs/diagnostics.md (新增)
  - 内容: 错误码 -> 描述 -> 触发来源；指标字典
  - Requirements: 5,4,6

- [x] 21. 清理与重构 (小范围) (Req 全局)
  - File: services/risk_engine.py / account_service.py 仅最小必要调整；删除遗留未用导入
  - Requirements: all

- [x] 22. 上线顺序与 Feature Flags (Rollout Plan)
  - File: docs/rollout_plan.md (新增)
  - 内容: 各特性 flag 名称、默认值、回滚步骤
  - Requirements: all

- [x] 23. 指标回归检查脚本 (Req5)
  - File: scripts/metrics_sanity_check.py (新增)
  - 内容: 启动局部模拟→采集 metrics→断言关键指标存在
  - Requirements: 5

- [x] 24. 文档内引用需求 ID 交叉核对 (Req 审核)
  - File: docs/traceability_matrix.md (新增)
  - 内容: Requirement -> Tasks -> Test 覆盖表
  - Requirements: all

