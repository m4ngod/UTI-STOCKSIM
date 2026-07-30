# UTI-STOCKSIM 多智能体模型训练设计

_Last updated: 2026-04-29_

## Implementation Status - 2026-04-29

The current platform has moved past single-episode attachment for `ppo_lstm_v1`.
The implemented path now supports repeatable Arena experiment runs, multi-PPO
episodes, execution-health reporting, checkpoint creation, PBT lineage, and
sequential multi-generation series where a losing model can enter the next
generation as a `*.genN.*` child model.

The next design focus remains unchanged: do not add a new algorithm family yet.
Use longer multi-generation PPO/LSTM series to tune reward weights, liquidity
depth, parent eligibility gates, and evaluation stability before introducing
Transformer encoders, payoff matrices, or adversarial scenario generation.

## 1. 文档目的

本文档用于将 UTI-STOCKSIM 从“具备真实交易语义的仿真市场”推进到“可进行模型对抗、自我迭代、代际传承和风险约束训练的研究平台”。

本文档的目标不是给出某一个单点算法答案，而是给出一套适合当前项目现实约束的训练设计：

- 在保留当前交易运行时真实性的前提下，把模型代理接入现有 runtime。
- 让多个模型可以在带有 retail 噪声的市场中进行长期对抗和迭代。
- 支持“胜者将经验/参数传授给失败者，再进入下一轮”的代际演化。
- 保留种群多样性，避免所有模型快速同质化。
- 将风险约束、回撤约束和现实交易规则纳入训练系统，而不是只优化收益。

本文档以当前 README 所反映的项目现状为基础：系统已经拥有多标的撮合、账户资金与冻结、成交结算、T+1、卖空、IPO、retail persona/calibration、桌面观察面板、PostgreSQL 持久化和 run 级数据链路，因此训练设计必须建立在“现有 runtime truth”之上，而不是绕开现有平台另起炉灶。

---

## 2. 核心结论

### 2.1 推荐主线

对于本项目，推荐的主训练范式不是 GAN，也不是不明确的 GCA，而是：

```text
Anchored Retail Ecology
 + League / PSRO-style Self-Play
 + Recurrent Actor-Critic
 + Population Based Training (PBT)
 + Hall-of-Fame + Payoff Matrix + Alpha-Rank
 + CVaR / Constrained Risk Layer
```

更直白地说：

```text
真实仿真市场
 + 锚定的散户群体噪声
 + 多模型联盟对抗
 + 周期性评估/淘汰/继承/扰动
 + 保留历史强者
 + 风险约束与尾部风险目标
```

### 2.2 第一代模型建议

第一代模型不需要追求“最新”，而应追求：

- 容易接入现有系统
- 训练稳定
- 便于观察和排障
- 能承受部分可观测、非平稳、多对手环境

因此，第一代模型建议：

```text
PPO + GRU/LSTM Recurrent Actor-Critic
```

它不是最终形态，但非常适合作为 v1 baseline。

### 2.3 第二代升级方向

在 v1 跑通后，再逐步升级到：

```text
GTrXL / Transformer Temporal Encoder
+ 更强的多智能体 league 调度
+ partial inheritance / distillation
+ Alpha-Rank 评估
+ adversarial scenario generator
```

### 2.4 不建议作为主线的方向

#### GAN

GAN 可以作为辅助工具，用于：

- 生成极端市场场景
- 生成对抗性订单流
- 扩充 market scenario
- 做环境分布层面的对抗训练

但它不适合作为核心交易智能体训练主干，因为本项目的本质是：

```text
观察 -> 决策 -> 下单 -> 承担账户后果 -> 长期优化
```

这是序列决策和多智能体对抗问题，不是静态生成问题。

#### GCA

“GCA”并不是一个像 PPO、MAPPO、PSRO、PBT 那样定义清晰且工程路径成熟的主训练基座。即便某个语境中的 GCA 表示群体交叉/群组竞争思想，它更适合被解释为：

