# UTI-STOCKSIM

_Last updated: 2026-05-17_

UTI-STOCKSIM 是一个桌面级交易仿真、多智能体训练与研究证据平台。它不是股票行情玩具，也不是传统回测脚本集合，而是一个以真实交易语义为核心、以 PySide6 桌面应用为观察与控制台、以 PostgreSQL 持久化为运行事实底座的模拟市场系统。

一句话定位：

```text
PySide6 桌面应用层
  + 内嵌交易运行时后端
  + PostgreSQL-first 权威持久化
  + 事件/快照/K线/回放恢复链
  + Retail 行为生态
  + Model Agent / Arena / PBT 训练闭环
  + Evidence Runner / Evidence Gate 研究证据层
```

当前项目已经从“能跑原型”进入“能否成为可信研究平台”的工程治理阶段。现在最重要的不是继续堆更复杂模型，而是把 live PostgreSQL-backed Arena 长跑、Evidence Runner、Strict Parent Gate、Research Acceptance Lock 和 Model Route Gate 变成实际约束模型路线的证据系统。

---

## 当前阶段结论

当前系统主架构已经成形，工程方向正确：

- 交易 runtime 已覆盖多标的撮合、订单簿、账户、冻结、费用、风控、T+1、卖空、IPO、成交结算和事件发布。
- 桌面前端已经收束到 `setup_frontend_entry.py`、`app/app_context.py`、`app/ui/main_window.py` 和 `RuntimeGateway` 主链。
- 正式运行默认使用 PostgreSQL；SQLite 只保留给测试、demo 和轻量诊断。
- 模型通过 `obs.v1`、`act.v1`、`rew.v1` 接入 runtime，不能绕过订单、账户、风控和撮合语义。
- Arena、PBT、checkpoint、lineage、episode result 和 Evidence Board 已经进入平台主线。
- Evidence Runner 已形成 schema、runner、artifact、aggregate、board 和 contract-test 边界，并已能基于 live PostgreSQL/runtime facts 生成 Task 101 level-1 engineering acceptance package。

当前最新状态是 **Evidence Runner level-1 engineering acceptance 已通过**：

- Task 101 live package 已从真实 PostgreSQL/runtime 证据重算为 `status=complete`、`go_no_go=go`、`status_counts={"pass": 7}`。
- baseline、calibration、hidden evaluation、exploit test、paired sensitivity、strict parent gate 和 research acceptance lock 均已在 level-1 工程验收口径下 pass。
- `paired_sensitivity_artifact_v1` 已覆盖 `base`、`high_fee`、`high_impact`、`low_liquidity` 四个 live 成对场景，并包含 `twap`、`vwap`、`ac_lite` 基线。
- leaderboard 收益不能作为父代资格、模型晋升或研究结论依据。
- 当前通过不等于高层级研究结论或真实市场迁移承诺；`research_claim_eligible` 仍不是通过状态，Transformer、GTrXL、复杂 MARL、historical replay、hybrid env、alpha-claim 等复杂路线仍应受 `ModelRouteGate` 约束。

近期允许的核心路线是：继续用 `ppo_lstm_v1`、外部静态候选和规则基线巩固 live evidence 闭环，并在更高层级证据补齐前避免升级模型复杂度。

## 提交包说明

评审用提交包通过以下命令生成：

```powershell
..\Quent\.venv\Scripts\python.exe scripts\package_submission.py
```

生成的 `stock_sim.zip` 只保留源码、配置、测试、文档和必要入口文件，不包含 `.venv/`、`.idea/`、`.pytest_cache/`、`__pycache__/`、`tmp/`、`logs/`、`output/`、`stock_sim.egg-info/` 或旧 evidence package。历史 output 与旧证据包仅为本地运行记录，不作为本文证据；若需要随包保留证据，只采用 `evidence/latest/` 下的 `latest_package.json`、`evidence_manifest.json`、`artifact_hashes.json`、`run_readback_summary.json`。

---

## 快速启动

真实 GUI 入口：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py
```

安装后的脚本入口：

```powershell
frontend-trading-ui
```

数据库健康检查：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --check-db --require-postgres
```

紧急诊断时跳过启动数据库检查：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --skip-db-check
```

Headless 入口用于 CI、测试和无 GUI 检查：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --headless
```

常用测试入口：

```powershell
..\Quent\.venv\Scripts\python.exe -m pytest -q
```

Arena 实验入口：

```powershell
..\Quent\.venv\Scripts\python.exe scripts\run_arena_experiment.py --generations 2 --duration 45 --retail-count 80 --symbols "001,002,003"
```

