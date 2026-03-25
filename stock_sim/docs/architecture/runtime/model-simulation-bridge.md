# UTI-STOCKSIM 模型-仿真高频桥接方案（初版）

_创建时间：2026-03-23 17:14 (Asia/Shanghai)_

## 1. 文档目的

本文档用于定义未来模型训练 / 在线推理 与交易仿真平台之间的高频桥接方案。

目标不是先写某个临时训练脚本，而是先明确：

1. 模型从哪里拿数据
2. 模型向哪里发动作
3. 哪一层负责把动作变成订单/调仓指令
4. 哪些路径适合高频
5. 哪些路径不能承载高频
6. GUI 与训练运行时如何解耦

本文档面向未来的：

- 强化学习训练
- 模型在线推理
- 高频参数交互
- 多账户/多 agent 仿真
- 运行结果回放与分析

---

## 2. 核心结论

## 2.1 GUI 不是高频模型交互总线

未来模型与仿真平台的高频交互，不应通过以下层完成：

- `app/panels/*`
- `app/controllers/*`
- `app/ui/adapters/*`
- Qt widget 事件

原因：

- GUI 层天然面向显示与交互，不面向高频执行闭环
- 会引入线程模型复杂度
- 会引入刷新频率与运行频率耦合
- 会让“UI correctness”和“runtime correctness”混在一起
- 高频情况下容易卡顿、抖动、调试困难

因此：

> **GUI 只能是观察与控制层，不能是模型高频运行时主链路。**

---

## 2.2 模型必须通过 runtime bridge 接入仿真平台

未来模型应通过一个明确的 runtime bridge 与平台交互。

这个 bridge 的职责是：

- 收集 observation
- 接收 action
- 将 action 转换为 runtime order/rebalance 语义
- 执行后返回 execution/result/info
- 控制高频路径的状态流转

这个 bridge 可以复用/扩展现有雏形：

- `rl/account_adapter.py`
- `rl/trading_env.py`
- `rl/vectorized_env.py`
- `services/order_service.py`
- `services/account_service.py`

但它最终应被提升为一个**平台级 runtime bridge 概念**，而不是仅仅属于 RL demo。

---

## 2.3 高频路径优先走内存态 / 事件态，不走 GUI，不走关系库往返

高频模型回路里，优先路径应为：

- in-memory runtime state
- event bus / event snapshot
- ring buffer
- 必要时 Redis / shared cache

不推荐把以下路径作为高频主回路：

- 每 step 查 SQL 数据库
- 通过 GUI panel/controller 获取数据
- 通过文件系统做 step 级交换

数据库更适合承担：

- run 级落盘
- 结果归档
- replay
- 审计
- snapshot/history

而不是每一步 observation/action 的主交换路径。

---

## 3. 目标架构

建议未来形成如下分层：

```text
+--------------------------------------------------------------+
| GUI / Desktop App                                            |
| app/ui, app/panels, app/controllers, app/ui/adapters         |
| 用于监控、配置、调试、回放、人工控制                         |
+--------------------------------------------------------------+
| Model Runtime Bridge                                         |
| observation builder / action translator / execution adapter  |
| reward info / reject info / 高频步进 / 向量化                |
+--------------------------------------------------------------+
| Runtime Truth                                                |
| core/* + services/order_service + account/risk/matching      |
+--------------------------------------------------------------+
| Persistence / Replay / RunContext / Snapshots / Event Log    |
+--------------------------------------------------------------+
```

这意味着：

- GUI 不拥有模型 runtime truth
- RL/training 也不应自造另一套交易语义
- bridge 层负责把模型世界和交易世界接起来

---

## 4. Observation contract（模型输入契约）

未来应将模型看到的 observation 正式化，而不是长期在训练代码里临时拼接。

## 4.1 Observation 的来源层次

建议按优先级划分：

### Level A：交易运行时核心状态（权威）
- latest price
- best bid / best ask
- top-N bid/ask depth
- latest trade volume
- current position
- available cash
- frozen cash
- borrowed qty
- account equity / exposure

### Level B：聚合特征 / bars / indicators（衍生）
- OHLCV
- rolling volume
- moving average
- RSI / MACD
- event-node features
- normalized returns

### Level C：上下文与控制信息（辅助）
- sim time / sim day
- market phase
- symbol status
- run id / episode id
- reject flags / risk state

---

## 4.2 Observation contract 最小建议字段

建议至少支持以下最小 observation：

### 市场状态
- `symbol`
- `last_price`
- `volume`
- `turnover`
- `bid_levels`
- `ask_levels`
- `spread`
- `market_phase`

### 账户状态
- `cash`
- `frozen_cash`
- `frozen_fee`
- `positions`
- `borrowed_qty`
- `equity`
- `gross_exposure`
- `net_exposure`

### 时间与上下文
- `sim_day`
- `sim_dt`
- `run_id`
- `step_index`

