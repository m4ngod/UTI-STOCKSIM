# Release Pretest Status

## Module

发布前最小运行链路测试（instrument / retail / IPO / account / market）

## Current state

verification-needed

## Task 2026-03-24-release-pretest-01
- **time**: 2026-03-24 23:xx
- **status**: verification-needed
- **goal**: 在发布前验证最小运行链路是否具备可交付基础：创建 instrument、确认 IPO 最小路径、确认账户/市场前端 contract、确认 headless 最小 e2e 路径；并记录当前阻塞点。
- **files involved**:
  - `tests/test_ipo_minimal_path.py`
  - `tests/test_tplus1_order_flow.py`
  - `tests/test_order_funding_semantics.py`
  - `tests/test_order_tif_semantics.py`
  - `tests/test_order_short_cover_semantics.py`
  - `tests/frontend/unit/test_account_contract.py`
  - `tests/frontend/unit/test_market_detail_contract.py`
  - `tests/frontend/unit/test_market_detail_contract_extended.py`
  - `tests/frontend/unit/test_market_detail_contract_overall_health.py`
  - `tests/frontend/unit/test_orders_contract.py`
  - `tests/frontend/unit/test_market_panel_detail_open_regression.py`
  - `tests/frontend/e2e/test_create_instrument_and_batch_agents.py`
  - `app/ui/adapters/account_adapter.py`
  - `tests/test_kline_and_account_events.py`
  - `tests/test_release_minimal_runtime_chain.py`
- **change summary**:
  - 实际执行了一组发布前高相关回归：IPO 最小路径、T+1、资金冻结/释放、IOC/FOK、short cover、Account/Orders/Market detail contract、Market detail 打开回归、headless instrument+retail 批量 e2e。
  - 该组回归结果：`21 passed`。
  - 在继续补测更贴近发布链路时，发现 `tests/test_kline_and_account_events.py::test_account_adapter_adds_account_on_created_event` 暴露出 `AccountPanelAdapter` headless 路径缺失 `_create_headless_widget()`；已补上最小实现。
  - 进一步验证时发现该测试并非普通断言失败，而是在 adapter/headless 路径上触发进程直接退出，表现更像前端适配层异常而非交易/runtime 主语义异常。
  - 新增了 `tests/test_release_minimal_runtime_chain.py`，尝试把 instrument -> 下单成交 -> IPO 打开 -> snapshot -> account view -> market detail 串成一个更贴近发布目标的集成链路。
  - 对该测试的进一步定位确认了两个事实：
    1. 原先的卡死点来自 `SnapshotPersistenceListener` 使用独立 SQLite session 写库，形成写锁竞争；改为同 session 后，链路可继续推进。
    2. 更关键的真实缺口不是 UI 假象，而是 IPO 开盘成交后，买方账户持仓并未进入 runtime 账户状态。debug 脚本里 `ipo_book.trades` 已有 `100000` 成交量，但 `AccountService.get_position(buyer, symbol)` 仍为 `qty=0`，说明 **IPO open path 与 account settlement 当前没有形成闭环**。
    3. 继续读代码后已确认根因：`services/ipo_service.py::maybe_auto_open_ipo()` 在第二阶段只发布 `Trade` 事件并扩展 `book.trades`，没有调用 `OrderService._after_trades()`、也没有走 `AccountService.settle_trades_batch()`。因此 IPO 开盘成交天然不会落到账户/持仓/账本层。
  - 另外，`app/services/account_service.py` 先前完全依赖 synthetic fetcher，已补了一个“优先读 runtime 本地库、失败再回退 synthetic”的最小 runtime fetcher。这样 account panel 至少不再天然与 runtime truth 脱节。
- **purpose**:
  - 用真实测试结果而不是主观判断来评估发布前主链路 readiness。
  - 把“已验证通过的链路”和“仍阻塞发布的链路”明确分开。
- **impact / risk**:
  - 正向：runtime 关键业务语义、Market detail 合同、Account/Orders 合同、headless 创建 instrument + 批量 retail 这几块已有较扎实回归护栏。
  - 风险：`AccountPanelAdapter` 的 headless/account-created 事件路径仍有异常，说明 GUI/account 适配层在发布前还不能视作完全稳定。
  - 风险：更贴近你要求的“一条龙最小发布链路”新集成测试还未跑稳，不能宣称已完整打通 GUI 账户资金变动 + Market K 线绘制的真实发布链路。
- **verified facts**:
  - 已通过测试集命令：
    - `.\.venv\Scripts\python -m pytest tests\test_ipo_minimal_path.py tests\test_tplus1_order_flow.py tests\test_order_funding_semantics.py tests\test_order_tif_semantics.py tests\test_order_short_cover_semantics.py tests\frontend\unit\test_account_contract.py tests\frontend\unit\test_market_detail_contract.py tests\frontend\unit\test_market_detail_contract_extended.py tests\frontend\unit\test_market_detail_contract_overall_health.py tests\frontend\unit\test_orders_contract.py tests\frontend\unit\test_market_panel_detail_open_regression.py tests\frontend\e2e\test_create_instrument_and_batch_agents.py -q`
  - 结果：`21 passed, 4 warnings in 2.23s`
- **current conclusion**:
  - 发布前核心 runtime 语义链路大体是通的。
  - 但“GUI/account adapter headless 事件链路异常”与“更贴近发布目标的一条龙集成测试未稳定”意味着当前还不适合轻率宣称整条发布链路已经完全打通。
- **next actions**:
  - 继续定位 `tests/test_kline_and_account_events.py::test_account_adapter_adds_account_on_created_event` 的进程退出根因。
  - 继续稳定 `tests/test_release_minimal_runtime_chain.py`，优先找出卡住点是 MarketPanel/detail、snapshot listener、还是 account panel/app-layer service。
  - 在新链路稳定前，不再新增计划型文档；只记录实际验证结果与真实阻塞点。
