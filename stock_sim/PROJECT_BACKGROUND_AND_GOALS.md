# UTI-STOCKSIM 项目背景与目标说明

_Last updated: 2026-05-10_

## 1. 项目背景

UTI-STOCKSIM 是一个面向交易仿真、行为金融模拟和多智能体强化学习训练的桌面级平台。项目的出发点不是做一个简单的股票行情演示程序，而是构建一套具有真实交易语义、可观察运行过程、可持续扩展的模拟市场环境。

在真实市场中，交易策略并不是只面对价格序列本身，还会受到订单簿深度、撮合机制、账户资金、持仓冻结、交易规则、交易费用、散户行为噪声和市场时钟等因素影响。如果模型训练环境过于简化，模型可能学到只在玩具环境中有效的行为，进入真实市场后策略表现会迅速失效。

因此，本项目的核心背景是：需要一个比传统回测框架更接近交易运行时的仿真平台，让机器学习模型在训练阶段就面对更完整的市场约束和参与者生态。

## 2. 项目设计目的

项目最终希望设计一个可靠的交易仿真平台，使模型在其中训练得到的策略，能够尽可能具备迁移到真实市场后的有效性。

为了实现这一目标，平台需要满足以下设计目的：

1. 构建具有真实交易语义的模拟市场，包括多标的、订单簿、撮合、成交、账户、冻结、结算、费用、T+1、IPO 分配和卖空约束。
2. 构建可信的市场参与者生态，让大量 retail agent 以行为家族、性格参数和状态变量驱动市场噪声，而不是简单随机买卖。
3. 支持多个模型 agent 同时进入市场，在相同市场环境中对抗、学习、排名、继承和迭代。
4. 提供可观察的桌面前端，使开发者能够看到市场、账户、订单、agent 状态、K 线、排行榜和训练 Arena 的运行状态。
5. 提供正式的数据持久化和实验记录，使训练 episode、模型收益、transition、checkpoint 和 lineage 能被分析和比较。
6. 保留内部模拟时钟和可变速功能，使市场运行节奏能够被控制，便于加速训练、观察不同交易日周期下的行为变化。

项目不是为了让模型记住某一段固定行情，也不是为了只优化历史收益曲线。它的目标是提供一个足够真实、足够可控、足够可扩展的训练场，让模型在训练时接触到更接近真实交易的约束条件。

## 3. 核心技术路线

项目当前采用的核心技术路线可以概括为：

```text
真实交易语义 runtime
 + 锚定的 retail 行为生态
 + 多模型 Arena 对抗训练
 + Observation / Action / Reward contract
 + Recurrent Actor-Critic baseline
 + Population Based Training
 + Evidence Runner / Evidence Gate
 + Model Route Gate
 + PostgreSQL 持久化
 + 桌面级可观察 GUI
```

### 3.1 真实交易语义 runtime

交易运行时是平台的根基。所有模型和 retail agent 都必须通过正式订单、账户、风控和撮合路径参与市场，不能绕过交易规则直接修改价格或账户结果。

这一层负责保证：

- 订单提交、撤单、撮合和成交语义一致。
- 资金、持仓、冻结资金、冻结持仓和结算账本可追踪。
- T+1、卖空、费用、IPO 分配等交易规则由平台统一执行。
- K 线、快照、成交、账户状态来自同一套运行事实。

### 3.2 锚定的 retail 行为生态

真实市场不是只有模型之间互相交易。平台需要大量具有差异化行为的 retail agent，作为市场噪声、流动性来源和行为金融环境。

retail agent 的设计重点包括：

- 行为家族配比，例如均值回归、逢跌买入、止盈、流动性噪声等。
- 性格参数，例如风险偏好、损失厌恶、勇气、耐心、价格敏感度和持仓倾向。
- 状态变量，例如现金、持仓、可卖数量、近期盈亏、未成交挂单和持仓时间。
- calibration 指标，例如买卖比例、双边挂单覆盖率、持仓周期、成交活跃度和价格波动状态。

这部分的目标是让模型面对一个稳定但不死板的背景市场，避免训练环境过于干净，导致模型学到脱离现实的策略。

### 3.3 多模型 Arena 对抗训练

Arena 是模型训练的运行容器。它负责把多个模型、retail 背景、标的 universe、内部时钟和 episode 管理放在同一个训练场景中。

Arena 的作用包括：

- 创建一组模型 agent 和 retail agent。
- 启动一个训练 episode。
- 将模型绑定到同一市场环境。
- 收集 transition、收益、风险和成交质量。
- 在 episode 结束后进行排名。
- 触发 checkpoint、lineage 和 PBT 继承。
- 将胜者经验传递给失败者，让下一代模型继续进入市场。

