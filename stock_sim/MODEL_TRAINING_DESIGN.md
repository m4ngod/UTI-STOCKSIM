# UTI-STOCKSIM 模型对抗训练设计文档

_Last updated: 2026-04-26_

## 1. 设计目的

UTI-STOCKSIM 的长期目标不是单纯运行一个散户市场，而是构建一个可以让多个机器学习模型在同一仿真市场中进行观察、交易、学习和对抗的训练平台。

桌面应用当前已经基本具备仿真交易平台的基础条件：

- 多标的撮合
- 账户、冻结、结算、T+1、IPO、持仓和订单语义
- 100+ retail 背景交易者
- 内部时钟和 K 线
- PostgreSQL runtime 持久化
- Market / Agent / Account / Orders / Leaderboard / Clock 等观察面板

下一阶段的核心目标是：

> 将模型作为一等 Agent 挂载到平台中，让 2 个或更多模型在带有 retail 噪声和真实交易约束的市场里进行自我迭代、对抗学习和周期性演化。

---

## 2. 专业判断：应该采用什么训练范式

### 2.1 推荐主线

建议采用：

```text
League Self-Play
  + Population Based Training
  + Recurrent Actor-Critic
```

也就是：

```text
多个模型群体
  -> 在同一仿真市场中对抗
  -> 按 episode 评估胜负和稳健性
  -> 胜者进入 Hall of Fame
  -> 失败者部分继承胜者参数
  -> 对继承参数做扰动和再探索
  -> 下一轮继续对抗
```

这个方向比“两个模型互相打，赢家完全覆盖输家”更可靠。原因是交易市场高度非平稳、噪声大、局部最优很多，必须保留种群多样性和历史对手，否则模型会快速过拟合当前一批对手或当前一轮 retail 噪声。

### 2.2 第一代模型建议

第一代模型建议使用：

```text
Recurrent Actor-Critic
  temporal encoder: GRU 或 LSTM
  policy head: 输出 target_weight / order action
  value head: 估计未来收益
  optional risk head: 估计 drawdown / exposure / inventory risk
  training algorithm: PPO 起步
```

PPO+LSTM 虽然是早期计划，但它并不过时。对本项目来说，它仍然是稳妥的第一代基线，因为：

- 市场是部分可观测环境
- retail 噪声具有时序依赖
- 盘口、成交、持仓和资金状态不是单步就能完整解释
- 多模型对抗会导致环境非平稳
- recurrent policy 能保留短期市场记忆和自身行为上下文

后续可以升级为：

```text
Market encoder: cross-symbol attention / Transformer
Temporal encoder: GRU/LSTM -> Transformer/TCN
Training: PPO/IPPO -> MAPPO 或 PSRO-style league
Population control: PBT + Hall-of-Fame
```

---

## 3. 不建议将 GAN 或不明确的 GCA 作为主线

### 3.1 GAN 的位置

GAN 适合做：

- 生成行情片段
- 生成极端市场场景
- 生成对抗性 order flow
- 做 market scenario augmentation

但 UTI-STOCKSIM 的核心问题是：

```text
观察市场状态 -> 做交易决策 -> 承担账户后果 -> 长期优化策略
```

这是序列决策和多智能体强化学习问题，而不是“生成一个像真实市场的数据样本”的问题。因此 GAN 可以作为辅助工具，但不应作为主训练框架。

### 3.2 GCA 的位置

“GCA”不是像 PPO、SAC、MAPPO、PSRO、PBT 那样稳定、通用且定义明确的主流路线。不同论文或语境中的 GCA 可能指代不同算法。

如果 GCA 指的是某种竞争/协同进化思想，那么它更适合作为外层种群演化机制，而不是替代 RL 主体：

```text
内层：PPO / MAPPO 训练单个模型
外层：PBT / League / Hall-of-Fame 管理模型群体
```

---

## 4. 核心训练架构

## 4.1 Arena

新增训练概念：`Arena`。

Arena 是一次模型对抗训练的运行容器，负责把模型、retail 背景、交易标的、clock、episode、run_id 和评估规则绑定到一起。

示例配置：

```python
{
    "arena_id": "arena_001",
    "models": ["model_alpha", "model_beta"],
    "background_agents": {
        "retail_count": 100,
        "enabled": True,
    },
    "symbols": ["001", "002"],
    "clock": {
        "day_seconds": 4.0,
        "speed": 240.0,
    },
    "episode": {
        "max_sim_days": 30,
        "reset_market": False,
        "reset_accounts": True,
    },
    "reward_profile": "relative_equity_risk_adjusted_v1",
}
```

Arena 职责：

- 创建或绑定多个 Model Agent
- 可选启动 retail 背景交易者
- 管理 episode_id / run_id
- 推动 clock 和模型 step
- 收集 reward、transition、PnL、drawdown、turnover、exposure
- 计算排行榜
- 驱动 PBT 复制、扰动、淘汰和 Hall-of-Fame 更新

## 4.2 Model Agent

Model Agent 是平台中的一等 Agent。它不直接访问撮合引擎，也不直接操作数据库，而是通过正式 contract 与 runtime 交互。