```text
一种外层种群调度或进化机制
```

而不是内层 RL 主体。

因此本设计的态度是：

```text
GCA-like idea 可以吸收
GCA 作为唯一主算法 不建议采用
```

---

## 3. 设计原则

### 3.1 训练制度优先于“换一个新算法名词”

本项目最大的优势不是“还缺一个花哨算法”，而是已经有较完整的交易仿真语义：

- 多标的撮合与订单簿
- 账户现金、冻结、持仓、成交、结算
- T+1、卖空、IPO、风险检查
- retail 行为家族、persona、状态变量、校准报告
- GUI 面板与 run 级持久化

因此训练系统必须优先利用这些资产，把算法嵌入 runtime，而不是把训练逻辑做成独立的黑盒。

### 3.2 锚定生态，不让市场背景自由漂移

retail 群体是现实感锚点。训练过程中，不应让所有背景代理都与模型一起无限制地共同演化，否则整个市场可能很快偏离“可信散户群体”。

因此必须区分：

- **锚定生态**：retail 家族配比、persona 分布、校准指标
- **可学习生态**：对抗模型群体
- **受约束的环境对抗层**：只允许在 realism constraint 下生成更难场景

README 已明确指出，retail 行为的调参应依赖 calibration report，而不是只看单次 UI 表现。该原则必须直接纳入训练平台设计。

### 3.3 保留种群多样性

如果简单采用“赢家完全覆盖输家”的做法，容易出现：

- 种群快速同质化
- 对当前一代对手过拟合
- 历史弱点被遗忘
- 出现循环克制却无法发现

因此胜者传参必须设计为：

```text
继承 + 扰动 + 历史对手保留 + 非传递评估
```

### 3.4 硬规则留在环境，软目标进入奖励

交易语义层面的规则必须继续放在 runtime / services / risk engine 中：

- T+1
- 持仓冻结/释放
- 卖空限制
- 费用
- 账户校验
- 风险边界

而 RL 奖励函数只负责优化：

- 相对收益
- 风险调整收益
- 回撤惩罚
- 换手惩罚
- 库存/暴露惩罚
- 存活奖励

这样可以避免模型用“违反交易语义”的方式获取虚假优势。README 已明确 `order_service.py` 和 `account_service.py` 是交易语义核心，训练设计必须尊重这一边界。

### 3.5 先稳定训练闭环，再追求样本效率极限

第一阶段的首要目标不是追求最强样本复用，而是先建立稳定闭环：

```text
observation -> action -> execution -> reward -> transition -> update -> evaluation -> inheritance
```

这意味着 v1 更适合用 on-policy PPO 跑通，而不是一开始就引入复杂的 recurrent replay、世界模型或高度耦合的 off-policy 集群。

---

## 4. 目标系统全景

建议将训练平台拆成三层生态：

```text
Layer A: Anchored Retail Ecology
 固定/缓慢调整的散户家族与 persona 分布
 由 calibration 指标守护 realism

Layer B: Learnable Model League
 多个模型代理在同一市场中对抗
 通过 PBT/League/Hall-of-Fame 持续演化

Layer C: Adversarial Scenario Generator
 在 realism constraint 下生成更难的 market regime / shock / order flow
```

这三层分别解决三个不同问题：

- A 解决“市场背景是否可信”
- B 解决“模型是否能通过对抗学习迭代变强”
- C 解决“模型是否只会在单一舒适区表现好”

---

## 5. 系统架构设计

### 5.1 新增核心概念

#### Arena

Arena 是一次训练对抗的运行容器，用于把以下对象绑定在一起：

- 模型集合
- retail 背景群体
- 标的 universe
- 时钟与交易日设置
- reward 配置
- episode 边界
- evaluation 策略
- checkpoint 与 lineage 记录

示意：

