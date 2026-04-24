# StockSim项目架构分析报告

更新时间：2026-03-28

## 1. 报告定位

本报告基于当前代码状态重写，目标不是回顾历史设计，而是说明：

- 这个项目现在到底是怎样运行的
- 前端、runtime、后端、持久化之间当前的真实主链是什么
- 哪些架构问题已经被收束
- 哪些问题仍然存在，后续应该如何推进

结论先行：

StockSim 现在不是“普通桌面前端 + 一堆后端脚本”的结构，而是一个单进程内运行的桌面仿真交易平台，核心由四部分组成：

1. `app/`：桌面应用层，负责窗口、面板、控制器、视图模型和应用级服务
2. `services/ + core/`：runtime 后端，负责时钟、撮合、账户、风控、IPO、事件、恢复与回放
3. `persistence/`：当前承压中的兼容持久化层，仍是主链一部分
4. `docs/data/ + services/persistence_layer/`：未来正式存储架构的目标态和迁移边界

## 2. 项目总体架构

当前推荐从下面这条链路理解整个系统：

```text
桌面入口
  -> AppContext
  -> MainWindow / HeadlessMainWindow
  -> Panel Logic + UI Adapters
  -> Controllers
  -> App Services
  -> RuntimeGateway
  -> RuntimeCommandService / RuntimeQueryService
  -> Backend Services
  -> MatchingEngine / SimClock / EventBus / Persistence
```

更具体一点：

```text
用户操作
  -> app/ui/*.py
  -> app/panels/*.py
  -> app/controllers/*.py
  -> app/services/*.py
  -> app/runtime_gateway.py
  -> services/runtime_command_service.py / services/runtime_query_service.py
  -> services/order_service.py / account_service.py / instrument_service.py ...
  -> core/matching_engine.py / services/sim_clock.py / infra/event_bus.py
  -> persistence/*.py
```

这是当前项目最重要的架构事实：

- 前端不再鼓励直接碰 runtime ORM
- app 层通过 `RuntimeGateway` 访问后端
- `RuntimeGateway` 本身也不再是“大总管”，而是继续委托给 backend 的 query/command service
- runtime 的事实写入、读取、回放、恢复已经开始围绕 `run_id` 收束

## 3. 启动链与运行入口

### 3.1 GUI 入口

当前桌面主入口是：

- `setup_frontend_entry.py`

它负责：

- 初始化设置
- `reset_app_context()`
- 启动 `start_frontend_bridge()`
- 启动 runtime 支撑服务 `start_runtime_support_services()`
- 注册面板占位与 UI adapter
- 创建并显示 `MainWindow`

### 3.2 Headless 入口

当前 headless 入口是：

- `app/headless.py`

它与 GUI 入口共享同一套应用上下文，只是不启动真实 Qt 事件循环，而是返回 `HeadlessMainWindow` 作为轻量外观，便于测试和无界面运行。

### 3.3 Runtime 支撑服务

GUI/headless 启动时还会拉起：

- `services/snapshot_listener.py`
- `services/bar_aggregator.py`

也就是说，桌面端现在已经不只是 UI 容器，而是会主动把 runtime 的 snapshot/bar 聚合链挂起来。

## 4. 前端应用层架构

### 4.1 组合根：AppContext

当前桌面端真正的组合根是：

- `app/app_context.py`

它集中创建并持有共享实例：

- `RuntimeGateway`
- `MarketDataService / MarketController`
- `AccountService / AccountController`
- `TradingService / TradingController`
- `AgentService / AgentController`
- `ClockService / RollbackService / ClockController`
- `LeaderboardService / LeaderboardController`

这意味着：

- 各面板已经不再各自 new 一套独立 service/controller
- 主窗口和动态 detail 页也应共享同一套应用上下文

这是近阶段架构收束里最重要的一步之一。

### 4.2 面板体系

当前面板系统由三层组成：

1. `app/panels/__init__.py`
   - 注册占位 panel
   - 在启动时用真实 panel + adapter 替换占位项
2. `app/panels/*/panel.py`
   - 面板逻辑层
   - 负责状态组织、视图模型拼装、交互语义
3. `app/ui/adapters/*.py`
   - Qt 适配层
   - 负责把 panel logic 绑定到真实 `QWidget`