标准循环：

```text
clock running?
  -> build observation
  -> policy.act(observation)
  -> validate action
  -> translate action to runtime command
  -> execute through runtime truth
  -> build reward
  -> record transition
  -> optional learn()
  -> publish status / metrics
```

建议新增：

```text
app/services/runtime_model_agent.py
app/services/model_registry_service.py
app/services/training_arena_service.py
rl/reward_builder.py
rl/contracts.py
```

---

## 5. 模型接口 Contract

## 5.1 Observation

继续沿用 `obs.v1` 方向，但必须从 single-symbol 扩展到 multi-symbol universe。

顶层结构保持：

```python
{
    "contract_version": "obs.v1",
    "market": {...},
    "account": {...},
    "context": {...},
    "features": {...},
}
```

推荐扩展：

```python
"market": {
    "symbols": ["001", "002"],
    "snapshots": {
        "001": {...},
        "002": {...},
    },
    "bars": {
        "001": {"1d": [...], "1m": [...]},
        "002": {"1d": [...], "1m": [...]},
    },
    "order_books": {
        "001": {"bids": [...], "asks": [...]},
        "002": {"bids": [...], "asks": [...]},
    },
}
```

`account` 必须包含：

- cash
- frozen_cash
- frozen_fee
- equity
- gross_exposure
- net_exposure
- positions
- available_sell_qty
- borrowed_qty

`context` 必须包含：

- run_id
- episode_id
- step_index
- sim_day
- clock_running
- symbol_universe
- agent_id
- opponent_ids

`features` 可以包含：

- normalized bars
- returns window
- volatility
- spread
- imbalance
- own previous action
- opponent summary features

## 5.2 Action

沿用 `act.v1`，支持四类动作：

```text
hold
order
target_position
target_weight
```

第一阶段重点支持 `target_weight`，因为它更适合多标的组合控制和 RL 训练。

示例：

```python
{
    "contract_version": "act.v1",
    "action_type": "target_weight",
    "target": {
        "account_id": "model_alpha",
        "symbols": ["001", "002"],
    },
    "payload": {
        "weights": {
            "001": 0.45,
            "002": -0.10,
        },
        "cash_buffer_ratio": 0.05,
        "rebalance_mode": "market",
    },
    "constraints": {
        "allow_short": True,
        "max_gross_leverage": 1.5,
        "clip_to_limits": True,
    },
    "meta": {
        "model_id": "ppo_lstm_v1",
        "episode_id": "episode_001",
    },
}
```

Action 必须经过：

1. parse
2. schema validate
3. semantic validate
4. translate to orders / target portfolio intents
5. runtime execution

模型输出不是订单本身，而是平台可校验的意图。

## 5.3 Reward

需要新增 `rew.v1`。

第一版建议：

```python
{
    "reward_version": "rew.v1",
    "step_reward": 0.012,
    "components": {
        "delta_equity": 0.018,
        "relative_alpha": 0.006,
        "realized_pnl": 0.004,
        "unrealized_pnl": 0.014,
        "fee_penalty": -0.002,
        "drawdown_penalty": -0.003,
        "turnover_penalty": -0.001,
        "inventory_penalty": 0.0,
    },
    "meta": {
        "reward_profile": "relative_equity_risk_adjusted_v1",
    },
}
```

不要只用最终收益作为胜负标准。否则模型容易学出极端赌博策略。

推荐综合评分：

```text
score =
    equity_return
  + opponent_relative_alpha
  - drawdown_penalty
  - turnover_penalty
  - fee_penalty
  - concentration_penalty
  + survival_bonus
```

---

## 6. 胜者向失败者传授参数

用户希望每个周期中胜出的模型可以把参数传授给失败模型，然后进入下一轮对抗。这个方向是合理的，但不能使用简单完整覆盖。

错误做法：

```text
loser.parameters = winner.parameters
```

风险：

- 种群多样性快速消失
- 所有模型变得越来越像
- 过拟合当前 retail 噪声
- 容易出现循环策略和灾难性遗忘

推荐机制：

```text
Top 20%:
  保留原样，进入 Hall of Fame

Middle 50%:
  继续训练，不复制

Bottom 30%:
  从胜者或 Hall-of-Fame 成员继承参数
  + mutation
  + optional distillation
```

可用的传授方式：

1. **Full clone + mutation**
   - 复制全部参数
   - 扰动学习率、entropy coefficient、reward weights、action noise

2. **Partial inheritance**
   - 只继承 encoder
   - policy head / value head 重新初始化或小幅扰动
   - 适合保留市场表示能力，同时鼓励策略差异

3. **Distillation**
   - 失败模型不直接拷贝胜者
   - 通过行为克隆学习胜者在历史 observation 上的 action 分布
   - 更平滑，但实现复杂度更高

4. **Hybrid**
   - encoder clone
   - policy distill
   - value head 保留或重训

第一阶段建议：

```text
Full clone + controlled mutation
```

第二阶段再引入：

```text
partial inheritance + behavior distillation
```

---

## 7. League 与 Hall-of-Fame

