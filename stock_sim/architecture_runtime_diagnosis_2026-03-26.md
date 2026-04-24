# UTI-STOCKSIM 前后端架构梳理与缺陷诊断

日期：2026-03-26

## 1. 当前架构主链

### 1.1 启动链

- GUI 入口：`setup_frontend_entry.py`
- Headless 入口：`app/headless.py`
- 两条入口都会启动：
  - `app.event_bridge.start_frontend_bridge()`
  - `app.runtime_bootstrap.start_runtime_support_services()`
  - `app.panels.register_builtin_panels()`
  - `app.panels.register_ui_adapters()`

### 1.2 前端装配链

- `app/panels/__init__.py` 是当前桌面前端的面板工厂中心。
- 每个面板在这里各自实例化自己的：
  - `service`
  - `controller`
  - `logic panel`
  - `Qt adapter`
- 典型链路：
  - `Market`: `MarketDataService -> MarketController -> MarketPanel -> MarketPanelAdapter`
  - `Account`: `AccountService -> AccountController -> AccountPanel -> AccountPanelAdapter`
  - `Clock`: `ClockService -> ClockController -> ClockPanel -> ClockPanelAdapter`
  - `Agents`: `AgentService -> AgentController -> AgentsPanel -> AgentsPanelAdapter`

### 1.3 Runtime 主链

- 标的创建：`app/controllers/market_controller.py` -> `services/instrument_service.py`
- 下单链：`app/services/trading_service.py` -> `services/order_service.py` -> `core/matching_engine.py`
- 账户链：`services/account_service.py`
- 时钟链：`app/services/clock_service.py` -> `services/sim_clock.py`
- 行情落地链：`services/snapshot_listener.py` + `services/bar_aggregator.py`
- Retail 运行时交易链：`app/services/agent_service.py` -> `app/services/runtime_retail_agent.py`

### 1.4 事件链

- app 侧和 runtime 侧目前都各有一个 `event_bus`
- `app/event_bridge.py` 负责：
  - 订阅 runtime snapshot
  - 归一化成前端 snapshot batch
  - 在 app/runtime 两侧总线上重复发布部分消息
- 部分交易事件会由 `app/services/trading_service.py` 再次桥接成：
  - `Trade`
  - `TradeEvent`
  - `frontend.order.submitted`

## 2. 当前已经接上 runtime 的部分

- Instrument 创建已经能注册到 runtime engine。
- Orders 面板已经能看到 runtime trade/order 事件。
- Market 面板已经能消费 runtime snapshot batch。
- Clock 已经能驱动 runtime `sim_clock`。
- Retail 已经是 runtime 自动交易单元，而不再只是前端占位对象。
- Leaderboard 默认已经切到 runtime 账户/持仓推导。
- Account 面板默认已禁用 synthetic fallback。

## 3. 仍未完全接上 runtime 的前端点

### 3.1 Agent 面板仍是 app 内存态主导

- `app/services/agent_service.py` 的 `_agents` 和 `_runtime_agents` 都是进程内内存。
- 这意味着：
  - Agent 列表不是从 runtime 权威存储读取
  - 重启 GUI 后 agent 元信息会丢
  - UI 看到的状态和 runtime 真状态可能漂移

### 3.2 Market K 线历史仍保留 synthetic fallback

- `app/services/market_data_service.py` 会优先读 runtime bars。
- 但若 runtime bars 为空，仍会退回 `_synthetic_fetcher()`。
- 这会导致：
  - 某些 symbol 的图表是“真数据 + 占位数据”混合语义
  - 前端必须持续区分 `placeholder`
  - 用户容易误判图表真实性

### 3.3 Market holdings 仍不是权威仓位面板

- `app/panels/market/panel.py` 里的 holdings 仍是 detail 辅助视图。
- 它虽然现在能从 runtime position book 推导部分结果，但仍被代码显式标记为：
  - helper
  - non-authoritative
  - placeholder-capable

### 3.4 Account 面板仍是“拉取式 DTO 视图”，不是 runtime 账户 store

- `app/services/account_service.py` 每次是从 runtime DB 拉一份 `AccountDTO`。
- 它不是 event-sourced 的账户 store，也不是统一缓存中心。
- 因此：
  - 数据刷新依赖 UI 显式切换或事件触发 reload
  - 账户生命周期与面板生命周期耦合较强

### 3.5 Leaderboard 图表仍是合成曲线

- 排行榜表格本身已经更多依赖 runtime。
- 但面板里用于展示的 `equity_curve / drawdown_curve` 仍是前端合成占位曲线，不是 runtime 历史权益曲线。

### 3.6 Run 语义没有完全贯穿前端

- `sim_day` 已基本接到 runtime。
- 但 `run_id` 仍没有作为前端所有面板的统一上下文被完整传递和显示。
- 这会让：
  - 同一轮仿真的状态边界不够清晰
  - rollback / checkpoint / replay / persistence 的语义难统一

## 4. 主要架构缺陷与矛盾

### 4.1 没有统一的 App 容器，导致多处状态源并存

- `app/panels/__init__.py` 里每个面板都自己 new 一套 service/controller。
- 结果是桌面前端不是“一个应用上下文”，而是“多个局部上下文并列”。
- 直接后果：
  - 每个面板拥有自己的缓存和局部状态
  - 面板之间一致性依赖事件碰运气同步
  - 很难界定哪个对象是当前桌面的真正 source of truth

### 4.2 app 与 runtime 边界不清，违反层次收敛

