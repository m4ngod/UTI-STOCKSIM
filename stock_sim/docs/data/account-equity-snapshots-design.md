# account_equity_snapshots 设计草案

_Last updated: 2026-03-22_

本文档定义 `account_equity_snapshots` 这张表的职责、字段、索引、与 `simulation_runs` / `accounts` / `positions` / `ledgers` 的关系，以及推荐写入时机。

---

## 1. 为什么需要 `account_equity_snapshots`

当前系统已经有：

- `accounts`：账户当前状态
- `positions`：当前持仓状态
- `trades`：成交历史
- `ledgers`：资金变化历史

但如果未来要稳定支持：

- 多轮模拟结果比较
- 净值曲线展示
- drawdown / 风险暴露分析
- retail 与 agent 排名对比
- 不同时点账户状态回顾

仅靠 `accounts + positions + ledgers` 现算会变得：

- 查询复杂
- 成本高
- 不稳定
- 难以做标准化分析

所以需要一张独立的历史快照表：

> `account_equity_snapshots` = 在关键时点记录账户净值与风险状态的历史表

---

## 2. 表定位

### 定位
`account_equity_snapshots` = **账户权益历史快照表**

### 层级
建议放在：

- **PostgreSQL 权威主库**

### 角色
它属于：

- 历史快照表
- 分析支撑表
- 排行榜/净值曲线/回测统计基础表

### 它不是什么
它不是：

- 账户当前状态的唯一来源
- 每笔成交的明细事实表
- 持仓明细替代表

换句话说：
- 当前状态看 `accounts` / `positions`
- 资金变化事实看 `ledgers`
- 成交事实看 `trades`
- 时点净值轨迹看 `account_equity_snapshots`

---

## 3. 设计目标

这张表未来应该支持：

1. 按账户画净值曲线
2. 按 run 对比账户表现
3. 计算最大回撤 / 波动 / 收益区间
4. 给 leaderboard / agent 对比提供稳定数据源
5. 在不重放全部事件的前提下，快速查看关键时点账户状态

---

## 4. 推荐字段

## 4.1 主键与归属字段

### `id`
- 类型：`BIGSERIAL` / `BIGINT`
- 含义：自增主键

### `run_id`
- 类型：`UUID` 或 `VARCHAR(64)`
- 含义：归属的模拟运行
- 外键目标：`simulation_runs.run_id`

### `account_id`
- 类型：`VARCHAR(64)`
- 含义：账户标识
- 外键目标：`accounts.id`（若采用当前模型）

---

## 4.2 模拟时间字段

### `sim_day`
- 类型：`INT`
- 含义：模拟日

### `sim_dt`
- 类型：`TIMESTAMP`
- 含义：模拟时点

### `snapshot_kind`
- 类型：`VARCHAR(32)`
- 含义：快照类型
- 建议取值：
  - `interval`
  - `daily_close`
  - `risk_event`
  - `manual`
  - `run_end`
  - `recovery_point`

### `sequence_no`
- 类型：`BIGINT`
- 含义：同一 run 内的顺序编号（可选）

---

## 4.3 账户权益字段

### `cash`
- 类型：`DOUBLE PRECISION`
- 含义：现金余额

### `frozen_cash`
- 类型：`DOUBLE PRECISION`
- 含义：冻结现金

### `frozen_fee`
- 类型：`DOUBLE PRECISION`
- 含义：冻结手续费

### `market_value`
- 类型：`DOUBLE PRECISION`
- 含义：持仓市值（多头与空头估值合成后的总市场价值口径，需统一定义）

### `equity`
- 类型：`DOUBLE PRECISION`
- 含义：账户总权益

### `available_equity`
- 类型：`DOUBLE PRECISION`
- 含义：可用权益（可选）

---

## 4.4 风险暴露字段

### `gross_exposure`
- 类型：`DOUBLE PRECISION`
- 含义：总敞口

### `net_exposure`
- 类型：`DOUBLE PRECISION`
- 含义：净敞口

### `long_market_value`
- 类型：`DOUBLE PRECISION`
- 含义：多头市值

