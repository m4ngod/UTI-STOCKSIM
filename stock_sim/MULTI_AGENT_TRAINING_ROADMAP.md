# UTI-STOCKSIM 多智能体对抗交易训练平台改造路线

_Last updated: 2026-04-26_

## Implementation Progress Ledger

This section is the authoritative anti-duplication checklist for the platform rewrite.

### Completed in round 1

- [x] Agent panel supports `All / Retail / Model` filtering.
- [x] `Model` is a first-class app-layer agent type.
- [x] `ModelRegistryService` exists with `HoldModel` and `RandomWeightModel`.
- [x] `RuntimeModelAgent` MVP exists.
- [x] `obs.v1` has a multi-symbol builder path.
- [x] `act.v1` parses `target_weight` and `target_position`.
- [x] `ModelBridge` translates `target_weight` into runtime orders.
- [x] `rew.v1` exists through `RewardBuilder`.
- [x] Model reward contract documentation exists.

### Completed in round 2

- [x] Added persistence models for `training_episodes`, `model_episode_results`, and `model_transitions`.
- [x] Added `TrainingEpisodeService` for episode creation, transition recording, result upsert, and ranking.
- [x] `RuntimeModelAgent` can persist per-step transitions and update per-agent episode results.
- [x] `RuntimeModelAgent` reports `last_reward`, `last_action`, `equity`, and `pnl` back to `AgentService`.
- [x] Agent panel model rows can display the latest model metrics.

### Completed in round 3

- [x] Added `TrainingArenaService` MVP.
- [x] Arena service supports create/start/stop/evaluate.
- [x] Arena start creates a training episode and binds model agents to it.
- [x] Arena evaluate ranks episode results and completes the episode.
- [x] Arena service can optionally create and start retail background agents.

### Completed in round 4

- [x] Added `model_checkpoints` and `model_lineage` persistence.
- [x] Added `ModelCheckpointService` for checkpoint, Hall-of-Fame, and lineage records.
- [x] Added `ModelPopulationService` MVP for episode-based PBT inheritance.
- [x] Top episode models are saved as Hall-of-Fame checkpoints.
- [x] Bottom episode models receive full-clone-plus-mutation lineage records.

### Completed in round 5

- [x] `ModelCheckpointService` materializes JSON checkpoint artifacts alongside DB rows.
- [x] Checkpoint artifacts include episode score, rank metrics, generation, Hall-of-Fame flag, and payload metadata.
- [x] `AgentService` exposes `apply_model_inheritance(...)` for controlled Model Agent identity updates.
- [x] `ModelPopulationService` can apply PBT inheritance back to losing live Model Agents.
- [x] Applied inheritance increments `params_version`, records parent checkpoint metadata, and clears stale runtime instances.

### Completed in round 6

- [x] `ModelRegistryService` can discover checkpoint-backed child models from `model_lineage`.
- [x] `ModelRegistryService.create_policy(...)` can instantiate checkpoint-backed child policies.
- [x] Checkpoint-backed policies expose parent checkpoint metadata in action `meta`.
- [x] `RuntimeModelAgent` can run a PBT child model id produced by lineage.
- [x] Unknown `*.gen*` child ids gracefully fall back to their known built-in parent policy when DB lineage is unavailable.

### Completed in round 7

- [x] Added `ExternalPolicyAdapter` for registry-backed non-built-in policies.
- [x] Added `TrainableModelPolicy` protocol for optional `learn(...)` and `save_checkpoint(...)` support.
- [x] `ModelRegistryService` can persist external policy metadata to `output/model_registry/policies.json`.
- [x] `ModelRegistryService` can load `static_action` and injected `callable` policy adapters.
- [x] `RuntimeModelAgent` can run registered external policies through the same `act.v1` path.
- [x] Added `docs/contracts/runtime/model-adapter-contract.md`.

### Completed in round 8

