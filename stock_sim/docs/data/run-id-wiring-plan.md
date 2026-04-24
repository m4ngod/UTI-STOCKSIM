# run_id 挂接方案

_Last updated: 2026-03-22_

本文档定义如何把新的 `simulation_runs` / `account_equity_snapshots` 设计，挂接到现有：

- `orders`
- `order_events`
- `trades`
- `ledgers`
- `event_log`
- `bars_*`
- `snapshots_1s`
- `agent_bindings`

目标不是一次性重写所有表，而是制定一条**可渐进迁移**的挂接路线。

---

## 1. 目标

### 我们要解决的问题

未来系统需要稳定回答：

- 这笔订单属于哪一次模拟运行？
- 这笔成交属于哪个场景？
- 这条账本变化属于哪个 run？
- 这个事件日志是哪个 run 产生的？
- 某次 run 的所有数据能不能被隔离查询 / 清理 / 对比？

如果没有 `run_id`，这些问题都会越来越难。

### 设计目标

1. 给关键动态表建立统一归属字段 `run_id`
2. 让 `simulation_runs` 成为全链路主锚点
3. 控制迁移复杂度，允许渐进接入
4. 不立即破坏现有 SQLite/dev 路径

---

## 2. 挂接原则

### 原则 1：先挂核心事实表
优先顺序：
1. `orders`
2. `trades`
3. `ledgers`
4. `order_events`
5. `event_log`
6. `account_equity_snapshots`

原因：这些表最能直接体现 run 归属。

### 原则 2：先加 nullable 字段，再逐步收紧
不要一上来就强制所有写入都必须有 `run_id`。

推荐迁移策略：
- 第一步：加 `run_id nullable`
- 第二步：运行时开始尽量写入 `run_id`
- 第三步：验证数据链完整性
- 第四步：再决定是否收紧非空约束

### 原则 3：历史数据允许为空
已有历史数据不一定能回填出正确 `run_id`。
因此：
- 老数据允许 `run_id = NULL`
- 新数据尽量强制写入 `run_id`

---

## 3. 推荐挂接范围

## 3.1 第一批：必须挂 `run_id`

### `orders`
来源：`models_order.py`

#### 为什么必须挂
订单是主业务入口。
几乎所有后续归属关系都能从订单开始串起来。

#### 建议新增字段
- `run_id VARCHAR(64)` 或 `UUID`

#### 建议索引
- `(run_id)`
- `(run_id, symbol, ts_created)`
- `(run_id, account_id, status)`

#### 运行时写入点
- `OrderService._persist_order()`
- 下单入口处拿当前 run context

---

### `trades`
来源：`models_trade.py`

#### 为什么必须挂
成交是 run 结果统计核心。

#### 建议新增字段
- `run_id`

#### 建议索引
- `(run_id, symbol, ts)`
- `(run_id, buy_account_id)`
- `(run_id, sell_account_id)`

#### 运行时写入点
- `OrderService._after_trades()`
- `OrderService.flush_batch()`

---

### `ledgers`
来源：`models_ledger.py`

#### 为什么必须挂
资金变化和收益统计必须支持按 run 切割。

#### 建议新增字段
- `run_id`

#### 建议索引
- `(run_id, account_id, ts)`
- `(run_id, symbol, ts)`

#### 运行时写入点
- `AccountService._write_ledger()`

---

## 3.2 第二批：强烈建议挂 `run_id`

### `order_events`
来源：`models_order_event.py`

#### 原因
虽然它可以通过 `order_id -> orders.run_id` 间接拿到归属，
但直接挂 `run_id` 有两个好处：
- 查询简单
- 避免跨表追踪成本

#### 建议新增字段
- `run_id`

#### 写入点
- `OrderService._persist_event()`

---

### `event_log`
来源：`models_event_log.py`

#### 原因
它是回放/恢复/审计总线，必须支持按 run 查询。

#### 建议新增字段
- `run_id`
- （可选）`account_id`

#### 建议索引
- `(run_id, ts_ms)`
- `(run_id, type, ts_ms)`

#### 写入点
- `event_persistence_service` 写 event_log 时从上下文携带

---

## 3.3 第三批：视语义挂接

### `bars_1m` / `bars_1h` / `bars_1d`

#### 判断
如果这些 bars 是：
- 外部静态行情 → 不一定必须挂 `run_id`
- 模拟/回放生成 bars → 建议挂 `run_id`

#### 推荐策略
增加可空 `run_id`：
- 外部基准 bars：`run_id = NULL`
- 某次运行派生 bars：写具体 `run_id`

---

### `snapshots_1s`

#### 判断
如果只是全局市场参考快照，不一定非要挂 run。
如果它承载的是某次模拟运行的节流快照，则建议挂。

#### 推荐策略
加可空 `run_id`。

---

### `agent_bindings`