---

## 总体架构

当前最重要的运行链路：

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

市场数据和事件链路：

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

训练与证据链路：

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

---

## 目录与边界

```text
app/                    PySide6 桌面应用层、panel、controller、adapter、app service
core/                   撮合、订单簿、订单、成交、快照、集合竞价等领域模型
services/               runtime 后端服务、订单/账户/时钟/事件/恢复/训练编排
persistence/            SQLAlchemy ORM、数据库配置、schema guard、持久化模型
agents/                 retail 行为家族、persona、calibration、报告采集
rl/                     obs/act/rew contract、模型桥、PPO/LSTM 适配器、训练环境
infra/                  事件总线等基础设施
observability/          指标、性能监控、结构化日志
scripts/                诊断、回放、benchmark、Arena 实验和运维脚本
tests/                  前端、runtime、集成、回放恢复、训练和证据测试
docs/                   架构、契约、数据、路线、当前状态和任务记录
```

几个关键边界必须长期保持：

- `app/` 是桌面应用层，不应直接吸收 runtime ORM 查询。
- `RuntimeGateway` 是 app 层访问 runtime 的稳定边界。
- `RuntimeQueryService` / `RuntimeCommandService` 分别承载后端读/写入口。
- `core/` 只放领域模型和撮合规则，不放 GUI、ORM 或训练报告逻辑。
- 模型只能通过 observation/action/reward contract 与 runtime 交互。

---

## 数据与持久化

正式桌面 runtime 默认使用 PostgreSQL 作为权威业务库。SQLite 仅用于测试、轻量诊断和本地 demo。

默认数据库 URL：

```text
postgresql+psycopg://stock_sim:stock_sim@127.0.0.1:5432/stock_sim
```

数据库选择优先级：

1. `STOCKSIM_DB_URL`
2. `DB_URL`
3. 内置 PostgreSQL 默认 URL

当前持久化覆盖：

- accounts / positions / ledgers
- instruments
- orders / order_events / trades
- snapshots_1s / bars_1m / bars_1h / bars_1d
- event_log
- simulation_runs
- account_equity_snapshots
- agent_bindings
- training_episodes / model_episode_results / model_transitions
- model_checkpoints / model_lineage

当前仍未完成：

- Alembic 或等价正式迁移工具。
- Redis hot-state / realtime cache layer。
- SQLite 到 PostgreSQL 的正式实验数据迁移工具。

相关文档：

- `docs/data/data-layering-design.md`
- `docs/data/data-layering-table-plan.md`
- `docs/data/postgresql-runtime-migration.md`
- `docs/data/run-context-design.md`
- `docs/data/run-id-wiring-plan.md`

---

## 桌面应用模块

当前核心面板：

- Market：标的列表、市场快照、创建 instrument、进入 Symbol Detail。
- Symbol Detail：单标的 K线、盘口、成交 tape、指标、持仓辅助和健康状态。
- Account：现金、冻结现金、冻结费用、持仓、借入数量和风险暴露。
- Orders：订单提交、成交、撤单、拒单、账户影响和生命周期解释。
- Agents：retail、strategy、model agent 的创建、批量启动、停止与状态观察。
- Arena：训练 Arena、episode、排行榜、收益曲线和 Evidence Board。
- Leaderboard：agent/model 表现排行和账户权益历史。
- Clock：内部模拟时钟、交易日推进、暂停/恢复/速度控制。
- Settings / Notifications：设置、提示和告警。

Market Detail 需要特别理解：它不是单一后端查询对象，而是多源聚合页：

- `snapshot` / `order_book`：controller snapshot cache，事件驱动。
- `series` / `chart_meta`：app-layer market data service，bars/cache/runtime trade fallback。
- `trades`：runtime trade log + 页面本地 event overlay。
- `holdings`：app-layer helper，目前不是最强权威路径。
- `indicators`：基于 series 派生。
- `detail_health`：页面级健康解释。

字段权威性见：

- `docs/contracts/market/market-detail-contract.md`

---

## Runtime 交易后端

`services/order_service.py` 当前是订单主流程 facade，而不是继续承担所有细节的大泥球。订单路径已经拆给：

- `order_pretrade_service.py`：标准化、校验、风控、费用估算、冻结、拒单。
- `order_cancel_service.py`：撤单、IOC/FOK 剩余撤销、冻结释放、撤单事件。
- `order_engine_router.py`：symbol 到 engine 的解析和 registry 同步。
- `order_trade_settlement_service.py`：成交持久化、订单状态、账户结算、费用多退少补。
- `order_auction_reconciliation_service.py`：集合竞价残余清理。
- `order_maintenance_service.py`：交易日边界维护。
- `order_runtime_sync_service.py`：ORM 状态与 runtime order/book 同步。
- `order_persistence_service.py` / `trade_persistence_service.py`：订单和成交写入边界。

