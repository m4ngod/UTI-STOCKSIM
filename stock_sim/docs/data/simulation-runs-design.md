# simulation_runs 设计草案

_Last updated: 2026-03-22_

本文档定义 `simulation_runs` 这张表的职责、字段、索引、与现有表的关系，以及写入时机建议。

---

## 1. 为什么需要 `simulation_runs`

UTI-STOCKSIM 未来不是只做一次单机模拟，而是要支持：

- 多轮模拟
- 不同场景/参数配置对比
- 多个 retail 与多个 agent 的长期运行
- 回测、仿真、训练、重放的结果隔离
- 后续统计、分析、归档

如果没有 `run_id` / `simulation_runs` 这一层，后面会遇到这些问题：

- 不同模拟批次的数据混在一起
- 很难比较两个场景的收益表现
- 很难只清理某一次运行产生的数据
- 很难回答“这条订单/成交属于哪一次模拟”
- 很难做回放/恢复与实验管理

所以 `simulation_runs` 必须成为未来存储架构中的一级对象。

---

## 2. 表定位

### 定位
`simulation_runs` = **模拟运行主记录表**

它的职责不是存放具体订单或成交，而是作为：

- 一次模拟运行的主键锚点
- 全部动态历史数据的归属容器
- 运行配置与结果摘要的入口

### 层级
建议放在：

- **PostgreSQL 权威主库**

### 表角色
属于：

- 主数据 / 管理数据 / 元数据表

---

## 3. 推荐字段

## 3.1 核心主键与标识字段

### `run_id`
- 类型：`UUID` 或 `VARCHAR(64)`
- 建议：优先 `UUID`
- 含义：唯一标识一次模拟运行

### `name`
- 类型：`VARCHAR(128)`
- 含义：用户可读名称
- 示例：
  - `baseline-retail-001`
  - `ipo-stress-test-v2`
  - `ppo-paper-run-2026-03-22`

### `scenario_name`
- 类型：`VARCHAR(128)`
- 含义：场景/实验名
- 用途：把多个 run 归类到同一实验主题下

---

## 3.2 运行类型与状态字段

### `run_type`
- 类型：`VARCHAR(32)` 或枚举
- 建议取值：
  - `simulation`
  - `backtest`
  - `replay`
  - `training`
  - `paper`

### `status`
- 类型：`VARCHAR(32)` 或枚举
- 建议取值：
  - `created`
  - `starting`
  - `running`
  - `paused`
  - `completed`
  - `failed`
  - `canceled`
  - `recovered`

### `failure_reason`
- 类型：`TEXT` / `VARCHAR(512)`
- 含义：失败摘要

---

## 3.3 时间字段

### `started_at`
- 类型：`TIMESTAMP`
- 含义：真实世界启动时间

### `ended_at`
- 类型：`TIMESTAMP`
- 含义：真实世界结束时间

### `created_at`
- 类型：`TIMESTAMP`
- 含义：记录创建时间

### `updated_at`
- 类型：`TIMESTAMP`
- 含义：记录更新时间

### `sim_start_day`
- 类型：`INT` 或 `DATE-like string`
- 含义：模拟起始日

### `sim_end_day`
- 类型：`INT` 或 `DATE-like string`
- 含义：模拟结束日（若已完成）

### `last_sim_day`
- 类型：`INT`
- 含义：最后推进到的模拟日

### `last_sim_dt`
- 类型：`TIMESTAMP`
- 含义：最后推进到的模拟时点

---

## 3.4 配置与执行环境字段

### `speed_profile`
- 类型：`VARCHAR(64)` 或 JSON
- 含义：模拟速度配置摘要
- 示例：
  - `1x`
  - `30x`
  - `adaptive`
  - `custom-json-ref`

### `config_version`
- 类型：`VARCHAR(64)`
- 含义：配置版本号/哈希

### `config_snapshot_json`
- 类型：`JSONB`（PostgreSQL）
- 含义：运行启动时的关键配置快照

### `seed`
- 类型：`BIGINT` / `VARCHAR(64)`
- 含义：随机种子

### `environment_tag`
- 类型：`VARCHAR(64)`
- 含义：运行环境标签
- 示例：
  - `dev`
  - `staging`
  - `research`
  - `paper-prod-like`

---

## 3.5 参与者规模摘要字段

### `retail_count`
- 类型：`INT`
- 含义：该 run 包含的 retail 数量

### `agent_count`
- 类型：`INT`
- 含义：该 run 包含的 agent 数量

### `instrument_count`
- 类型：`INT`
- 含义：该 run 中启用的标的数量

### `universe_ref`
- 类型：`VARCHAR(128)`
- 含义：标的池/宇宙配置引用

---

## 3.6 结果摘要字段

### `final_equity`
- 类型：`DOUBLE PRECISION`
- 含义：总权益摘要

### `final_pnl`
- 类型：`DOUBLE PRECISION`
- 含义：最终收益摘要

### `max_drawdown`
- 类型：`DOUBLE PRECISION`
- 含义：最大回撤摘要

### `trade_count`
- 类型：`BIGINT`
- 含义：总成交笔数

### `order_count`
- 类型：`BIGINT`
- 含义：总订单数

### `event_count`
- 类型：`BIGINT`
- 含义：总事件数（若启用 event_log）

### `summary_json`
- 类型：`JSONB`
- 含义：更灵活的结果摘要

---

## 3.7 附加说明字段

### `notes`
- 类型：`TEXT`
- 含义：用户注释 / 运行备注

### `tags_json`
- 类型：`JSONB`
- 含义：标签集合

