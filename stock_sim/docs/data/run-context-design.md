# RunContext 设计草案

_Last updated: 2026-03-22_

本文档定义 `RunContext` 这一运行时概念，用于把：

- `simulation_runs`
- `run_id`
- 模拟时间
- 运行模式 / 场景信息

稳定地从“运行调度层”传递到：

- `OrderService`
- `AccountService`
- `event_persistence_service`
- bars / snapshot 写入服务
- 后续的 equity snapshot / recovery / leaderboard 逻辑

---

## 1. 为什么需要 RunContext

目前系统里已经逐步明确：

- 未来需要 `simulation_runs`
- 多张事实表需要挂 `run_id`
- 多次模拟必须有可分离的数据边界

但如果没有运行时上下文对象，后面会立即碰到这些问题：

- `OrderService` 怎么知道当前订单属于哪个 run？
- `AccountService._write_ledger()` 怎么知道该把 ledger 归到哪个 run？
- `event_persistence_service` 怎么给 `event_log` 补 `run_id`？
- bars / snapshots 的持久化怎么知道自己属于哪次模拟？
- 测试里如何显式构造“有 run / 无 run”两种路径？

因此需要一个明确的运行时桥梁对象：

> `RunContext` = 当前模拟运行的显式运行时上下文

---

## 2. 设计目标

`RunContext` 要解决的是**运行态身份传递**问题，而不是存所有业务数据。

### 目标
1. 给核心服务统一提供 `run_id`
2. 提供当前 run 的最小关键元信息
3. 避免底层代码靠全局猜测当前 run
4. 兼容当前无 `run_id` 的开发/测试路径
5. 为后续 `simulation_runs` / `account_equity_snapshots` / `event_log` 写入打基础

---

## 3. 设计原则

### 原则 1：显式传递优于隐式猜测
首选：
- 在创建服务对象时显式传入 `run_context`

不推荐长期依赖：
- 全局变量
- 猜当前唯一运行对象
- 从任意事件 payload 倒推 run

### 原则 2：允许无 run 场景
当前系统仍有大量：
- pytest
- smoke
- 本地 demo
- 小脚本

这些路径不能因为没 run_id 就全部炸掉。

所以：
- `run_context` 可以为空
- 关键写入表的 `run_id` 初期允许为 `NULL`

### 原则 3：RunContext 只存“运行桥梁信息”
不要把它设计成一个巨大的万能对象。

它应该只承载：
- run 身份
- 场景摘要
- 当前模拟时间
- 运行类型
- 配置摘要引用

---

## 4. RunContext 最小字段集合

## 4.1 推荐最小字段

### `run_id`
- 类型：`str`
- 含义：当前模拟运行唯一标识

### `run_type`
- 类型：`str`
- 示例：
  - `simulation`
  - `backtest`
  - `replay`
  - `training`
  - `paper`

### `scenario_name`
- 类型：`str | None`
- 含义：场景/实验名

### `sim_day`
- 类型：`int | None`
- 含义：当前模拟日

### `sim_dt`
- 类型：`datetime | None`
- 含义：当前模拟时点

### `config_version`
- 类型：`str | None`
- 含义：配置版本摘要

### `speed_profile`
- 类型：`str | None`
- 含义：当前运行速度摘要

---

## 4.2 可选扩展字段

### `environment_tag`
- `dev` / `research` / `paper-prod-like`

### `owner`
- 当前 run 的发起者 / 维护者

### `tags`
- 运行标签列表

### `meta`
- 额外上下文信息（轻量）

---

## 5. 推荐数据结构

### Python 草案

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass(slots=True)
class RunContext:
    run_id: str
    run_type: str
    scenario_name: str | None = None
    sim_day: int | None = None
    sim_dt: datetime | None = None
    config_version: str | None = None
    speed_profile: str | None = None
    environment_tag: str | None = None
    owner: str | None = None
    tags: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)