- [x] Added HTTP mode to `ExternalPolicyAdapter`.
- [x] HTTP policies can call remote `/act` endpoints and normalize returned actions into `act.v1`.
- [x] HTTP policies can optionally call remote `/learn` and `/checkpoint` endpoints.
- [x] `RuntimeModelAgent` can run registry-backed HTTP policies without runtime branching.
- [x] HTTP adapter failures fall back to `hold` with error metadata instead of crashing the runtime loop.

### Completed in round 9

- [x] Added subprocess mode to `ExternalPolicyAdapter`.
- [x] Subprocess policies exchange JSON over stdin/stdout.
- [x] Subprocess policies can provide `act`, `learn`, and `checkpoint` operations.
- [x] `RuntimeModelAgent` can run registry-backed subprocess policies without runtime branching.
- [x] Subprocess adapter failures fall back to `hold` with error metadata instead of crashing the runtime loop.

### Completed in round 10

- [x] Added tensor checkpoint save/load support to `ModelCheckpointService`.
- [x] Tensor checkpoints materialize `.npz` weight files plus JSON manifests.
- [x] Tensor checkpoint manifests record tensor names, shapes, dtypes, score, generation, episode, and Hall-of-Fame metadata.
- [x] Tensor checkpoint rows update `meta_json` with artifact schema, tensor file path, and tensor count.

### Not done yet

- [ ] Dedicated Arena panel.
- [ ] Real PPO/LSTM or external model adapter.

## 1. 文档目的

本文件用于规划 UTI-STOCKSIM 下一阶段的主线工作：从“桌面级交易仿真平台”改造为“多智能体对抗交易训练平台”。

上一份文档 `MODEL_TRAINING_DESIGN.md` 主要回答：

- 应该采用什么训练范式
- 为什么推荐 League Self-Play + PBT + Recurrent Actor-Critic
- 为什么 GAN / 不明确的 GCA 不适合作为主框架
- 胜者如何向失败者传授参数

本文档回答：

> 接下来具体要做哪些工程工作，按什么顺序做，每一步的产物和验收标准是什么。

---

## 2. 下一阶段总目标

下一阶段的目标是让平台支持：

1. 模型作为一等 Agent 被创建、启动、停止和观察。
2. 2 个或更多模型可以挂载到同一仿真市场中进行对抗。
3. retail 群体作为背景市场噪声和行为生态持续存在。
4. 模型通过正式 Observation / Action / Reward contract 与 runtime 交互。
5. 每个 episode 能生成训练报告、排名和模型 lineage。
6. 每轮胜者可以通过 PBT 机制向失败者传授参数，并继续下一轮对抗。
7. 桌面前端能区分 Retail / Model / Arena，并展示训练状态。

最终形态：

```text
Desktop App
  -> create arena
  -> attach model agents
  -> attach retail background agents
  -> start clock
  -> run episode
  -> collect rewards / rankings / checkpoints
  -> apply PBT inheritance
  -> start next generation
```

---

## 3. 当前基础条件

当前平台已经具备以下基础：

- PostgreSQL-first runtime persistence
- 多标的撮合和 instrument 管理
- retail 群体创建、启动、停止和持久化
- Market 面板与 Symbol detail K 线
- Agent 面板支持多选 start / stop 的基础能力
- Clock 内部时钟与 sim_day 推进
- `rl/model_bridge.py`、`rl/observation_builder.py`、`rl/action_parser.py` 的 MVP
- `docs/contracts/runtime/model-observation-contract.md`
- `docs/contracts/runtime/model-action-contract.md`
- `MODEL_TRAINING_DESIGN.md`

主要缺口：

- 还没有正式 `Model` agent 类型
- 还没有 runtime model agent 生命周期
- action contract 还未完整支持 `target_weight`
- reward contract 尚未落地
- 没有 Arena / Episode / League / PBT 管理层
- Agent 面板还不能按 Retail / Model 清晰筛选和展示
- 模型训练结果、checkpoint、lineage 还没有持久化路径

---

## 4. 架构改造原则

## 4.1 模型不能直接访问撮合引擎

