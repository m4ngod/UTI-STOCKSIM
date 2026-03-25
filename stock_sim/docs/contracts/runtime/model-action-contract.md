# UTI-STOCKSIM 模型 Action Contract（初版）

_创建时间：2026-03-23 17:27 (Asia/Shanghai)_

## 1. 文档目的

本文档用于定义模型训练 / 在线推理 / 高频仿真桥接时，模型输出 action 的正式契约。

它要解决的问题是：

- 模型输出不能长期是随意 dict
- 训练模式与推理模式不能各说各话
- 权重调仓型模型与订单型模型需要统一落在平台可执行语义上
- 高频运行下 action 必须可校验、可翻译、可测试、可回放

因此，本文档的作用是：

> **给模型输出建立一个正式、可版本化、可翻译、可执行的 contract。**

---

## 2. 设计原则

## 2.1 action 必须先标准化，再执行

模型输出不能直接“塞进平台里试试看”，而必须经过：

1. contract parse
2. schema validate
3. semantic validate
4. translate to runtime intent
5. dispatch to runtime truth

也就是说：

> 模型输出不是订单本身，而是要先变成平台能理解的标准动作对象。

---

## 2.2 action 应同时支持两类语义

当前建议同时支持：

### Type A：订单级动作（order-oriented）
适合：
- 微观执行研究
- 订单级策略
- 强调价格与 TIF 的模型

### Type B：目标仓位/目标权重动作（portfolio-oriented）
适合：
- RL 训练
- 高频调仓
- 多标的组合控制
- 向量化环境

这两类动作不应互相覆盖，而应作为并行的正式 contract 类型。

---

## 2.3 action contract 顶层必须稳定

无论动作类型如何，建议顶层统一保留以下信息：

- `contract_version`
- `action_type`
- `target`
- `payload`
- `constraints`
- `meta`

这样未来：

- 可扩版本
- 可加类型
- 可统一日志与回放
- 可统一 bridge 验证逻辑

---

## 3. 顶层结构

建议 action 统一为如下结构：

```python
{
  "contract_version": "act.v1",
  "action_type": "order" | "target_weight" | "target_position" | "hold",
  "target": {...},
  "payload": {...},
  "constraints": {...},
  "meta": {...}
}
```

---

## 4. Action type A：订单级动作

## 4.1 适用场景

订单级动作适合：

- 限价单/市价单策略
- 盘口敏感模型
- 执行路径研究
- 模拟真实交易行为

---

## 4.2 推荐结构

```python
{
  "contract_version": "act.v1",
  "action_type": "order",
  "target": {
    "account_id": "ACC1",
    "symbol": "AAA"
  },
  "payload": {
    "side": "BUY",
    "order_type": "LIMIT",
    "price": 10.05,
    "quantity": 500,
    "tif": "IOC"
  },
  "constraints": {
    "allow_short": false,
    "max_slippage_bps": 10
  },
  "meta": {
    "model_id": "model-x",
    "decision_ts": "2026-03-23T17:27:00+08:00"
  }
}
```

---

## 4.3 `payload` 字段说明

- `side`
  - `BUY` / `SELL`
- `order_type`
  - `LIMIT` / `MARKET`
- `price`
  - 对 LIMIT 必须提供
  - 对 MARKET 可为 `null`
- `quantity`
  - 整数，建议与 lot 规则保持可翻译性
- `tif`
  - 如 `GFD` / `IOC` / `FOK`

---

## 4.4 校验要求

bridge 层至少应校验：

- `side` 是否合法
- `order_type` 是否合法
- `quantity > 0`
- `price` 与 `order_type` 组合是否合理
- `symbol` 是否在 universe 中
- `tif` 是否为允许值

注意：

- 风控最终真相仍在 runtime truth 层
- 但 bridge 可以做前置结构校验

---

## 5. Action type B：目标权重动作

## 5.1 适用场景

目标权重动作适合：

- 组合型 RL
- 高频调仓
- 多标的权重控制
- 向量化训练

---

## 5.2 推荐结构

```python
{
  "contract_version": "act.v1",
  "action_type": "target_weight",
  "target": {
    "account_id": "ACC1",
    "symbols": ["AAA", "BBB", "CCC"]
  },
  "payload": {
    "weights": {
      "AAA": 0.40,
      "BBB": 0.35,
      "CCC": -0.10
    },
    "cash_buffer_ratio": 0.05,
    "rebalance_mode": "market"
  },
  "constraints": {
    "max_gross_leverage": 1.5,
    "allow_short": true,
    "clip_to_limits": true
  },
  "meta": {
    "model_id": "ppo-v3",
    "decision_ts": "2026-03-23T17:27:00+08:00"
  }
}
```

---