```python
{
  "arena_id": "arena_train_001",
  "models": ["model_main_01", "model_exploiter_01"],
  "background_agents": {
    "retail_enabled": True,
    "retail_count": 100,
    "scenario_profile": "retail_anchor_v1",
  },
  "symbols": ["001", "002", "003"],
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
  "matchmaking_profile": "league_v1",
}
```

Arena 职责：

- 绑定模型与账户
- 启动/停止 retail 背景群体
- 驱动 episode 生命周期
- 收集所有模型的 reward 与风险指标
- 形成排行榜、payoff、lineage 事件
- 触发 PBT / 继承 / checkpoint / Hall-of-Fame 更新

#### Model Agent

Model Agent 是平台中的一等 Agent，与 retail agent 平级，但职责不同。

标准循环：

```text
build observation
 -> policy.act(observation)
 -> validate action
 -> translate action to runtime command
 -> execute via runtime truth
 -> build reward
 -> append transition
 -> optional learn/update
 -> publish metrics
```

Model Agent 不能绕过 runtime 直接修改账户或订单状态，必须走既有 command/query 边界。

#### League Manager

负责：

- 管理当前种群
- 分配角色
- 采样对手
- 调度 episode matchup
- 把每轮结果送入 PBT 与 Hall-of-Fame

#### Hall-of-Fame

用于保留历史强者，避免当前种群只适应最近一代对手。

#### Payoff Matrix / Alpha-Rank Service

用于替代“只看单轮收益”的粗糙评估方式，识别：

- 非传递关系
- 循环克制
- 伪强者
- 对某类对手特别脆弱的策略

#### PBT Engine

用于执行：

- 排名
- 淘汰
- 继承
- mutation
- 超参数扰动
- lineage 记录

#### Scenario Generator

用于生成：

- retail 家族配比变化
- 事件冲击
- 流动性状态变化
- 活跃度路径
- 更难但仍可信的市场 regime

### 5.2 与当前项目结构的接线

建议新增或扩展：

```text
app/services/runtime_model_agent.py
app/services/model_registry_service.py
app/services/training_arena_service.py
app/services/league_manager_service.py
app/services/model_checkpoint_service.py
rl/contracts.py
rl/reward_builder.py
rl/payoff_matrix.py
rl/pbt_engine.py
rl/alpha_rank_service.py
rl/scenario_generator.py
rl/model_adapters/
```

并遵守当前分层原则：

- UI 只负责展示/控制
- controller / panel / adapter 不承载训练核心逻辑
- runtime_gateway 仍是桌面层边界
- 交易语义继续由 services 与 core 保持权威

这与 README 中现有 controller / panel / adapter / runtime_gateway 分层原则保持一致。

---

## 6. 模型架构建议

### 6.1 v1：PPO + GRU/LSTM Recurrent Actor-Critic

建议作为第一代正式 baseline：

```text
Market encoder: MLP / shallow attention
Temporal encoder: GRU 或 LSTM
Policy head: target_weight / target_position / order intent
Value head: state value
Optional risk head: drawdown / exposure / inventory risk
Algorithm: PPO
```

理由：

- 环境是部分可观测的
- market state 具有明显时序依赖
- retail 噪声并非独立同分布
- 多模型对抗会导致环境非平稳
- PPO 易于稳定训练和调试
- LSTM/GRU 较容易接进现有 Python 训练框架与 runtime

### 6.2 v2：GTrXL / Transformer 系列升级

在 v1 跑稳之后，升级方向：

```text
Cross-symbol encoder: attention / transformer
Temporal encoder: GTrXL / Transformer / TCN
Policy/value/risk multi-head
Algorithm: PPO 或 MAPPO-style 变体
```

建议不要一开始就把全部复杂性叠满，否则问题很难定位：是 observation contract 有问题、reward 有问题、执行延迟有问题，还是 transformer 本身训练不稳定。

### 6.3 关于 MAPPO 的使用方式

如果后续引入 MAPPO 类设计，需要注意：

- 不应默认所有 agent 共用完整策略头
- 最多共享 market encoder / lower layers
- 不同行为角色、不同模型 archetype 应保留独立 head 或 adapter