模型只允许通过 contract 与平台交互：

```text
ObservationContract -> model.act() -> ActionContract -> runtime execution -> RewardContract
```

禁止：

- 模型直接调用 matching engine
- 模型直接改 account / position
- 模型直接写数据库
- 模型依赖 Qt / panel / adapter 语义

## 4.2 Runtime truth 仍然在 services 层

模型输出只是 intent，不是事实。

事实仍由以下路径决定：

- `services/order_service.py`
- `services/account_service.py`
- `services/risk_engine.py`
- `services/instrument_service.py`
- `services/runtime_command_service.py`
- `services/runtime_query_service.py`

## 4.3 前端只观察和控制，不承载训练逻辑

Agent 面板和未来 Arena 面板只负责：

- 创建配置
- 启停控制
- 状态展示
- 报告入口

训练循环、episode 管理、PBT、checkpoint 不应写进 UI adapter。

## 4.4 先跑通闭环，再追求算法复杂度

第一阶段的目标不是立刻训练出强模型，而是跑通：

```text
Model Agent -> observation -> action -> execution -> reward -> report
```

只要闭环可靠，后续才能安全接入 PPO/LSTM、MAPPO、PSRO 或外部模型服务。

---

## 5. 目标模块设计

## 5.1 Model Agent 层

新增：

```text
app/services/runtime_model_agent.py
app/services/model_registry_service.py
```

`RuntimeModelAgent` 职责：

- 生命周期：start / pause / stop
- 决策循环：按 clock 和 decision_interval 执行
- observation 构建
- 调用 policy
- action 解析和执行
- reward 构建
- transition 记录
- heartbeat / metrics 发布

`ModelRegistryService` 职责：

- 注册模型类型
- 加载内置模型
- 加载 checkpoint
- 绑定 policy path / external endpoint
- 提供模型状态摘要

第一阶段内置模型：

```text
RandomWeightModel
HoldModel
SimpleMomentumModel
```

这些模型不是为了盈利，而是为了验证 contract 和 runtime 闭环。

## 5.2 Contract 层

扩展：

```text
rl/contracts.py
rl/observation_builder.py
rl/action_parser.py
rl/reward_builder.py
```

需要落地：

- `obs.v1` multi-symbol universe
- `act.v1` target_weight
- `act.v1` target_position
- `rew.v1`
- transition record

最小 transition：

```python
{
    "run_id": "...",
    "episode_id": "...",
    "arena_id": "...",
    "agent_id": "...",
    "step_index": 12,
    "observation": {...},
    "action": {...},
    "execution_result": {...},
    "reward": {...},
    "next_observation_ref": "...",
}
```

## 5.3 Arena 层

新增：

```text
app/services/training_arena_service.py
```

职责：

- 创建 arena
- 绑定模型 agent
- 绑定 retail 背景数量
- 管理 episode
- 启动 / 停止 / 重置
- 统计每个模型表现
- 生成 episode report
- 调用 PBT 策略

Arena 状态：

```text
CREATED
READY
RUNNING
PAUSED
EVALUATING
EVOLVING
STOPPED
FAILED
```

## 5.4 PBT / League 层

新增：

```text
app/services/model_population_service.py
app/services/model_checkpoint_service.py
```

职责：

- 保存 top model checkpoint
- 维护 Hall-of-Fame
- 对 bottom model 执行 inheritance
- 对继承模型执行 mutation
- 记录 lineage

第一版 inheritance：

```text
Full clone + controlled mutation
```

第二版再做：

```text
Partial inheritance + behavior distillation
```

## 5.5 Frontend 层

改造：

```text
app/panels/agents/panel.py
app/ui/adapters/agents_adapter.py
```

目标：

- Agent 面板支持 All / Retail / Model 过滤
- 表格展示模型字段
- 选中 Model 时显示训练详情
- 支持 Start all models / Stop all models

后续可新增：

```text
app/panels/arena/panel.py
app/ui/adapters/arena_adapter.py
```

