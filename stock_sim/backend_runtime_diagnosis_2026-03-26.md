# UTI-STOCKSIM 后端 runtime 诊断

日期：2026-03-26

## 1. 结论

当前后端已经形成了一条可工作的 runtime 主链，但仍存在三类明显问题：

1. 旧服务对象职责过重，runtime 引入后没有彻底收口。
2. 有几条老路径已经脱离当前主链，却还留在代码里制造误导。
3. 前端虽然开始通过 `RuntimeGateway` 收边界，但仍有多处直接 import backend runtime/persistence。

后端真正应保留并继续强化的主链应是：

- `core/matching_engine.py`
- `services/order_service.py`
- `services/account_service.py`
- `services/instrument_service.py`
- `services/engine_registry.py`
- `services/sim_clock.py`
- `services/run_context.py`
- `services/simulation_run_service.py`
- `services/event_persistence_service.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `services/replay_service.py`
- `services/recovery_service.py`

## 2. 当前后端主链

按当前代码，runtime 主链已经基本清晰：

- 标的创建：`app/controllers/market_controller.py` -> `services/instrument_service.py`
- 下单撮合：`app/services/trading_service.py` -> `app/runtime_gateway.py` -> `services/order_service.py` -> `core/matching_engine.py`
- 账户结算：`services/account_service.py`
- 时间推进：`app/services/clock_service.py` -> `app/runtime_gateway.py` -> `services/sim_clock.py`
- 运行批次语义：`services/run_context.py` + `services/simulation_run_service.py`
- 事件落地：`services/event_persistence_service.py`
- Snapshot/Bar 落地：`services/snapshot_listener.py` + `services/bar_aggregator.py`
- 回放/恢复：`services/replay_service.py` + `services/recovery_service.py`

这条链是应该继续保留并收束的“后端 runtime 核心”。

## 3. 主要缺陷

### 3.1 `OrderService` 仍然是过大的 runtime 总控对象

证据：

- [services/order_service.py](/F:/PythonProjects/stock_sim/services/order_service.py) 第 16-53 行在模块导入阶段 monkeypatch `AccountService`
- [services/order_service.py](/F:/PythonProjects/stock_sim/services/order_service.py) 第 91 行构造函数同时接管 `MatchingEngine / InstrumentService / RunContext / SimulationRunService / AccountService`
- [services/order_service.py](/F:/PythonProjects/stock_sim/services/order_service.py) 第 105 行 `_get_engine()` 承担了 engine 路由、instrument 回退、IPO/phase 修补等多重职责

诊断：

- 这是当前后端最明显的“God service”。
- `AccountService` 的运行时方法不应该由 `OrderService` 在 import 时动态注入。
- engine 获取、run 注册、冻结/释放/结算、风险/费用/快照挂钩，都堆在一个对象里，后续很难继续演进。

处理建议：

- 保留 `OrderService`，但只保留下单编排职责。
- 把 monkeypatch 过来的账户冻结/结算逻辑彻底收回 `services/account_service.py`。
- 把 `_get_engine()` 中的 instrument/engine 修补逻辑下沉到单独的 runtime engine resolver 或 instrument runtime service。

### 3.2 `InstrumentService` 混合了 CRUD 和 runtime bootstrap

证据：

- [services/instrument_service.py](/F:/PythonProjects/stock_sim/services/instrument_service.py) 第 73 行 `create()` 同时写 DB、建 instrument、建 engine、注册 engine、写 snapshot 初值、设置 IPO timer
- [services/instrument_service.py](/F:/PythonProjects/stock_sim/services/instrument_service.py) 第 251 行 `instrument_service_factory()` 自己创建 `SessionLocal()`

诊断：

- 这是典型的“持久化服务 + runtime bootstrap 服务”混写。
- 这种写法让调用方很难判断：自己是在做数据写入，还是在触发整套引擎副作用。
- `instrument_service_factory()` 还引入了隐藏 session 生命周期，容易制造事务边界不清。

处理建议：

- 保留 `InstrumentService` 但拆为两层：
- 一层是纯 DB/instrument repository service。
- 一层是 runtime instrument bootstrap service，负责 engine registry、IPO phase/timer、initial snapshot。
- 删除 `instrument_service_factory()` 这种隐式 session 工厂。

### 3.3 行情查询层存在命名重叠和层次倒挂

证据：

- [services/market_data_service.py](/F:/PythonProjects/stock_sim/services/market_data_service.py) 是 runtime engine 读模型
- [services/market_data_query_service.py](/F:/PythonProjects/stock_sim/services/market_data_query_service.py) 是持久化快照/特征查询
- [services/market_data_query_service.py](/F:/PythonProjects/stock_sim/services/market_data_query_service.py) 第 29 行定义了 `TickDTO`
- [core/ring_buffer.py](/F:/PythonProjects/stock_sim/core/ring_buffer.py) 复用了 `services.market_data_query_service.TickDTO`

诊断：

- 现在有两个都叫 market-data-service 的东西，但一个偏 runtime，一个偏 query/read-model。
- `core` 反向依赖 `services` 里的 DTO，是层次倒挂。

处理建议：

- `services/market_data_service.py` 可以更名为 runtime snapshot/book read service。
- `services/market_data_query_service.py` 应明确为 persisted market-data query service。
- `TickDTO` 应迁到独立 DTO 模块，避免 `core` 依赖 query service。

### 3.4 有几条老后端路径已基本脱链

证据：

- [services/snapshot_service.py](/F:/PythonProjects/stock_sim/services/snapshot_service.py) 只有自身和文档提及，未进入当前 GUI/headless/runtime bootstrap 主链
- [services/order_dispatcher.py](/F:/PythonProjects/stock_sim/services/order_dispatcher.py) 代码检索只剩自身定义，无当前主链引用
- [core/matching_engine_extended.py](/F:/PythonProjects/stock_sim/core/matching_engine_extended.py) 代码检索只剩文件自身

诊断：

- `snapshot_service.py` 是旧的文件快照导出方案，与现在的 `event_persistence_service + snapshot_listener + bar_aggregator + replay/recovery` 是平行旧链。
- `order_dispatcher.py` 看起来像早期异步下单队列壳层，但当前桌面/runtime 主链没有使用。
- `matching_engine_extended.py` 现在只是说明性空壳。

处理建议：

- 这三者都更接近“可删除/归档候选”，不是继续融进 runtime 的优先对象。
- 删除前只需要再做一轮针对 `scripts/` 和历史测试的确认即可。

### 3.5 前端与后端的边界还没有完全收干净

证据：

- [app/controllers/market_controller.py](/F:/PythonProjects/stock_sim/app/controllers/market_controller.py) 第 31-34、48-58、242-261 行仍直接碰 runtime session、instrument service、IPO distribution、sim_clock
- [app/services/account_service.py](/F:/PythonProjects/stock_sim/app/services/account_service.py) 第 31-42、113-123 行仍直接查 runtime ORM
- [app/services/market_data_service.py](/F:/PythonProjects/stock_sim/app/services/market_data_service.py) 第 16-27、196-206、262-274 行仍直接查 runtime bars/positions
- [app/services/runtime_retail_agent.py](/F:/PythonProjects/stock_sim/app/services/runtime_retail_agent.py) 第 10-19、134-189、329-362 行仍直接碰 engine registry、sim_clock、runtime account service
- [app/ui/adapters/market_adapter.py](/F:/PythonProjects/stock_sim/app/ui/adapters/market_adapter.py) 第 49-54、409 行仍直接读取 `current_sim_day`

诊断：

- `RuntimeGateway` 已经出现，但还没成为 app 层唯一后端入口。
- 当前 app 层仍有不少“直接摸 runtime”的代码，说明前后端边界只完成了第一阶段收口。

处理建议：

- 继续把 instrument 创建、account 查询、market history/holdings 查询、runtime retail 所需 runtime 读写，逐步收进 `app/runtime_gateway.py`。
- `market_adapter.py` 这类 UI 组件不应继续直接 import `services.sim_clock`。

## 4. 应保留并继续强化的 runtime 概念

下面这些不是冗余，反而是后端需要继续围绕 runtime 收束的核心：

- `run_context.py`
- `simulation_run_service.py`
- `event_persistence_service.py`
- `snapshot_listener.py`
- `bar_aggregator.py`
- `replay_service.py`
- `recovery_service.py`

原因：

- 这几项已经形成了“运行 -> 落地 -> 聚合 -> 校验/回放/恢复”的闭环。
- 它们的方向与 runtime 概念一致，不应该被当作旧代码删除。

其中要特别注意：

- [services/recovery_service.py](/F:/PythonProjects/stock_sim/services/recovery_service.py) 已经把 `run_id`、`EventLog`、`Snapshot1s`、`Bar1m/1h/1d` 串起来，这条线应继续保留。
- [services/replay_service.py](/F:/PythonProjects/stock_sim/services/replay_service.py) 已经是基于 `run_id/sim_day/sim_dt` 的事件回放和持久化对账工具，属于 runtime 的下游能力，不是废代码。

## 5. 删除 / 保留 / 融合建议

### 5.1 建议保留并拆层

- `services/order_service.py`
- `services/account_service.py`
- `services/instrument_service.py`
- `services/market_data_service.py`
- `services/market_data_query_service.py`

### 5.2 建议保留并继续 runtime 化

- `services/run_context.py`
- `services/simulation_run_service.py`
- `services/event_persistence_service.py`
- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `services/replay_service.py`
- `services/recovery_service.py`

### 5.3 建议列为安全删除候选

- `services/snapshot_service.py`
- `services/order_dispatcher.py`
- `core/matching_engine_extended.py`

## 6. 目标后端结构

建议最终收束成下面这套边界：

### 6.1 `core/`

只保留纯撮合与领域模型：

- matching engine
- order / trade / const
- instrument domain object

### 6.2 `services/`

按职责再分三类：

- runtime command services
- runtime persistence sidecars
- runtime query services

更具体地说：

- command：`order_service / account_service / instrument_runtime_bootstrap / sim_clock / ipo_service`
- persistence sidecars：`event_persistence_service / snapshot_listener / bar_aggregator`
- query：`market_data_query_service / replay_service / recovery_service`

### 6.3 `app/`

只通过 `RuntimeGateway` 访问 runtime：

- app 不直接 import persistence ORM
- app 不直接 import runtime sidecar/service
- UI adapter 不直接 import `services.sim_clock` 或 `engine_registry`

## 7. 建议的收束顺序

1. 先拆 `OrderService` 的 monkeypatch 和 engine resolver。
2. 再拆 `InstrumentService` 的 CRUD/runtime bootstrap 混写。
3. 把 app 层剩余直接 runtime import 收进 `RuntimeGateway`。
4. 迁移 `TickDTO` 到独立 DTO 模块，理顺 `core` 与 query service 的层次。
5. 最后再删除 `snapshot_service.py`、`order_dispatcher.py`、`matching_engine_extended.py` 这类已脱链文件。

## 8. 这次诊断后的判断

当前后端真正的问题，不是“runtime 引入失败”，而是“runtime 已经形成主链，但旧服务设计和旧辅助路径没有彻底退场”。  
所以这轮不建议盲目大删；正确顺序应该是：

- 先把主链边界理顺
- 再让前端只经由 gateway 访问 runtime
- 最后删掉已经确认脱链的旧代码

这样风险最低，也最符合现在项目的演进状态。
