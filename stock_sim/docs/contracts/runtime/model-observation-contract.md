# UTI-STOCKSIM 模型 Observation Contract（初版）

_创建时间：2026-03-23 17:25 (Asia/Shanghai)_

## 1. 文档目的

本文档用于定义模型训练 / 在线推理 / 高频仿真桥接时，模型输入 observation 的正式契约。

目标是避免未来长期出现以下问题：

- 训练脚本各自临时拼 observation
- 同一模型在不同环境看到的字段不一致
- GUI 看的数据和模型吃的数据不是同一语义层
- runtime truth、bars 特征、衍生指标混在一起没有边界
- 高速迭代中 observation silently drift（悄悄漂移）

因此，本文档的作用是：

> **给模型输入建立一个正式、可版本化、可测试、可扩展的 contract。**

---

## 2. 设计原则

## 2.1 observation 必须分层

模型输入不是一坨任意 dict，而应分成至少四层：

1. `market`：市场权威状态
2. `account`：账户/持仓权威状态
3. `context`：时间/运行上下文
4. `features`：衍生特征与模型辅助输入

这样做的目的是避免：

- 把权威字段和衍生字段混为一谈
- 模型对“缓存特征”误以为是“交易真相”
- 后期无法追踪字段来源

---

## 2.2 observation 必须区分 authority 与 derivation

建议将字段分为两类：

### authoritative（权威）
来自 runtime truth，例如：
- `last_price`
- `bid_levels`
- `cash`
- `positions`
- `borrowed_qty`

### derived（衍生）
来自聚合/缓存/特征工程，例如：
- MA
- RSI
- bars_window
- normalized returns
- feature vector

模型可以同时使用二者，但 bridge 层和测试必须知道：

> 哪些字段是交易真相，哪些字段只是派生输入。

---

## 2.3 observation 应尽量避免 GUI 语义

observation 不应包含 GUI 特有表达，例如：

- panel state
- widget visibility
- adapter-specific labels
- UI placeholder / debug text

模型只应看到 runtime-friendly contract，而不是 UI-friendly payload。

---

## 2.4 observation 应支持版本化

建议每份 observation 都具备版本字段，例如：

- `contract_version`

这样后续扩字段或改结构时，旧模型和旧训练结果不会完全失去可解释性。

---

## 3. 顶层结构

建议 observation 统一为如下结构：

```python
{
  "contract_version": "obs.v1",
  "market": {...},
  "account": {...},
  "context": {...},
  "features": {...}
}
```

说明：

- `market` / `account` / `context` / `features` 四个顶层 key 建议长期保留
- 即使某部分暂无数据，也建议返回空对象或明确空值，而不是结构漂移

---

## 4. `market` contract

`market` 用于表达模型当前面对的市场状态。

## 4.1 最小字段（推荐）

```python
"market": {
  "symbol": "AAA",
  "last_price": 10.05,
  "volume": 150000,
  "turnover": 1509000.0,
  "bid_levels": [[10.05, 1200], [10.04, 800]],
  "ask_levels": [[10.06, 600], [10.07, 700]],
  "best_bid": 10.05,
  "best_ask": 10.06,
  "spread": 0.01,
  "market_phase": "CONTINUOUS"
}
```

## 4.2 字段说明

- `symbol`
  - 当前标的
  - authoritative
- `last_price`
  - 最新成交价或最近有效价格
  - authoritative
- `volume`
  - 当前累计成交量
  - authoritative
- `turnover`
  - 当前累计成交额
  - authoritative
- `bid_levels`
  - 买盘前 N 档
  - authoritative / snapshot-derived but runtime-authoritative
- `ask_levels`
  - 卖盘前 N 档
  - authoritative / snapshot-derived but runtime-authoritative
- `best_bid`
  - 第一买价
- `best_ask`
  - 第一卖价
- `spread`
  - `best_ask - best_bid`
  - derived, but cheap/runtime-near
- `market_phase`
  - 如 `CALL_AUCTION` / `CONTINUOUS` / `CLOSED`
  - authoritative

## 4.3 可扩展字段

未来可加：

- `open`
- `close`
- `high`
- `low`
- `vwap`
- `trade_count`
- `imbalance`
- `snapshot_ts`

---

## 5. `account` contract

`account` 用于表达模型当前账户状态。

## 5.1 最小字段（推荐）

```python
"account": {
  "account_id": "ACC1",
  "cash": 988765.12,
  "frozen_cash": 5000.0,
  "frozen_fee": 12.5,
  "equity": 1002310.44,
  "gross_exposure": 152000.0,
  "net_exposure": 86000.0,
  "positions": [
    {
      "symbol": "AAA",
      "quantity": 1500,
      "frozen_qty": 0,
      "avg_price": 9.97,
      "borrowed_qty": 0
    }
  ]
}
```

## 5.2 字段说明

- `account_id`
  - 当前账户标识
- `cash`
  - 可用现金
  - authoritative
- `frozen_cash`
  - 冻结现金
  - authoritative
- `frozen_fee`
  - 冻结手续费
  - authoritative
- `equity`
  - 当前权益
  - 可为 authoritative-near derived
- `gross_exposure`
  - 总名义敞口
  - derived
- `net_exposure`
  - 净敞口
  - derived