必须保留历史强者作为对手，否则模型只会适应当前一代对手。

建议：

- 每轮 top model 进入 Hall-of-Fame
- 新一轮对抗时，部分 episode 对战当前种群
- 部分 episode 对战 Hall-of-Fame 旧模型
- 评分时同时考虑当前对手和历史对手

对手采样：

```text
70% current population
20% Hall-of-Fame
10% exploit known weakness opponent
```

这样可以降低策略遗忘和循环克制问题。

---

## 8. 前端显示优化

Agent 面板需要从普通 agent 列表升级为模型训练控制台。

## 8.1 顶部过滤

新增过滤器：

```text
All | Retail | Model | Running | Training | Stale
```

第一阶段至少实现：

```text
All | Retail | Model
```

## 8.2 表格列

当前列偏 retail / generic agent。

建议改为：

```text
agent_id
type
family/model
status
account
universe
mode
episode
last_reward
equity
pnl
last_action
heartbeat
```

Retail 行：

- `family/model` 显示 strategy / persona family
- `mode` 显示 retail

Model 行：

- `family/model` 显示 model_id
- `mode` 显示 inference / online_train / collect_only
- `last_reward` 显示最近 step reward
- `last_action` 显示 hold / target_weight / order

## 8.3 详情区

选中 Retail：

- strategy
- persona 参数摘要
- 当前持仓
- 最近行为
- heartbeat

选中 Model：

- model_id
- policy path / endpoint
- device
- training mode
- reward profile
- universe
- last observation summary
- last action
- last reward
- episode metrics
- loss / entropy / value_loss
- parent_model / generation

## 8.4 批量控制

新增或明确：

```text
Start selected
Stop selected
Start all retail
Start all models
Start arena
Stop arena
```

当前多选 start/stop 已经是必要基础，后续要把 Model 组控制补齐。

---

## 9. 数据持久化建议

模型训练需要新增持久化对象。

建议表或 ORM 模型：

```text
model_agents
model_checkpoints
training_arenas
training_episodes
model_episode_results
model_transitions
model_lineage
```

最小第一阶段可以只落：

```text
agent_bindings.meta
training_episodes
model_episode_results
model_checkpoints
```

关键字段：

- run_id
- episode_id
- arena_id
- agent_id
- model_id
- generation
- parent_model_id
- checkpoint_path
- score
- equity_return
- max_drawdown
- turnover
- win_rank
- reward_profile

---

## 10. 第一阶段落地路线

## Phase 1：Agent 面板支持模型视图

目标：

- Agent 面板支持 `All / Retail / Model` 过滤
- 表格支持模型相关字段的占位显示
- 逻辑层可返回 type=Model 的 AgentMeta

交付：

- 前端过滤器
- 测试：Retail / Model 混合列表过滤

## Phase 2：Model Agent MVP

目标：

- 新增 `RuntimeModelAgent`
- 支持一个 dummy/random model
- 走完整 observation -> action -> execution -> reward 链路

交付：

- `runtime_model_agent.py`
- `reward_builder.py`
- model action parser 支持 `target_weight`
- 测试：两个模型可同时运行并产生订单或 hold

## Phase 3：Arena MVP

目标：

- 可创建 2 个模型 + 100 retail 背景对抗
- 记录 episode report
- 计算排名

交付：

- `training_arena_service.py`
- episode report
- Agent 面板显示 arena / episode / reward

## Phase 4：PBT / 传授机制

目标：

- 周期结束后进行排名
- top model 保存 checkpoint
- bottom model 继承 top / Hall-of-Fame 参数并 mutation

交付：

- model checkpoint manager
- lineage 记录
- mutation config
- 测试：失败模型继承后 generation / parent_model_id 正确变化

## Phase 5：真实模型接入

目标：

- 接入 Recurrent PPO baseline
- 支持 collect-only / online_train 两种模式
- 输出训练指标

交付：

- model registry
- PPO/LSTM adapter
- transition buffer
- training metrics panel fields

---

## 11. 当前建议的第一轮实现范围

不要一口气做完整 RL 平台。

第一轮最合理的目标是：

```text
1. Agent 面板支持 All / Retail / Model 过滤
2. 新增 Model agent 类型
3. 实现 RuntimeModelAgent MVP
4. 实现 RandomWeightModel 作为可运行模型占位
5. 生成 model episode report
6. 文档和测试锁定 contract
```

完成后，UTI-STOCKSIM 就正式具备：

> 可挂载模型、可运行对抗、可观察训练状态、可继续演化的训练平台雏形。

---

## 12. 参考方向

这些方向是本设计的主要思想来源：

- Population Based Training：用于胜者传授、超参数扰动和种群演化
- League Self-Play：用于保留历史强者、避免策略遗忘
- AlphaStar / OpenAI Five：复杂多智能体对抗中的 league / self-play 工程范式
- PPO / Recurrent Actor-Critic：第一代稳定基线
- MAPPO / PSRO：后续多智能体扩展方向
- GAN：仅作为未来市场场景生成或对抗噪声生成工具，不作为主训练框架

