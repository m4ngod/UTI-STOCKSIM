# UTI-STOCKSIM Runtime Critical Path Test Matrix

_生成时间：2026-03-22 17:16 (Asia/Shanghai)_

本文档用于定义运行时主链路的最小关键测试矩阵，目标是为后续结构收束、职责收束、存储演进和核心业务重构提供基础护栏。

---

# 1. 文档目标

本矩阵重点解决三个问题：

1. 哪些 runtime 链路属于必须优先保护的关键路径
2. 每条关键路径当前由哪些代码负责
3. 每条链路目前已有/缺失哪些测试护栏

这不是覆盖率文档，而是**重构风险控制文档**。

---

# 2. 当前最小关键路径范围

本轮先聚焦以下七类路径：

1. BUY 冻结 → 成交 → 退差额 → 账户更新
2. SELL 冻结 → 成交 → 持仓/冻结数量变化
3. IOC 未成交剩余释放
4. FOK 不满足直接取消
5. 空头开仓 / 回补 / borrowed_qty 变化
6. T+1 约束
7. IPO 最小开盘路径

---

# 3. 路径矩阵

## RT-001 BUY 冻结 → 成交 → 退差额 → 账户更新

**风险等级**
- 高

**核心代码**
- `services/order_service.py`
- `services/account_service.py`
- `services/fee_engine.py`

**必须验证的语义**
- 下 BUY 单时冻结现金
- 买单手续费预冻结逻辑成立
- 成交后从 `frozen_cash` 扣减真实成交成本
- 若挂单价高于实际成交价，差额退回 `cash`
- 账户事件语义不自相矛盾

**当前覆盖状态**
- **部分覆盖**

**当前已覆盖**
- `tests/test_order_funding_semantics.py::test_buy_fill_refunds_price_improvement_difference_to_cash`
  - 显式锁住价格改善后的差额返还
- `tests/test_account_service_semantics.py::test_t_plus_one_style_same_day_bought_shares_remain_frozen_until_release_or_next_day_logic`
  - 间接覆盖买入成交后的冻结归零语义

**当前未完全锁住**
- BUY 侧账户事件 payload 的更细粒度一致性
- 手续费预冻结/实扣/退款在更复杂成交组合下的完整闭环

**下一步**
- 如后续改动 fee/funding path，优先补充更细的 fee lifecycle 测试

---

## RT-002 SELL 冻结 → 成交 → 持仓/冻结数量变化

**风险等级**
- 高

**核心代码**
- `services/order_service.py`
- `services/account_service.py`

**必须验证的语义**
- SELL 冻结不应在 freeze 阶段直接篡改真实持仓数量
- 成交后 `quantity` 与 `frozen_qty` 的变化正确
- 剩余未成交部分释放正确

**当前覆盖状态**
- **部分覆盖**

**当前已覆盖**
- `tests/test_account_service_semantics.py::test_sell_freeze_locks_only_existing_long_and_does_not_mutate_quantity`
  - 锁住 account-service 层 SELL freeze 不改 `quantity`
- `tests/test_order_funding_semantics.py::test_sell_order_freeze_does_not_reduce_position_before_trade`
  - 锁住 order-service 主链路视角下 SELL freeze 不提前减仓

**当前未完全锁住**
- SELL 成交后 `quantity/frozen_qty` 在更多部分成交场景下的组合变化
- SELL 残余撤单释放的更细分生命周期

**下一步**
- 若后续改动 SELL lifecycle，补部分成交 + 撤单释放组合测试

---

## RT-003 IOC 未成交剩余释放

**风险等级**
- 高

**核心代码**
- `services/order_service.py`
- `services/account_service.py`

**必须验证的语义**
- IOC 剩余部分不会留在簿上
- 剩余冻结主体会释放
- BUY 侧未成交手续费按比例退还
- 状态转移与取消事件一致

**当前覆盖状态**
- **已覆盖（最小显式护栏）**

**当前已覆盖**
- `tests/test_order_tif_semantics.py::test_ioc_unfilled_releases_buy_freeze_and_cancels_order`
  - 显式锁住 IOC 未成交释放与取消语义

**当前未完全锁住**
- IOC 部分成交后剩余释放 + 手续费比例退还的更细场景

**下一步**
- 如后续调整 IOC 路径，补部分成交版本测试

---

## RT-004 FOK 不满足直接取消

**风险等级**
- 高

**核心代码**
- `services/order_service.py`
- `services/risk_engine.py`
- `services/risk_rule_registry.py`

**必须验证的语义**
- FOK 无法满足时不应部分成交
- 冻结释放必须完整
- 事件与最终订单状态一致

**当前覆盖状态**
- **已覆盖（最小显式护栏）**

**当前已覆盖**
- `tests/test_order_tif_semantics.py::test_fok_unfillable_does_not_partially_fill_and_releases_buy_freeze`
  - 显式锁住 FOK 不可满足时的取消与释放语义

**当前未完全锁住**
- 更复杂簿深度下 FOK 预检查与事件一致性

**下一步**
- 若后续改动 FOK 风控/预检查逻辑，补更细簿深场景

---

## RT-005 空头开仓 / 回补 / borrowed_qty 变化

