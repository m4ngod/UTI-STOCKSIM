# UTI-STOCKSIM 数据分层设计

_Last updated: 2026-03-22_

## 1. 背景

UTI-STOCKSIM 的目标已经不再是单机小型 demo，而是逐步走向：

- 上百个 retail 交易者
- 少量但持续运行的智能体 / 模型代理
- 可变速模拟交易
- 长期静态数据 + 高频动态数据并存
- 可审计、可回放、可恢复、可统计分析

在这样的目标下，继续把 **SQLite** 作为未来主运行存储并不合适。

SQLite 仍然适合：

- 本地开发
- 单元测试 / 小型集成测试
- 小规模 smoke / demo
- 单文件离线结果包

但不建议继续作为未来正式模拟运行的主数据库。

---

## 2. 总体决策

### 结论

未来推荐采用以下存储分层：

1. **PostgreSQL**：唯一权威业务主库
2. **Redis**：实时缓存 / 高频状态 / 推送桥接
3. **SQLite**：开发 / 测试 / 本地 demo / 离线包

### 核心原则

- 强一致、可追溯、需要 SQL 分析的数据进 PostgreSQL
- 高频、可丢失、主要服务于 UI/运行态的数据进 Redis 或内存缓存
- 测试和轻量环境继续保留 SQLite，但不作为长期主运行方案

---

## 3. 为什么不建议 SQLite 作为未来主库

### 3.1 写并发能力不足

系统未来会存在大量写入：

- 订单
- 成交
- 账户状态变化
- 持仓变化
- 账本
- 快照 / 资产快照
- agent 元数据 / 状态
- 事件日志

SQLite 在这种场景下容易出现：

- 写锁竞争
- 事务阻塞
- 并发测试假红
- `OperationalError` / `PendingRollbackError` 之类的噪音问题

### 3.2 不利于复杂分析查询

未来系统很可能需要查询：

- 某账户某阶段权益曲线
- 某 agent 的多轮模拟收益表现
- 某 symbol 某日的订单 / 成交 / 账本链路
- 某日全部账户的风险暴露排行
- 策略 / 模型在不同阶段的效果对比

SQLite 不是完全做不到，而是会越来越难维护。

### 3.3 不适合作为长期系统演进底座

未来如果系统继续扩大，SQLite 会让：

- schema 演进
- 并发写入
- 归档策略
- 数据治理
- 运行时排障

都变得更别扭。

---

## 4. 推荐的数据分层

系统数据建议分成三层。

---

## 4.1 第一层：主业务数据（PostgreSQL）

这一层是系统的**运行真相**。

### 适合存储的数据

#### 静态 / 半静态主数据
- traders / retail_accounts
- agents / strategy_bindings
- instruments
- scenario_configs
- simulation_runs
- risk_rule_configs

#### 核心交易状态数据
- accounts
- positions
- orders
- order_events
- trades
- ledgers
- agent_bindings

#### 高价值快照数据
- account_equity_snapshots
- daily_position_snapshots
- latest persisted market snapshots（节流后）
- recovery checkpoints / state markers

#### 可回放 / 可审计数据
- event_log
- replay checkpoints
- configuration change records

### 为什么这层放 PostgreSQL

因为这些数据：

- 需要强事务语义
- 需要结构化关联
- 需要长期保留
- 需要做条件查询 / 聚合统计
- 需要支持恢复、回放、审计

---

## 4.2 第二层：热状态 / 高频缓存（Redis）

这一层不是最终真相，而是**运行时热态**。

### 适合放 Redis 的数据

- 当前盘口 top N
- 最新 snapshot
- 最新 bar / rolling window
- 当前 leaderboard
- 当前 sim clock 状态
- UI 订阅桥接状态
- agent heartbeat / online status
- 高频中间态缓存
- 指标 / 计算结果短期缓存
- pub/sub / stream 风格事件转发

### 为什么放 Redis

因为这些数据的特点是：

- 高频更新
- 对低延迟敏感
- 丢了可以重建或重新计算
- 更多服务于实时显示和运行协调

### 注意

Redis 适合做：

- 实时层
- 缓存层
- 推送桥接层

不适合替代 PostgreSQL 作为主业务权威存储。

---

## 4.3 第三层：开发 / 测试 / 离线包（SQLite）

SQLite 继续保留，但角色要明确降级。

### 适合使用 SQLite 的场景

- pytest
- 本地功能验证
- smoke / demo
- 单文件实验环境
- 导出后的离线结果包

### 不建议的用途

- 多交易者正式模拟运行主库
- 高频并发长时间运行
- 正式回放审计主数据库

---

## 5. 动态数据如何存

你特别提到：

- 交易者名称、标的名称（长期数据）
- 每天的账户资产（动态历史）
- 标的价格（动态历史）

这里建议明确区分。

---

## 5.1 交易者名称 / 标的名称

这类属于主数据。

### 建议
放 PostgreSQL。

### 典型表
- `accounts` / `traders`
- `agents`
- `instruments`
- `strategy_profiles`

这些表结构化维护，允许后续挂载：

- 显示名称
- 类型
- 风险偏好
- 所属策略
- 是否启用
- 初始资金设定
- settlement_cycle
- 交易限制等

---

## 5.2 每天的账户资产

这类不能只存当前值，要存**历史快照**。

### 建议新增表
`account_equity_snapshots`

