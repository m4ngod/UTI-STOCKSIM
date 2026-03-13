# Design: instrument-details-and-batch-dialog-fixes

## Overview
实现三项改进：
- 修复 AgentsPanelAdapter 缺失 `_open_batch_dialog()`，对接 AgentCreationModal 逻辑对话框，避免崩溃并展示进度。
- 标的列表双击打开详情页，并在详情页加入：L2 五档表格、日K图（可缩放/拖动，边界至发行首日和最新日）、“多策略散户总体”持仓占比饼图。
- 创建标的弹窗三元联动推导逻辑的 UI 实时显示与行为规则：优先改动价格；若修改的是价格，则改动流通股。

## Architecture
- UI 采用 Adapter 与 Panel 分离：
  - MarketPanelAdapter 负责左侧 watchlist 与右侧详情区域；复用 MarketPanel.detail_view() 数据。
  - SymbolDetailAdapter 负责详情区域渲染：
    - 五档：QTableWidget（BID/ASK 价格与数量，取前 5 档）。
    - K 线：使用 pyqtgraph（如可用）绘制日K；若 headless 则文本占位。
    - 饼图：pyqtgraph.PlotWidget + PieSegment 或用 matplotlib；headless 用文本占位。
  - AgentsPanelAdapter 增补 `_open_batch_dialog()`，调用 app.ui.agent_creation_modal.AgentCreationModal 以触发批量创建，并轮询/订阅进度刷新现有进度标签。
- 逻辑层：
  - MarketPanel/MarketDataService/Snapshot/TradeDTO 等已存在，detail_view() 已返回 series、snapshot、order_book、trades。
  - “多策略散户总体”持仓统计：在服务层提供汇总接口 get_retail_holdings(symbol) -> { account: pct } 或 { category: pct }；若暂缺，则从 AgentService/Portfolio 汇总或提供模拟数据接口，避免阻塞 UI。
  - 创建标的对话框：已存在 app.panels.market.dialog.CreateInstrumentDialog，包含 derive_third_value 推导；如与规则不符，将在 validators 或 dialog 内调整策略。

## Data Contracts
- MarketPanel.detail_view():
  - series: { ts[], open[], high[], low[], close[], volume[] }
  - order_book: { bids: list[(price, qty)], asks: list[(price, qty)] }
  - snapshot: { last, bid_levels, ask_levels, ... }
  - holdings: { labels: list[str], pct: list[float] }  // 新增，可无则显示“无数据”
- AgentsPanel.get_view():
  - 保持现状；batch 结构已含 in_progress/created/failed/requested。

## UI Behavior
- 双击 watchlist 条目打开详情：在 MarketPanelAdapter.symbol 列表绑定 itemDoubleClicked，调用 _handle_select(symbol)。
- K 线交互：
  - 鼠标滚轮缩放、拖动平移（pyqtgraph 默认支持，通过 setMouseEnabled/enableAutoRange 配置）；
  - 左右边界：绘制全序列后由用户交互移动，初始视图显示最近一段，支持滚动至最左（IPO）与最右（最新）。
- 饼图：按 holdings.pct 画扇形；若无数据则显示空状态。
- 创建标的三元联动：
  - UI 输入变化 -> dialog.set_fields() -> get_view().derived，derived.field/derived.value 在界面显示。
  - 若规则需更改：在 validators.derive_third_value 中实现“优先改动价格；若修改的是价格，则改动流通股”。

## Changes
1) app/ui/adapters/agents_adapter.py
- 新增方法 _open_batch_dialog()：
  - 若可用 Qt：弹出 QDialog，字段：count、agent_type、name_prefix、strategies（多行文本）。
  - 调用 AgentCreationModal 进行校验与提交；提交后关闭对话框；刷新视图。
  - 无 Qt：使用默认参数调用 AgentsPanel.start_batch_create。
- 绑定按钮事件已存在，无需变更。

2) app/ui/adapters/market_adapter.py
- 列表绑定 itemDoubleClicked 打开详情。
- 为 SymbolDetailAdapter 增加：
  - K 线绘图（pyqtgraph/candlestick），后备文本。
  - 饼图绘图，后备文本。
- _apply_view 传递 detail_view() 到 SymbolDetailAdapter.apply_detail() 已有。

3) app/panels/market/panel.py
- detail_view() 新增 holdings 字段（从服务聚合；若无返回 None）。

4) app/panels/market/dialog.py 或 app/utils/validators.py
- derive_third_value 策略校对/调整：
  - 当用户变更字段为 price -> 改动 float_shares；
  - 其他情况下 -> 改动 price；
  - 维持步长与边界；返回 { derived_field: value }。
- 需要额外传入 last_changed 字段时，在 set_fields 中记录最近变更字段来源（通过 UI侧传入），供 _recompute 调用。

## Edge Cases
- 非法数值或空值：显示错误信息，不提交。
- K 线数据为空：不崩溃，显示空状态。
- PySide6/pyqtgraph 不可用：使用降级文本。
- 进度事件偶发：保持现有节流与退避。

## Testing
- 单元：
  - validators.derive_third_value 策略：多组 price/fs/mcap 的变更路径。
  - AgentCreationModal.submit 输入校验。
- 集成：
  - 点击 Batch Create… 不再抛 AttributeError，能返回 True。
  - 双击 watchlist 打开详情，K 线与饼图组件创建成功（headless 使用桩）。

## Migration/Compat
- API 兼容：未修改现有数据结构；新增字段 holdings 可选。
- 风险低：更改集中于 UI Adapter 与对话框逻辑。

