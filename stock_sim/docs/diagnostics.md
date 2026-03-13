# Diagnostics 参考 (错误码 & 指标 & 事件)

Spec: platform-hardening  Task:20  Requirements: Req5(可观测) / Req4(风险扩展) / Req6(恢复)

## 1. 错误码 (Error Codes)
来源集中于订单流转与系统状态防护。前缀说明:
- REJECT_METRIC_PREFIX = `reject_` (settings 中配置) -> 每个拒单理由都会派生一个指标: `reject_<code_lower>`
- 下表列出当前可能出现的 code (区分大小写)。

| Code | 场景类别 | 触发来源 / 路径 | 说明 | 伴随指标 |
|------|----------|-----------------|------|----------|
| MIN_QTY | ORDER_VALIDATION | OrderService.place_order lot/min 对齐 | 下单数量对齐后仍 < 最小值 | orders_rejected, reject_min_qty |
| PRICE_LE_0 | ORDER_VALIDATION | basic_order_checks | 价格<=0 | orders_rejected, reject_price_le_0 |
| QTY_LE_0 | ORDER_VALIDATION | basic_order_checks | 数量<=0 | orders_rejected, reject_qty_le_0 |
| READONLY_RECOVERY | SYSTEM_STATE | 恢复失败进入只读 (recovery_is_readonly) | 系统处于只读恢复保护模式 | orders_rejected, reject_readonly_recovery |
| FEE_FREEZE_FAIL | FEES | 手续费预冻结不足 | 现金余额不足以冻结预估费用 | orders_rejected, reject_fee_freeze_fail |
| FREEZE_FAIL | RESOURCES | 主体资金/持仓冻结失败 | 现金不足或内部冻结失败 | orders_rejected, reject_freeze_fail |
| <risk_rule_code> (动态) | RISK | 风险规则校验 (RiskEngine.validate) | 任一注册规则拒绝 | orders_rejected, reject_<risk_rule_code>, risk_reject_total{rule="RuleName"} |
| FOK_UNFILLABLE | TIME_IN_FORCE | FOK 订单首次撮合无法完全成交 | 全量未满足 | N/A (取消路径) |
| IOC_UNFILLABLE | TIME_IN_FORCE | IOC 首次撮合 0 成交 | 无成交立即取消 | N/A |
| IOC_REMAIN_CANCEL | TIME_IN_FORCE | IOC 部分成交后剩余取消 | 部分撮合后剩余撤销 | N/A |
| AUCTION_UNMATCHED | AUCTION | 集合竞价结束残余未成交自动取消 | 竞价阶段未成交订单出清 | N/A |

说明:
1. risk_rule_code 由具体规则返回 (rr.code.lower())，当前示例规则可能使用自定义 name；扩展规则应保证唯一。
2. 新增拒绝原因时：保持 CODE 大写，写入持久化事件使用原始 CODE，指标自动使用小写。

### 1.1 分类建议
- ORDER_VALIDATION: 基础价格/数量
- RISK: 风险限制 (敞口/仓位/融资融券等)
- FEES: 手续费相关冻结/结算
- RESOURCES: 资金或资源锁失败
- SYSTEM_STATE: 系统模式 (只读 / 维护)
- TIME_IN_FORCE: IOC/FOK 语义取消
- AUCTION: 集合竞价阶段特有

### 1.2 扩展规范
新增规则/拒绝:
- 返回对象含 ok=False, reason=<描述>, code=<CODE>(若路径允许)；或兼容当前 RiskResult 结构。
- 统一在 OrderService 中 metrics.inc("orders_rejected") + metrics.inc(reject_<code_lower>)。

## 2. 指标字典 (Metrics)
除下表列出指标外, MetricsExporter 还会导出衍生/聚合指标与直方统计。