### 衍生特征（可选）
- `bars_window`
- `feature_vector`
- `indicator_vector`

---

## 4.3 Observation contract 的结构建议

建议以一个明确 DTO/contract 表达，而不是散落 dict：

```python
{
  "market": {...},
  "account": {...},
  "context": {...},
  "features": {...}
}
```

这样有几个好处：

- 便于版本化
- 便于测试
- 便于将来跨进程/远程推理
- 便于区分权威字段和衍生字段

---

## 5. Action contract（模型输出契约）

模型输出不能长期用“随便一个脚本 dict”来表达，必须标准化。

建议未来同时支持两类动作语义。

## 5.1 类型 A：订单级动作（execution-oriented）

适合：

- 微观执行研究
- 订单级策略
- 强调限价/市价/TIF 的模型

建议字段：

- `symbol`
- `side`
- `order_type`
- `price`
- `quantity`
- `tif`
- `meta`

优点：

- 贴近真实交易
- 与 runtime truth 最接近

风险：

- 动作空间复杂
- 学习难度高

---

## 5.2 类型 B：目标仓位 / 目标权重动作（portfolio-oriented）

适合：

- 组合控制
- RL 训练
- 高频调仓
- 向量化环境

建议字段：

- `symbol` 或 `symbols`
- `target_position`
  或
- `target_weight`
- `max_leverage`
- `allow_short`
- `rebalance_mode`

优点：

- 更适合训练
- 更稳
- 更容易统一风控

风险：

- 需要 bridge 负责翻译为执行动作

---

## 5.3 当前建议

未来平台最好**同时支持两种动作层级**：

- 研究/训练优先用：目标权重/目标仓位
- 精细执行/微结构实验用：订单级动作

不要强迫所有模型都直连订单级动作。

---

## 6. Bridge 层的职责定义

建议新增/明确一个模型-仿真 bridge 层，其职责至少包括：

1. observation build
2. action validate
3. action translate
4. execution dispatch
5. result pack
6. reward / info build
7. 高频状态缓存
8. run_id / episode_id / step_id 透传

---

## 6.1 不应由 bridge 层承担的职责

bridge 层不应负责：

- GUI 渲染
- 数据库主持久化策略设计
- 撮合核心规则
- 账户最终真相
- 风控最终真相

这些仍应留在 runtime truth 层。

---

## 7. 高频路径建议

## 7.1 单步交互建议路径

```text
runtime state -> observation builder -> model inference/train step
             -> action translator -> order/rebalance dispatch
             -> runtime execute -> result/reward/info -> next step
```

这条路径应尽可能避免：

- GUI 往返
- DB 往返
- 文件 I/O

---

## 7.2 高频数据交换建议

### 优先方案（单进程）
- 直接内存对象
- ring buffer
- lightweight DTO

### 中期方案（跨进程）
- Redis / shared cache
- event channel
- 明确序列化 contract

### 不建议方案
- 每 step SQL roundtrip
- panel/controller 取数
- 文本文件中转

---

## 8. GUI 与训练运行解耦策略

## 8.1 GUI 的职责

GUI 应负责：

- 实时监控
- 参数配置
- 手工控制
- 调试展示
- 回放/审计

## 8.2 训练运行时的职责

训练运行时应负责：

- 高频 step
- observation/action 闭环
- reward 计算
- model rollout
- vectorized batch execution

## 8.3 原则

> GUI 可以观察训练运行时，但训练运行时不应依赖 GUI 存在。

---

## 9. 与现有代码的结合点

当前最适合演进为 bridge 体系基础的部分包括：

- `rl/account_adapter.py`
- `rl/trading_env.py`
- `rl/vectorized_env.py`
- `services/order_service.py`
- `services/account_service.py`
- `services/risk_engine.py`
- `docs/data/run-context-design.md`

当前建议不是推翻它们，而是：

> **把它们从“训练子系统里的实现细节”提升为“平台 runtime bridge 的正式设计对象”。**

---

## 10. 当前最值得优先推进的下一步

## Priority 1
定义 observation contract 初版

## Priority 2
定义 action contract 初版（至少区分订单级 vs 目标权重级）

## Priority 3
明确 bridge 与 GUI/controller 的边界，避免未来高频路径误入 app 层

## Priority 4
把 run_id / episode_id / step_id 贯穿到 bridge 设计中

---

## 11. 建议的后续文档

建议后续继续补两份执行型文档：

1. `docs/contracts/runtime/model-observation-contract.md`
2. `docs/contracts/runtime/model-action-contract.md`

如果确认要进入实现阶段，再补：

3. `docs/tasks/runtime/model-bridge-implementation-plan.md`

---

## 12. 一句话结论

> UTI-STOCKSIM 未来如果要承载模型训练与高频在线推理，就必须把模型交互从 GUI 层剥离出来，建立正式的 runtime bridge，让 observation、action、execution、reward 和 run-context 在同一条高频、可测试、可扩展的运行链路中闭环。