### 推荐字段
- `id`
- `run_id`
- `account_id`
- `sim_day`
- `sim_dt`
- `cash`
- `frozen_cash`
- `market_value`
- `gross_exposure`
- `net_exposure`
- `equity`
- `drawdown`
- `borrowed_notional`
- `created_at`

### 写入策略建议
不要每一笔成交都强制写全量账户快照。

建议采用：

- 每日收盘必写
- 风险事件时写
- 固定时间粒度抽样写（例如每 N 秒模拟时钟）
- UI 高频展示仍从缓存拿，不直接查这张表

---

## 5.3 标的价格

这类要分两种。

### A. 历史 bars / K 线
适合 PostgreSQL。

例如：
- `bars_1s`
- `bars_1m`
- `bars_1h`
- `bars_1d`

如果未来体量上去，可进一步做：

- 按时间分区
- 按 symbol + 日期建立复合索引

### B. 实时盘口 / 快照
适合 Redis + 节流落库。

建议：
- 最新状态：Redis / 内存
- 需要审计的节流快照：PostgreSQL
- 不要把每一次盘口变化都无脑写主库

---

## 6. 推荐的表级分层

以下是建议分层。

### PostgreSQL 主库

#### 主数据类
- `accounts`
- `agents`
- `instruments`
- `simulation_runs`
- `strategy_bindings`
- `risk_configs`

#### 运行状态类
- `positions`
- `orders`
- `order_events`
- `trades`
- `ledgers`

#### 历史快照类
- `account_equity_snapshots`
- `position_snapshots_daily`
- `snapshots_1s`（若保留节流落库）
- `bars_*`

#### 审计 / 回放类
- `event_log`
- `recovery_markers`
- `config_change_log`

### Redis 热层
- `latest:snapshot:{symbol}`
- `latest:orderbook:{symbol}`
- `leaderboard:current`
- `clock:state`
- `agent:heartbeat:{id}`
- `account:view:{account_id}`
- `market:bars:cache:{symbol}:{tf}`
- `stream:event:*` 或 pub/sub topic

---

## 7. 推荐的架构原则

### 7.1 当前状态表 + 历史事件表并存

不要只存当前值，也不要只存事件流。

### 建议并存

#### 当前状态
- accounts
- positions
- latest snapshots
- current leaderboard state

#### 历史事实
- trades
- ledgers
- order_events
- event_log
- equity_snapshots

这样：

- UI 查当前状态快
- 审计 / 回放有历史依据
- 恢复时不必纯靠全量重演

---

## 7.2 `run_id` / `simulation_id` 作为一级字段

这是模拟平台，不是单一实盘系统。

几乎所有动态表都建议带：

- `run_id`
- 或 `simulation_id`

### 建议带 `run_id` 的表
- orders
- order_events
- trades
- ledgers
- equity_snapshots
- bars_generated
- event_log

这样未来你才方便：

- 对比不同模拟批次
- 隔离不同场景
- 清理历史 run
- 做统计与复盘

---

## 7.3 T+1 / 配置语义必须以权威配置为准

近期已经暴露出一个关键问题：

- symbol 推断的默认交易规则
- 不能覆盖数据库里显式配置的 `settlement_cycle`

因此未来必须坚持：

### 规则
1. `Instrument/DB` 配置为权威来源
2. symbol 推断仅作兜底
3. engine 注册时必须携带真实 `settlement_cycle`
4. 风险规则读取的应是显式配置真相，而不是历史默认值

这条原则会同时影响：

- 数据存储设计
- engine registry
- 风控
- 测试策略

---

## 8. 推荐的迁移路径

### Phase A：角色重新定义
- 保留 SQLite，但明确仅用于 dev/test/demo
- 将 PostgreSQL 定义为未来主运行库
- 将 Redis 定义为热态/缓存层

### Phase B：梳理现有表语义
- 明确哪些表属于主业务真相
- 明确哪些表只是缓存 / 中间态
- 明确哪些快照要长期保留

### Phase C：引入快照策略
- 增加 `account_equity_snapshots`
- 明确 `bars_*` 的权威来源与保留策略
- 明确 `snapshots_1s` 是审计节流快照，不是全量 tick 替代物

### Phase D：运行时分层
- 高频 UI / 排行榜 / 最新盘口 -> Redis
- 核心交易事实 -> PostgreSQL
- 回放/恢复 -> PostgreSQL + event_log

### Phase E：测试策略分离
- SQLite 保持单元测试与轻量集成测试
- 更接近真实运行的回归，逐步提供 PostgreSQL 测试配置

---

## 9. 对当前项目的直接建议

### 当前建议拍板

#### 正式方向
- **PostgreSQL = 权威业务库**
- **Redis = 热缓存 / 实时层**
- **SQLite = 开发测试用途**

#### 近期优先落地
1. 保持现有 ORM 层尽量向 PostgreSQL 兼容靠拢
2. 新设计的动态历史表优先按 PostgreSQL 习惯设计
3. 不再把 SQLite 当未来主架构目标
4. 文档、测试、配置里都逐步体现这一点

---

## 10. 一句话总结

> 对 UTI-STOCKSIM 未来的规模与目标而言，SQLite 适合做开发/测试底座，但不适合继续做正式主运行存储。推荐采用 PostgreSQL 作为权威业务库，Redis 作为实时热层，并通过快照表 + 事件表 + 当前状态表的组合，承载长期静态数据与高频动态模拟数据。
