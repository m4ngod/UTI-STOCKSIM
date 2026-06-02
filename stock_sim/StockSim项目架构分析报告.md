# StockSim 项目分析报告

更新时间：2026-05-11
分析视角：顶级交易系统架构师、量化研究平台负责人、桌面产品工程负责人联合视角

## 1. 报告定位

本报告基于当前代码与文档状态重新更新。参考范围包括：

- `README.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `docs/code-index.md`
- `docs/chief-engineer-handover.md`
- `docs/project-memory.md`
- `docs/decision-log.md`
- `docs/data/*`
- `docs/contracts/market/*`
- `docs/contracts/runtime/*`
- `docs/design/model-training-design.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/current-work-status/model-training.md`
- 当前 `app/`、`services/`、`core/`、`persistence/`、`agents/`、`rl/`、`tests/` 代码结构

本报告不再沿用 2026-03 版本中“兼容持久化层承压、RuntimeGateway 刚刚收束”的旧判断，而是按 2026-05-11 的真实工程状态重新评估项目。

结论先行：

**UTI-STOCKSIM 当前已经不是普通 Python GUI 或简单回测项目，而是一个单进程桌面应用承载的交易仿真 runtime、数据持久化平台、多智能体训练平台和研究证据平台。**

它的正确架构定义应是：

```text
PySide6 桌面应用层
  + 内嵌交易运行时后端
  + PostgreSQL-first 权威持久化
  + 事件/快照/K线/回放恢复链
  + Retail 行为生态
  + Model Agent / Arena / PBT 训练闭环
  + Evidence Runner / Evidence Gate 研究证据层
```

当前项目已经具备复杂系统雏形，且主线方向正确。现在最重要的工作不是继续堆更复杂模型，而是完成三件事：

1. 保持 Task 101 live PostgreSQL-backed evidence package 的 `complete / go` 可重跑性，并把 level-1 engineering acceptance 与更高层级研究结论严格区分。
2. 继续稳定 runtime truth，尤其是订单、账户、事件、run_id、K线和恢复链路。
3. 把证据门控从“报告可见”推进到“训练和模型路线实际强制执行”。

## 2. 项目总定位

StockSim 的目标不是做一个“股票行情演示器”，而是构建一个足够接近真实交易约束的训练沙盘。模型、retail agent、订单簿、账户、冻结、撮合、费用、T+1、IPO、卖空、时钟、K线和回放恢复都必须被放在同一套 runtime truth 中。

因此，该项目的产品形态和工程性质更接近：

```text
交易运行时内核
  -> 桌面观察与控制台
  -> 数据与实验记录系统
  -> 多智能体训练 Arena
  -> 研究证据与模型准入平台
```

它不是传统 Web 架构中的“前端 SPA + 后端 API”。当前前后端关系更准确地说是：

- 前端：PySide6 桌面 UI + app-layer service/controller/panel/adapter
- 后端：同进程内嵌 runtime service + core matching engine + ORM persistence
- 边界：`app/runtime_gateway.py`
- 后端读写分流：`services/runtime_query_service.py` 与 `services/runtime_command_service.py`
- 数据权威：正式 runtime 默认 PostgreSQL，SQLite 只作为测试、demo、诊断兼容路径

这是一种“模块化前后端边界”，不是物理进程隔离。

## 3. 总体架构主链

当前最重要的运行链路如下：

```text
setup_frontend_entry.py
  -> database health check
  -> reset_app_context()
  -> start_frontend_bridge()
  -> start_runtime_support_services()
  -> register_builtin_panels()
  -> register_ui_adapters()
  -> MainWindow

用户操作
  -> app/ui/adapters/*
  -> app/panels/*
  -> app/controllers/*
  -> app/services/*
  -> app/runtime_gateway.py
  -> services/runtime_query_service.py
     services/runtime_command_service.py
  -> services/*
  -> core/*
  -> persistence/*
```

事件和市场数据链路并行存在：

```text
OrderService / MatchingEngine / AccountService
  -> infra/event_bus.py
  -> snapshot_listener
  -> snapshots_1s
  -> bar_aggregator
  -> bars_1m / bars_1h / bars_1d
  -> EventBridge
  -> Market / Symbol Detail / Account / Orders / Leaderboard UI
```

训练链路则是：

```text
AgentService
  -> RuntimeRetailAgent / RuntimeModelAgent
  -> ModelRegistryService
  -> Observation / Action / Reward contracts
  -> TrainingArenaService
  -> ArenaExperimentRunner
  -> TrainingEpisodeService
  -> Checkpoint / PBT / Lineage
  -> Evidence Runner Stack
  -> Evidence Board / Strict Parent Gate / Research Acceptance Lock / Model Route Gate
```

这个结构说明项目已经从“能跑”进入“能审计、能训练、能追踪、能治理”的阶段。

## 4. 前端架构分析

### 4.1 入口与组合根

当前真实 GUI 入口是：

- `setup_frontend_entry.py`

该入口负责：

- 命令行参数解析
- PostgreSQL/SQLite 数据库健康检查
- 初始化语言与主题
- 重建共享 `AppContext`
- 启动 `EventBridge`
- 启动 runtime 支撑服务
- 注册面板与 Qt adapter
- 创建并展示 `MainWindow`

Headless 入口仍由：

- `app/headless.py`

负责，语义是“不启动真实 GUI 事件循环，但尽可能复用同一套 app context 与 panel logic”。

真正的桌面组合根是：

- `app/app_context.py`

它集中创建并共享：

- `RuntimeGateway`
- `MarketDataService / MarketController`
- `AccountService / AccountController`
- `TradingService / TradingController`
- `AgentService / AgentController`
- `ClockService / RollbackService / ClockController`
- `LeaderboardService / LeaderboardController`
- `TrainingArenaService`
- `ArenaExperimentRunner`

这是当前前端架构中最关键的收束点：面板不再各自随意创建 runtime service，而是共享同一套运行上下文。

### 4.2 UI 分层

当前前端不是“Qt 控件直接调用后端”，而是有清晰层次：

```text
app/ui/main_window.py        主窗口、工作区、Dock/页面承载
app/panels/*                UI-neutral 页面逻辑与视图模型
app/controllers/*           面向用户动作的控制边界
app/services/*              桌面应用层服务、DTO、缓存与 runtime 边界调用
app/ui/adapters/*           PySide6 渲染适配层
app/event_bridge.py         runtime event -> frontend topic/payload
```

这种分层适合桌面复杂工具，因为 UI adapter 可以变，panel/controller/service 的语义仍可保持稳定。

### 4.3 核心前端模块

当前桌面核心面板包括：

- Market：标的列表、市场快照、创建 instrument、进入详情。
- Symbol Detail：单标的 K线、盘口、成交 tape、持仓辅助、指标、健康状态。
- Account：现金、冻结资金、冻结费用、持仓、借入数量、风险暴露。
- Orders：提交、成交、撤单、拒单、账户影响和生命周期解释。
- Agents：retail、strategy、model agent 的创建、批量启动、状态观察。
- Arena：模型训练 Arena、episode、排行榜、收益曲线、Evidence Board。
- Leaderboard：agent/model 表现排行与账户权益历史。
- Clock：内部模拟时钟、交易日推进、暂停/恢复/速度控制。
- Settings / Notifications：设置、提示、告警与辅助状态。

### 4.4 Market Detail 的架构位置

Market Detail 是当前前端最能体现项目复杂度的页面。它不是后端一次查询返回的单源详情，而是多路径聚合：

- `snapshot` / `order_book`：来自 controller 的 snapshot cache，事件驱动。
- `series` / `chart_meta`：来自 `MarketDataService` 的 bars/cache/runtime trade fallback。
- `trades`：来自 runtime trade log + 页面本地 event overlay。
- `holdings`：来自 app-layer holdings helper，目前不是最强权威路径。
- `indicators`：来自 series 派生计算。
- `detail_health`：页面级健康解释对象。

当前契约文档已经明确：UI 必须诚实表达 `available / missing / stale / placeholder / error` 等状态，不能把多源数据伪装成同一个实时权威对象。

这是非常成熟的工程判断。交易系统前端最怕“看起来统一，实际上数据源不统一”。当前项目已经开始正面处理这个问题。

### 4.5 前端优势

当前前端架构的主要优势是：

1. 真实入口清晰，`setup_frontend_entry.py` 和 `MainWindow` 已成为主路径。
2. `AppContext` 是稳定组合根，减少服务实例漂移。
3. `RuntimeGateway` 形成 app/backend 边界。
4. panel/controller/service/adapter 分层基本成形。
5. Market Detail 已有明确数据契约，避免 UI 近似掩盖 runtime truth。
6. Account/Orders 已开始表达冻结、费用、借入、生命周期影响等交易语义。
7. Arena/Evidence Board 已进入桌面可见路径，不再只有命令行报告。

### 4.6 前端风险

仍需警惕：

- `app/ui/adapters/market_adapter.py`、`agents_adapter.py`、`arena_adapter.py` 仍然较重，adapter 层容易继续吸收状态判断。
- `EventBridge` 仍保留多 topic、兼容订阅、字符串事件名等历史负担。
- Market Detail 仍是多源聚合页，契约已经清楚，但长期最好继续提高 query/service 边界的一致性。
- `app/services/*` 与 `services/*` 同名较多，维护者必须持续区分 app-layer service 和 runtime service。

## 5. 后端 Runtime 架构分析

### 5.1 核心领域层

`core/` 是交易领域内核，主要包括：

- `matching_engine.py`
- `order_book.py`
- `order.py`
- `trade.py`
- `snapshot.py`
- `instruments.py`
- `auction_engine.py`
- `call_auction.py`
- `const.py`
- `validators.py`

它负责订单、撮合、订单簿、成交、快照、集合竞价、基本校验等低层语义。长期来看，`core/` 应保持“领域模型和撮合规则”定位，不应吸收 UI、ORM、训练报告等外层逻辑。

### 5.2 Runtime 服务层

`services/` 是当前后端主战场。它不是“工具函数目录”，而是 runtime 事实的编排层。

当前关键服务包括：

- `order_service.py`
- `account_service.py`
- `instrument_service.py`
- `risk_engine.py`
- `fee_engine.py`
- `engine_registry.py`
- `sim_clock.py`
- `runtime_command_service.py`
- `runtime_query_service.py`
- `simulation_run_service.py`
- `snapshot_listener.py`
- `bar_aggregator.py`
- `replay_service.py`
- `recovery_service.py`
- `training_episode_service.py`

### 5.3 OrderService 已从“巨型服务”拆成协调门面

旧报告认为 `OrderService` 是最大泥球风险。当前状态已经明显进步。

`services/order_service.py` 现在更接近订单主流程 facade，具体职责已拆给：

- `order_pretrade_service.py`：订单标准化、基础校验、风控、费用估算、冻结、拒单路径。
- `order_cancel_service.py`：用户撤单、IOC/FOK 剩余撤销、冻结释放、撤单事件。
- `order_engine_router.py`：symbol 到 engine 的解析、registry 同步、注入 engine 兼容。
- `order_trade_settlement_service.py`：成交持久化、订单状态更新、账户结算、费用多退少补。
- `order_auction_reconciliation_service.py`：集合竞价未成交残余清理。
- `order_maintenance_service.py`：交易日边界维护。
- `order_runtime_sync_service.py`：ORM 状态与内存 runtime order/book 的同步。
- `order_persistence_service.py` 与 `trade_persistence_service.py`：订单和成交写入边界。

当前订单路径大致为：

```text
place_order()
  -> recovery readonly guard
  -> auction reconciliation
  -> run registration
  -> pretrade.prepare_order()
  -> persist NEW
  -> engine.submit_order()
  -> trade_settlement.process_trades()
  -> cancellation / TIF finalize
  -> persist REST / FILLED / PARTIAL
```

这已经不是“一个文件包打天下”的状态。风险仍在，但已经从 P0 架构风险下降为“需要持续防止回流的大核心 facade”。

### 5.4 Account / Instrument / Runtime Command-Query

`services/account_service.py` 是账户语义中心，负责现金、冻结资金、冻结费用、持仓、借入数量、账本、结算和账户事件。

`services/instrument_service.py` 已收束为 instrument 行 CRUD、flush、runtime sync 调用。runtime engine bootstrap、phase、reference snapshot、IPO timer 等副作用已拆到：

- `services/instrument_runtime_service.py`

`RuntimeGateway` 现在已经很薄：

- 读侧委托 `RuntimeQueryService`
- 写侧委托 `RuntimeCommandService`

这条边界非常重要：

```text
app service/controller
  -> RuntimeGateway
  -> RuntimeQueryService / RuntimeCommandService
  -> backend domain services
```

它让 app 层无需直接打开 ORM session，也让后端查询和命令逻辑有了继续独立优化的空间。

### 5.5 时钟、RunContext 与 run_id

当前 runtime 会话语义已经明显成形：

- `services/run_context.py`
- `services/simulation_run_service.py`
- `services/sim_clock.py`
- `persistence/models_simulation_run.py`

正式桌面启动时，`RuntimeGateway.ensure_desktop_run()` 会确保 desktop-session 级 run 存在。核心事实表逐步带上 `run_id`：

- orders
- trades
- ledgers
- order_events
- event_log
- snapshots_1s
- bars_1m / 1h / 1d
- agent_bindings
- account_equity_snapshots
- training episodes / results / transitions / checkpoints / lineage

这意味着系统不再只是在“当前内存状态”里运行，而是开始形成可回放、可恢复、可比较的实验事实边界。

### 5.6 事件、快照、K线、回放恢复

当前事件基础设施是：

- `infra/event_bus.py`

市场事实链路是：

```text
MatchingEngine / OrderService / AccountService
  -> EventBus
  -> SnapshotPersistenceListener
  -> snapshots_1s
  -> BarAggregator
  -> bars_1m / bars_1h / bars_1d
  -> ReplayService / RecoveryService / frontend EventBridge
```

`start_runtime_support_services()` 在 GUI 启动时会启动：

- `snapshot_listener`
- `bar_aggregator`
- instrument runtime restore

这说明快照与 K线链不再是离线脚本，而是桌面 runtime 标准启动链的一部分。

## 6. 数据与持久化架构

### 6.1 PostgreSQL-first 已成为当前事实

旧报告把存储描述为“兼容持久化层承压”。当前应更新为：

**正式桌面 runtime 默认使用 PostgreSQL 作为权威业务库，SQLite 只保留给测试、轻量诊断和 demo。**

数据库 URL 优先级是：

1. `STOCKSIM_DB_URL`
2. `DB_URL`
3. 内置默认 PostgreSQL URL

默认 URL：

```text
postgresql+psycopg://stock_sim:stock_sim@127.0.0.1:5432/stock_sim
```

`persistence/db_config.py` 已经完成：

- PostgreSQL URL normalization
- SQLite/PostgreSQL dialect 判断
- PostgreSQL pool 配置
- SQLite dev/test 参数保留

### 6.2 Schema guard 与 ORM 模型

`persistence/models_init.py` 负责：

- `Base.metadata.create_all`
- event_log 表创建
- snapshot 扩展列
- sim_day / sim_dt / run_id 列补齐
- run-aware indexes
- legacy bar unique index 降级

当前 ORM 模型覆盖：

- accounts / positions / ledgers
- instruments
- orders / order_events / trades
- snapshots / bars
- event_log
- simulation_runs
- account_equity_snapshots
- agent_bindings
- training_episodes
- model_episode_results
- model_transitions
- model_checkpoints
- model_lineage

这已经能支撑运行事实、桌面展示、回放恢复和模型训练记录。

### 6.3 仍未完成的存储目标

当前存储路线仍有三个明确缺口：

1. 还没有 Alembic 等正式迁移工具，生产级 schema 演进仍依赖启动期 schema guard。
2. Redis 热状态层尚未真正落地，latest snapshot/order-book/leaderboard 等高频状态仍主要通过事件、内存和关系库路径协同。
3. 既有 SQLite 实验数据到 PostgreSQL 的迁移工具尚未形成正式能力。

因此当前评价是：

**PostgreSQL-first 已经落地到默认运行路径，但数据平台还未达到生产级迁移治理状态。**

## 7. Retail、Agent 与市场生态

项目的 market realism 不只来自撮合引擎，也来自 retail 参与者。

当前 retail 生态包括：

- `agents/retail_strategy.py`
- `agents/retail_persona.py`
- `agents/retail_calibration.py`
- `agents/retail_calibration_report.py`
- `app/services/runtime_retail_agent.py`

retail agent 不再只是随机下单，而是包含：

- 行为家族：momentum、mean revert、buy the dip、profit taking、liquidity noise 等。
- persona 参数：风险偏好、损失厌恶、勇气、耐心、价格敏感度、持仓倾向。
- 状态变量：现金、持仓、可卖数量、未成交挂单、近期盈亏、持仓时间。
- calibration 指标：买卖比例、双边覆盖、持仓周期、成交活跃度、波动特征。

`RuntimeRetailAgent` 已经通过 `RuntimeGateway` 读取时钟、可卖数量和提交订单，而不是直接打开后端 ORM session。这是 app/backend 边界收束的一部分。

Agent 模块还支持：

- retail 批量创建
- model agent 创建
- agent runtime binding
- agent 状态同步
- runtime meta 持久化
- 批量控制 start/stop

## 8. Model Training、Arena 与 Evidence Runner

### 8.1 训练系统当前定位

训练系统已经从“有 RL 目录”推进到：

```text
Model Agent
  -> Observation / Action / Reward contract
  -> RuntimeModelAgent
  -> TrainingArenaService
  -> ArenaExperimentRunner
  -> TrainingEpisodeService
  -> Checkpoint / PBT / Lineage
  -> Evidence Runner Stack
```

当前推荐模型路线仍是：

```text
Anchored Retail Ecology
 + League / Self-Play
 + Recurrent Actor-Critic
 + PBT
 + Hall-of-Fame / Payoff Matrix / Risk Constraints
```

但项目已经明确：近期不应升级 Transformer、GTrXL、复杂 MARL、historical replay、hybrid env 或 alpha claim 路线。

### 8.2 Contract 层

模型交互已通过 contract 约束：

- `obs.v1`：按 `market / account / context / features` 分层，区分 runtime truth 和 derived features。
- `act.v1`：支持 `order`、`target_weight`、`target_position`、`hold` 等动作语义。
- `rew.v1`：默认 `relative_equity_risk_adjusted_v1`，包含 equity、alpha、fee、drawdown、turnover、inventory 等组件。
- adapter contract：约束内置、checkpoint、HTTP、subprocess 等模型接入方式。

这是非常正确的方向。模型不能直接操作撮合引擎或账户结果，只能通过正式 action 进入 runtime truth。

### 8.3 Arena 与 PBT

`TrainingArenaService` 提供：

- create arena
- start arena
- stop arena
- evaluate arena
- 创建/绑定模型 agent
- 创建 retail 背景
- 创建 training episode
- episode 结束后排名和 summary

`ArenaExperimentRunner` 在此基础上承担：

- 多代实验
- 多模型同场对抗
- 训练流动性注入
- execution health
- checkpoint
- PBT
- lineage
- series report
- research acceptance sections

当前已有 `ppo_lstm_v1` 作为真实 recurrent actor-critic baseline，规则基线包括 hold/random/target_weight/TWAP/VWAP/AC-lite 等。

### 8.4 Evidence Runner Stack

第二轮专家评审后，项目已经从“metadata completeness phase”切换到“Evidence Runner phase”。这非常关键。

当前已形成或落地的证据组件包括：

- `evidence_core.py`
- `evidence_artifact_writer.py`
- `hidden_world_runner.py`
- `paired_sensitivity_runner.py`
- `exploit_test_runner.py`
- `strict_parent_gate.py`
- `research_acceptance_lock.py`
- `series_evidence_aggregate.py`
- `evidence_board_service.py`
- `long_arena_dry_run.py`
- `model_route_gate.py`

证据类型包括：

- WorldSpec
- RandomSeedLedger
- Calibration artifact
- Baseline artifact
- Hidden evaluation artifact
- Exploit test artifact
- Paired fee/impact sensitivity artifact
- Strict parent gate artifact
- Research acceptance lock
- Series evidence aggregate
- Evidence Board
- Model Route Gate

这套体系的核心目的不是“让报告更好看”，而是防止模型因为仿真器漏洞、数据泄漏、费用/冲击边界、单一世界过拟合或 PBT 选择偏差而被错误晋升。

### 8.5 当前 Go / 受限结论

当前模型路线已经从 Evidence Runner No-Go 推进到 level-1 engineering acceptance：

- schema、runner、gate、aggregate、board、contract test、headless package 边界已经形成。
- 本地 Python/runtime 依赖阻塞已解除，live PostgreSQL/runtime 长 Arena series 已能运行并生成真实 database/runtime evidence package。
- Task 101 最新 live package `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-paired-20260509194542-package-e8f5ef55ca6f7c07.json` 已重算为 `status=complete`、`go_no_go=go`、`status_counts={"pass": 7}`、`failure_reasons=[]`。
- baseline、calibration、hidden evaluation、exploit test、paired sensitivity、strict parent gate 和 level-1 research acceptance lock 均已在 live evidence 链路下通过。
- Paired Sensitivity 已覆盖 `base`、`high_fee`、`high_impact`、`low_liquidity` 四个 live 成对场景，以及 `twap`、`vwap`、`ac_lite` 基线。
- 但这仍只是 level-1 engineering acceptance；`research_claim_eligible` 仍不是通过状态，不能把当前静态候选解释为高层级研究结论、alpha claim 或真实市场迁移承诺。
- 复杂模型路线仍应由 Model Route Gate 按证据层级约束，不能用 leaderboard 收益替代 Evidence Board、Strict Parent Gate 和 Research Acceptance Lock。

这是一个成熟且克制的研究工程判断。交易模型研究最危险的不是慢，而是把工程验收通过误读成研究结论有效。

## 9. 功能模块全景

### 9.1 Market 模块

职责：

- instrument 列表
- 标的创建
- snapshot 合并
- 市场状态展示
- 进入 Symbol Detail

核心文件：

- `app/controllers/market_controller.py`
- `app/panels/market/panel.py`
- `app/services/market_data_service.py`
- `app/ui/adapters/market_adapter.py`

当前判断：主链清晰，但 detail 多源聚合仍需继续硬化 contract 与 UI 表达。

### 9.2 Orders 模块

职责：

- 下单
- 撤单
- 显示订单生命周期
- 解释账户影响

核心文件：

- `app/services/trading_service.py`
- `app/controllers/trading_controller.py`
- `app/panels/orders/panel.py`
- `app/ui/adapters/orders_adapter.py`
- `services/order_service.py`

当前判断：Orders 已经比普通订单列表更进一步，开始表达 runtime lifecycle semantics。

### 9.3 Account 模块

职责：

- 现金、冻结现金、冻结费用
- 持仓、冻结持仓、借入数量
- 账户状态和风险暴露
- runtime account event store

核心文件：

- `app/services/account_runtime_store.py`
- `app/services/account_service.py`
- `app/controllers/account_controller.py`
- `app/panels/account/panel.py`
- `app/ui/adapters/account_adapter.py`
- `services/account_service.py`

当前判断：账户模块是验证交易语义是否正确的关键视图，不能退化成普通资产摘要页。

### 9.4 Agents 模块

职责：

- retail/model/strategy agent 管理
- 批量创建
- 启动、暂停、停止
- 运行状态同步
- 模型 episode 绑定

核心文件：

- `app/services/agent_service.py`
- `app/controllers/agent_controller.py`
- `app/panels/agents/panel.py`
- `app/ui/adapters/agents_adapter.py`
- `app/services/runtime_retail_agent.py`
- `app/services/runtime_model_agent.py`

当前判断：Agent 模块已经从 UI 管理扩展为 runtime participant 管理层。

### 9.5 Arena 模块

职责：

- 多模型训练场
- episode 生命周期
- retail 背景注入
- 模型排名
- evidence board

核心文件：

- `app/services/training_arena_service.py`
- `app/services/arena_experiment_runner.py`
- `app/panels/arena/panel.py`
- `app/ui/adapters/arena_adapter.py`
- `services/training_episode_service.py`

当前判断：Arena 是项目从“仿真平台”升级为“研究平台”的关键模块，但 live 长跑证据仍未完成。

### 9.6 Leaderboard 模块

职责：

- agent/model 表现排行
- equity history
- 运行期表现视图

核心文件：

- `app/services/leaderboard_service.py`
- `app/controllers/leaderboard_controller.py`
- `app/panels/leaderboard/panel.py`
- `app/ui/adapters/leaderboard_adapter.py`

当前判断：Leaderboard 是观察入口，不应再作为模型晋升或研究结论的依据。

### 9.7 Clock 模块

职责：

- 内部交易日时钟
- start/pause/resume/stop/speed
- sim_day 推进
- run_id 关联

核心文件：

- `app/services/clock_service.py`
- `app/controllers/clock_controller.py`
- `app/panels/clock/panel.py`
- `services/sim_clock.py`
- `services/runtime_command_service.py`

当前判断：Clock 是连接 GUI、runtime、K线、T+1、retail 耐心、episode 节奏的基础设施。

### 9.8 Data / Replay / Recovery 模块

职责：

- 运行事实持久化
- 快照/K线聚合
- run report
- replay
- recovery

核心文件：

- `services/snapshot_listener.py`
- `services/bar_aggregator.py`
- `services/replay_service.py`
- `services/recovery_service.py`
- `services/run_persistence_query_service.py`
- `persistence/*`

当前判断：这是从“演示系统”走向“实验平台”的底座。后续应继续让 run_id 和事实链完全一致。

## 10. 测试与文档资产

当前项目测试资产已经相当丰富，包含：

- frontend unit
- frontend integration
- frontend e2e/headless
- runtime tests
- order/account semantics tests
- replay/recovery tests
- database health/config tests
- market detail contract tests
- model/Arena/evidence tests

当前仓内 `test_*.py` 规模已经超过两百个文件，测试函数数量也达到数百级。文档资产同样庞大，`docs/` 下有架构、契约、数据、当前状态、任务拆分、测试矩阵等大量 Markdown。

这说明项目不是“无测试靠手感推进”，而是已经具备复杂重构所需的护栏。下一步重点不是简单增加测试数量，而是让最关键的 live runtime + PostgreSQL + Arena evidence package 长期保持可重复验证。

## 11. 当前最强优势

从专家视角看，StockSim 当前最强的地方有七个：

1. **交易语义意识强**：订单、账户、冻结、费用、T+1、卖空、IPO 没有被 UI 或模型训练简化掉。
2. **前后端边界已经真实存在**：`RuntimeGateway -> RuntimeQueryService / RuntimeCommandService` 是有效收束。
3. **OrderService 拆分方向正确**：pretrade、cancel、router、settlement、runtime sync 已从主服务拆出。
4. **PostgreSQL-first 路线已经落地**：默认运行心智从 SQLite 转向正式业务库。
5. **Market Detail 契约意识成熟**：承认多源事实，比伪装单源更专业。
6. **模型训练没有绕过 runtime truth**：obs/act/rew contract 约束了模型进入市场的方式。
7. **Evidence Runner 思路非常正确**：收益排名不再直接等于父代资格或研究结论。

## 12. 当前核心风险

### P0：Evidence Runner level-1 go 的可重跑性与边界

当前 live PostgreSQL/runtime 长 Arena series 已经跑通，并生成 `complete / go` 的 level-1 engineering acceptance package。新的风险不再是“跑不通”，而是后续迭代中回退到 injected artifact、旧格式 artifact 或把 level-1 go 误读成 research/transfer claim。

建议：

- 保持 Task 101 live package 可一键重跑，并保留 source run ids、runner version、artifact hash 与 gate decision。
- 明确禁止用 headless injected package 替代 live research evidence。
- 在 Evidence Board、Series Evidence Aggregate、Strict Parent Gate、Research Acceptance Lock 中持续区分 `level_1_engineering_acceptance` 与更高层级 claim。
- Model Route Gate 继续按证据层级约束复杂路线。

### P0：PostgreSQL schema 治理仍偏工程过渡态

默认 PostgreSQL 已落地，但生产式迁移工具仍缺失。

建议：

- 引入 Alembic 或等价迁移机制。
- 将 startup schema guard 降级为 dev/test 兼容手段。
- 固化 run-aware index、training tables、evidence artifacts 的迁移脚本。

### P0：订单/账户语义仍需持续严防回流

虽然 `OrderService` 已拆分，但它仍是 runtime 的关键门面。后续任何新功能都可能顺手塞回主服务。

建议：

- 明确禁止把新业务直接塞进 `OrderService.place_order()`。
- 对 pretrade、cancel、settlement、auction、maintenance 分别维护测试。
- 对账户冻结、释放、费用、借入、T+1 建立更高层 invariant 测试。

### P1：Redis 热状态层尚未落地

项目目标中 Redis 是 hot-state / real-time cache layer，但当前仍主要依赖事件、内存和 PostgreSQL。

建议：

- 先选一个最小切片，例如 latest snapshot/order-book 或 leaderboard hot cache。
- 不要一开始做全量 Redis 化。
- 保持 PostgreSQL 作为 authoritative store。

### P1：EventBridge 兼容负担

事件桥仍有 canonical topic 与 legacy topic 并存的状态。

建议：

- 建立事件 topic registry。
- 给事件 payload contract 加版本和 schema 测试。
- 分阶段减少 legacy topic 的订阅面。

### P1：UI adapter 仍然偏重

特别是 Market/Arena/Agents adapter，仍有继续长胖风险。

建议：

- 把状态判断放回 panel/service。
- adapter 只负责渲染和 UI 事件绑定。
- 为复杂 label/table/chart builder 保持纯函数测试。

### P2：包结构与命名仍可能误导新人

`app/services/account_service.py` 与 `services/account_service.py` 这类同名文件需要持续文档化，否则新人很容易混淆 app-layer 与 runtime-layer。

建议：

- 在 code-index 和开发文档中持续强调命名边界。
- 未来如果重构成本可控，可逐步改成 `app_facade`、`runtime_service` 等更显式命名。

## 13. 建议路线图

### 未来 2 周

1. 保持 Task 101 live evidence package 的 `complete / go` 可重跑性，确保 paired sensitivity、parent gate 和 research lock 不回退到 injected 或旧 artifact 口径。
2. 将 `ModelRouteGate` 的证据层级决策接入模型注册或 Arena 配置入口，防止复杂路线绕过。
3. 继续保证 `setup_frontend_entry.py --check-db --require-postgres` 是正式运行前置检查。
4. 明确区分 level-1 engineering acceptance 与更高层级 research/transfer acceptance，在 UI 和文档中避免误读。

### 未来 1 个月

1. 引入正式迁移方案，先覆盖已有 run_id/training/evidence 相关表。
2. 将 Evidence artifacts 的存储从 JSON 文件边界进一步规划到数据库或 artifact registry。
3. 强化 Market Detail 的 holdings 权威路径，减少 placeholder 语义。
4. 对 Account/Orders 做一组跨 UI + runtime 的端到端语义验收。

### 未来 2 到 3 个月

1. 选择 Redis 最小落地点，优先处理 latest market state 或 leaderboard hot cache。
2. 将 Evidence Board 从“展示状态”推进为“阻断父代/晋升/研究结论”的实际控制面。
3. 运行多轮真实 Arena series，验证 PBT 是否在 hidden/exploit/sensitivity 中保持稳健。
4. 在更高层级 Evidence Runner 证据补齐后，再评估 Transformer、GTrXL、复杂 MARL 或 historical replay 路线。

## 14. 专家总评

StockSim 当前处在一个很关键也很有价值的阶段。

它已经越过了“能不能跑起来”的原型期，进入“能不能作为可信研究平台”的工程治理期。真正的好消息是：项目并没有被复杂模型诱惑带偏，而是开始把 runtime truth、数据契约、run_id、PostgreSQL、Arena、PBT、Evidence Gate 放到同一套可审计体系里。

当前最值得肯定的不是某个单点功能，而是系统方向：

```text
模型必须通过真实交易语义行动；
收益必须被证据解释；
父代资格必须被门控；
研究结论必须依赖独立 artifact；
桌面 UI 必须显示 runtime truth，而不是制造漂亮幻觉。
```

这正是交易仿真与量化研究平台应该有的工程伦理。

但也必须保持克制：当前 Evidence Runner 已达到 level-1 engineering acceptance，不再是旧的 No-Go；不过 PostgreSQL schema 迁移治理还不够正式，Redis hot-state 层尚未落地，`research_claim_eligible` 仍不是通过状态，复杂模型路线仍应按证据层级受控。

一句话结论：

**StockSim 的主架构已经成形，工程方向是对的；下一阶段成败不取决于是否更快引入复杂模型，而取决于能否把已经跑通的 live PostgreSQL-backed Evidence Gate 固化为可重跑、可阻断、可区分工程验收与研究结论的治理系统。**