但第一阶段不强制新增 Arena 面板，可以先复用 Agent 面板和命令服务。

---

## 6. 数据持久化规划

## 6.1 第一阶段最小持久化

第一阶段优先复用：

- `agent_bindings`
- `simulation_runs`
- `orders`
- `trades`
- `ledgers`
- `bars_1m / bars_1d`

新增或扩展：

```text
training_episodes
model_episode_results
model_checkpoints
model_lineage
```

## 6.2 建议表结构概念

### training_episodes

```text
episode_id
arena_id
run_id
generation
status
started_at
ended_at
sim_day_start
sim_day_end
config_json
summary_json
```

### model_episode_results

```text
episode_id
agent_id
model_id
generation
score
rank
equity_start
equity_end
equity_return
max_drawdown
turnover
fee_total
trade_count
reward_total
metrics_json
```

### model_checkpoints

```text
checkpoint_id
model_id
agent_id
generation
episode_id
path
score
created_at
meta_json
```

### model_lineage

```text
child_model_id
parent_model_id
generation
inheritance_mode
mutation_json
episode_id
created_at
```

---

## 7. 分阶段实施计划

## Phase 1：Agent 面板模型视图

目标：

- 让前端能清楚区分 Retail 和 Model。
- 不要求真实模型训练，只要求显示结构准备好。

工作内容：

1. `AgentsPanel` 增加 agent type filter state。
2. `AgentsPanelAdapter` 顶部增加过滤控件。
3. 表格列调整为兼容 Retail / Model。
4. headless/unit 测试覆盖 All / Retail / Model 过滤。

验收：

- Retail 和 Model 混合数据下，过滤准确。
- 多选 start / stop 不受过滤影响。
- 没有 Model 时 UI 不报错。

## Phase 2：Model Agent MVP

目标：

- 平台能创建并启动一个 Model Agent。
- Model Agent 能通过 contract 执行 hold 或 target_weight。

工作内容：

1. 新增 `RuntimeModelAgent`。
2. 新增 `ModelRegistryService`。
3. `AgentService` 支持 `Model` agent type。
4. 新增 `RandomWeightModel` / `HoldModel`。
5. `ActionParser` 支持 `target_weight`。
6. 新增 `RewardBuilder`。

验收：

- 创建 2 个 Model Agent。
- 启动 clock 后，Model Agent 按 interval 产生 action。
- action 被执行或被明确拒绝。
- reward 可计算并进入 agent view。

## Phase 3：Multi-Model Episode

目标：

- 两个或更多模型可以在同一 run / episode 中对抗。

工作内容：

1. 引入 `episode_id`。
2. Model Agent 记录 step_index。
3. episode 内收集每个模型的 reward / equity / trades。
4. 生成 `model_episode_results`。
5. Leaderboard 或 Agent view 能展示 episode rank。

验收：

- 2 个模型 + 100 retail 可以跑完一个短 episode。
- episode report 包含 score、rank、equity_return、drawdown、turnover。
- 重启应用后能查询最近 episode 结果。

## Phase 4：Arena Service

目标：

- 把多模型 episode 从手动流程收束成 Arena。

工作内容：

1. 新增 `TrainingArenaService`。
2. 支持 arena create / start / stop / evaluate。
3. 支持配置 retail_count、symbols、clock、episode length。
4. 支持 arena 状态持久化。

验收：

- 可以通过服务创建 arena。
- arena 能启动模型和 retail 背景。
- episode 结束自动进入 evaluating。
- 结果写入 PostgreSQL。

## Phase 5：PBT 传授机制

目标：

- 每轮结束后，胜者能够影响失败者，并进入下一轮。

工作内容：

1. 新增 checkpoint 保存接口。
2. 新增 population ranking。
3. top model 写入 Hall-of-Fame。
4. bottom model 从 top/Hall-of-Fame clone。
5. mutation config 生效。
6. 写入 lineage。

验收：