### `short_market_value`
- 类型：`DOUBLE PRECISION`
- 含义：空头市值

### `borrowed_notional`
- 类型：`DOUBLE PRECISION`
- 含义：借券名义敞口

### `leverage`
- 类型：`DOUBLE PRECISION`
- 含义：杠杆率摘要

### `margin_ratio`
- 类型：`DOUBLE PRECISION`
- 含义：保证金比率 / 风险比率（若系统启用）

---

## 4.5 收益与风险摘要字段

### `realized_pnl`
- 类型：`DOUBLE PRECISION`
- 含义：累计已实现收益

### `unrealized_pnl`
- 类型：`DOUBLE PRECISION`
- 含义：未实现收益

### `pnl_total`
- 类型：`DOUBLE PRECISION`
- 含义：总收益

### `drawdown`
- 类型：`DOUBLE PRECISION`
- 含义：当前回撤

### `peak_equity`
- 类型：`DOUBLE PRECISION`
- 含义：截至当前快照的峰值权益

### `return_since_start`
- 类型：`DOUBLE PRECISION`
- 含义：相对 run 起点收益率

---

## 4.6 摘要辅助字段

### `position_count`
- 类型：`INT`
- 含义：持仓标的数

### `trade_count_cum`
- 类型：`BIGINT`
- 含义：累计成交数（可选）

### `order_count_cum`
- 类型：`BIGINT`
- 含义：累计订单数（可选）

### `meta_json`
- 类型：`JSONB`
- 含义：保留灵活附加字段

### `created_at`
- 类型：`TIMESTAMP`
- 含义：快照记录写入时间

---

## 5. 推荐建表草案（PostgreSQL 语义）