仍需长期警惕：任何新功能都不应顺手塞回 `OrderService.place_order()`。

其他关键 runtime 服务：

- `services/account_service.py`：账户、冻结、持仓、账本、结算。
- `services/instrument_service.py`：instrument 行 CRUD 和 runtime sync 调用。
- `services/instrument_runtime_service.py`：engine bootstrap、phase、reference snapshot、IPO timer。
- `services/sim_clock.py`：内部时钟和交易日推进。
- `services/simulation_run_service.py` / `services/run_context.py`：run_id 与 run 事实。
- `services/snapshot_listener.py` / `services/bar_aggregator.py`：快照和 K线持久化。
- `services/replay_service.py` / `services/recovery_service.py`：回放、run report 和恢复。

---

## Retail 行为生态

Retail 不是固定脚本或纯随机噪声，而是当前仿真真实性的核心来源。

当前 retail 能力包括：

- 行为家族：`mean_revert`、`buy_the_dip`、`profit_taking`、`liquidity_noise` 等。
- persona 参数：风险偏好、损失厌恶、勇气、耐心、价格敏感度、持仓倾向。
- 状态变量：现金、可卖持仓、未成交挂单、近期盈亏、持仓时间。
- calibration：buy/sell ratio、two-sided coverage、holding bars、成交活跃度、市场波动等指标。

关键文件：

- `agents/retail_strategy.py`
- `agents/retail_persona.py`
- `agents/retail_calibration.py`
- `agents/retail_calibration_report.py`
- `app/services/runtime_retail_agent.py`
- `scripts/run_retail_calibration_episode.py`
- `docs/architecture/runtime/retail-persona-calibration-blueprint.md`

---

## 模型训练、Arena 与 Evidence Runner

当前推荐路线仍是：

```text
Anchored Retail Ecology
 + League / Self-Play
 + Recurrent Actor-Critic
 + Population Based Training (PBT)
 + Hall-of-Fame / Payoff Matrix / Risk Constraints
```

已具备的训练能力：

- `Model` 是一等 agent 类型，可在 Agent 面板和 runtime 中创建、启动、停止、观察。
- `ppo_lstm_v1` 已作为 recurrent actor-critic baseline 接入。
- `RuntimeModelAgent` 记录 transition，并回写 reward、equity、pnl、last_action。
- `TrainingArenaService` 支持 Arena 创建、模型/retail 绑定、episode 启停和评估。
- `ArenaExperimentRunner` 支持多代实验、训练流动性注入、checkpoint、PBT 和 lineage。
- `TrainingEpisodeService` 负责 episode、result、transition 等训练事实持久化。

Evidence Runner phase 已形成以下边界：

- `world_spec_v1`
- `random_seed_ledger_v1`
- `calibration_artifact_v1`
- `baseline_artifact_v1`
- `hidden_eval_artifact_v1`
- `exploit_test_artifact_v1`
- `paired_sensitivity_artifact_v1`
- `parent_gate_artifact_v2`
- `research_acceptance_lock_v2`
- `series_evidence_aggregate_v1`
- `evidence_board`
- `model_route_gate_v1`

关键文件：

- `app/services/training_arena_service.py`
- `app/services/arena_experiment_runner.py`
- `app/services/model_registry_service.py`
- `app/services/runtime_model_agent.py`
- `app/services/model_checkpoint_service.py`
- `app/services/model_population_service.py`
- `app/services/evidence_core.py`
- `app/services/evidence_artifact_writer.py`
- `app/services/hidden_world_runner.py`
- `app/services/paired_sensitivity_runner.py`
- `app/services/exploit_test_runner.py`
- `app/services/strict_parent_gate.py`
- `app/services/research_acceptance_lock.py`
- `app/services/series_evidence_aggregate.py`
- `app/services/evidence_board_service.py`
- `app/services/long_arena_dry_run.py`
- `app/services/model_route_gate.py`
- `rl/model_adapters/ppo_recurrent_adapter.py`
- `services/training_episode_service.py`
- `scripts/run_arena_experiment.py`

当前研究纪律：