否则容易让种群失去结构性多样性。

### 6.4 关于 off-policy / R2D2 类路线

off-policy recurrent 方向可以在未来引入，但不应作为 v1 主线。原因：

- 自博弈环境中对手分布持续变化
- replay 中旧数据很快陈旧
- recurrent hidden state 维护更复杂
- 实现和调试成本高于第一阶段需求

### 6.5 关于 world model / Dreamer 类路线

未来可将 learned world model 作为：

- 训练加速器
- policy pretraining 辅助器
- 对抗场景的廉价 surrogate

但不建议在当前阶段把其设为主训练框架，因为项目已经拥有较强的显式 simulator，过早引入 learned world model 容易先把 model bias 带入训练系统。

---

## 7. 训练制度设计

### 7.1 Outer Loop：League / PSRO-style 自博弈

外循环目标：持续产生更强、更稳健、且能应对多类对手的策略群体。

推荐角色：

```text
1 x Main Agent
2 x Main Exploiters
2 x League Exploiters
1 x Risk-Averse Exploiter
```

角色职责：

- **Main Agent**：追求综合稳健表现，作为主要候选冠军。
- **Main Exploiter**：专门寻找当前 Main Agent 的局部弱点。
- **League Exploiter**：专门寻找整个联盟共享的系统性漏洞。
- **Risk-Averse Exploiter**：专门在高回撤、流动性紧张、库存失衡情境下逼迫对手暴露缺陷。

### 7.2 Opponent Sampling

每个 episode 的对手来源建议：

```text
70% current population
20% Hall-of-Fame
10% targeted exploiters / weakness-specific opponents
```

这样可以减少：

- 策略遗忘
- 当前代过拟合
- “最近打得好”但历史上很脆弱的假强者

### 7.3 Inner Loop：PPO 更新

每个模型在自身采样的数据上做 PPO 更新。可以先支持两种模式：

```text
collect_only
online_train
```

其中：

- `collect_only` 用于生成轨迹、做评估、做蒸馏数据集
- `online_train` 用于边收集边更新

### 7.4 胜者传授给失败者：PBT + Kickstarting + Distillation

“胜者把参数传授给失败者”是合理方向，但不应理解为：

```text
loser = exact copy of winner
```

推荐设计为三阶段：

#### 第一阶段：Full Clone + Controlled Mutation

适合快速落地：

```text
Bottom 30% <- clone from Top 20% or Hall-of-Fame
      + mutate lr / entropy / reward weights / exploration noise
```

#### 第二阶段：Partial Inheritance

更稳健：

```text
inherit market encoder
retain or lightly reset policy head
retain or re-train value head
```

#### 第三阶段：Distillation / Kickstarting

更成熟的教师-学生机制：

```text
teacher: winner / Hall-of-Fame expert
student: loser / new-born agent
loss: RL objective + KL distillation + optional behavior cloning
```

### 7.5 代际保留策略

建议默认：

```text
Top 20%  -> 保留 + checkpoint + 进入 Hall-of-Fame 候选
Middle 50%-> 继续训练，不复制
Bottom 30%-> 接受继承、扰动、重生
```

这一比例不是固定真理，但作为 v1 是合理起点。

---

## 8. 风险与奖励设计

### 8.1 风险层分工

#### 环境硬约束

保留在 runtime/services/risk_engine：

- 最大杠杆
- 账户可用资金
- 可卖数量
- 卖空限制
- T+1
- 费用
- 订单合法性
- 撮合和结算规则

#### 奖励软约束

保留在 RL 目标：

- 风险调整收益
- 回撤惩罚
- 换手惩罚
- 库存惩罚
- 集中度惩罚
- 极端暴露惩罚
- 生存奖励

### 8.2 Reward Contract

