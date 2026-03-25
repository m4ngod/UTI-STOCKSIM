# UTI-STOCKSIM Runtime Critical Path Coverage Summary

_生成时间：2026-03-23 01:52 (Asia/Shanghai)_

本文档用于给出 runtime critical path matrix 的当前覆盖现状摘要，便于后续判断：

- 哪些主链路已经有显式护栏
- 哪些只做到部分覆盖
- 哪些后续仍值得补强

---

# 当前覆盖总览

## 已覆盖（当前核心场景）

- IOC 未成交释放
- FOK 不满足直接取消
- T+1 核心路径
- IPO 最小开盘闭环

## 部分覆盖

- BUY 冻结 → 成交 → 差额返还
- SELL 冻结 → 成交 → 冻结数量变化
- 空头开仓 / 回补 / borrowed_qty 变化

---

# 已新增/已确认的关键测试

## 订单 TIF 语义
- `tests/test_order_tif_semantics.py`
  - IOC
  - FOK

## 订单资金/冻结语义
- `tests/test_order_funding_semantics.py`
  - BUY 价格改善差额返还
  - SELL freeze 不提前减仓

## short / cover 边界
- `tests/test_order_short_cover_semantics.py`
  - full cover back to flat
  - partial cover remains short
- `tests/test_account_service_semantics.py`
  - settlement 层 short open
  - settlement 层 short cover + flip long

## T+1
- `tests/test_tplus1_order_flow.py`
  - T+1 拒卖
  - T+0 放行
  - IPO + T+1 组合路径

## IPO 最小路径
- `tests/test_ipo_minimal_path.py`
  - call auction → clearing buffer → continuous + trade produced

---

# 当前最值得继续补强的点

1. BUY fee lifecycle 更细粒度闭环
2. SELL 部分成交 + 残余释放组合
3. short-open 在 order-path 层的正式所有权是否要显式化
4. IPO instrument-level `ipo_opened` 同步是否应成为正式不变量

---

# 一句话总结

> BL-002 当前已经从“列测试计划”进入“形成 runtime 底板”，但还没到彻底封板；下一步应针对部分覆盖区继续做有选择的补强，而不是盲目追求测试数量。

---

_文档状态：coverage summary 初版完成_