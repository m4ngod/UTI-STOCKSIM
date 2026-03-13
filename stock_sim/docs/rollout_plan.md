# Platform Hardening Rollout Plan (Feature Flags & Phased Enablement)

Spec: platform-hardening  Task:22  Scope: 全部关键新增能力 (风险/恢复/观测/性能/队列)

本文目的: 
1. 统一列出可控 Feature Flags / 关键参数及默认值。
2. 给出分阶段灰度上线顺序、观测指标与回滚步骤。
3. 降低一次性全量启用导致的复杂联动风险。

## 1. Flag / 开关一览
| Flag / 参数 | 默认 | 作用域 | 影响模块 | 关键指标 / 事件 | 风险 | 回滚方式 |
|-------------|------|--------|----------|----------------|------|-----------|
| EVENT_PERSIST_ENABLED | True | 事件持久化 | event_persistence_service | persistence_failures_total, PersistenceDegraded | I/O 写放大 | 设 False -> 内存模式 |
| EVENT_PERSIST_BATCH_MAX / FLUSH_MS | 64 / 50ms | 持久化批规模 | event_persistence_service | event_queue_size | 批过大延迟 | 调整为更小 |
| SNAPSHOT_ENABLE | True | RDB 快照 | snapshot_service | snapshot_threshold{symbol} | 频繁 I/O / 阻塞 | False 停止新快照 |
| SNAPSHOT_THROTTLE_N_PER_SYMBOL | 5 | 快照触发基准 | adaptive_snapshot_service | snapshot_threshold{symbol} 波动 | 过小=>I/O增加 | 放大数值 |
| BORROW_FEE_ENABLED | True | 借券费用计提 | borrow_fee_scheduler | borrow_fee_accrual_batches/errors | 利润计算偏差 | False 禁用计提 |
| BORROW_RATE_DAILY | 0.0005 | 日费率 | borrow_fee_scheduler | borrow_fee_accrual_batches | 收费不合理 | 热更新调整 |
| LIQUIDATION_ENABLED | True | 强平 | forced_liquidation_service | LiquidationTriggered | 误触平仓 | False 停止生成 |
| MAINTENANCE_MARGIN_RATIO | 0.25 | 维持保证金 | forced_liquidation_service | LiquidationTriggered | 参数过高/低 | 热更新微调 |
| LIQUIDATION_ORDER_SLICE_RATIO | 0.25 | 强平切片 | forced_liquidation_service | LiquidationTriggered | 流动性影响 | 调整比例或停用 |
| BORROW_FEE_MIN_NOTIONAL | 0 | 费用过滤 | borrow_fee_scheduler | borrow_fee_accrual_batches | 小额噪声 | 调整阈值 |
| RISK_DISABLE_SHORT | False | 全局禁卖空 | risk_engine / 规则 | risk_reject_total{rule=ShortInventoryRule?} | 限制策略 | True 立即禁止 |
| BROKER_UNLIMITED_LENDING | True | 券源充足 | risk_engine / lending_pool | risk_reject_total | 过度杠杆 | False 触发真实借券逻辑 |
| MAX_GROSS_EXPOSURE_NOTIONAL 等风险参数 | 各默认 | 敞口限制 | risk_engine | risk_reject_total{rule="*"} | 过严/过松 | 热更新修正 |
| IPO_INTERNAL_AUTO_OPEN_ENABLED | False | IPO 自动开盘 | matching_engine IPO | IPOOpened, 价格跳变 | 时间未对齐 | False 手动/外部触发 |
| AUCTION_ENABLED | True | 集合竞价总体 | auction_engine | IPOOpened / auction阶段订单事件 | 测试覆盖不足 | False 退回连续竞价 |
| AUCTION_SIM_FAST | True | 集合竞价加速 | auction_engine | IPOOpened 时间戳 | 时序不真实 | False 使用真实节奏 |
| ORDER_DISPATCH_COMMIT_N | 200 | 撮合批提交 | order_dispatcher | lock_timeouts, order_latency_hist_* | 死锁/延迟 | 调低数值 |
| BATCH_SETTLEMENT_SIZE | 0 | 成交批结算 | order_service / fee_engine | trades_settled | 延迟 / 内存峰值 | 设 0 关闭 |
| REDIS_ENABLED | False | 外部 Redis 功能 | redis_client / ipo_grant_queue | redis_health_fail/ok | 外部依赖不稳 | False 全部回退本地 |
| REDIS_PREFIX | stocksim | Redis key 前缀 | ipo_grant_queue | N/A | key 冲突 | 修改前缀 |
| IPO Grant Queue (implicit via REDIS_ENABLED) | Off | IPO 初始持仓发放异步化 | ipo_grant_queue | ACCOUNT_UPDATED 事件节奏 | 丢队列/重复 | 回退 fallback_direct_grant |
| FORCE_CROSS_PRICE | False | 诊断强制成交 | matching_engine | orders_with_trades 异常提升 | 非真实撮合 | False 禁用 |
| CONFIG 热更新字段集 | - | 动态调参 | config_hot_reload | config_hot_reload_changed/invalid | 错误修改 | patch 回滚 / 重启 |
| REJECT_METRIC_PREFIX | reject_ | 指标命名前缀 | metrics_exporter | reject_<code> | 冲突 | 改前缀并重启 |