- app 层大量直接 import runtime 的：
  - SQLAlchemy model
  - persistence session
  - runtime service
- 这意味着 app 并不是一个清晰的“前端应用层”，而是半个 runtime 运维层。
- 直接后果：
  - UI/adapter/service 容易直接碰数据库
  - 重构 runtime schema 时会联动炸前端
  - 边界测试困难

### 4.3 双 event bus + 字符串 topic + 重复桥接，语义脆弱

- `app/event_bridge.py` 同时对 app/runtime 两个 `event_bus` 做订阅和转发。
- `app/services/trading_service.py` 又额外重复广播 `Trade` / `TradeEvent`。
- 这会带来：
  - 重复事件
  - 丢事件时难定位是 runtime 没发、bridge 没接、还是 app 没订阅
  - topic 命名不统一，如 `SnapshotUpdated`、`Trade`、`TradeEvent`、`AccountUpdated`

### 4.4 生产主链里仍混着 synthetic / placeholder / helper 逻辑

- 这在原型期很方便，但现在已经开始冲击“桌面仿真平台”的可信度。
- 典型问题：
  - 用户看到的数据未必是 runtime 权威
  - 代码里到处需要 `placeholder` 分支
  - 很难定义“某个面板现在是否真的接上后端”

### 4.5 Agent 运行时与 Agent UI 元数据仍分裂

- Retail 真正交易的是 `RuntimeRetailAgent`
- 但 UI 展示和控制的核心元信息仍存于 `AgentService._agents`
- 这是典型的“双写状态”
- 直接后果：
  - UI 状态和实际线程/账户状态可能不一致
  - 将来如果接入持久化 agent lifecycle，会很难迁移

### 4.6 时间模型比以前好，但仍未完全统一

- 现在 `Clock -> sim_clock -> sim_day` 已基本打通。
- 但 app 面板仍经常把时间当作字符串展示 DTO，而不是统一 runtime 时间对象。
- `run_id / sim_day / sim_dt` 三者尚未成为前端统一可见的上下文。

### 4.7 前端 adapter 承担了过多数据同步责任

- 例如 `AccountPanelAdapter`、`MarketPanelAdapter` 同时负责：
  - UI 组件
  - 事件订阅
  - runtime 账户补发现
  - 刷新节流
  - 局部同步策略
- adapter 已经超出“纯视图适配层”的职责，变成了半个 presenter/store。

## 5. 当前最典型的矛盾表现

### 5.1 “已经有 runtime 数据，但面板不刷新”

- 根因通常不是 runtime 没有数据，而是：
  - 面板没订阅到
  - 当前 service/controller 缓存没更新
  - adapter 没触发当前选中对象 reload

### 5.2 “图表有数据链，但显示语义不稳定”

- 因为 K 线链混合了：
  - persisted runtime bars
  - runtime trade 临时补桥 bars
  - synthetic fallback bars

### 5.3 “账户、成交、持仓三块能分别工作，但联动不稳”

- 因为三者分别依赖：
  - DB 拉取
  - 事件桥
  - 面板内缓存
- 它们不是建立在同一个统一 store 上。

## 6. 我认为最关键的结构性改造方向

### 6.1 引入统一的 Frontend AppContext

- 不再在 `app/panels/__init__.py` 里各自 new service/controller。
- 改为启动时只创建一套：
  - runtime gateway
  - event hub
  - market store
  - account store
  - agent store
  - clock store
- 各面板只消费这一套共享上下文。

### 6.2 建立明确的 RuntimeGateway

- app 层以后不直接 import runtime ORM/model/service。
- 改成统一经由一层 gateway：
  - `RuntimeGateway.create_instrument()`
  - `RuntimeGateway.submit_order()`
  - `RuntimeGateway.list_accounts()`
  - `RuntimeGateway.get_account_snapshot()`
  - `RuntimeGateway.list_agents()`
- 这样前后端边界才清晰。

### 6.3 统一事件总线与 topic 契约

- 最好只保留一个桌面进程内统一事件入口。
- 至少需要：
  - 统一 topic 命名
  - 统一 payload schema
  - 避免 app/runtime 双重重复广播

### 6.4 逐步把 synthetic/placeholder 从桌面主链中剥离

- 桌面正式运行模式下应默认：
  - 没有 runtime 数据就显示“无数据”
  - 不再用 synthetic 填坑
- synthetic 只保留给测试或 demo。

### 6.5 把 agent lifecycle runtime 化

- Agent 列表、状态、绑定关系、最近心跳，应该有一套 runtime 权威记录。
- UI 只读和控制它，而不是自己在内存里维护主状态。

### 6.6 把 `run_id / sim_day / sim_dt` 统一为平台级上下文

- 任何面板都应明确知道：
  - 当前是哪一轮 run
  - 当前是第几个 sim_day
  - 当前 sim_dt 是多少
- 这会直接改善：
  - rollback 语义
  - K 线坐标
  - IPO 首日逻辑
  - T+1 / 日切风控

## 7. 结论

当前项目已经不是“前端没接后端”，而是进入了一个更微妙的阶段：

- 主链已经基本打通
- 但系统还没有完成“单一权威状态源”的收束
- 最大问题不是功能没有，而是状态边界还不够干净

一句话总结：

这个项目现在最需要的，不再是继续堆单点功能，而是把 `AppContext / RuntimeGateway / EventContract / Store` 这四层收拢起来，让前端真正变成 runtime 的稳定桌面壳，而不是半个 UI、半个 backend patch 层。
