# UTI-STOCKSIM 表级存储清单

_Last updated: 2026-03-22_

本文档是 `docs/data/data-layering-design.md` 的表级落地版。
目标：把现有 persistence 模型、建议新增表、以及 Redis 热层职责，映射成可执行的存储蓝图。

---

## 1. 使用方式

后续做存储架构演进时，优先回答三个问题：

1. 这是**权威真相**还是**热缓存**？
2. 这是**当前状态**还是**历史事实**？
3. 这是**必须长期保留**还是**可以重建/可丢失**？

若答案是：
- 权威真相 + 当前状态/历史事实 + 长期保留 → PostgreSQL
- 高频热态 + 可重建/可丢失 → Redis
- 开发/测试轻量环境 → SQLite

---

## 2. 现有 persistence 模型清单

当前 `persistence/` 下已有模型：

- `models_account.py`
- `models_agent_binding.py`
- `models_bars.py`
- `models_event_log.py`
- `models_feature_buffer.py`
- `models_instrument.py`
- `models_ledger.py`
- `models_order.py`
- `models_order_event.py`
- `models_position.py`
- `models_snapshot.py`
- `models_trade.py`

从运行语义看，它们不应该被同等对待，而应分层。

---

## 3. PostgreSQL 权威层：现有表去向

## 3.1 主数据 / 配置数据

### `instruments`
来源：`models_instrument.py`

#### 建议定位
**PostgreSQL 主数据表**

#### 原因
它保存：
- symbol
- 名称
- tick_size
- lot_size
- min_qty
- settlement_cycle
- total_shares
- free_float_shares
- initial_price
- ipo_opened

这些都是交易语义权威来源，不应依赖 symbol 推断替代。

#### 后续建议
- 将 `settlement_cycle` 明确作为 engine 注册权威来源
- 未来增加：
  - instrument_type
  - market_type
  - listing_date
  - delisting_date
  - trading_session_template

---

### `agent_bindings`
来源：`models_agent_binding.py`

#### 建议定位
**PostgreSQL 主数据 / 半静态关系表**

#### 原因
它描述账户和策略/智能体绑定关系，属于重要业务配置。

#### 后续建议
可增加：
- `run_id`
- `binding_status`
- `effective_from`
- `effective_to`
- `config_version`

---

## 3.2 核心运行状态表

### `accounts`
来源：`models_account.py`

#### 建议定位
**PostgreSQL 当前状态表**

#### 原因
它是账户当前状态的权威来源，保存：
- cash
- frozen_cash
- frozen_fee
- tradable_t0 / tradable_t1
- sim_day / sim_dt

#### 后续建议
- 当前状态保留在 `accounts`
- 不把历史权益变化直接堆进本表
- 历史轨迹转移到快照表/账本表

---

### `positions`
来源：`models_position.py`

#### 建议定位
**PostgreSQL 当前状态表**

#### 原因
它表示账户在当前时点的持仓真相：
- quantity
- frozen_qty
- avg_price
- borrowed_qty
- borrow_fee_last_day

#### 后续建议
- 保持为当前状态表
- 历史持仓变化不要依赖本表追溯，应结合 trades / ledgers / position snapshots

---

### `orders`
来源：`models_order.py`

#### 建议定位
**PostgreSQL 当前状态 + 历史保留表**

#### 原因
订单是主业务事实，必须长期保留。

#### 建议语义
- 当前订单状态：由本表承载
- 订单生命周期细节：由 `order_events` 承载

#### 后续建议
增加：
- `run_id`
- `strategy_id` / `agent_id`
- `source_channel`
- `reject_code`

---

### `order_events`
来源：`models_order_event.py`

#### 建议定位
**PostgreSQL 历史事实表**

#### 原因
它是订单生命周期历史。

#### 价值
- 调试
- 审计
- 回放辅助
- 前端订单阶段解释

#### 后续建议
- 增加标准化 `event_type`
- 保留 `detail`
- 可补充 `event_meta_json`

---

### `trades`
来源：`models_trade.py`

#### 建议定位
**PostgreSQL 历史事实表**

#### 原因
成交是最核心的不可丢失业务事实之一。

#### 后续建议
- 强化索引：`(run_id, symbol, sim_dt)`、`(buy_account_id)`、`(sell_account_id)`
- 后续支持分区表（按 sim_day / run_id / 日期）

---

### `ledgers`
来源：`models_ledger.py`

#### 建议定位
**PostgreSQL 历史事实表**

#### 原因
资金变化、费用、借券费、已实现结果，天然应该通过 ledger 追踪。

#### 这是未来非常关键的一张表
用于回答：
- 账户为什么变了
- 是哪笔交易/费用导致的
- 借券费何时计提
- 回补/卖出产生了什么资金影响

#### 后续建议
- 保持不可轻易篡改语义
- 增加 `run_id`
- 增加更强的 `kind` 或结构化分类字段

---

## 3.3 市场历史 / 快照表

### `snapshots_1s`
来源：`models_snapshot.py`

#### 建议定位
**PostgreSQL 节流后历史快照表**

#### 不是“全量逐变动历史”
它更适合作为：
- 节流后的持久化快照
- 审计/回放辅助
- 非 tick 级别的市场状态留痕

#### 不建议
- 把每一次盘口变化都硬塞这里
- 把它当成唯一市场事实来源

#### 配套建议
最新 snapshot 应由 Redis / 内存承载，
`snapshots_1s` 只存经过策略保留的快照。

---

### `bars_1m` / `bars_1h` / `bars_1d`
来源：`models_bars.py`

#### 建议定位
**PostgreSQL 历史行情表**

#### 原因
bars 适合关系库存储，也适合后续做分区、索引、统计分析。