建议新增 `rew.v1`：

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
    "concentration_penalty": -0.001,
    "tail_risk_penalty": -0.002,
  },
  "meta": {
    "reward_profile": "relative_equity_risk_adjusted_v1"
  },
}
```

### 8.3 胜负与综合评分

不要只用最终收益作为评估标准，否则模型容易学出“单次赌对但长期脆弱”的策略。

建议综合评分：

```text
score =
  equity_return
 + relative_alpha
 - max_drawdown_penalty
 - turnover_penalty
 - fee_penalty
 - concentration_penalty
 - tail_risk_penalty
 + survival_bonus
```

### 8.4 CVaR / Constrained RL

第二阶段建议把以下目标接入：

- CVaR of episodic return
- max drawdown constraint
- gross exposure constraint
- inventory risk constraint

目标不是让模型“绝不亏损”，而是显式地优化尾部风险和极端情境稳健性。

---

## 9. Observation / Action / Reward Contract

### 9.1 Observation：obs.v1 扩展到多标的

建议保留统一合同：

```python
{
  "contract_version": "obs.v1",
  "market": {...},
  "account": {...},
  "context": {...},
  "features": {...},
}
```

并扩展到多标的：

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

`account` 至少包含：

- cash
- frozen_cash
- frozen_fee
- equity
- gross_exposure
- net_exposure
- positions
- available_sell_qty
- borrowed_qty

`context` 至少包含：

- run_id
- arena_id
- episode_id
- step_index
- sim_day
- clock_running
- symbol_universe
- agent_id
- opponent_ids
- generation

`features` 可包含：

- normalized bars
- returns window
- realized volatility
- spread
- imbalance
- own previous action
- opponent summary features
- market regime tag

### 9.2 Action：act.v1

动作语义建议支持四类：

```text
hold
order
target_position
target_weight
```

第一阶段重点支持 `target_weight`，因为它更适合组合控制与 RL 输出。

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

Action 执行链：

```text
parse -> schema validate -> semantic validate -> translate -> runtime execution
```

模型输出的是“可验证的交易意图”，而不是绕过平台直接写订单簿。

---

## 10. 锚定的 Retail Ecology 设计

### 10.1 Retail 继续作为 realism anchor

当前 README 已明确：retail 群体由行为家族、persona 参数、状态变量与 calibration report 驱动。训练系统不得破坏这一基本路线。

### 10.2 建议做法

将 retail 生态分成两部分：

#### Stable Anchor Pool

- family 比例较稳定
- persona 分布有固定基础范围
- 只允许小幅慢速调整
- 作为所有训练与评估的基准背景

#### Scenario-conditioned Variation Pool

- 在 realism constraint 下改变 retail 家族配比
- 可调整风险偏好、耐心、价格敏感度等群体分布
- 用于提高模型稳健性

### 10.3 Calibration Gate

所有 scenario 变体都必须通过一组现实性门槛，例如：

- buy/sell ratio 范围
- two-sided coverage 下限
- holding bars 范围
- 成交活跃度区间
- spread / turnover / participation 合理区间

若某 scenario 导致 retail 行为明显失真，则不得进入正式训练池。

---

## 11. 创新扩展：对抗式场景生成器

这是本项目最值得探索的创新方向之一。

### 11.1 基本思想

不把 GAN 当作交易策略主体，而是把“对抗生成”思想用在环境分布上：

```text
Scenario Generator
 -> 生成更难的 retail 配比 / shock / liquidity regime
Champion Model
 -> 在该场景中对抗并暴露弱点
Calibration Gate
 -> 约束生成结果仍然像可信市场