```sql
CREATE TABLE account_equity_snapshots (
  id BIGSERIAL PRIMARY KEY,
  run_id UUID NOT NULL,
  account_id VARCHAR(64) NOT NULL,

  sim_day INTEGER NOT NULL,
  sim_dt TIMESTAMP NOT NULL,
  snapshot_kind VARCHAR(32) NOT NULL,
  sequence_no BIGINT NULL,

  cash DOUBLE PRECISION NOT NULL DEFAULT 0,
  frozen_cash DOUBLE PRECISION NOT NULL DEFAULT 0,
  frozen_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
  market_value DOUBLE PRECISION NOT NULL DEFAULT 0,
  equity DOUBLE PRECISION NOT NULL DEFAULT 0,
  available_equity DOUBLE PRECISION NULL,

  gross_exposure DOUBLE PRECISION NOT NULL DEFAULT 0,
  net_exposure DOUBLE PRECISION NOT NULL DEFAULT 0,
  long_market_value DOUBLE PRECISION NOT NULL DEFAULT 0,
  short_market_value DOUBLE PRECISION NOT NULL DEFAULT 0,
  borrowed_notional DOUBLE PRECISION NOT NULL DEFAULT 0,
  leverage DOUBLE PRECISION NULL,
  margin_ratio DOUBLE PRECISION NULL,

  realized_pnl DOUBLE PRECISION NULL,
  unrealized_pnl DOUBLE PRECISION NULL,
  pnl_total DOUBLE PRECISION NULL,
  drawdown DOUBLE PRECISION NULL,
  peak_equity DOUBLE PRECISION NULL,
  return_since_start DOUBLE PRECISION NULL,

  position_count INTEGER DEFAULT 0,
  trade_count_cum BIGINT NULL,
  order_count_cum BIGINT NULL,
  meta_json JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 6. 推荐索引

### 必要索引

```sql
CREATE INDEX idx_aes_run_id ON account_equity_snapshots(run_id);
CREATE INDEX idx_aes_account_id ON account_equity_snapshots(account_id);
CREATE INDEX idx_aes_run_account_simdt ON account_equity_snapshots(run_id, account_id, sim_dt);
CREATE INDEX idx_aes_run_simday ON account_equity_snapshots(run_id, sim_day);
CREATE INDEX idx_aes_snapshot_kind ON account_equity_snapshots(snapshot_kind);
```

### 建议唯一约束（视快照策略而定）
如果你希望同一 run + account + sim_dt + kind 不重复：

```sql
CREATE UNIQUE INDEX uq_aes_run_account_dt_kind
ON account_equity_snapshots(run_id, account_id, sim_dt, snapshot_kind);
```

---

## 7. 与现有表的关系建议

## 7.1 与 `simulation_runs`

强关系：
- 一个 `simulation_runs` 对应多个 `account_equity_snapshots`

用途：
- 分 run 汇总
- 清理某次模拟
- 比较不同场景
- 结果页展示

---

## 7.2 与 `accounts`

关系：
- `account_equity_snapshots.account_id` 指向账户身份

注意：
- `accounts` 是当前状态
- `account_equity_snapshots` 是历史轨迹

两者不能混用。

---

## 7.3 与 `positions`

`positions` 不直接被替代。

推荐做法：
- 账户层面总权益、敞口等摘要进 `account_equity_snapshots`
- 更细粒度持仓历史放 `position_snapshots_daily` 或未来更细的 position snapshot 表

---

## 7.4 与 `ledgers` / `trades`

关系：
- `ledgers` / `trades` 是事实明细
- `account_equity_snapshots` 是聚合后时点摘要

用途分工：
- 查“为什么变了” → `ledgers` / `trades`
- 查“那一刻是多少” → `account_equity_snapshots`

---

## 8. 推荐写入时机

这张表最关键的不是“要不要有”，而是“何时写”。

## 8.1 必写场景

### A. 每日收盘
这是最推荐的最低保留粒度。

优点：
- 成本可控
- 足够支撑长期曲线
- 适合统计和归档

### B. run 结束时
无论正常结束还是失败结束，建议补一条：
- `snapshot_kind = run_end`

### C. 风险事件时
例如：
- 强平触发
- 保证金不足
- 恢复只读切换
- 借券风险显著变化

这类时点很值得记录。

---

## 8.2 可选场景

### A. 固定时间粒度抽样
例如：
- 每 N 秒模拟时钟
- 每根 bar 结束时
- 每隔 N 笔成交后

### B. 人工/调试快照
例如：
- 用户点击“保存状态”
- 调试模式下记录

---

## 8.3 不建议的写法

### 不建议每笔成交都写一条全量账户快照
原因：
- 写放大严重
- 对 PostgreSQL 压力大
- 查询时也不一定真需要这么密

更合理方式是：
- `ledgers` / `trades` 保明细
- `account_equity_snapshots` 保关键时点摘要

---

## 9. 推荐计算口径

这张表最大的风险是“字段很多，但口径混乱”。

建议后续明确一版统一公式。

## 最低统一口径建议

### `equity`
建议定义为：

```text
cash + market_value - borrow_cost_adjustments(optional)
```

### `gross_exposure`
建议定义为：

```text
sum(abs(position market value))
```

### `net_exposure`
建议定义为：

```text
sum(signed position market value)
```

### `drawdown`
建议定义为：

```text
(peak_equity - equity) / peak_equity
```

### `return_since_start`
建议定义为：

```text
(equity - start_equity) / start_equity
```

口径统一后，前端排行榜、分析报表、agent 对比才不会互相打架。

---

## 10. 与排行榜 / 前端的关系

未来如果做：
- retail 排行榜
- agent 排行榜
- 权益曲线页
- 风险监控页

优先从 `account_equity_snapshots` 提供数据，而不是每次都从当前账户状态临时重算全历史。

### 好处
- 查询稳定
- 性能更可控
- UI 逻辑更简单
- 历史复盘更一致

---

## 11. 推荐下一步

在这张表之后，最自然的下一步是二选一：

1. `position_snapshots_daily` 设计草案
2. `simulation_runs` / `account_equity_snapshots` 与现有 `orders/trades/ledgers` 的 `run_id` 挂接方案

如果优先考虑可执行迁移，建议先做 **第 2 个**。

---

## 12. 一句话总结

> `account_equity_snapshots` 不是替代账户状态表，而是为每个账户在每个关键模拟时点留下可分析、可对比、可追溯的权益与风险轨迹。它是未来净值曲线、排行榜、回撤分析和 agent 表现对比的核心历史基础表。
