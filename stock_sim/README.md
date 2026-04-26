# UTI-STOCKSIM

_Last updated: 2026-04-26_

UTI-STOCKSIM 是一个桌面级交易仿真平台。它的核心目的不是做一个简单的股票行情玩具，而是在尽量贴近真实交易语义的前提下，为研究、教学、策略实验、行为金融模拟和强化学习训练提供一套可运行、可观察、可扩展的市场运行时。

项目最早立项时强调的方向仍然成立：

- 多标的撮合与订单簿
- 账户现金、冻结资金、冻结持仓、成交结算
- 风控、费用、T+1、融券卖空、IPO 分配等交易语义
- 大量 retail 交易者与少量模型/策略代理共同形成市场
- 可变速内部时钟、K 线、快照、成交、账本和运行统计
- 桌面前端用于观察、操作和调试完整模拟市场

现在项目已经从早期原型走向“交易运行时内核 + 桌面应用层 + 数据/实验平台”的阶段。README 只保留当前维护最需要的总览；更细的设计记录见 `docs/`。

---

## 当前定位

系统要回答的问题是：

> 如果把许多个有行为差异的交易者、真实约束的账户系统、撮合引擎、交易日时钟和可持久化的数据层放在一起，一个可研究、可调参、可回放的模拟市场应该怎样运行？

因此 UTI-STOCKSIM 的优先级是：

1. **交易语义正确**：订单、冻结、成交、结算、T+1、IPO、卖空等规则要有清晰来源。
2. **市场行为可信**：retail 不是固定脚本，而是由行为家族、性格参数和状态变量驱动。
3. **运行过程可观察**：market、agent、account、orders、leaderboard、clock 等面板能展示同一套 runtime truth。
4. **数据可恢复和可分析**：正式桌面运行默认使用 PostgreSQL，按 run 记录关键业务事实。
5. **重构可持续**：关键用户路径有回归测试，文档说明当前真实入口和真实数据源。

---

## 当前架构

```text
setup_frontend_entry.py
  ├─ app/app_context.py          组合桌面应用上下文
  ├─ app/ui/main_window.py       真实桌面主窗口
  ├─ app/panels/*                页面逻辑层
  ├─ app/controllers/*           面向页面的控制层
  ├─ app/ui/adapters/*           PySide6 渲染适配层
  └─ app/runtime_gateway.py      桌面层访问运行时的边界

services/*
  ├─ order_service.py            订单生命周期编排
  ├─ account_service.py          账户、冻结、持仓、账本、结算
  ├─ risk_engine.py              风控检查
  ├─ instrument_service.py       标的创建与撮合引擎注册
  ├─ runtime_command_service.py  桌面运行时命令入口
  ├─ runtime_query_service.py    桌面运行时查询入口
  └─ bar_aggregator.py           快照/成交到 K 线的聚合与持久化

core/*                           撮合、订单、交易、快照等领域模型
persistence/*                    SQLAlchemy ORM、数据库会话与 schema guard
agents/*                         retail 行为家族、persona、calibration
rl/*                             强化学习环境和策略实验代码
infra/*                          事件总线等基础设施
observability/*                  指标与结构化日志
docs/*                           架构、数据、契约、当前状态和任务记录
```

当前真实 GUI 启动入口是 `setup_frontend_entry.py`，安装后的脚本名是 `frontend-trading-ui`。`app/main.py` 已经不再是主入口。

---

## 数据与持久化

桌面运行默认使用 PostgreSQL 作为权威业务库。SQLite 只保留给测试、轻量诊断和本地 demo。

默认数据库 URL：

```text
postgresql+psycopg://stock_sim:stock_sim@127.0.0.1:5432/stock_sim
```

数据库选择优先级：

1. `STOCKSIM_DB_URL`
2. `DB_URL`
3. 内置 PostgreSQL 默认 URL