补充: 其它风险/延迟相关数值 (ORDER_RATE_MAX, TXN_MAX_SECONDS 等) 在初期不建议频繁调整。

## 2. 分阶段上线顺序
| Phase | 目标 | 启用项 | 验证指标 & 阈值 (建议) | 观察窗口 | 通过标准 | 回滚条件 |
|-------|------|--------|-------------------------|-----------|-----------|------------|
| P0 (Baseline) | 最小稳定撮合 | 核心撮合, 基础风险(静态), SNAPSHOT_ENABLE, AUCTION_ENABLED | orders_submitted/filled 比例, orders_rejected (<5%) | 1 日 / 5k+ 订单 | 无异常错误码集中 | reject_* 突增 或 lock_timeouts >0.5% |
| P1 (Observability) | 指标与持久化 | EVENT_PERSIST_ENABLED, MetricsExporter | persistence_failures_total =0, event_queue_size 平稳 (< batch*5) | 1 日 | 无失败事件 | persistence_failures_total > 10 / 5min |
| P2 (Risk Extensions) | 扩展规则 & 敞口 | MAX_GROSS_EXPOSURE_NOTIONAL / 新规则 | risk_reject_total{rule} 分布合理 | 1-2 日 | 规则拒绝占比 < 15% | 单规则 >50% 或骤增翻倍 |
| P3 (Borrow & Liquidation) | 杠杆 + 费用 + 强平 | BORROW_FEE_ENABLED, LIQUIDATION_ENABLED | borrow_fee_accrual_errors=0, LiquidationTriggered 稀疏 | 2-3 日 | 强平仅在真实高杠杆账户 | LiquidationTriggered 激增且 NAV 未异常 |
| P4 (Adaptive Snapshot / Batch) | 性能优化 | SNAPSHOT_THROTTLE_N_PER_SYMBOL 调整, ORDER_DISPATCH_COMMIT_N 调大, BATCH_SETTLEMENT_SIZE>0 | order_latency_hist_p99 改善 / 稳定 | 1 日 | p99 降或不升 | p99 > 基线 +20% |
| P5 (Redis 集成) | 外部依赖接入 | REDIS_ENABLED (及 IPO Grant Queue) | redis_health_fail 占比<5%, fallback 调用≈0 | 1 日 | 健康且 ACCOUNT_UPDATED 正常 | fail 连续 >5 次或队列堆积 |
| P6 (IPO 自动) | IPO 体验自动化 | IPO_INTERNAL_AUTO_OPEN_ENABLED | IPOOpened 时序正确 | 多次 IPO | 正确阶段切换 | 时间漂移 / 异常未开盘 |
| P7 (Fine Tuning) | 调参 / RL | 热更新风险 & RL 扩展 | config_hot_reload_invalid≈0 | 持续 | 参数调整生效 | invalid 增长 |