#### 后续建议
- 加 `run_id`（若存在模拟生成 bars）
- 若是外部行情与模拟行情混用，增加 `source_type`
- 对 `symbol + ts` 做强索引

---

## 3.4 审计 / 回放 / 恢复类

### `event_log`
来源：`models_event_log.py`

#### 建议定位
**PostgreSQL 历史审计表**

#### 原因
用于：
- 事件持久化
- 回放
- 故障恢复
- 链路审计

#### 建议
这是 PostgreSQL 很适合承担的一类表。
若未来非常大，可再做：
- 分区
- 冷热分层
- 归档到对象存储/Parquet

---

### `feature_buffer`
来源：`models_feature_buffer.py`

#### 建议定位
**短期：PostgreSQL / 中期：可迁移**

#### 原因
它更像训练/特征工程辅助表。

#### 判断
如果它只是临时缓存，未来未必必须放主业务库。
若长期需要保留训练证据，可继续留 PostgreSQL。
若只是高频中间特征，未来更适合：
- Redis
- 文件缓存
- Parquet
- 单独特征存储

#### 当前建议
先保留 PostgreSQL，但标记为“候选迁移表”。

---

## 4. Redis 热层：建议承担的职责

Redis 不直接复刻所有 PostgreSQL 表，而是只承接热态。

## 4.1 市场热状态

### `latest:snapshot:{symbol}`
内容：
- last
- bid1..bidN
- ask1..askN
- vol
- turnover
- spread
- imbalance
- ts

### `latest:orderbook:{symbol}`
内容：
- top N 档深度
- 仅用于实时 UI / 轻量查询

### `bars:cache:{symbol}:{tf}`
内容：
- 最近窗口 bars
- 用于前端/策略近端读取

---

## 4.2 账户热视图

### `account:view:{account_id}`
内容：
- cash
- frozen_cash
- equity
- gross_exposure
- net_exposure
- positions brief
- last_update

#### 注意
这个不是权威真相，只是 UI 加速层。

---

## 4.3 排行榜 / 运行态

### `leaderboard:current`
内容：
- 当前账户排行
- 当前 agent 表现排行

### `clock:state`
内容：
- sim_day
- sim_dt
- speed
- status

### `agent:heartbeat:{id}`
内容：
- 在线状态
- 最后活跃时间
- 当前任务摘要

---

## 4.4 事件桥接

### `stream:event:*` 或 pub/sub topics
用途：
- UI 推送
- 日志桥接
- 轻量实时订阅
- runtime 状态更新广播

---

## 5. 建议新增的 PostgreSQL 表

以下表尚未在当前 persistence 模型中清晰落地，但未来非常值得新增。

## 5.1 `account_equity_snapshots`

### 用途
记录账户在关键时间点的净值/资产状态。

### 建议字段
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

### 定位
**PostgreSQL 历史快照表**

---

## 5.2 `position_snapshots_daily`

### 用途
每日收盘/关键时点持仓快照。

### 建议字段
- `id`
- `run_id`
- `account_id`
- `symbol`
- `sim_day`
- `sim_dt`
- `quantity`
- `frozen_qty`
- `avg_price`
- `borrowed_qty`
- `market_price`
- `market_value`

### 定位
**PostgreSQL 历史快照表**

---

## 5.3 `simulation_runs`

### 用途
统一标识模拟运行批次。

### 建议字段
- `run_id`
- `name`
- `scenario_name`
- `status`
- `started_at`
- `ended_at`
- `speed_profile`
- `config_version`
- `notes`

### 定位
**PostgreSQL 主数据 / 管理表**

### 重要性
后续大量表都建议挂 `run_id`。

---

## 5.4 `config_change_log`

### 用途
记录运行中配置变化。

### 定位
**PostgreSQL 审计表**

---

## 5.5 `recovery_markers`

### 用途
记录恢复点、只读模式切换、恢复校验结果。

### 定位
**PostgreSQL 恢复/审计表**

---

## 6. 现有表的明确分类总结

## PostgreSQL 权威层（保留/强化）
- `accounts`
- `positions`
- `orders`
- `order_events`
- `trades`
- `ledgers`
- `instruments`
- `agent_bindings`
- `event_log`
- `bars_1m`
- `bars_1h`
- `bars_1d`
- `snapshots_1s`（节流快照而非全量逐变动）
- `feature_buffer`（暂留，候选迁移）

## PostgreSQL 建议新增
- `simulation_runs`
- `account_equity_snapshots`
- `position_snapshots_daily`
- `config_change_log`
- `recovery_markers`

## Redis 热层
- latest snapshot
- latest order book
- account view cache
- leaderboard current state
- current sim clock
- agent heartbeats
- recent bars cache
- push/stream topics

## SQLite 保留用途
- pytest
- 本地单机 smoke
- demo
- 离线包

---

## 7. 当前最值得优先推进的表级工作

### 优先级 1
- 引入 `simulation_runs`
- 明确动态表挂 `run_id`

### 优先级 2
- 引入 `account_equity_snapshots`
- 明确账户净值历史的抽样/收盘写入策略

### 优先级 3
- 明确 `snapshots_1s` 与 Redis latest snapshot 的职责边界

### 优先级 4
- 为 PostgreSQL 运行模式梳理索引、唯一约束、分区前提

---

## 8. 一句话总结

> 表级存储策略的核心不是“所有数据都进一个数据库”，而是：权威业务真相留在 PostgreSQL，实时热态留在 Redis，SQLite 保留给开发测试；同时通过当前状态表、历史事实表、快照表三种角色分工，让 UTI-STOCKSIM 能从可运行系统稳步走向可维护的复杂系统。