**风险等级**
- 极高

**核心代码**
- `services/account_service.py`
- `services/order_service.py`
- `services/lending_pool.py`（若存在真实集成）
- 风险规则相关模块

**必须验证的语义**
- 卖超已有多头时能形成空头
- `borrowed_qty` 增长逻辑正确
- 买入回补时 `borrowed_qty` 回落正确
- 空翻多边界条件正确

**当前覆盖状态**
- **部分覆盖**

**当前已覆盖**
- `tests/test_account_service_semantics.py::test_sell_settlement_can_open_short_and_credit_net_cash`
  - 锁住 settlement 层 short open 语义
- `tests/test_account_service_semantics.py::test_buy_settlement_can_cover_short_and_rebuild_long_basis`
  - 锁住 settlement 层 short cover + flip long 语义
- `tests/test_order_short_cover_semantics.py::test_buy_trade_can_fully_cover_short_back_to_flat_without_flipping_long`
  - 锁住 order-path full cover to flat
- `tests/test_order_short_cover_semantics.py::test_buy_trade_can_partially_cover_short_without_flipping_long`
  - 锁住 order-path partial cover remains short

**当前未完全锁住**
- order-service 主链路层面的稳定 short-open 显式场景
- 借券库存/限制与 short open 的更明确路径所有权

**下一步**
- 先保持 current split：short open 由 settlement/account 语义护栏，short cover 由 order-path 护栏。
- 如果未来明确 short-open 的 order-path 保证，再补一条稳定显式测试。

---

## RT-006 T+1 约束

**风险等级**
- 极高

**核心代码**
- `services/risk_engine.py`
- `services/risk_rule_registry.py`
- `services/order_service.py`

**必须验证的语义**
- T+1 标的同日买入后不可卖出
- T+0 标的不应被误杀
- 与 IPO / 冷启动场景组合时语义不漂移

**当前覆盖状态**
- **已覆盖（当前核心场景）**

**当前已覆盖**
- `tests/test_tplus1_order_flow.py::test_same_day_buy_then_sell_is_blocked_for_t1_instrument`
- `tests/test_tplus1_order_flow.py::test_same_day_buy_then_sell_allowed_for_t0_instrument`
- `tests/test_tplus1_order_flow.py::test_ipo_open_then_same_day_sell_is_blocked_for_t1_instrument`

**当前未完全锁住**
- 更复杂冷启动/多引擎交互下的 T+1 路由细节

**下一步**
- 仅在 T+1 规则或 engine routing 发生结构改动时，再补更复杂组合测试

---

## RT-007 IPO 最小开盘路径

**风险等级**
- 高

**核心代码**
- `core/matching_engine` 相关
- `services/order_service.py`
- IPO 相关 service / logic

**必须验证的语义**
- 集合竞价 → 开盘逻辑成立
- IPO_OPENED 相关路径不与普通撮合混淆
- 与 T+1 / 初始库存等组合时不出现错误假设

**当前覆盖状态**
- **已覆盖（最小闭环）**

**当前已覆盖**
- `tests/test_ipo_minimal_path.py::test_ipo_minimal_open_path_transitions_to_continuous_and_produces_trade`
  - 锁住 IPO 最小开盘闭环：call auction → clearing buffer → continuous + trade produced
- `tests/test_tplus1_order_flow.py::test_ipo_open_then_same_day_sell_is_blocked_for_t1_instrument`
  - 锁住 IPO 与 T+1 组合路径

**当前未完全锁住**
- `instrument.ipo_opened` 标志在该路径上的同步是否应成为正式不变量
- 更复杂 IPO 分配/剩余买单迁移细节

**下一步**
- 保持最小 IPO path 测试聚焦业务稳定真相。
- 若未来明确 `ipo_opened` flag 同步归属，再单独补测试，不在最小闭环里混入实现细节。

---

# 4. 本轮执行策略

本轮不追求把所有测试一次补满，而是按以下顺序推进：

1. **先盘点已有测试**
2. **先补缺失最明显的显式测试**
3. **先锁主语义，不追求极端细枝末节**
4. **先让高风险链路“有护栏”，再谈扩大覆盖面**

---

# 5. 当前建议优先顺序

建议按这个顺序执行：

1. T+1
2. short open / cover
3. BUY 差额返还
4. SELL freeze 语义
5. IOC
6. FOK
7. IPO 最小路径

原因：

- T+1 与 short 语义最容易因为重构而漂移
- BUY/SELL 冻结与返还是最核心资金语义
- IOC/FOK 是典型订单生命周期完整性校验点
- IPO 路径特殊但重要，适合以“最小闭环”锁住

---

# 6. 与 docs 结构的关系

本文件属于：
- `docs/testing/runtime/`

定位：
- 二级测试治理文档

如果后续某一条路径需要展开为更详细测试说明，可进入三级文档，例如：
- `docs/testing/runtime/tplus1-test-notes.md`
- `docs/testing/runtime/short-cover-regression-notes.md`

---

# 7. 一句话总结

> Runtime 主链路测试矩阵的目标不是追求“测试很多”，而是保证以后敢动核心代码时，不是在闭眼拆炸弹。

---

_文档状态：runtime critical path matrix 初版完成_