## 3. 验证与观测清单 (每阶段开始前后)
- 指标采集: `python scripts/stocksimctl.py metrics` -> 保存基线 JSON 快照。
- 日志: struct.log 中筛选 ERROR / WARN；PersistenceDegraded / RecoveryFailed / LiquidationTriggered。
- 风险拒绝结构化导出: 若 risk_reject_total 异常, 抽样订单上下文。
- 资源: 若开启 Redis, 监控连接数与 latency (health log 输出)。

## 4. 回滚策略
| 场景 | 快速处置 | 深层次回滚 | 备注 |
|------|----------|------------|------|
| 持久化大量失败 | EVENT_PERSIST_ENABLED=False | 清理未刷写队列后重启 | 保留内存事件确保撮合不阻塞 |
| 风险规则误杀 | 调低相关阈值 / 热更新 RISK_DISABLE_SHORT=True | 临时移除规则模块 | 保留最小价格/数量校验 |
| 强平误触 | LIQUIDATION_ENABLED=False | 调回参数 / 重放事件校验 | 关闭后不再生成新强平单 |
| 借券费异常 | BORROW_FEE_ENABLED=False | 修正费率后恢复 | 费用计提中断不影响撮合 |
| Redis 不稳定 | REDIS_ENABLED=False | 清理队列后改为 fallback | 队列中积压条目可批量直接发放 |
| Snapshot 造成阻塞 | SNAPSHOT_ENABLE=False | 调整频率后再启用 | 注意恢复后需补一次全量快照 |
| IPO 自动开盘异常 | IPO_INTERNAL_AUTO_OPEN_ENABLED=False | 由外部脚本驱动 | 验证逻辑后重试 |

## 5. 决策与准入门槛 (Go / No-Go)
| 阶段 | Go 标准 | No-Go 示例 |
|------|---------|------------|
| P1 -> P2 | persistence_failures_total=0 且 p99 未升 | p99 上升>15% 或 5min 内>3 次持久化失败 |
| P2 -> P3 | 单规则拒绝比例 < 15% 且集中度 < 50% | 单规则 >60% 或 risk_reject_total 翻倍 |
| P3 -> P4 | LiquidationTriggered 总数 < 账户数 5% | 连续两个观察窗均 >10% |
| P4 -> P5 | p99 改善或持平 & 没有 backlog | event_queue_size 升高且持续增长 |
| P5 -> P6 | redis_health_fail 占比 <5% | 连接波动>20% 或 fail 连续>5 |

## 6. 与需求的对应 (Trace)
| Requirement | 支撑点 |
|-------------|--------|
| Req1 基础 | 分阶段控制 (Baseline/Adaptive) 保证核心功能稳定性 |
| Req2 回放 | 持久化开关 + 批策略确保可重放一致性 |
| Req3 保证金/借券 | 借券/强平独立可控，便于灰度 |
| Req4 风险扩展 | 风险规则配置逐步放量，指标 gating |
| Req5 可观测 | 各阶段 gating 指标表 & 回滚信号 |
| Req6 恢复 | 持久化与快照可独立关闭帮助恢复路径 |
| Req7 RL 扩展 | 在 P7 精细调参与向量化；前置阶段保证数据质量 |

## 7. 运营流程建议
1. 每次变更只提升一个 Phase，记录 T+0 / T+1 指标对比。
2. 变更窗口内禁止同时修改多个风险阈值 (避免归因困难)。
3. 所有 flag 修改通过 config 热更新（若受支持）或受控重启单实例。
4. 回滚后需记录 root cause 并在文档追加案例 (Appendix Section)。

## 8. 附录 & 后续迭代
- 计划增加: 自动回滚脚本 (基于指标阈值) -> 后续 Task。
- 可选扩展: 将 flag 状态导出到 metrics: feature_flag_state{name="FLAG"} 便于可视化。
- 建议: 为风险规则添加 whitelist 账户机制，降低对关键策略的初期冲击。

---
更新策略: 新增 Feature Flag 或阶段时追加到表格并更新 Trace 映射。