当前第一代真实模型以 `ppo_lstm_v1` 为 baseline。它不是最终形态，而是用于先跑通完整训练闭环：观察、决策、下单、成交、奖励、学习、评估、继承。

### 3.4 模型交互 contract

模型不能直接依赖 GUI 或数据库表结构。平台通过正式 contract 与模型交互：

- Observation：模型能看到什么市场状态、账户状态和历史特征。
- Action：模型能表达什么交易意图，例如目标仓位、目标权重或保持不动。
- Reward：模型如何根据收益、风险、费用、换手、回撤和成交质量得到训练信号。
- Adapter：外部模型如何通过内置策略、HTTP、subprocess 或后续扩展接口接入平台。

这套 contract 的意义是把模型训练和交易运行时解耦，使后续可以替换 PPO/LSTM、接入外部深度学习脚本或引入新的策略模型，而不破坏平台核心交易语义。

### 3.5 PBT 与代际继承

单个模型从零训练容易不稳定，多模型环境也天然非平稳。因此平台采用种群式训练思想：

- 多个模型在同一市场中训练。
- 每个 episode 后对模型进行排名。
- 胜者保存 checkpoint。
- 失败者可以继承胜者参数，并带有扰动进入下一代。
- Hall-of-Fame 和 lineage 记录保留历史强者和代际关系。

这种机制的目标不是让所有模型快速变成同一个模型，而是在继承优秀经验的同时保留种群多样性，减少过拟合某一轮对手或某一种市场状态的风险。

### 3.6 PostgreSQL 持久化

正式桌面运行默认使用 PostgreSQL 作为业务数据和实验数据的持久化基础。它负责保存：

- 标的、订单、成交、账户、持仓和账本。
- agent 状态、模型 episode、transition 和结果排名。
- checkpoint、lineage 和训练实验报告。
- K 线、快照和运行统计。

持久化的目的不是把平台做成单纯的数据展示工具，而是确保每次训练和仿真运行产生的关键事实可以被追踪、诊断、统计和比较。

当前本地 Windows Python 3.11 runtime 已修复 PostgreSQL driver 路径：`psycopg[binary]` 在该环境不可用，纯 `psycopg` 又缺少 system `libpq`，因此项目现在声明并验证 `pg8000` 作为纯 Python fallback driver。无显式 `STOCKSIM_DB_URL` 时，默认 PostgreSQL URL 会解析为 `postgresql+pg8000://stock_sim:***@127.0.0.1:5432/stock_sim`；显式 `postgresql+psycopg://...`、`postgresql+pg8000://...` 和 `postgresql+psycopg2://...` 仍会被保留。

### 3.7 Evidence Runner 与模型路线闸门

第二轮专家评审后，项目的模型训练路线从“继续补齐报告字段”切换为“优先生成独立证据”。也就是说，Arena leaderboard 和训练收益不再足以支持父代继承、checkpoint 晋升或研究结论；模型必须通过 separate artifacts 和 evidence gate。

当前 Evidence Runner phase 的核心边界包括：

- `world_spec_v1` 与 `random_seed_ledger_v1`，用于固定世界身份、split、seed derivation 和可复现边界。
- `calibration_artifact_v1`、`baseline_artifact_v1`、`hidden_eval_artifact_v1`、`exploit_test_artifact_v1`、`paired_sensitivity_artifact_v1` 和 `parent_gate_artifact_v2`，用于把不同证据拆成独立 schema、独立 hash 和独立 runner ownership。
- Hidden-World Runner、Paired Fee/Impact Runner、Exploit Test Runner、Strict Parent Gate v2、Research Acceptance Lock v2、Series Evidence Aggregate、Evidence Board 和 Evidence Contract Tests。
- Long Arena Dry Run Package，用于把多代 series report、evidence aggregate、Evidence Board 和 gate review 收束成可 hash 的 evidence package。
- Evidence Runner Go / No-Go Review 和 Model Route Gate，用于在 live evidence package 通过之前阻止 Transformer、GTrXL、复杂 MARL、historical replay、hybrid env 和 alpha-claim 路线升级。