当前默认工作区主面板包括：

- `agents`
- `leaderboard`
- `clock`
- `market`
- `account`
- `orders`

### 4.3 控制器与应用服务

前端并不是直接从 UI 打到 runtime，而是通过：

- Controller：面向交互动作
- App Service：面向桌面端需要的 DTO / 视图数据 / 调度行为

当前主线大致是：

- `MarketController` 负责标的创建、watchlist/detail 协调
- `AccountService` 负责桌面账户视图 DTO
- `MarketDataService` 负责 detail 数据、bars、holdings、chart meta
- `TradingService` 负责桌面端下单/撤单
- `AgentService` 负责 agent 管理、runtime retail 生命周期
- `ClockService` 负责桌面端时钟状态与 runtime 时钟控制

### 4.4 EventBridge

事件桥在：

- `app/event_bridge.py`

当前职责是：

- 订阅 runtime snapshot 相关主题
- 把 runtime 的 `SnapshotUpdated` 规范化为前端可消费的 payload
- 批量发布 `frontend.snapshot.batch`
- 为 GUI 和 headless 提供统一的 bridge 启停接口

它的意义是：

- runtime 事件流和前端 UI 刷新不直接耦合
- 前端 adapter 更多消费统一 topic，而不是各自拼后端事件

## 5. 前后端边界

### 5.1 RuntimeGateway 的定位

当前 app 层与 runtime 后端的稳定边界是：

- `app/runtime_gateway.py`

它对 app 层暴露的能力大致分两类：

- 读：
  - `get_account_snapshot`
  - `get_current_sim_day`
  - `get_bars`
  - `get_retail_holdings`
  - `list_leaderboard_snapshots`
  - `list_account_ids`
- 写/命令：
  - `create_instrument`
  - `submit_order`
  - `cancel_order`
  - `start_clock / pause_clock / resume_clock / stop_clock`
  - `bootstrap_agent_account`
  - `allocate_pending_ipo_distributions`

### 5.2 RuntimeGateway 下面的真实实现

`RuntimeGateway` 现在已经继续拆成：

- `services/runtime_query_service.py`
- `services/runtime_command_service.py`

所以当前更准确的边界关系是：

```text
UI -> app service/controller -> RuntimeGateway -> RuntimeQueryService / RuntimeCommandService -> backend services
```

这是当前项目前后端解耦的核心成果。

### 5.3 目前边界的优点

- app 层标准路径不再直接开 runtime session
- app 层不再直接拼 ORM 查询
- 未来如果 backend 内部继续重构，app 层接口可以保持稳定

### 5.4 目前边界仍然不完美的地方

- `RuntimeGateway` 仍然是项目内自建边界，不是进程间 RPC；也就是说前后端逻辑仍运行在同一进程里
- `EventBridge` 仍带有字符串 topic 和双 event bus 兼容语义，调试成本偏高
- 个别 adapter 仍然偏重，UI 刷新和事件消费耦合较深

## 6. 后端 runtime 架构

### 6.1 核心运行时

后端 runtime 当前主要由这些模块构成：

- `core/matching_engine.py`
- `core/order_book.py`
- `core/order.py`
- `core/trade.py`
- `core/snapshot.py`
- `services/sim_clock.py`
- `services/engine_registry.py`

其中：

- `MatchingEngine` 是实际撮合核心
- `engine_registry` 管理 symbol -> engine 的全局映射
- `sim_clock` 是 runtime 时间权威源

### 6.2 订单、账户、标的三条主服务

#### OrderService

文件：

- `services/order_service.py`

当前角色：

- 订单生命周期编排
- engine 路由
- 风控、费用、冻结、成交后结算协同
- 事件发布
- `run_context` 下的事实写入

当前状态：

- 已经比以前收干净很多
- 但仍然是后端里最重、最复杂的服务之一

#### AccountService

文件：

- `services/account_service.py`

当前角色：

- 账户创建
- 资金冻结/释放
- 持仓查询与更新
- 账本和权益快照写入协同

它已经开始通过：

- `services/account_persistence_service.py`

把底层写入和业务编排分开。

#### InstrumentService

文件：

- `services/instrument_service.py`

当前角色：