- `positions`
  - 当前持仓数组

### `positions[*]`
- `symbol`
- `quantity`
- `frozen_qty`
- `avg_price`
- `borrowed_qty`

这些字段未来必须和 runtime account semantics 保持一致，不能由 GUI summary 近似代替。

## 5.3 可扩展字段

未来可加：

- `available_to_sell`
- `unrealized_pnl`
- `realized_pnl`
- `margin_used`
- `drawdown`
- `position_weights`

---

## 6. `context` contract

`context` 用于表达模型当前所处的运行上下文。

## 6.1 最小字段（推荐）

```python
"context": {
  "sim_day": "2025-01-06",
  "sim_dt": "2025-01-06T09:30:15",
  "run_id": "run-20250323-001",
  "episode_id": "ep-0001",
  "step_index": 124,
  "symbol_universe": ["AAA", "BBB", "CCC"]
}
```

## 6.2 字段说明

- `sim_day`
  - 仿真交易日
- `sim_dt`
  - 仿真时间戳
- `run_id`
  - 当前运行实例标识
- `episode_id`
  - 当前训练/推理 episode 标识
- `step_index`
  - 当前步数
- `symbol_universe`
  - 当前环境可交易标的集合

## 6.3 当前建议

即使当前 `run_id` / `episode_id` 尚未完全贯穿到代码，也建议 contract 先预留这些字段。

---

## 7. `features` contract

`features` 用于承载衍生特征和辅助输入。

## 7.1 最小字段（推荐）

```python
"features": {
  "bars_window": {
    "timeframe": "1m",
    "rows": [
      {"open": 10.0, "high": 10.1, "low": 9.98, "close": 10.05, "volume": 12000}
    ]
  },
  "indicators": {
    "ma_5": 10.01,
    "ma_20": 9.94,
    "rsi_14": 58.2
  },
  "feature_vector": [0.01, -0.03, 0.12]
}
```

## 7.2 字段说明

- `bars_window`
  - K线窗口
  - derived
- `indicators`
  - 技术指标
  - derived
- `feature_vector`
  - 压缩后的训练输入向量
  - derived

## 7.3 原则

- `features` 是可选层，但结构建议稳定
- 即使某模型只吃向量，也应保留 `market` / `account` / `context`
- 未来若做不同模型 profile，可允许 `features` 因策略不同而变化，但顶层结构尽量不变

---

## 8. 最小 Observation 示例

```python
{
  "contract_version": "obs.v1",
  "market": {
    "symbol": "AAA",
    "last_price": 10.05,
    "volume": 150000,
    "turnover": 1509000.0,
    "bid_levels": [[10.05, 1200], [10.04, 800]],
    "ask_levels": [[10.06, 600], [10.07, 700]],
    "best_bid": 10.05,
    "best_ask": 10.06,
    "spread": 0.01,
    "market_phase": "CONTINUOUS"
  },
  "account": {
    "account_id": "ACC1",
    "cash": 988765.12,
    "frozen_cash": 5000.0,
    "frozen_fee": 12.5,
    "equity": 1002310.44,
    "gross_exposure": 152000.0,
    "net_exposure": 86000.0,
    "positions": [
      {
        "symbol": "AAA",
        "quantity": 1500,
        "frozen_qty": 0,
        "avg_price": 9.97,
        "borrowed_qty": 0
      }
    ]
  },
  "context": {
    "sim_day": "2025-01-06",
    "sim_dt": "2025-01-06T09:30:15",
    "run_id": "run-20250323-001",
    "episode_id": "ep-0001",
    "step_index": 124,
    "symbol_universe": ["AAA"]
  },
  "features": {
    "bars_window": {
      "timeframe": "1m",
      "rows": []
    },
    "indicators": {},
    "feature_vector": []
  }
}
```

---

## 9. 不同运行模式下的 contract 约束

## 9.1 手工 GUI 模式

- GUI 可以展示比 contract 更多的东西
- 但 bridge 输出给模型的 observation 仍应遵守本 contract

## 9.2 训练模式

- 应优先保证字段稳定性
- 不应为了临时实验随意漂移 key 结构

## 9.3 高频推理模式

- 应优先保证权威字段低延迟
- `features` 可延迟或裁剪
- `market` / `account` / `context` 不应轻易缺失

---

## 10. 当前不建议做的事

- 不建议直接把 GUI detail payload 当 observation
- 不建议让不同模型各自定义完全不同的顶层结构
- 不建议长期依赖匿名 list/tuple 传 observation
- 不建议把权威字段和衍生字段混在同一层没有来源说明

---

## 11. 后续建议

建议紧接着补：

1. `docs/contracts/runtime/model-action-contract.md`
2. `docs/tasks/runtime/model-bridge-implementation-plan.md`

如果进入代码落地阶段，应让以下内容首先对齐：

- observation builder 的输出形状
- runtime truth 字段来源
- 高频模式下哪些字段必须实时，哪些允许降级

---

## 12. 一句话结论

> 模型 observation 必须从“训练脚本里随手拼的数据”升级为正式 contract：按 `market / account / context / features` 分层，区分权威字段与衍生字段，并为未来高频训练与在线推理提供稳定、可测试、可版本化的输入基线。