```

### 11.2 生成器输入

- 当前冠军模型弱点摘要
- 最近 payoff matrix
- 风险暴露统计
- retail calibration 基准
- 允许变动的 scenario 参数空间

### 11.3 生成器输出

例如：

- mean_revert / buy_the_dip / liquidity_noise 的比例变化
- 波动冲击计划
- 开盘/尾盘活跃度曲线
- 流动性稀薄窗口
- 做多热情降低或追涨增强的群体偏置

### 11.4 训练目标

目标不是“生成最怪的市场”，而是：

```text
在 realism constraint 下，最大化当前冠军的 regret / drawdown / exploitability
```

### 11.5 实现建议

第一阶段不用 GAN，先用：

- rule-based scenario mutation
- Bayesian optimization / evolutionary search
- curriculum over regime difficulty

第二阶段再尝试：

- adversarial generator
- GAIL / imitation warm start（仅当拿到真实人类轨迹时）

---

## 12. 评估体系

### 12.1 单回合指标

每个模型每个 episode 至少输出：

- equity_return
- realized_pnl
- unrealized_pnl
- max_drawdown
- turnover
- fee_paid
- exposure profile
- inventory concentration
- Sharpe-like proxy
- CVaR proxy
- survival flag
- rank

### 12.2 Cross-Play Matrix

不能只看“当前这一轮谁赚得最多”。必须构造策略对战矩阵：

```text
model_i vs model_j under scenario_k
```

并记录：

- average relative return
- win rate
- drawdown gap
- exploitability pattern

### 12.3 Hall-of-Fame 回放评估

新模型至少要在以下集合上评估：

- 当前人口
- 历史强者
- 风险对手
- 极端场景
- 锚定 retail 基准场景

### 12.4 Alpha-Rank / 非传递排名

最终不应只用简单 Elo 或单一收益排名。建议第二阶段引入 Alpha-Rank 或等价非传递评估方法，用于识别：

- A 胜 B、B 胜 C、C 胜 A 的循环关系
- 高收益但不稳健的偏科策略
- 看起来强但实际上只克某一类对手的伪冠军

### 12.5 发布门槛

建议将正式“冠军替换”设为多指标门槛，而不是单一排名：

```text
1. anchor retail benchmark 不退化
2. Hall-of-Fame cross-play 优于当前冠军
3. max drawdown / CVaR 不恶化到阈值之外
4. 至少在 N 个 scenario 上保持稳健
```

---

## 13. 参数传承与 lineage 设计

### 13.1 不推荐的做法

```text
loser.parameters = winner.parameters
```

问题：

- 过快同质化
- 忘记旧对手
- 失去探索能力
- 单一局部最优统治种群

### 13.2 推荐继承机制

#### v1

```text
Full clone + controlled mutation
```

#### v2

```text
encoder clone
+ head perturbation
+ hyperparameter mutation
```

#### v3

```text
encoder inheritance
+ policy distillation
+ teacher-student kickstarting
```

### 13.3 需要记录的 lineage 字段

- model_id
- parent_model_id
- generation
- source_checkpoint
- mutation_profile
- reward_profile
- arena_id
- episode_range
- promotion_reason
- retirement_reason

### 13.4 继承触发条件

可基于：

- rolling score percentile
- exploitability threshold
- stagnation threshold
- risk violation frequency

---

## 14. 数据持久化设计

结合当前 PostgreSQL runtime truth 与 run_id 设计，训练平台需要新增训练层持久化对象。README 已说明正式 runtime 使用 PostgreSQL，并按 run 记录关键业务事实，因此训练链路必须与现有 run/episode 语义对齐。

建议新增表或 ORM 模型：

```text
model_agents
model_checkpoints
training_arenas
training_episodes
model_episode_results
model_transitions
model_lineage
payoff_matrix_entries
hall_of_fame_entries
scenario_profiles
```

第一阶段最小可落地集合：

```text
training_episodes
model_episode_results
model_checkpoints
model_lineage
```

关键字段：

- run_id
- arena_id
- episode_id
- agent_id
- model_id
- model_role
- generation
- parent_model_id
- checkpoint_path
- score
- equity_return
- max_drawdown
- turnover
- tail_risk_proxy
- scenario_profile
- reward_profile
- opponent_set_hash

---

## 15. 前端与可观察性设计

当前桌面系统已经拥有 Market、Symbol detail、Agents、Account、Orders、Leaderboard、Clock 等面板。训练设计应在此基础上扩展，而不是额外做一套旁路 UI。

### 15.1 Agent 面板升级

新增过滤器：

```text
All | Retail | Model | Running | Training | Stale
```

第一阶段至少支持：

```text
All | Retail | Model
```

### 15.2 Model 行展示字段

建议 Agent 表格新增或补齐：

- agent_id
- type
- family/model
- mode
- arena_id
- episode_id
- generation
- parent_model_id
- equity
- pnl
- last_reward
- last_action
- exposure
- heartbeat

### 15.3 Model 详情区

建议展示：

- model_id
- policy path / backend
- device
- training mode
- reward profile
- universe
- last observation summary
- last action
- last reward
- episode metrics
- loss / entropy / value_loss
- parent_model_id
- generation
- role（main / exploiter / hof_eval）

### 15.4 Arena 控制

建议新增：

```text
Start arena
Stop arena
Reset episode
Promote checkpoint
Retire model
Replay matchup
```

### 15.5 Leaderboard 升级

Leaderboard 不再只看单期收益，建议支持视图切换：

- Return
- Risk-adjusted Score
- Drawdown
- Cross-play Rank
- Hall-of-Fame Rank
- Recent Form

---

## 16. 第一阶段实施路线

### Phase 0：合同与最小数据链路

目标：

- 明确 `obs.v1 / act.v1 / rew.v1`
- 定义 model meta、episode meta、checkpoint meta
- 与现有 run_id wiring 对齐

交付：

- `rl/contracts.py`
- `docs/` 中的 contract 说明
- 对应 schema / ORM 占位

### Phase 1：Model Agent MVP

目标：

- 引入 `RuntimeModelAgent`
- 支持一个 dummy/random/heuristic model
- 打通 observation -> action -> execution -> reward

交付：

- `app/services/runtime_model_agent.py`
- `rl/reward_builder.py`
- `target_weight` action parser
- 测试：两个模型能并行运行并产生可验证动作

### Phase 2：Arena MVP

目标：

- 支持“2 个模型 + 100 retail 背景”对抗
- 记录 episode report
- 在 GUI 中显示训练状态

交付：

- `training_arena_service.py`
- `training_episodes` / `model_episode_results`
- Agent 面板显示 arena / reward / generation

### Phase 3：PPO Baseline

目标：

- 接入 PPO + GRU/LSTM baseline
- 支持 collect-only / online-train
- 输出 loss、entropy、value loss

交付：

- `rl/model_adapters/ppo_recurrent_adapter.py`
- transition buffer
- checkpoint manager
- 训练指标展示

### Phase 4：PBT / 胜者传授机制

目标：

- 周期结束后排名
- top 模型 checkpoint 化
- bottom 模型继承 top / Hall-of-Fame 参数并 mutation

交付：

- `rl/pbt_engine.py`
- `model_lineage`
- mutation config
- 测试：generation / parent_model_id 正确演进

### Phase 5：League / Hall-of-Fame / Cross-Play

目标：

- 引入 main / exploiter / risk-averse roles
- 保留历史强者
- 输出 payoff matrix

交付：

- `league_manager_service.py`
- `payoff_matrix.py`
- `hall_of_fame_entries`

### Phase 6：Alpha-Rank + Scenario Generator

目标：

- 引入非传递评估
- 引入受约束的场景生成器

交付：

- `alpha_rank_service.py`
- `scenario_generator.py`
- realism gate

### Phase 7：第二代模型升级

目标：

- 尝试 GTrXL / Transformer temporal encoder
- 尝试 partial inheritance / distillation
- 引入 CVaR / constrained objective

---

## 17. 第一轮最合理的实现边界

不建议一开始就做完整“AlphaStar 式超级训练平台”。

第一轮最合理的目标是：

```text
1. Agent 面板支持 Retail / Model 区分
2. 新增 RuntimeModelAgent
3. obs/action/reward contract 定型
4. 跑通 2 模型 + retail 背景对抗
5. 记录 episode report 和 checkpoint
6. 做最小 PBT 继承
```

完成这一步之后，平台就真正从：

```text
可运行市场模拟器
```

升级为：

```text
可承载模型对抗与代际演化的训练平台
```

---

## 18. 风险与缓解

### 18.1 过拟合当前 retail 噪声

缓解：

- Hall-of-Fame 回放
- 多 scenario 评估
- anchor retail benchmark
- scenario generator 受 realism gate 约束

### 18.2 种群同质化

缓解：

- 不做简单 winner overwrite loser
- 保留独立 policy head / adapter
- mutation + targeted exploiter
- non-transitive evaluation

### 18.3 奖励黑客

缓解：

- 奖励组件透明化
- 强制风险硬约束
- cross-play + risk metrics 双评估
- 回撤和尾部风险门槛

### 18.4 工程复杂度过高

缓解：

- 先做 MVP 闭环
- 先 PPO/LSTM，后 GTrXL
- 先 rule-based scenario mutation，后 adversarial generator
- 先 checkpoint + lineage，后 distillation

---

## 19. 建议的默认配置（v1）

```yaml
training:
 algorithm: ppo_recurrent
 temporal_encoder: lstm
 rollout_length: 256
 minibatches: 4
 epochs: 4
 gamma: 0.99
 gae_lambda: 0.95
 clip_ratio: 0.2
 entropy_coef: 0.01
 value_coef: 0.5