- instrument 行本身的 CRUD
- flush/stamp
- 显式 runtime 同步调用

runtime 侧副作用已经拆到：

- `services/instrument_runtime_service.py`

这比之前“CRUD 和 runtime bootstrap 混在一个服务里”的状态要好很多。

### 6.3 运行时会话与时间

当前时间和会话语义的关键模块是：

- `services/sim_clock.py`
- `services/run_context.py`
- `services/simulation_run_service.py`

当前语义已经基本明确：

- 一个 `run_id` 表示一次完整模拟会话
- 同一会话中 `run_id` 不应旋转
- `sim_day` 在该 `run_id` 内推进
- `Clock Start` 会建立或恢复稳定的 desktop-session `run_id`
- `Clock Stop` 会结束该 run

### 6.4 retail、IPO 与交易启动

与桌面主链相关的交易参与者/启动逻辑主要包括：

- `app/services/runtime_retail_agent.py`
- `agents/retail_strategy.py`
- `services/ipo_retail_distribution.py`
- `services/ipo_service.py`

当前方向是：

- 用真实 retail 微订单，而不是假 bars，来解决冷启动
- IPO 发股、连续竞价启动、retail 自动交易都尽量纳入 runtime 主链

## 7. 数据与持久化架构

### 7.1 当前状态：兼容持久化仍是承压主链

当前项目依然依赖：

- `persistence/`
- `SessionLocal`
- SQLAlchemy 模型

来承载这些事实：

- accounts / positions / instruments / agent_bindings
- orders / order_events / trades / ledgers
- snapshots / bars
- simulation_runs
- account_equity_snapshots

所以当前存储不能简单视为“旧代码”，它仍然是活的主链。

### 7.2 持久化边界已经开始成形

当前已拆出的写侧协作者包括：

- `services/order_persistence_service.py`
- `services/trade_persistence_service.py`
- `services/account_persistence_service.py`

读侧协作者包括：

- `services/run_persistence_query_service.py`

这意味着：

- 订单/成交/账本/权益快照/回放恢复的持久化访问，已经不全都直接写在大服务内部
- 后面替换底层存储时，不必先改掉交易主逻辑

### 7.3 持久化迁移入口

当前已经落地的迁移边界在：

- `services/persistence_topology.py`
- `services/persistence_layer/`

其中：

- `persistence_topology.py` 给出了当前各 domain 的存储拓扑
- `services/persistence_layer/__init__.py` 提供统一包入口
- `services/persistence_layer/migration_plan.py` 给出迁移 phase 顺序和验收条件

### 7.4 目标态

根据 `docs/data/`，项目的正式目标态是：

- PostgreSQL：权威业务存储
- Redis：热状态/缓存/实时投递层
- SQLite：开发/测试/演示兼容层

当前判断是：

- 方向正确
- 但现在还处于“兼容存储承压 + 边界逐步收束”的过渡阶段
- 不能先删旧持久化，再谈新架构

## 8. 事件、快照、K线与回放恢复

### 8.1 事件主线

当前 runtime 内部通信基础仍是：

- `infra/event_bus.py`

重要事件消费者/生产者包括：

- `services/event_persistence_service.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `app/event_bridge.py`

### 8.2 snapshot/bar 主链

当前真实主链大致是：

```text
撮合/订单簿变化
  -> SnapshotUpdated
  -> snapshot_listener 持久化 snapshots_1s
  -> bar_aggregator 聚合 bars
  -> EventBridge 规范化并推给前端