- episode 结束后 generation +1。
- 失败模型记录 parent_model_id。
- 继承后模型仍可启动下一轮。
- Hall-of-Fame 至少保留 N 个历史强者。

## Phase 6：真实 PPO/LSTM 接入

目标：

- 用真实 Recurrent PPO baseline 替换 dummy model。

工作内容：

1. 定义 policy adapter。
2. transition buffer 持久化或文件化。
3. 支持 collect_only 模式。
4. 支持 online_train 模式。
5. 显示 loss / entropy / value_loss / policy_update_count。

验收：

- PPO/LSTM 模型能完成 act。
- collect_only 能导出训练数据。
- online_train 能更新参数并保存 checkpoint。

## Phase 7：Arena 前端与训练控制台

目标：

- 提供专门训练控制台，而不把所有复杂状态塞进 Agent 面板。

工作内容：

1. 新增 Arena 面板。
2. 展示 arena 列表、当前 episode、模型排名。
3. 展示 generation lineage。
4. 提供 start episode / evolve population 操作。
5. 展示 checkpoint 和 Hall-of-Fame。

验收：

- 用户可以从桌面端创建并启动一次 arena。
- 能看到模型排行和传承关系。
- 能打开历史 episode report。

---

## 8. 推荐最先执行的工作包

第一轮建议只做一个小闭环：

```text
Work Package 1: Agent 面板支持 Retail / Model 过滤
Work Package 2: 新增 Model Agent 元数据和 dummy Model
Work Package 3: RuntimeModelAgent 跑通 hold / target_weight
Work Package 4: RewardBuilder + episode mini report
```

不要第一轮就做 PPO 训练，也不要第一轮就做完整 Arena UI。

原因：

- contract 闭环比算法强度更重要
- 前端必须先能观察 Model Agent
- dummy model 能更快暴露 runtime 接口问题
- episode report 是后续 PBT 的基础

---

## 9. 测试策略

每个阶段必须补测试。

建议测试目录：

```text
tests/frontend/unit/test_agents_model_filter.py
tests/runtime/test_runtime_model_agent.py
tests/runtime/test_model_action_target_weight.py
tests/runtime/test_reward_builder.py
tests/runtime/test_training_episode_report.py
tests/runtime/test_pbt_lineage.py
```

关键测试路径：

- Retail / Model 混合列表过滤
- Model Agent lifecycle
- invalid action reject
- target_weight 翻译为订单意图
- reward component 计算
- episode ranking
- checkpoint lineage
- PBT inheritance 后模型可继续运行

---

## 10. 风险与约束

## 10.1 非平稳性

模型互相学习会导致环境非平稳。必须使用 Hall-of-Fame 和种群多样性控制。

## 10.2 过拟合 retail 噪声

如果 retail 种子和市场配置固定，模型会学习噪声模式。需要：

- 多 seed
- 多 symbol
- 不同 retail mix
- 不同 episode start state

## 10.3 简单复制会导致同质化

胜者传授不能简单覆盖。必须 mutation 或 partial inheritance。

## 10.4 前端卡顿风险

模型推理和训练不能运行在 UI 线程。前端只展示状态，训练逻辑必须在 service / worker 层。

## 10.5 Reward 设计风险

只奖励收益会诱导赌博。必须引入 drawdown、turnover、fee、concentration 等惩罚项。

---

## 11. 文档维护规则

相关文档：

- `README.md`：项目总览
- `MODEL_TRAINING_DESIGN.md`：训练范式和算法设计
- `MULTI_AGENT_TRAINING_ROADMAP.md`：下一阶段工程路线
- `docs/contracts/runtime/model-observation-contract.md`
- `docs/contracts/runtime/model-action-contract.md`

后续新增时建议补：

- `docs/contracts/runtime/model-reward-contract.md`
- `docs/architecture/runtime/training-arena-design.md`
- `docs/current-work-status/agents.md`
- `docs/current-work-status/model-training.md`

本文档应在每个 phase 完成后更新状态，避免路线和实现再次分离。