```

### 设计说明
- 用 dataclass 足够
- `slots=True` 可以让它更轻量
- `meta` 只做补充，不应成为垃圾桶

---

## 6. 推荐接入方式

## 6.1 首选：构造器显式注入

### 推荐方式

```python
OrderService(session, engine=..., instrument_service=..., run_context=ctx)
AccountService(session, run_context=ctx)
```

### 为什么最好
- 调用关系清晰
- 测试容易构造
- 不依赖进程全局状态
- 更适合未来多 run / 多场景并行

---

## 6.2 次优：contextvar / thread-local

### 适用场景
- 迁移早期，不想改太多构造器签名
- 需要从调用链隐式读取当前运行上下文

### 风险
- 可见性差
- 调试更难
- 容易被误用成“看不见的全局变量”

### 结论
只建议做过渡方案，不建议作为最终架构。

---

## 6.3 不推荐：从底层写入时猜当前 run

例如：
- 进入 `_write_ledger()` 时再想办法全局猜当前运行是谁
- 在 event persistence 层根据 topic 反推出 run

这种方式后面一定会脏。

---

## 7. 建议接入的服务对象

## 7.1 `OrderService`

### 为什么优先接这里
订单是整个业务链的入口。

### 推荐字段
- `self.run_context`

### 受影响的方法
- `_persist_order()`
- `_persist_state()`
- `_persist_event()`
- `_after_trades()`
- `flush_batch()`

### 作用
- 写 `orders.run_id`
- 写 `order_events.run_id`
- 写 `trades.run_id`

---

## 7.2 `AccountService`

### 推荐字段
- `self.run_context`

### 受影响的方法
- `_write_ledger()`
- 未来的 equity snapshot writer

### 作用
- 写 `ledgers.run_id`
- 写 `account_equity_snapshots.run_id`

---

## 7.3 `event_persistence_service`

### 推荐字段来源
- 显式传入
- 或临时从 contextvar 读取（过渡）

### 作用
- 写 `event_log.run_id`

---

## 7.4 未来其它接入点

- bars persistence
- snapshot persistence
- leaderboard aggregation
- recovery markers
- config change logging

---

## 8. 推荐兼容策略

## 8.1 短期策略

允许：
- `run_context = None`
- 没有 `run_id` 时，现有逻辑继续工作
- 持久化时 `run_id` 可为空

这样可以保证：
- 当前测试不全部重写
- 小脚本不被阻断
- 迁移可以渐进推进

---

## 8.2 中期策略

对于正式 run：
- 创建 `simulation_runs`
- 生成 `RunContext`
- 核心服务全部接入 `run_context`

对于测试/本地路径：
- 继续允许空上下文

---

## 8.3 长期策略

未来一旦主链路稳定：
- 正式模拟运行必须带 `RunContext`
- 关键事实表新数据默认不应再缺失 `run_id`

---

## 9. 推荐的辅助接口

可以考虑增加一个轻量 helper：

```python
def get_run_id(run_context) -> str | None:
    return None if run_context is None else run_context.run_id
```

或：

```python
def apply_run_context(obj, run_context):
    if run_context is not None:
        obj.run_id = run_context.run_id
```

目的是减少每个写入点重复写样板代码。

---

## 10. 推荐的第一步落地顺序

### Step 1
定义 `RunContext` 数据结构（文档 + 代码草案）

### Step 2
给 `OrderService` 增加可选参数：
- `run_context=None`

### Step 3
给 `AccountService` 增加可选参数：
- `run_context=None`

### Step 4
先在以下写入链使用：
- orders
- trades
- ledgers
- order_events

### Step 5
再扩展到：
- event_log
- account_equity_snapshots
- bars/snapshots

---

## 11. 与 simulation_runs 的关系

RunContext 不是数据库表，但它应与 `simulation_runs` 一一对应。

也就是说：
- 创建一条 `simulation_runs` 记录
- 生成一个对应的 `RunContext`
- 后续整个 run 的服务调用都持有它

关系可以理解为：

> `simulation_runs` 是持久化主记录
> `RunContext` 是运行时同名影子对象

---

## 12. 一句话总结

> `RunContext` 是把“数据设计”变成“代码可落地设计”的桥梁。没有它，run_id 只能停留在表结构层；有了它，orders / trades / ledgers / event_log 才能在运行时稳定共享同一个模拟运行身份。