- Leaderboard 只是观察入口，不是父代资格。
- PBT 继承必须保留 checkpoint、lineage 和证据状态。
- 研究结论必须通过 Evidence Runner，而不是只看收益曲线。
- level-1 engineering acceptance 只能说明工程证据门可通过；在更高层级研究证据补齐前，不升级复杂模型路线。

相关文档：

- `docs/design/model-training-design.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/contracts/runtime/model-observation-contract.md`
- `docs/contracts/runtime/model-action-contract.md`
- `docs/contracts/runtime/model-reward-contract.md`
- `docs/contracts/runtime/model-adapter-contract.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

---

## 测试

测试重点：

- Market 列表与 Symbol Detail 打开。
- K线加载、bar 聚合、持久化与重启恢复。
- Agent 创建、批量启动、runtime binding 和状态持久化。
- Clock 推进、sim_day、run_id 与内部时钟。
- 订单、成交、冻结、释放、T+1、IPO、卖空、费用。
- PostgreSQL runtime 查询和写入路径。
- Replay / Recovery / run report。
- Model agent transition、reward、online learn、checkpoint、PBT lineage。
- Arena 多模型 episode、Evidence Board、Strict Parent Gate、Research Acceptance Lock、Model Route Gate。

测试覆盖索引：

- `docs/testing/runtime/runtime-critical-path-test-matrix.md`
- `docs/testing/runtime/runtime-critical-path-test-coverage-summary.md`

---

## 文档导航

新接手维护时建议按这个顺序读：

1. `StockSim项目架构分析报告.md`
2. `PROJECT_BACKGROUND_AND_GOALS.md`
3. `docs/code-index.md`
4. `docs/chief-engineer-handover.md`
5. `docs/project-memory.md`
6. `docs/decision-log.md`
7. `docs/current-work-status/`
8. `docs/contracts/market/market-detail-contract.md`
9. `docs/data/postgresql-runtime-migration.md`
10. `docs/current-work-status/model-training.md`
11. `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

README 只描述当前总貌。模块细节、任务记录、契约和落地状态应继续放在 `docs/` 或专题报告中，避免 README 再次膨胀成不可维护的长文档。

---

## 当前工程原则

- PostgreSQL 是正式 runtime truth；SQLite 不是大量 retail 或正式训练的默认方案。
- `setup_frontend_entry.py` + `app/ui/main_window.py` 是真实桌面入口。
- 新功能优先走 controller / panel / adapter / runtime_gateway 分层，不把业务逻辑塞进 Qt 控件。
- app 层不直接打开 runtime ORM session；标准路径应通过 `RuntimeGateway`。
- `services/order_service.py` 是协调门面，新职责应优先拆入专门 collaborator。
- `services/account_service.py` 的冻结、费用、借入、持仓语义必须被测试保护。
- Market Detail 必须显式表达不同字段的来源、权威性和 freshness。
- 模型训练必须尊重 runtime truth，只能通过 obs/act/rew contract 进入市场。
- PBT、模型晋升和研究结论必须依赖 evidence artifacts，而不是只依赖 leaderboard。
- Evidence Runner 的 level-1 go 不是 alpha/research claim；复杂模型路线仍应由 Model Route Gate 按证据层级约束。

---

## 近期路线

1. 保持 Task 101 live evidence package 的 `complete / go` 可重跑性，避免回退到 headless injected package 口径。
2. 将 `ModelRouteGate` 接入模型注册或 Arena 配置入口，按证据层级阻止复杂路线越权。
3. 为 PostgreSQL 引入正式迁移机制，减少 startup schema guard 的生产责任。
4. 继续稳定 Market Detail / K线 / bar 聚合 / 重启恢复链路。
5. 强化 Account / Orders 的端到端交易语义验收。
6. 完善 retail persona、持仓时间、多标的选择和 100+ retail calibration。
7. 选择 Redis 最小落地点，例如 latest snapshot/order-book 或 leaderboard hot cache。
8. 在更高层级 Evidence Runner 证据补齐后，再评估 Transformer、GTrXL、复杂 MARL 或 historical replay 路线。

---

## 旧内容处理说明

旧版 README 中关于“交易仿真平台、撮合、账户、风控、IPO、RL、桌面可视化”的立项目标仍然适用。

以下内容不再作为当前事实保留：

- MySQL 作为主要存储的旧设想。
- `app/main.py` 作为主入口的旧路径。
- 早期 GUI 形态。
- 未落地的 Redis/Kafka 大方案描述。
- 已经漂移的 ER/事件示例。
- 只用 leaderboard 收益判断模型好坏的早期训练心智。

需要恢复历史设计时，应整理进 `docs/` 下对应主题文件，而不是继续扩张 README。
