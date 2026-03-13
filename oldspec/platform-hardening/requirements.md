# Requirements Document

## Introduction
本规格目标：针对当前 StockSim 平台（撮合 / 账户 / 风控 / 卖空 / IPO / RL / 可视化）在 README.md 描述与实际扩展需求之间的差距，制定一系列“平台加固 (Platform Hardening) 与 关键增强”需求。聚焦：风险控制精细化、事件持久化与回放、快照/撮合性能自适应、卖空与借券经济逻辑补全、可观测性与回放一致性、RL 环境真实账户融合、数据库迁移与数据一致性、安全输入与恢复能力。目标是在不破坏现有核心 API（订单服务、撮合、账户结算）前提下提升稳定性、可扩展性与研究复现能力。

## Alignment with Product Vision
- 与“贴近真实微观结构 + 策略/教学/研究底座”愿景一致：通过补足风险、回放、费用/借券与恢复机制，使仿真结果更可复现、数据更可信。 
- 支撑 Roadmap 中：更精细节流、事件外部化、借券利率、回放工具、RL 向量化、风控实盘映射等条目，形成结构化落地路径。
- 为未来分布式撮合 / Kafka 事件流 / 多账户策略沙盒提供合规与工程基础。

## Requirements

### Requirement 1: 自适应快照与事件节流 (Adaptive Snapshot & Event Throttling)
**User Story:** 作为策略研发人员，我希望系统在高撮合频率时自动调节快照/事件发布频率，在低活跃度时保持及时性，以减少无效 I/O 与内存压力，同时不影响关键成交/状态事件及时性。
#### Acceptance Criteria
1. WHEN 每 symbol 的撮合操作速率 > 预设阈值区间 THEN 系统 SHALL 动态提升快照触发最小操作计数阈值 (上限可配置)。
2. WHEN 成交发生 THEN 系统 SHALL 仍然强制立即发布最新快照 (force 模式不受节流延迟影响)。
3. IF 过去 T 秒无订单/成交活动 THEN 系统 SHALL 降低节流阈值回到基线以保证“冷启动”策略快速获得状态。
4. WHEN 节流阈值调整 THEN 系统 SHALL 通过 EVENT `SNAPSHOT_POLICY_CHANGED` 发布参数变化（含旧/新阈值、触发原因）。
5. WHEN 运行中关闭/调整节流配置 (settings 热更新接口) THEN 系统 SHALL 在 ≤1 秒内应用并记录一次结构化日志与指标。

### Requirement 2: 事件持久化与可回放 (Event Sourcing & Replay)
**User Story:** 作为回测/审计使用者，我希望能够将撮合/订单/账户/快照事件顺序化持久化，并在任意时间点重放以重构订单簿与账户状态用于策略复现实验。
#### Acceptance Criteria
1. WHEN 开启 `EVENT_PERSIST_ENABLED=true` THEN 系统 SHALL 将核心事件序列化(按严格时间顺序)写入事件存储 (表或压缩行日志)。
2. IF 事件写入失败（数据库暂时不可用） THEN 系统 SHALL 采用内存环形缓冲重试并暴露丢弃计数指标 (failures_total)。
3. WHEN 调用 replay 工具 并提供起止时间/事件 ID 范围 THEN 系统 SHALL 可在“dry-run”模式重建簿与账户快照且不得影响当前运行实例。
4. WHEN 重放完成 THEN 系统 SHALL 输出一致性校验报告（订单数量 / 成交数量 / 最终持仓 / 现金）与原始快照对比偏差 ≤ 允许公差 0（完全一致）。
5. IF 输入事件流存在缺口或乱序 THEN 系统 SHALL 中止重放并报告第一个缺陷位置 (missing_id / out_of_order_id)。

### Requirement 3: 卖空与借券经济逻辑增强 (Short Selling Economics)
**User Story:** 作为风险管理员，我希望模拟借券成本与强平逻辑，以更真实评估策略在卖空/高杠杆场景下的资本占用与收益。
#### Acceptance Criteria
1. WHEN position.borrowed_qty > 0 THEN 系统 SHALL 按日(或步)计提借券费用：`fee = borrowed_qty * price_ref * borrow_rate_daily` 写入 Ledger（类型=BORROW_FEE）。
2. IF 账户净资产比率 < 强平阈值 (maintenance_margin_ratio) THEN 系统 SHALL 触发强平流程：按流动性优先/风险权重排序生成强平订单事件。
3. WHEN 借券归还 (borrowed_qty 由 >0 变为 0) THEN 系统 SHALL 记录 REPO_RETURN 事件并停止后续计息。
4. WHEN 无可借库存且 BROKER_UNLIMITED_LENDING=false THEN 系统 SHALL 拒绝新卖空订单并返回明确风险拒绝码 SHORT_INVENTORY_EXHAUSTED。
5. WHEN 借券费率或强平参数通过配置变更 THEN 系统 SHALL 记录参数变更审计事件（含旧/新值、操作时间）。

### Requirement 4: 高精度风险控制扩展 (Advanced Risk Controls)
**User Story:** 作为风控人员，我需要更细粒度控制（账户/分组/标的/日内窗口），并对撮合前/后风险敞口进行统一核算，以减少绕过单点规则的可能。
#### Acceptance Criteria
1. WHEN 下单前 THEN 系统 SHALL 聚合计算账户 + 分组（group_id 可选）当前净/毛敞口并与阈值比较，超限拒绝订单。
2. IF 订单类型为 FOK THEN 风险引擎 SHALL 在预检查中基于当前簿深度估算是否一次完全可成交，否则拒绝而不冻结资金。
3. WHEN 任一风险拒绝 THEN 系统 SHALL 发布 ORDER_REJECTED 且 detail 包含 machine_code 与人类可读 message。
4. WHEN 日切 (SIM_DAY) 事件触发 THEN 系统 SHALL 重置日内速率/成交额/净额计数且生成 RISK_RESET 事件。
5. IF 调用风险诊断接口 (新 REST/内部服务) THEN 系统 SHALL 返回最近 N 次拒绝摘要 (含规则 ID, 频次, 首末时间)。

