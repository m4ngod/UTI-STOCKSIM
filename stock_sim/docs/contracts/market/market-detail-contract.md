# UTI-STOCKSIM Market Detail 数据契约

_生成时间：2026-03-22 16:17 (Asia/Shanghai)_

本文档用于把 Market detail 从“多源混合页面”收束为“字段来源、权威性、刷新机制、降级语义明确”的可维护页面。

---

# 1. 文档目标

本契约要解决四个问题：

1. **字段从哪里来**
2. **哪个字段是权威来源，哪个只是辅助来源**
3. **字段如何刷新，可能为什么变旧或缺失**
4. **UI 应该如何诚实地表达这些状态**

该契约不追求一次性把所有数据路径统一为单源，而是先让现状变得**可解释、可调试、可重构**。

---

# 2. 页面范围

本文档覆盖的 Market detail 指当前标的详情区域中以下字段/区块：

- `symbol`
- `timeframe`
- `series`
- `snapshot`
- `order_book`
- `trades`
- `holdings`
- `indicators`
- `detail_health`
- 各类 `*_meta`

主要相关实现文件：

- `app/controllers/market_controller.py`
- `app/panels/market/panel.py`
- `app/ui/adapters/market_adapter.py`
- `app/services/market_data_service.py`
- `app/event_bridge.py`

---

# 3. 当前核心原则

## 3.1 detail 页面不是单一权威数据页

当前 Market detail 本质上是一个**多数据路径聚合页**，而不是一个由单一后端查询直接返回的完整详情对象。

因此，任何字段都必须回答：

- 它来自哪个路径？
- 它是不是权威真相？
- 它更新节奏是什么？
- 它缺失时该怎么解释？

## 3.2 UI 必须诚实表达“权威性”和“状态”

后续 UI 不能再默认：

- 所有字段都同样新鲜
- 所有字段都来自后端权威源
- 所有空值都只是“暂时没加载”

UI 至少应在内部 contract 与 debug/status 层面体现：

- authority
- source
- refresh model
- status

## 3.3 契约优先于表现

在修视觉、修交互、修图表前，必须先明确字段契约。

否则：

- 修复会变成局部补丁
- 页面“看起来统一”，但底层继续混乱
- 调试会越来越难

---

# 4. 字段级正式契约

## 4.1 `symbol`

**含义**
- 当前 detail 正在展示的标的代码

**当前来源**
- `SymbolDetailPanel` 当前选中 symbol 状态

**权威性**
- 当前 detail 视图内权威
- 但不是后端 instrument registry 的声明式真相来源

**刷新方式**
- 用户选择 symbol
- 页面切换 symbol

**状态语义**
- `None`：当前未选中标的
- 非空字符串：当前 detail 已绑定到该 symbol

**UI 规则**
- 不应将空 symbol 渲染成伪详情页
- 无 symbol 时应明确显示“未选择标的”状态

---

## 4.2 `timeframe`

**含义**
- 当前 detail 图表与相关指标使用的时间粒度

**当前来源**
- `SymbolDetailPanel._timeframe`

**权威性**
- detail 视图内部权威
- 不是后端 snapshot 的权威字段

**刷新方式**
- 用户切换 timeframe
- `load_symbol` / `set_timeframe`

**状态语义**
- 缺失时使用默认 timeframe

**UI 规则**
- timeframe 改变后，不应假设 snapshot/order_book 路径也同步切换
- 它主要约束 `series` / `indicators`

---

## 4.3 `series`

**含义**
- 当前 symbol 在当前 timeframe 下的 K 线 / bars 数据

**当前来源**
- `app/services/market_data_service.py`
- 由 app-layer bars cache / fetcher path 提供

**权威性**
- **非 runtime snapshot 权威源**
- 是当前图表区块的工作数据源
- 更接近“前端应用层缓存视图”而非“交易运行时权威详情”