当前阶段的结论是：Evidence Runner 的 schema、runner、gate、aggregate、board、contract-test、headless package 和 live PostgreSQL/runtime package 边界已经形成。Python/runtime 依赖阻塞已解除，Task 101 已通过真实 `build_app_context()`、`ArenaExperimentRunner.run_generations(...)`、`RuntimeModelAgent`、`TrainingArenaService`、`TrainingEpisodeService` 和 PostgreSQL ORM 生成 database/runtime 证据包。随后修正了 Task 101 package status 语义：证据失败不再使包本身变成 `incomplete`，缺失或 not_available 才表示包不完整；旧格式 artifact 也会被 strict aggregate 拒绝，仅有 `pass_fail=true` 而缺少 `source=live_postgresql_runtime`、`pass_gate`、`runner_version` 时不能被当作研究证据通过。到 2026-05-10，live K 线事实链路、`MarketMetricsExtractor` 字段适配、exploit fee accounting、Paired Sensitivity live 成对场景、Strict Parent Gate v2 和 level-1 Research Acceptance Lock 已完成本轮工程闭环，最新 Task 101 live package 已进入 `complete / go`，7 项证据均为 pass。该结论只代表 level-1 engineering acceptance；`research_claim_eligible` 仍不是通过状态，后续若要进入更高层级研究或迁移结论，仍需按 gate 继续补证。

## 4. 各功能模块作用

### 4.1 Market 模块

Market 模块展示标的列表、最新价格、成交量、K 线和市场状态。它帮助用户观察当前仿真市场是否有合理的价格波动、成交活跃度和标的差异。

### 4.2 Symbol Detail 模块

Symbol Detail 模块用于查看单个标的的详细市场状态，包括 K 线、盘口、近期成交和相关持仓信息。它用于判断单个 instrument 的流动性、成交连续性和价格变化是否符合预期。

### 4.3 Orders 模块

Orders 模块展示订单生命周期，包括提交、部分成交、完全成交、撤单、拒单和冻结释放等状态。它是排查交易语义是否正确的重要入口。

### 4.4 Account 模块

Account 模块展示账户现金、冻结资金、持仓、可卖数量、成本、盈亏和风险暴露。模型和 retail 的行为最终都必须反映到账户结果中，因此账户模块是检验策略后果的核心视图。

### 4.5 Agents 模块

Agents 模块用于管理 retail agent、普通策略 agent 和 model agent。它负责展示 agent 状态、类型、运行状态、收益、最近动作和模型相关信息。

对于 retail，它关注行为家族和市场噪声；对于 model，它关注模型版本、训练模式、reward、equity、pnl 和运行状态。

### 4.6 Arena 模块

Arena 模块是多模型训练入口。它用于组织 episode、启动模型对抗、查看训练报告、观察收益曲线、检查 checkpoint 和 PBT 继承结果。

Arena 的目标是把模型训练从零散脚本推进为平台内的一等功能。第二轮 Evidence Runner 推进后，Arena 还需要承担证据展示入口的职责：不只显示收益排名，还要通过 Evidence Board 展示 baseline、calibration、hidden、exploit、fee/impact sensitivity、parent eligible 和 research claim eligible 等状态。

### 4.7 Leaderboard 模块

Leaderboard 模块展示 agent 或模型的收益排名。它不追求复杂的基金绩效系统，而是提供一个直观入口，让用户看到哪些 agent 在当前运行中表现更好，哪些模型在训练 episode 中排名靠前。

但在模型研究决策中，Leaderboard 已被降级为辅助视图。高收益不能自动代表模型可继承、可晋升或可写入研究结论；这些资格必须由 Evidence Board、parent gate artifact 和 research acceptance lock 决定。

### 4.8 Clock 模块

Clock 模块提供内部模拟时钟和可变速运行能力。它让平台可以按照内部交易日推进市场状态，也能加速 episode，便于训练和观察。

内部时钟是 K 线换 bar、持仓时间、T+1、retail 耐心参数和 episode 节奏的重要基础。

### 4.9 Data 与 Persistence 模块

数据层负责保存运行中的关键业务事实和训练结果。它不是前端展示的附属品，而是保证平台可诊断、可统计、可持续训练的基础设施。

### 4.10 Testing 与 Calibration 模块

测试模块保证订单、账户、K 线、agent、Arena 和模型训练链路不会在迭代中被破坏。Calibration 模块用于评估 retail 群体行为是否符合目标市场特征。

这两部分共同保证平台不是“看起来能跑”，而是在关键路径上具备持续维护能力。

## 5. 最终预期目的

项目的最终预期不是得到一个只在演示界面中好看的市场，而是形成一个能够支撑模型训练研究的可靠仿真平台。

最终平台应达到以下状态：