league:
 main_agents: 1
 main_exploiters: 2
 league_exploiters: 2
 risk_exploiters: 1
 hall_of_fame_max: 20
 opponent_sampling:
  current_population: 0.70
  hall_of_fame: 0.20
  targeted_exploiters: 0.10

pbt:
 promote_top_pct: 0.20
 preserve_mid_pct: 0.50
 replace_bottom_pct: 0.30
 mutation:
  lr: [0.8, 1.2]
  entropy_coef: [0.8, 1.2]
  turnover_penalty: [0.8, 1.2]
  risk_penalty: [0.8, 1.2]

risk:
 reward_profile: relative_equity_risk_adjusted_v1
 max_allowed_drawdown: 0.20
 cvar_alpha: 0.10
```

以上数值只是建议起点，不是最终定案。

---

## 20. 伪代码：训练总循环

```python
while training_active:
  arena = league_manager.sample_arena()

  episode_result = arena.run_episode(
    models=league_manager.sample_matchup(),
    retail_profile=scenario_generator.sample_constrained_profile(),
  )

  metrics_store.record(episode_result)
  payoff_matrix.update(episode_result)

  if episode_result.checkpoint_needed:
    checkpoint_service.save(episode_result)

  if pbt_engine.should_evolve():
    ranking = evaluator.rank_population(
      payoff_matrix=payoff_matrix,
      risk_metrics=metrics_store,
      hall_of_fame=hall_of_fame,
    )
    pbt_engine.evolve(ranking)
    hall_of_fame.update(ranking)
```

---

## 21. 最终结论

本项目最合适的路线不是：

```text
GAN / GCA 直接作为主训练算法
```

而是：

```text
Anchored Retail Ecology
+ League / PSRO-style Self-Play
+ PPO Recurrent Baseline
+ PBT / Inheritance / Hall-of-Fame
+ Risk-Constrained Rewarding
+ Alpha-Rank / Cross-Play Evaluation
+ Adversarial Scenario Generation (as constrained extension)
```

一句话概括：

> 最该升级的不是“把 PPO 换成某个新名词”，而是把训练制度从单模型优化升级为“联盟对抗 + 代际传承 + 风险约束 + 非传递评估”的完整体系。

这套体系既能保留当前 UTI-STOCKSIM 的交易语义优势，也能把你想要的“胜者传授、失败者再战、从 0 开始自我迭代的对抗学习”真正工程化落地。