**刷新方式**
- 选中 symbol 时初次加载
- 切换 timeframe 时重载
- 主动 refresh 时更新
- 部分时钟/事件触发轻量刷新

**可能变旧的原因**
- app-layer cache 未刷新
- fetcher 更新节奏与 snapshot path 不一致
- symbol 切换后缓存刚建立

**状态定义**
- `available`：成功加载并可用于绘图
- `missing`：当前没有 bars 数据
- `stale`：有数据，但 freshness 已不足
- `error`：结构不完整或转换失败

**UI 规则**
- 图表区必须允许显示 stale / missing，而不是一律当成“正常但空白”
- 不应把 series 当成 order_book/snapshot 的同源字段

---

## 4.4 `snapshot`

**含义**
- 当前 symbol 的最新快照型行情状态

**当前来源**
- `app/controllers/market_controller.py` 中 merged snapshot cache
- 上游来自 backend snapshot events → `app/event_bridge.py` → frontend batch merge

**权威性**
- **当前 detail 页面中的 quote / order-book 主权威来源**
- 但它仍然是事件驱动缓存，不等同于“随查随取数据库真相”

**刷新方式**
- 事件驱动 batch merge
- 非 series 同步刷新模型

**可能变旧的原因**
- event bridge 延迟
- batch merge 节流
- 当前 symbol 长时间无 snapshot 更新

**状态定义**
- `available`：存在最新快照对象
- `missing`：当前未拿到该 symbol 快照
- `degraded`：存在但 freshness 或字段完整性不足（后续可扩展）

**UI 规则**
- snapshot 应被视为 detail 中盘口/最新价的主来源
- 但要明确它是 event-cache authoritative，而非全系统唯一数据真相

---

## 4.5 `order_book`

**含义**
- detail 中展示的买卖盘档位

**当前来源**
- 从 `snapshot` 派生
- 本身不是独立查询路径

**权威性**
- 与 `snapshot` 权威性绑定
- 当前是 snapshot-driven order book view

**刷新方式**
- 仅随 snapshot 更新

**可能变旧的原因**
- snapshot 未更新
- event bridge 延迟

**状态定义**
- `available`：snapshot 存在且可解析出 bids/asks
- `missing`：snapshot 缺失
- `partial`：仅有部分字段（后续可扩展）

**UI 规则**
- order book 的状态不能脱离 snapshot 单独宣称“最新”
- 若 snapshot 缺失，盘口应显式视为 unavailable，而不是显示伪空表

---

## 4.6 `trades`

**含义**
- 当前 symbol 的最近逐笔/成交带视图

**当前来源**
- `SymbolDetailPanel` 本地 ring buffer
- 由 Trade 事件驱动 append

**权威性**
- **非后端历史成交权威查询**
- 当前只是“本地近期事件视图”

**刷新方式**
- event append
- 切换 symbol 时会重新初始化/清空本地缓冲

**可能变旧或不完整的原因**
- 页面切换后历史不回放
- 仅记录当前订阅期内的局部事件
- 不是数据库历史查询

**状态定义**
- `available`：本地缓冲内有数据
- `empty`：当前无缓冲数据
- `unavailable`：事件链路不可用（后续可扩展）

**UI 规则**
- trades 不能被表达成“完整成交历史”
- 应被视为“recent local tape”而不是 authoritative trade history

---

## 4.7 `holdings`

**含义**
- 当前 symbol 相关持仓/构成辅助显示

**当前来源**
- app-layer helper 或 placeholder payload
- 当前不是直接对接 runtime authoritative holdings path

**权威性**
- **非权威**
- 是 detail 页面中当前最弱的一条数据契约

**刷新方式**
- opportunistic helper fetch
- 若无可用 helper，则返回 placeholder

**可能失真原因**
- 不是 runtime 真正账户/持仓查询
- 可能缺失、占位、简化

**状态定义**
- `available`：helper 返回了可展示数据
- `unavailable`：当前没有 helper 数据
- `placeholder`：显式占位，不代表真实持仓
- `error`：helper 执行失败