1. 市场运行时足够真实，模型训练时必须面对账户、订单、撮合、费用、风险和交易日规则。
2. retail 群体足够丰富，能够提供稳定但有噪声的市场背景。
3. 多个模型可以在同一个市场中长期对抗，形成可比较的训练结果。
4. 模型可以通过正式接口接入，而不是和平台代码强耦合。
5. 每轮训练都能产生可分析的 episode 结果、收益曲线、transition、checkpoint、lineage 和 separate evidence artifacts。
6. 训练后的模型策略不仅在平台内部取得收益，还能在 calibration、baseline、hidden evaluation、exploit test、paired sensitivity 和 strict parent gate 中保持行为合理性。
7. 平台能够支持后续更复杂的模型，例如 Transformer temporal encoder、league self-play、risk-constrained policy 和外部模型服务，但前提是 Evidence Runner Go / No-Go review 进入 Go，且 Model Route Gate 不再阻止复杂路线。

更长期地说，UTI-STOCKSIM 希望成为一个从“仿真市场”通向“真实策略研究”的桥梁：先让模型在足够真实的市场沙盘中学习，再用严格的评估、风险约束和多场景测试，筛选出更有可能在真实市场中有效的策略。

## 6. 当前阶段重点

当前阶段的重点不是立刻追求复杂模型，而是把 live database/runtime evidence package 从“能跑通”推进到“能可信通过证据门”。截至 2026-05-10，本轮 Task 101 已达到 level-1 engineering acceptance：

1. Python/runtime 依赖环境已修复，live `ArenaExperimentRunner` 能够导入并运行 PostgreSQL-backed 长 Arena series；Task 101 live long Arena dry run 已输出真实 database/runtime 证据包，而不是只依赖 headless injected package。
2. K 线事实链路已恢复并纳入 live Evidence Runner。Task 101 live run ids `RUN-DESKTOP-20260509072221-396C59C7`、`RUN-DESKTOP-20260509072248-C4D84D72`、`RUN-DESKTOP-20260509072323-75EBC381` 可从 PostgreSQL 读回 3 条 `training_episodes`、21 条 `model_episode_results`、57 条 `model_transitions`、153 条 `orders`、16 条 `trades`、85 条 `agent_bindings`、27 条 `account_equity_snapshots`、31 条 `snapshots_1s` 与 12 条 `bars_1m`，证明快照落库和 1m bar 聚合链路已恢复。
3. `MarketMetricsExtractor` 的 live DB 字段适配与派生逻辑已修复，calibration artifact `output/evidence_artifacts/calibration_artifact_v1/calibration-9ec30592adc94308.json` 达到 `pass_gate=true / engineering_pass=true`，P0 指标无 missing/failed。
4. Exploit Test 的 fee accounting 误判已修复，artifact `output/evidence_artifacts/exploit_test_artifact_v1/exploit-test-84e02e27bb78f921.json` 为 `pass_gate=true`。
5. Paired Sensitivity 已从 live PostgreSQL/runtime 跑出同一验证链路下的 `base`、`high_fee`、`high_impact`、`low_liquidity` 成对场景，并覆盖 `twap`、`vwap`、`ac_lite` 基线。最新 artifact `output/evidence_artifacts/paired_sensitivity_artifact_v1/paired-sensitivity-b66e251aa1ee4fae.json` 为 `source=live_postgresql_runtime`、`pass_gate=true`、`missing_required_metrics=[]`，source run ids 为 `RUN-DESKTOP-20260509194542-29544FD5`、`RUN-DESKTOP-20260509194606-316E6374`、`RUN-DESKTOP-20260509194635-33E96D91`、`RUN-DESKTOP-20260509194700-4BB2FE3E`。
6. Strict Parent Gate v2 和 level-1 Research Acceptance Lock 已随 Paired Sensitivity 修复后打开。最新 parent gate artifact `output/evidence_artifacts/parent_gate_artifact_v2/parent-gate-417bbb23bdf263e1.json`、research lock record `output/evidence_artifacts/research_acceptance_lock_v2/T101LIVE_CANDIDATE_20260509072220_paired_live_pass-be0408e7719ab2f3.json` 均为 `pass_gate=true`。
7. 最新 long Arena package `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-paired-20260509194542-package-e8f5ef55ca6f7c07.json` 已重算为 `status=complete`、`go_no_go=go`、`status_counts={"pass": 7}`、`failure_reasons=[]`。这表示工程证据门已可通过，但当前静态 candidate 仍主要用于工程验证；`research_claim_eligible` 仍为 fail，不应把本次 level-1 engineering acceptance 误读为更高层级研究结论或真实市场迁移承诺。
8. 后续仍应以 `ppo_lstm_v1`、外部静态候选和规则基线为工程验证对象；在更高层级证据补齐前，不升级 Transformer、GTrXL、复杂 MARL、historical replay、hybrid env 或 alpha-claim 路线。Evidence Board、Series Evidence Aggregate、Strict Parent Gate v2、Research Acceptance Lock v2 和 Model Route Gate 继续作为主要判断入口，避免 leaderboard 收益替代证据门。
 