## 5.3 `payload` 字段说明

- `weights`
  - `symbol -> target_weight`
- `cash_buffer_ratio`
  - 预留现金比例
- `rebalance_mode`
  - 如：`market` / `limit_near_mid` / `twap_like`

---

## 5.4 校验要求

bridge 层至少应校验：

- 所有 symbol 是否在当前 universe 内
- 权重是否为可解析数值
- gross leverage 是否超过约束
- 若 `allow_short=false`，负权重是否需要 clip/reject
- 是否需要归一化或缩放

---

## 6. Action type C：目标仓位动作

## 6.1 适用场景

目标仓位动作适合：

- 单标的数量控制
- 组合系统内部已有权重转数量逻辑
- 需要显式 shares target 的策略

---

## 6.2 推荐结构

```python
{
  "contract_version": "act.v1",
  "action_type": "target_position",
  "target": {
    "account_id": "ACC1",
    "symbol": "AAA"
  },
  "payload": {
    "target_quantity": 2000,
    "rebalance_mode": "market"
  },
  "constraints": {
    "allow_short": false,
    "max_order_slices": 3
  },
  "meta": {
    "model_id": "lstm-policy",
    "decision_ts": "2026-03-23T17:27:00+08:00"
  }
}
```

---

## 7. Action type D：hold / no-op

## 7.1 适用场景

用于表示：

- 本步不交易
- 当前状态保持不变
- 模型刻意等待

## 7.2 推荐结构

```python
{
  "contract_version": "act.v1",
  "action_type": "hold",
  "target": {
    "account_id": "ACC1"
  },
  "payload": {},
  "constraints": {},
  "meta": {
    "reason": "confidence_low"
  }
}
```

---

## 8. `target` contract

`target` 用于表达动作作用对象。

## 8.1 推荐字段

- `account_id`
- `symbol` 或 `symbols`
- 未来可扩展：
  - `agent_id`
  - `strategy_id`
  - `portfolio_id`

## 8.2 原则

- 订单级动作通常用单 `symbol`
- 权重动作通常用 `symbols`
- target 层应只表达“作用对象”，不要把执行细节塞进去

---

## 9. `constraints` contract

`constraints` 用于表达模型动作附带的桥接层约束，而不是最终 runtime 风控替代品。

## 9.1 推荐字段

- `allow_short`
- `max_gross_leverage`
- `max_slippage_bps`
- `clip_to_limits`
- `max_order_slices`
- `reject_if_unexecutable`

## 9.2 原则

- bridge 层可先按约束裁剪或拒绝
- runtime 层仍负责最终风控和交易真相
- 不要把 runtime 风控逻辑全部复制到 action contract 中

---

## 10. `meta` contract

`meta` 用于承载调试、追踪、分析、回放辅助信息。

## 10.1 推荐字段

- `model_id`
- `policy_version`
- `decision_ts`
- `inference_latency_ms`
- `confidence`
- `trace_id`
- `notes`

## 10.2 原则

- `meta` 不应成为执行逻辑必需条件
- 它应服务于审计、诊断、回放、实验分析

---

## 11. Bridge 层对 action 的处理建议

建议 future bridge 层按以下阶段处理 action：

### Step 1：parse
识别 `contract_version` / `action_type`

### Step 2：schema validate
确认字段结构完整

### Step 3：semantic validate
确认 symbol、quantity、weights 等是否合理

### Step 4：translate
- `order` -> 订单对象
- `target_weight` -> 调仓意图 -> 一组订单/执行计划
- `target_position` -> 调整目标仓位 -> 一组订单/执行计划
- `hold` -> no-op

### Step 5：dispatch
交给 runtime truth：
- `services/order_service.py`
- account/risk/matching pipeline

### Step 6：result pack
返回执行摘要、拒绝原因、reward/info 等

---

## 12. 当前不建议做的事

- 不建议让不同模型完全自定义 action 顶层结构
- 不建议直接把模型输出字符串/裸 tuple 当正式动作协议
- 不建议用 GUI 层的按钮语义作为模型 action 语义
- 不建议把 bridge 层约束等同于 runtime 风控

---

## 13. 后续建议

建议紧接着补：

1. `docs/tasks/runtime/model-bridge-implementation-plan.md`

在进入实现时优先回答：

- 哪些 action type 先落地
- `target_weight` 如何翻译为执行计划
- 高频模式下 action reject / partial execution / reward info 如何统一

---

## 14. 一句话结论

> 模型 action 必须从“随意输出的策略信号”升级为正式 contract：在顶层统一结构下，至少同时支持订单级动作与目标权重/目标仓位动作，并通过 bridge 层完成验证、翻译和执行，才能支撑未来高频训练与在线推理的真实闭环。