**UI 规则**
- holdings 不能伪装成权威持仓分布
- placeholder 时应避免渲染假饼图/假占比
- 后续若要升级为权威路径，必须单独定义新 contract

---

## 4.8 `indicators`

**含义**
- 基于当前 `series` 派生的技术指标结果

**当前来源**
- `indicator_executor`
- 输入来自 `MarketDataService.get_closes()`

**权威性**
- 派生数据
- 权威性依赖 `series` 输入质量

**刷新方式**
- `load_symbol` / `refresh` 后调度
- bars 长度变化时失效重算

**状态定义**
- `available`
- `pending`
- `missing`
- `error`

**UI 规则**
- indicators 不应在 series 缺失时假装有效
- 任何指标解释都必须默认依赖当前 series 路径，而非 snapshot 路径

---

## 4.9 `detail_health`

**含义**
- 用于表达 detail 各子区块健康状态的聚合状态对象

**当前作用**
- 让 UI 和调试逻辑知道：
  - series 是否 stale/missing
  - snapshot 是否 missing
  - trades 是否 empty
  - overall 是否 degraded

**权威性**
- 页面级状态判断，不是业务真相对象

**建议状态字段**
- `series_status`
- `snapshot_status`
- `trades_status`
- `holdings_status`（建议补齐）
- `overall`

**UI 规则**
- detail_health 是页面状态解释器，不应被误用为业务数据本身

---

## 4.10 `*_meta`

**含义**
- 用于把每个区块的 source / authority / refresh / status 显式结构化

**当前价值**
- 它们是 detail 页面从“黑箱聚合”走向“可维护 contract”的关键桥梁

**必须坚持的字段**
- `source`
- `authoritative`
- `status`
- `refresh`（适用时）

**UI 规则**
- 即使不长期面向终端用户显示，也应保留给开发、调试、自动化验证使用

---

# 5. 页面级状态规则

## 5.1 detail 页面 overall != 所有区块都新鲜

`detail_health.overall = ok` 的最低含义应是：

- snapshot 可用
- series 可用且非明显 stale

但它不应自动意味着：

- trades 完整
- holdings 权威
- indicators 一定已完成计算

## 5.2 detail 页面允许“部分可用”

这是当前架构下必须接受的现实。

例如：

- snapshot available
- series stale
- trades empty
- holdings placeholder

这种组合不是异常，而是需要被 contract 明确支持的正常状态。

## 5.3 缺失不等于报错

以下情况需要严格区分：

- `missing`：没有数据
- `stale`：有旧数据
- `placeholder`：显式占位
- `error`：执行失败或结构损坏

UI 和测试都不能把它们混为一谈。

---

# 6. 当前建议的代码收束动作

基于本契约，接下来应推进以下代码动作：

## 6.1 补全 `detail_health`

建议增加：

- `holdings_status`
- `indicators_status`

让页面级健康状态更完整。

## 6.2 统一 `*_meta` 字段结构

当前已有方向，但建议进一步统一键结构，避免不同区块 meta 形状不一致。

建议统一最小结构：

```python
{
  "source": str,
  "authoritative": bool,
  "status": str,
  "refresh": str | None,
}
```

## 6.3 明确 UI 表达规则

建议 adapter 层后续统一：

- stale → 明确状态标记
- placeholder → 不渲染伪业务图形
- missing → 空态文案而非沉默失败

## 6.4 为 detail contract 补最小验证

至少增加：

- detail payload shape 测试
- holdings placeholder 行为测试
- snapshot/series 状态组合测试

---

# 7. 一句话总结

> Market detail 当前不是一个“后端一次查询出来的详情对象”，而是一个“多路径聚合、权威性不完全一致、必须显式表达状态”的前端详情视图。

只有先承认这一点，后续修 K 线、修详情、修刷新、修 UI，才不会继续变成补丁工程。

---

_文档状态：Market detail contract 初版完成_