### Requirement 5: 可观测性与运行健康 (Observability & Health)
**User Story:** 作为运维/研究者，我希望对撮合延迟、事件排队、数据库写放大、失败重试、风险拒绝频次等形成量化指标与告警基础。
#### Acceptance Criteria
1. WHEN 每笔订单流程结束 THEN 系统 SHALL 记录 end-to-end latency (下单到返回) 分桶指标。
2. WHEN 事件总线队列长度 > 阈值 THEN 系统 SHALL 触发 BACKPRESSURE_WARNING 日志与指标计数。
3. IF 数据库写操作失败重试次数 > retry_threshold THEN 系统 SHALL 发布 PERSISTENCE_DEGRADED 事件。
4. WHEN 导出 metrics (pull) 接口访问 THEN 系统 SHALL 提供标准化文本或 JSON（便于 Prometheus / 自定义抓取）。
5. WHEN 发生未捕获异常导致线程崩溃 THEN 系统 SHALL 增加 crash_counter 并写入结构化日志含 trace_id。

### Requirement 6: 恢复与状态重建 (Recovery & State Rebuild)
**User Story:** 作为系统维护者，我希望在异常崩溃后快速恢复，重建订单簿与账户状态，确保与崩溃前一致，降低停机影响。
#### Acceptance Criteria
1. WHEN 系统启动且启用恢复模式 THEN 系统 SHALL 读取最新持久化订单、未完成订单、持仓、最近一条快照并重建 BookState。
2. IF 快照缺失但有完整事件日志 THEN 系统 SHALL 通过事件重放恢复状态。
3. WHEN 恢复完成 THEN 系统 SHALL 输出一致性校验报告：未完成订单数、总持仓量、现金合计与数据库原始值差异=0。
4. WHEN 恢复失败 (缺口/校验不一致) THEN 系统 SHALL 进入只读安全模式 (拒绝新订单) 并抛出显式警告事件 RECOVERY_FAILED。
5. WHEN 恢复成功后首笔订单到来 THEN 系统 SHALL 记录 RECOVERY_RESUMED 事件一次。

### Requirement 7: RL 环境与真实账户融合 + 向量化 (RL-Account Integration & Vectorization)
**User Story:** 作为强化学习研究者，我希望 RL 环境使用真实 AccountService 数据，并支持多标的批量向量化 step 以提升训练吞吐。
#### Acceptance Criteria
1. WHEN RL 环境 step() 调用 THEN 系统 SHALL 从真实账户/快照拉取最新 pos_qty/cash 而不再使用占位值。
2. IF 配置开启 vectorized=True AND n_envs>1 THEN 环境 SHALL 在单次调用返回 batched obs/reward/done 结构。
3. WHEN 订单由 RL 动作生成 THEN 系统 SHALL 支持动作裁剪与失败原因回传 (risk reject 也写入 info)。
4. WHEN 训练结束保存 checkpoint THEN 系统 SHALL 记录当前策略签名/参数哈希并广播 AGENT_META_UPDATE。
5. IF 动作中请求卖空且系统风险禁止 THEN 环境 SHALL 自动在 reward 中追加 penalty（可配置权重）。

## Non-Functional Requirements

### Code Architecture and Modularity
- 遵循单一职责：新增模块分离为 `services/` (risk_ext, borrow_fee_scheduler, replay_service, recovery_service, metrics_exporter)。
- 明确接口契约：事件持久化接口 IEventSink / 重放 IEventSource / 恢复 IRecoveryStrategy。
- 插件化风险规则注册 (registry pattern)，允许动态增减。
- 配置集中：settings 增量字段分组（EVENT_* / RECOVERY_* / BORROW_* / METRICS_*）。

### Performance
- 自适应快照策略：在 1k+ orders/sec 下减小快照写入到 <5% 性能开销。
- 事件持久化异步批量写：单批最多 256 条或 50ms 刷新，目标降低数据库 QPS 50%+。
- 重放工具：≥ 50k events/sec 重建速度（内存模式）。
- RL 向量化：8 并行环境下 step 吞吐提升 ≥3x（基准为单环境）。

### Security
- 输入校验：订单 / 配置 / 外部接口 参数 schema 验证（Pydantic / dataclass）。
- 防注入：所有 SQL 通过 ORM 参数化；不允许字符串拼接执行原生 SQL（迁移除外）。
- 配置热更新需鉴权钩子（占位 simple token）。
- 强平/重放仅可在受控模式下触发（需 enable 标志）。

### Reliability
- 事件持久化写失败最大重试次数与指数退避；超过阈值进入降级模式并打标。
- 恢复流程幂等：多次启动恢复结果一致。
- 借券费用调度器：在时间漂移/日切异常下不重复计提（基于“最后成功计提日”标记）。

### Usability
- 统一 CLI：`stocksimctl replay|recover|metrics|risk-diagnose`。
- README 增补“恢复/重放/借券费率/自适应节流”章节。
- 指标命名规范与文档：延迟/histogram、失败计数/counter、状态 gauge。
- 错误码字典：风险/账户/恢复错误集中表格化。