#### 判断
如果 agent 绑定是全局长期关系，不一定挂 run。
如果 agent 绑定是“某次运行内的参与关系”，则建议挂。

#### 推荐策略
短期不强制。
中期若 run 内动态绑定增多，再加：
- `run_id`
- `binding_scope`

#### 2026-04-25 实施调整
- 已提前为 `agent_bindings` 增加 nullable `run_id`。
- 原因：Agent 面板会从持久化 binding 水合当前 agent 列表；如果这里没有 run 边界，旧 run / 旧实验批次会直接出现在当前桌面。
- 当前策略：默认查询只返回 active run 的 agent bindings，历史 binding 暂不在 Agent 面板展示。
- 后续策略：如果需要历史 run 浏览，应增加显式 run selector，而不是恢复全表默认水合。

---

## 4. 不建议第一时间挂 `run_id` 的表

## `accounts`

### 原因
当前 `accounts` 更像“账户身份 + 当前状态”混合体。
直接粗暴挂 `run_id` 可能会把：
- 账户身份
- 运行态状态

混在一起更难拆。

### 建议
短期先不强制挂。
后续如果系统演进为：
- `account_profiles`（静态身份）
- `run_accounts`（某次运行中的账户状态）

那时再系统化处理。

---

## `positions`

### 原因
和 `accounts` 一样，它现在更像当前运行态表。
若未来有多个 run 并行，就需要重新思考是不是应该拆成：
- 静态持仓定义
- run 内当前持仓表

### 建议
短期不先靠 `positions.run_id` 解决问题，
优先依赖：
- `orders`
- `trades`
- `ledgers`
- `account_equity_snapshots`

---

## 5. 推荐迁移顺序

## Phase 1：schema 预留

先对以下表加可空 `run_id`：
- `orders`
- `order_events`
- `trades`
- `ledgers`
- `event_log`
- `bars_*`
- `snapshots_1s`

### 原则
- 先不加严格外键约束也可以
- 先保证代码能逐步写入

---

## Phase 2：运行时上下文接入

引入一个统一概念：

### `RunContext`
至少包含：
- `run_id`
- `run_type`
- `scenario_name`
- `sim_day`
- `sim_dt`

#### 推荐接入位置
- `OrderService`
- `AccountService`
- `event_persistence_service`
- `bars/snapshot` 写入服务

---

## Phase 3：核心写入链打通

优先打通：
- 下单 → `orders.run_id`
- 成交 → `trades.run_id`
- 结算 → `ledgers.run_id`
- 订单事件 → `order_events.run_id`
- 事件总线持久化 → `event_log.run_id`

这一步完成后，run 级别统计和清理就已经有基础了。

---

## Phase 4：快照层挂接

再接：
- `account_equity_snapshots.run_id`
- `position_snapshots_daily.run_id`
- 需要时接 `bars_*` / `snapshots_1s`

---

## 6. 推荐的运行时传递方式

## 6.1 显式传入优于全局猜测

推荐：
- 创建 run 时显式生成 `run_id`
- 在核心服务对象初始化时传入 `run_context`

例如：
- `OrderService(session, engine=..., instrument_service=..., run_context=...)`
- `AccountService(session, run_context=...)`

而不是在底层模型写入时再去猜当前 run 是谁。

---

## 6.2 最低兼容方案

如果短期不想大改构造器，可先在服务内部增加：
- `self.run_id: str | None = None`
- 或通过 thread-local / contextvar 管理

但长期更建议显式上下文注入。

---

## 7. 对现有代码的直接影响点

## 7.1 `OrderService`

### 需要影响的方法
- `_persist_order()`
- `_persist_state()`
- `_persist_event()`
- `_after_trades()`
- `flush_batch()`

### 目标
让 orders / order_events / trades 在持久化时拿到统一 `run_id`。

---

## 7.2 `AccountService`

### 需要影响的方法
- `_write_ledger()`
- （未来）equity snapshot writer

### 目标
让 ledger 与权益快照都能按 run 聚合。

---

## 7.3 `event_persistence_service`

### 目标
给 `event_log` 增加 run 维度。

如果事件 payload 本身不带 run_id，建议在持久化前由上下文补齐。

---

## 8. 推荐的字段兼容策略

### 短期建议
- `run_id` 允许为空
- 新 run 数据尽量写
- 老数据保持兼容

### 中期建议
- 新建 run 的主链路必须写 `run_id`
- 关键分析查询默认按 `run_id` 做分组/过滤

### 长期建议
- 对关键事实表可考虑将 `run_id` 收紧为非空
- 但前提是运行上下文已经成熟稳定

---

## 9. 一句话总结

> `run_id` 挂接方案的核心，不是给所有表机械加一列，而是先把 orders / trades / ledgers / event_log 这些关键事实表统一纳入 `simulation_runs` 归属体系，再逐步扩展到快照与辅助表，从而建立真正可比较、可清理、可审计的 run 级数据边界。