常用检查命令：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --check-db --require-postgres
```

相关设计文档：

- `docs/data/data-layering-design.md`
- `docs/data/data-layering-table-plan.md`
- `docs/data/postgresql-runtime-migration.md`
- `docs/data/run-context-design.md`
- `docs/data/run-id-wiring-plan.md`

---

## Retail 行为模型

retail 交易者是当前仿真真实性的重点。目标不是让 20 个脚本账户机械买卖，而是在 100+ 规模下形成更接近散户群体的行为分布。

当前 retail 方向包括：

- 行为家族配比：如 `mean_revert`、`buy_the_dip`、`profit_taking`、`liquidity_noise` 等。
- persona 参数：风险偏好、损失厌恶、勇气、耐心、价格敏感度、持仓倾向等。
- 状态变量：现金、可卖持仓、未成交挂单、近期盈亏、内部时钟驱动的持仓时间等。
- calibration：通过 episode 统计 buy/sell ratio、two-sided coverage、holding bars、成交活跃度等指标，而不是只靠主观观感调参。

关键文件：

- `agents/retail_strategy.py`
- `agents/retail_persona.py`
- `agents/retail_calibration.py`
- `agents/retail_calibration_report.py`
- `app/services/runtime_retail_agent.py`
- `scripts/run_retail_calibration_episode.py`
- `docs/architecture/runtime/retail-persona-calibration-blueprint.md`

---

## 桌面应用

桌面应用基于 PySide6，当前核心面板包括：

- Market：标的列表、市场快照、K 线、标的详情入口
- Symbol detail：单标的 K 线、盘口、成交、持仓视图
- Agents：retail / strategy agent 创建、启动、停止与状态观察
- Account：账户现金、冻结资金、持仓、风险暴露
- Orders：订单生命周期与账户影响
- Leaderboard：运行期表现排行
- Clock：内部模拟时钟、交易日推进和运行速度

运行 GUI：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py
```

如需跳过启动数据库检查，仅用于紧急诊断：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --skip-db-check
```

---

## 测试

常用测试入口：

```powershell
..\Quent\.venv\Scripts\python.exe -m pytest -q
```

针对桌面关键路径，优先关注：

- Market 列表与标的详情打开
- K 线加载、持久化与重启恢复
- Agent 创建、批量启动、状态持久化
- Clock 推进与日 K 换 bar
- 订单、成交、冻结、释放、T+1、IPO 分配
- PostgreSQL runtime 查询和写入路径

测试覆盖索引见：

- `docs/testing/runtime/runtime-critical-path-test-matrix.md`
- `docs/testing/runtime/runtime-critical-path-test-coverage-summary.md`

---

## 文档导航

维护时优先阅读：

- `docs/chief-engineer-handover.md`：总工程师接管视角的系统判断
- `docs/project-memory.md`：稳定结论和历史路线更新
- `docs/code-index.md`：当前关键代码入口索引
- `docs/decision-log.md`：重要架构决策
- `docs/current-work-status/`：模块级当前状态
- `docs/contracts/market/market-detail-contract.md`：Market detail 数据契约
- `docs/data/postgresql-runtime-migration.md`：PostgreSQL 持久化迁移状态

README 只描述项目当前总貌；细节应放入对应 docs 文件，避免再次变成不可维护的长文档。

---

## 当前工程原则

- PostgreSQL 是正式 runtime truth；SQLite 不再作为大量 retail 运行的默认方案。
- `setup_frontend_entry.py` + `app/ui/main_window.py` 是真实桌面入口。
- `services/order_service.py` 和 `services/account_service.py` 是交易语义核心，改动必须有测试护栏。
- Market detail 的 snapshot、bars、trades、holdings 来自不同路径，字段权威性必须在契约中说明。
- 新功能优先走现有 controller / panel / adapter / runtime_gateway 分层，不把业务逻辑塞进 Qt 控件。
- 行为模型调参应依赖 episode report 和验收指标，而不是只看单次 UI 表现。

---

## 近期路线

1. 继续收束 PostgreSQL runtime 持久化，减少 SQLite 兼容路径对正式运行的影响。
2. 稳定 Market detail / K 线 / bar 聚合 / 重启恢复链路。
3. 完善 retail persona 的耐心、持仓时间和多标的选择行为。
4. 强化 100 到 120 个 retail 规模下的 episode calibration report。
5. 逐步引入 Redis 或 Redis-compatible 热状态层，用于高频 UI 状态和运行时缓存。
6. 为 PostgreSQL 引入正式迁移工具，减少启动期 schema guard 的生产责任。

---

## 旧 README 内容处理说明

旧版 README 里关于“交易仿真平台、撮合、账户、风控、IPO、RL、桌面可视化”的立项目标仍然适用；关于 MySQL、`app/main.py`、早期 GUI 形态、未落地的 Redis/Kafka 计划、过细且已经漂移的 ER/事件示例等内容已经不再作为当前事实保留。

如果需要恢复某段历史设计，请优先将它整理进 `docs/` 下对应主题文件，而不是继续扩张 README。