```

这条链已经进了桌面标准启动链，而不是只存在于离线脚本或局部逻辑。

### 8.3 回放与恢复

当前回放与恢复能力主要在：

- `services/replay_service.py`
- `services/recovery_service.py`
- `services/simulation_run_service.py`

并且已经开始围绕 `run_id` 事实收束。

这意味着项目当前并不是“只能跑 UI，不能验证历史事实”，而是已经有回放/恢复这条更偏实验平台和数据可信性的链路。

## 9. 目录分工总结

当前目录建议这样理解：

- `app/`
  - 桌面应用层
  - 面板、controller、app service、adapter、入口桥接
- `core/`
  - 撮合与市场核心模型
- `services/`
  - backend runtime、业务服务、事件、恢复、聚合、持久化边界
- `persistence/`
  - 当前 SQLAlchemy 模型与 DB 初始化
- `agents/`
  - retail/策略/强化学习参与者相关逻辑
- `rl/`
  - 强化学习环境与模型桥接
- `simulation/`
  - 历史仿真/市场时钟/流动性提供等实验模块
- `backtest/`
  - 回测入口
- `data_pipeline/`
  - 数据抓取与事件构建
- `tests/`
  - 前端、集成、回放、恢复、契约与行为验证
- `docs/`
  - 设计、迁移、工作状态文档

## 10. 当前架构的优点

当前版本相比早期状态，已经有以下明显优点：

1. 前端主链有了共享组合根，不再是一堆零散 service 实例
2. 前后端边界被收束到 `RuntimeGateway`
3. `RuntimeGateway` 本身又继续拆成 command/query，不至于立刻变新的大总管
4. `InstrumentService` 已从“CRUD + runtime 副作用混写”收成更清晰的边界
5. 持久化已经开始出现稳定的 boundary collaborator
6. `run_id` 会话语义已经从设计层落到桌面 runtime 主链
7. snapshot/bar/replay/recovery 不是孤立能力，而是逐步纳入统一 runtime 事实模型

## 11. 当前仍存在的架构缺陷

虽然整体结构已经比之前清楚很多，但当前仍有这些核心问题：

### 11.1 OrderService 仍然过重

`services/order_service.py` 仍然承担了过多职责：

- 下单编排
- engine 路由
- 费用/风控协同
- 结算逻辑
- 事件发布
- run 注册

它已经被拆小了一些，但依旧是后端最主要的复杂点。

### 11.2 app 与 backend 仍是单进程内解耦，不是物理分离

当前“前后端解耦”更多是模块和边界意义上的：

- 有稳定边界
- 没有直接 ORM 乱穿

但它不是：

- 独立后端服务
- 独立网络 API
- 独立部署拓扑

所以项目目前更适合被定义为：

“单进程桌面应用 + 内嵌 runtime 后端”

而不是传统意义上的网络型前后端系统。

### 11.3 事件系统仍然有历史兼容痕迹

`EventBridge` 和 runtime event bus 当前仍保留一定兼容/双总线/字符串 topic 负担：

- 功能可用
- 但语义和调试成本还不够硬朗

### 11.4 持久化仍处于过渡阶段

虽然已经有 `persistence_layer` 和 migration plan，但当前事实是：

- 运行时主链仍依赖本地 SQLAlchemy/兼容存储
- PostgreSQL/Redis 目标态尚未真正切换
- 一些表与服务已经是“技术临时、语义权威”

### 11.5 仓内仍有实验性/历史性目录

如：

- `simulation/`
- `rl/`
- `backtest/`
- `data_pipeline/`

这些目录并非都是坏代码，但并不都属于桌面 runtime 主链。后续要继续区分：

- 主链
- 实验链
- 工具链

## 12. 建议的后续推进方向

按当前代码状态，最合理的推进顺序是：

1. 继续收 `run_id` 到 snapshot/bar/historical facts 的全链一致性
2. 继续缩 `OrderService`，把更多查询/编排细节下沉到专门服务
3. 继续把当前兼容持久化压成更明确的 repository / persistence boundary
4. 在边界稳定后再推进 PostgreSQL/Redis 迁移
5. 梳理实验目录与主链目录，明确哪些是核心运行模块，哪些是辅助/研究模块

## 13. 总结

当前 StockSim 的最佳理解方式是：

它是一个以桌面应用为外壳、以内嵌 runtime 交易后端为核心、以事件与持久化事实为基础、并正在向更正式数据架构演进的仿真交易平台。

当前系统已经不是“杂糅的脚本集合”，也还不是“完全收束完毕的正式平台”。它正处于一个比较关键、也比较健康的中期阶段：

- 前端边界已经比以前清晰
- runtime 主链已经逐步集中
- 持久化迁移已经开始落代码边界
- 但 `OrderService`、事件链和正式数据后端迁移仍是后续主战场

如果只用一句话概括当前架构状态：

**项目主链已经成形，当前重点不再是从零搭框架，而是继续把核心事实链、持久化边界和 oversized service 收到可长期维护的程度。**