| Metric | 类型 | 说明 | 来源 / 计算 |
|--------|------|------|-------------|
| orders_submitted | counter | 进入下单处理总数 | OrderService.place_order 开始 |
| orders_rejected | counter | 拒绝订单数 (总) | 各拒绝分支 |
| reject_<code> | counter | 各拒绝原因子计数 | REJECT_METRIC_PREFIX + code.lower() |
| orders_with_trades | counter | 至少产生一笔成交的订单数 | 撮合返回 trades>0 |
| trades_count | counter | 累积撮合产生的成交条数 | len(trades) 累加 |
| orders_new | counter | 完整进入簿状态为 NEW | 初次状态持久化后 |
| orders_partial | counter | 部分成交订单数 | 状态 NEW->PARTIAL |
| orders_filled | counter | 完全成交订单数 | NEW/PARTIAL->FILLED |
| trades_processed | counter | (兼容扩展) 处理成交事件计数 | after trades loop |
| cash_refund_after_fill | counter | 成交后现金退还次数 | 订单结算后多余冻结释放 |
| fee_refund_after_fill | counter | 成交后手续费退款次数 | 订单部分/未成交手续费按比例退还 |
| borrow_fee_accrual_batches | counter | 借券费用计提批次数 | daily_reset -> borrow_fee_scheduler |
| borrow_fee_accrual_errors | counter | 借券计提错误次数 | 调度异常 |
| pos_create | counter | 新建持仓数 | account_service 创建 position |
| fee_frozen | counter | 费用冻结成功次数 | freeze_fee |
| fee_refund | counter | 手续费退款次数 | refund_fee |
| cash_frozen | counter | 现金冻结成功次数 | freeze BUY |
| qty_frozen | counter | 卖出冻结数量次数 | freeze SELL (示意) |
| cash_release | counter | 现金释放次数 | release BUY |
| qty_release | counter | 数量释放次数 | release SELL |
| trades_settled | counter | 批量结算成交次数 | settle_trades_batch |
| event_persist_written | counter | 事件持久化成功数 | event_persistence_service |
| event_persist_failures | counter | 事件持久化失败数 | 同上 (导出别名 persistence_failures_total) |
| persistence_failures_total | counter | 失败别名 (Exporter 衍生) | metrics_exporter 聚合 |
| event_queue_size | gauge | 事件总线当前队列长度 | metrics_exporter (长度探测) |
| crash_counter | counter | 进程级崩溃/严重异常计数 (占位) | 若未设置导出默认为0 |
| snapshot_threshold{symbol} | gauge | 自适应快照当前阈值 | AdaptiveSnapshotPolicyManager._states |
| risk_reject_total | counter | 聚合 risk_reject_total__* 求和 | metrics_exporter 派生 |
| risk_reject_total{rule="RULE"} | counter | 单规则拒绝次数 | counters 中 risk_reject_total__<rule> 前缀 |
| order_latency_hist_count | summary | 下单延迟样本数 | timings['order_latency'] |
| order_latency_hist_p50_ms | summary | 延迟 p50 | 排序计算 |
| order_latency_hist_p90_ms | summary | 延迟 p90 | 排序计算 |
| order_latency_hist_p99_ms | summary | 延迟 p99 | 排序计算 |
| orders_queue_in | counter | 进入分发队列的订单 | order_dispatcher |
| orders_failed_exception | counter | 撮合执行时异常 | order_dispatcher |
| lock_timeouts | counter | 数据库锁等待/超时重试 | order_dispatcher (异常解析) |
| gauge::<name> | gauge | 自定义瞬时值 | metrics.gauge(name, value) |

备注:
- risk_reject_total__<rule> 不直接导出；Exporter 转换为带标签 risk_reject_total{rule=""}。
- 若存在 risk_reject_total 聚合键则不会重复聚合。

### 2.1 指标采集示例
Prometheus-like:
```
# scrape_ts_ms 1736388888888
orders_submitted 120
orders_rejected 3
reject_min_qty 1
reject_price_le_0 2
risk_reject_total{rule="MaxGrossExposure"} 5
order_latency_hist_count 120
order_latency_hist_p50_ms 0.210
...
```
JSON:
```
{"timestamp_ms":1736388888888,"metrics":{"orders_submitted":120,...},"order_latency_hist":{"count":120,"p50":0.21},"snapshot_threshold":{"AAPL":7},"risk_reject_total_per_rule":{"MaxGrossExposure":5}}
```