### `owner`
- 类型：`VARCHAR(64)`
- 含义：发起者 / 实验维护者

---

## 4. 推荐建表草案（PostgreSQL 语义）

```sql
CREATE TABLE simulation_runs (
  run_id UUID PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  scenario_name VARCHAR(128),
  run_type VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  failure_reason VARCHAR(512),

  started_at TIMESTAMP NULL,
  ended_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

  sim_start_day INTEGER NULL,
  sim_end_day INTEGER NULL,
  last_sim_day INTEGER NULL,
  last_sim_dt TIMESTAMP NULL,

  speed_profile VARCHAR(64),
  config_version VARCHAR(64),
  config_snapshot_json JSONB,
  seed BIGINT NULL,
  environment_tag VARCHAR(64),

  retail_count INTEGER DEFAULT 0,
  agent_count INTEGER DEFAULT 0,
  instrument_count INTEGER DEFAULT 0,
  universe_ref VARCHAR(128),

  final_equity DOUBLE PRECISION NULL,
  final_pnl DOUBLE PRECISION NULL,
  max_drawdown DOUBLE PRECISION NULL,
  trade_count BIGINT DEFAULT 0,
  order_count BIGINT DEFAULT 0,
  event_count BIGINT DEFAULT 0,
  summary_json JSONB,

  owner VARCHAR(64),
  notes TEXT,
  tags_json JSONB
);
```

---

## 5. 推荐索引

### 必要索引

```sql
CREATE INDEX idx_sim_runs_status ON simulation_runs(status);
CREATE INDEX idx_sim_runs_run_type ON simulation_runs(run_type);
CREATE INDEX idx_sim_runs_scenario_name ON simulation_runs(scenario_name);
CREATE INDEX idx_sim_runs_started_at ON simulation_runs(started_at);
CREATE INDEX idx_sim_runs_created_at ON simulation_runs(created_at);
```

### 可选索引

```sql
CREATE INDEX idx_sim_runs_environment_tag ON simulation_runs(environment_tag);
CREATE INDEX idx_sim_runs_owner ON simulation_runs(owner);
```

### JSONB 可选索引（后期）
若你后面经常按 `config_snapshot_json` 或 `tags_json` 搜索，可加 GIN 索引。

---

## 6. 与现有表的关系建议

`simulation_runs` 的核心作用是把其它动态表串起来。

## 6.1 建议未来挂 `run_id` 的现有表

### 强烈建议挂 `run_id`
- `orders`
- `order_events`
- `trades`
- `ledgers`
- `event_log`
- `bars_*`（如果是模拟生成/回放生成）
- `snapshots_1s`（如果是运行期持久化快照）
- `agent_bindings`（若绑定是 run 范围内的）

### 可选挂 `run_id`
- `positions`
- `accounts`

#### 说明
对 `positions` / `accounts`：
- 如果它们表示“当前运行时状态”，则可以直接挂 `run_id`
- 如果以后想把“账号身份”与“某次 run 中的账号状态”拆开，就应分裂成：
  - 静态主数据表
  - 运行态状态表

---

## 7. 写入时机建议

## 7.1 创建时机

在以下时机创建 `simulation_runs` 记录：

- 用户显式启动一次模拟/回测/重放
- 系统创建一批 retail + agent 并准备进入运行态前

### 创建时建议状态
- `created`
或
- `starting`

---

## 7.2 启动时更新

当 sim clock 开始推进、引擎开始工作后：
- `status = running`
- 写 `started_at`
- 写 `sim_start_day`

---

## 7.3 运行中更新

运行中不必每条事件都更新 `simulation_runs`，否则会产生写放大。

建议：
- 周期性更新
- 状态切换时更新
- 风险事件/恢复事件时更新

可更新字段：
- `last_sim_day`
- `last_sim_dt`
- `trade_count`
- `order_count`
- `event_count`
- `updated_at`

---

## 7.4 结束时更新

在正常结束或异常结束时更新：

- `status`
- `ended_at`
- `sim_end_day`
- `final_equity`
- `final_pnl`
- `max_drawdown`
- `summary_json`
- `failure_reason`（若失败）

---

## 8. 与账户快照的关系

后续 `account_equity_snapshots` 应直接引用 `run_id`。

### 关系示意
- `simulation_runs` 1 --- N `account_equity_snapshots`
- `simulation_runs` 1 --- N `orders`
- `simulation_runs` 1 --- N `trades`
- `simulation_runs` 1 --- N `ledgers`

这样才能按 run 做：
- 汇总
- 清理
- 比较
- 回放

---

## 9. 设计建议：不要让 `simulation_runs` 变成大杂烩

这张表应当只存：

- 运行主信息
- 配置摘要
- 结果摘要
- 状态机信息

不要把：
- 所有账户明细
- 所有逐笔事件
- 所有净值序列

都直接塞进这张表。

原则是：
- 详细数据存在明细表
- `simulation_runs` 只做总入口与摘要

---

## 10. 推荐的下一步

在 `simulation_runs` 之后，最自然的下一张设计表是：

### `account_equity_snapshots`

因为一旦有了 `run_id`，这张表就能自然承担：
- 每个账户在每个模拟时点的净值轨迹
- 后续排行榜、收益曲线、风控分析、agent 对比

---

## 11. 一句话总结

> `simulation_runs` 是未来整个模拟平台的数据锚点。它不负责存细节，而负责把一次模拟运行的身份、状态、配置摘要、结果摘要统一下来，并为 orders/trades/ledgers/equity snapshots 提供可追踪的归属主键。
