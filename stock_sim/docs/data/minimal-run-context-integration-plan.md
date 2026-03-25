# 最小 RunContext 代码接入方案

_Last updated: 2026-03-22_

本文档是从：

- `simulation_runs` 设计
- `account_equity_snapshots` 设计
- `run_id` 挂接方案
- `RunContext` 运行时桥梁设计

进一步落到**第一批最小代码改造范围**的执行清单。

目标不是一次性完成所有 run-level 架构改造，而是用最小改动，先把：

- `orders`
- `order_events`
- `trades`
- `ledgers`

这四条核心写入链打通到 `RunContext` / `run_id` 体系里。

---

## 1. 目标

### 第一批必须实现的目标

1. `OrderService` 可选接收 `run_context`
2. `AccountService` 可选接收 `run_context`
3. `orders` 持久化时可写 `run_id`
4. `order_events` 持久化时可写 `run_id`
5. `trades` 持久化时可写 `run_id`
6. `ledgers` 持久化时可写 `run_id`
7. 没有 `run_context` 时，旧逻辑继续工作

---

## 2. 第一批改动边界

## 2.1 本次建议改动的文件

### persistence 模型
- `persistence/models_order.py`
- `persistence/models_order_event.py`
- `persistence/models_trade.py`
- `persistence/models_ledger.py`

### 运行时服务
- `services/order_service.py`
- `services/account_service.py`

### 新增运行时上下文代码（建议）
- `services/run_context.py` 或 `core/run_context.py`

### 文档 / 测试
- 新增最小接入测试文件
- 更新相关模块状态文档

---

## 2.2 本次明确不动的范围

第一批先不要碰：

- `event_persistence_service`
- `bars_*`
- `snapshots_1s`
- `agent_bindings`
- `accounts`
- `positions`
- `leaderboard`
- `recovery markers`

原因：
先把核心事实写入链做通，避免改动面失控。

---

## 3. schema 最小改造建议

## 3.1 `orders`

### 新增字段
- `run_id` (`String(64)` 或未来 PostgreSQL 中的 UUID)

### 第一批要求
- 允许为空
- 加索引

### 目标语义
- 如果订单来源于某次正式 run，则写入对应 `run_id`
- 否则为 `NULL`

---

## 3.2 `order_events`

### 新增字段
- `run_id`

### 第一批要求
- 允许为空
- 加索引

### 目标语义
- 与订单归属保持一致

---

## 3.3 `trades`

### 新增字段
- `run_id`

### 第一批要求
- 允许为空
- 加索引

### 目标语义
- 某次 run 中产生的全部成交都可按 `run_id` 查询

---

## 3.4 `ledgers`

### 新增字段
- `run_id`

### 第一批要求
- 允许为空
- 加索引

### 目标语义
- 资金变化可按 run 聚合与回溯

---

## 4. 运行时最小接入方式

## 4.1 推荐增加 RunContext 数据结构

建议新增一个最小实现文件，例如：

- `services/run_context.py`

### 最低结构

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(slots=True)
class RunContext:
    run_id: str
    run_type: str
    scenario_name: str | None = None
    sim_day: int | None = None
    sim_dt: datetime | None = None
    config_version: str | None = None
    speed_profile: str | None = None
```

第一批不必把它做得过大。

---

## 4.2 `OrderService` 构造器改造

### 当前形态
```python
OrderService(session, engine=None, instrument_service=None)
```

### 第一批建议改为
```python
OrderService(session, engine=None, instrument_service=None, run_context=None)
```

### 内部新增字段
- `self.run_context = run_context`

### 辅助接口建议
```python
def _get_run_id(self):
    return None if self.run_context is None else self.run_context.run_id
```

---

## 4.3 `AccountService` 构造器改造

### 当前形态
```python
AccountService(session)
```

### 第一批建议改为
```python
AccountService(session, run_context=None)
```

### 内部新增字段
- `self.run_context = run_context`

### 辅助接口建议
```python
def _get_run_id(self):
    return None if self.run_context is None else self.run_context.run_id
```

---

## 4.4 `OrderService` 内部需要接入的位置

### A. `_persist_order()`
写 `OrderORM` 时补 `run_id`

### B. `_persist_state()`
若更新订单状态，不必重复修改 `run_id`，但应保持已有值不丢失

### C. `_persist_event()`
写 `OrderEvent` 时补 `run_id`

### D. `_after_trades()`
写 `TradeORM` 时补 `run_id`

### E. `flush_batch()`
批量成交写 `TradeORM` 时补 `run_id`

---

## 4.5 `AccountService` 内部需要接入的位置

### A. `_write_ledger()`
写 `Ledger` 时补 `run_id`

### B. 后续（非第一批）
未来 equity snapshot writer 也要使用同一个 `run_context`

---

## 5. 最小测试计划

## 5.1 新增测试目标

### 测试 1：无 RunContext 兼容
目标：
- 不传 `run_context` 时现有下单/结算路径仍能工作
- `run_id` 允许为空

### 测试 2：有 RunContext 时 order 写入 run_id
目标：
- `OrderORM.run_id == ctx.run_id`

### 测试 3：有 RunContext 时 trade 写入 run_id
目标：
- 成交落库记录带 `run_id`

### 测试 4：有 RunContext 时 ledger 写入 run_id
目标：
- 账本落库记录带 `run_id`

### 测试 5：有 RunContext 时 order_event 写入 run_id
目标：
- 生命周期事件落库记录带 `run_id`

---

## 5.2 第一批测试不强求的内容

不在第一批里验证：
- `event_log.run_id`
- `bars_*` / `snapshots_1s` 的 run_id
- equity snapshots 写入
- 多 run 并行上下文冲突

这些都应放在第二批以后。

---

## 6. 兼容策略

## 6.1 为什么第一批一定要允许 `run_context=None`

因为当前系统还有很多路径：
- 旧测试
- 小脚本
- 手工调用
- smoke / demo

如果强行要求所有地方都传 run_context，会立刻扩大改动面。

### 第一批兼容原则
- 能不破就不破
- 新路径可用 run_id
- 旧路径继续可跑

---

## 6.2 第一批不建议的做法

### 不建议 1：直接强制所有写入必须有 run_id
会导致：
- 现有系统大面积补参数
- 改动失控

### 不建议 2：先上 contextvar 再说
这会把第一批复杂度拉高。

### 不建议 3：同时改太多外围服务
第一批先打通 orders/trades/ledgers/order_events 就足够了。

---

## 7. 推荐实施顺序

### Step 1
新增 `RunContext` 数据结构代码文件

### Step 2
给四张 persistence 模型加 `run_id`
- `orders`
- `order_events`
- `trades`
- `ledgers`

### Step 3
改 `OrderService` 构造器与写入点

### Step 4
改 `AccountService` 构造器与 `_write_ledger()`

### Step 5
新增/调整最小测试

### Step 6
文档同步更新

---

## 8. 第一批完成标准

当满足以下条件时，可视为第一批完成：

1. `OrderService(run_context=ctx)` 能正常工作
2. `AccountService(run_context=ctx)` 能正常工作
3. 新写入的 order / order_event / trade / ledger 都能带 `run_id`
4. 不传 `run_context` 的旧路径不报错
5. 对应测试覆盖至少有 3~5 条

---

## 9. 一句话总结

> 最小 RunContext 代码接入方案的目标，不是一次把全部 run 架构改完，而是用最小改动先打通 `orders → trades → ledgers → order_events` 这条核心事实链，让 `run_id` 第一次真正从设计文档进入可执行代码路径。