## 3. 事件类型 (EventType)
| 事件 | 含义 | 典型消费者 |
|------|------|------------|
| OrderAccepted | 订单被接受 (进入撮合流程) | 撮合、审计日志 |
| OrderRejected | 订单被拒绝 | UI / 风控审计 |
| OrderFilled | 订单完全成交 | 账户/持仓更新 |
| OrderPartiallyFilled | 部分成交 | 账户/持仓更新 |
| OrderCanceled | 用户 / 规则 / TIF 取消 | 账户释放 |
| TradeEvent | 成交事件 | 统计 / 回测重建 |
| AccountUpdated | 账户变动 | 持久化 / RL Adapter |
| SnapshotUpdated | 快照刷新 | 前端行情 / 训练特征 |
| BarUpdated | K线更新 | 策略因子 |
| StrategyChanged | 策略切换 | 调度 / 风控 |
| IPOOpened | IPO 集合竞价结束 | 引擎阶段切换 |
| SimDay | 新模拟交易日 | 日切流程 |
| AgentMetaUpdate | 智能体元数据变更 | 训练 / 看板 |
| SnapshotPolicyChanged | 自适应节流阈值调整 | 监控 / 调试 |
| PersistenceDegraded | 持久化大量失败 | 运维告警 |
| RecoveryFailed | 恢复失败进入只读 | 运维 / 风险停止下单 |
| RecoveryResumed | 恢复成功恢复撮合 | 恢复告警清除 |
| RiskReset | 风险窗口/日切重置 | 风控看板 |
| BorrowFeeAccrued | 借券费用计提 | 资金/费用流水 |
| LiquidationTriggered | 触发强平 | 监控 / 风控策略 |
| ConfigChanged | 配置热更新生效 | 各功能模块刷新缓存 |

## 4. 故障/告警参考
| 场景 | 触发信号 | 建议动作 |
|------|----------|----------|
| 持久化失败飙升 | persistence_failures_total 急增 + PersistenceDegraded 事件 | 回退到内存模式 / 降低写频率 |
| 风险拒绝异常上升 | risk_reject_total 或某单规则激增 | 检查新策略 / 配置热更新是否误限额 |
| 快照阈值频繁波动 | snapshot_threshold{symbol} 快速抖动 | 调整自适应参数或流量分片 |
| 只读恢复模式 | RecoveryFailed 事件 & reject_readonly_recovery 增长 | 排查恢复日志 / 触发手动恢复 |
| 强平频发 | LiquidationTriggered 频繁 | 调整保证金参数或风控模型 |

## 5. 扩展与最佳实践
- 新指标: 直接 metrics.inc / metrics.gauge；Exporter 会自动包含 (排除重复命名冲突)。
- 时序系统: 可将 Exporter.collect(prom) 暴露 HTTP；或外部采集 CLI: `python scripts/stocksimctl.py metrics`。
- 风险规则: 使用统一前缀 risk_reject_total__<RuleName> 统计单规则拒绝。
- 延迟: 在关键路径添加 metrics.timeit('order_latency') 上下文可扩展采样。

## 6. 需求覆盖 (Trace)
| Requirement | 覆盖点 |
|-------------|--------|
| Req4 (风险扩展) | risk_reject_total*, 风险拒绝错误码, RiskReset 事件 |
| Req5 (可观测) | 全量指标字典, Exporter 输出格式, 持久化失败/阈值/延迟统计 |
| Req6 (恢复) | RecoveryFailed/Resumed 事件, READONLY_RECOVERY 错误码 |

---
更新策略: 新增事件或指标后补充本文件，保持错误码/事件/指标三者在此处形成统一参考。

