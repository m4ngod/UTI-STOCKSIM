# UTI-STOCKSIM Evidence Runner Healthy No-Go 修复任务文档

> 适用对象：Codex / 自动编程 Agent  
> 任务类型：工程修复 + 证据链硬化 + 测试补齐  
> 当前阶段：Evidence Runner v0 已进入 live PostgreSQL/runtime 验证期，但仍为健康 No-Go  
> 总原则：不要降低 gate 标准，不要把 runner 可用误判为研究通过，不要在 evidence 未通过前升级复杂模型路线。

---

## 0. 背景摘要

导师评价当前项目已经从 `metadata completeness / headless injected package` 阶段推进到 `live PostgreSQL/runtime evidence package` 阶段。Python/runtime 阻塞已经解除，`pg8000` fallback 让本地 PostgreSQL-backed Arena 路径可运行；Task 101 live package 已能写入并读回真实 runtime/database 证据，包括 3 个 `training_episodes`、21 条 `model_episode_results` 和 38 条 `model_transitions`。当前 package 状态为 `status=complete`、`go_no_go=no_go`，并读回 `status_counts={"pass": 1, "fail": 6}`。

当前 No-Go 是正确结果，不是失败。它说明 Evidence Gate 已经开始根据真实运行结果阻断未经证实的模型晋升、父代继承和研究结论。当前 baseline evidence 已 pass，其余 6 个 fail 为：

| Evidence Section | 当前状态 | 失败类型 | 说明 |
|---|---:|---|---|
| baseline | pass | - | TWAP/VWAP/AC-lite 等基线体系已经能跑出有效对照 |
| calibration | fail | 上游世界质量证据失败 | world 是否像目标市场尚未形成通过证据 |
| hidden evaluation | fail | 上游模型泛化证据失败 | 静态候选没有打败 TWAP/VWAP/AC-lite |
| exploit test | fail | 上游安全/反作弊证据失败 | 缺关键 probe metrics |
| paired sensitivity | fail | 上游鲁棒性证据失败 | 费用、冲击、流动性成对压力测试未通过 |
| strict parent gate | fail | 下游派生失败 | 上游未过时必须阻断父代资格 |
| research acceptance lock | fail | 下游派生失败 | blocking sections 未清空时必须 locked |

本轮任务目标不是“消灭红灯”，而是把 evidence artifact 从“能生成”推进到“可复现、可审计、可解释、可阻断”。

---

## 1. 全局不可违背约束

Codex Agent 在执行任务时必须遵守以下约束：

1. **不得降低 gate 标准。** 不能为了让结果 pass 而放宽阈值、忽略关键指标、删除 blocking section 或改写失败逻辑。
2. **不得手动 override evidence 状态。** `SeriesEvidenceAggregate`、`StrictParentGate`、`ResearchAcceptanceLock` 必须从 artifact hash、artifact status、`pass_gate` 和 blocking metrics 重新计算。
3. **不得把 headless injected package 当作 live research evidence。** 本轮所有 evidence 必须尽量来自 live PostgreSQL/runtime facts。
4. **不得用 leaderboard 替代 evidence。** leaderboard 只可作为 UI 观察，不可作为 parent eligibility、research acceptance 或 model promotion 的依据。
5. **不得升级复杂模型路线。** 在 Evidence Runner Go / No-Go review 进入 Go 前，不引入或启用 Transformer、GTrXL、复杂 MARL、historical replay、hybrid env 或 alpha-claim 路线。
6. **Hidden evaluation candidate 必须 frozen。** 不允许在 hidden world 上训练、调参、选择 checkpoint 或修改 candidate。
7. **Hidden worlds/seeds 不得污染训练。** hidden split 必须与 training/validation split 可追踪地区分，并写入 artifact。
8. **所有新增 artifact 必须可 hash、可读回、可复算。** 修改后必须保证 Evidence Board 与 Series Evidence Aggregate 读回一致。
9. **失败原因必须结构化输出。** 每个 fail 至少包含 `failure_type`、`blocking_metrics`、`next_action`、`artifact_hash`、`runner_version`、`source_run_ids`。

---

## 2. 推荐执行顺序

按如下顺序执行，不要先追 hidden pass：

```text
1. Calibration
   先证明 world 有基本工程质量。

2. Exploit test
   再证明 runtime/reward/obs/fill/ledger 没有明显漏洞。

3. Paired sensitivity
   再证明策略不是靠低费用、低冲击、过度流动性赚钱。

4. Hidden evaluation
   最后证明 frozen candidate 在隐藏世界打败强基线。

5. Strict parent gate
   上游过后自然打开，不要手动放行。

6. Research acceptance lock
   最后只打开合适的 claim level，先 engineering acceptance，不直接打开 alpha/research claim。
```

---

## 3. 代码探索要求

执行前先在仓库中定位现有实现。优先搜索以下文件或等价模块：

```text
app/services/evidence_core.py
app/services/evidence_artifact_writer.py
app/services/hidden_world_runner.py
app/services/paired_sensitivity_runner.py
app/services/exploit_test_runner.py
app/services/strict_parent_gate.py
app/services/research_acceptance_lock.py
app/services/series_evidence_aggregate.py
app/services/evidence_board_service.py
app/services/long_arena_dry_run.py
app/services/model_route_gate.py
agents/retail_calibration.py
agents/retail_calibration_report.py
services/training_episode_service.py
services/runtime_query_service.py
services/runtime_command_service.py
persistence/*
tests/*evidence*
tests/*arena*
tests/*calibration*
tests/*exploit*
tests/*sensitivity*
```

如果实际文件名不同，以现有项目结构为准，保持现有 public API 尽量兼容。

---

# Task A：Calibration Target Bands v0

## A.1 目标

定义 `target_bands` 配置，先支持 engineering target，不宣称真实市场研究通过。该配置用于校准 world 的基础市场质量，使 `calibration_artifact_v1` 能判断指标是否齐全、稳定、无严重异常。

## A.2 建议新增或修改

优先寻找已有 calibration 配置目录。若不存在，可新增：

```text
configs/evidence/calibration_target_bands.v0.json
```

或使用项目现有 config 路径。

## A.3 必须覆盖的 P0 指标

`target_bands` 至少覆盖：

```text
spread
depth
turnover
volatility
return_autocorrelation
fill_rate
cancel_rate
buy_sell_ratio
holding_period
retail_family_mix
order_lifespan
```

每个指标至少包含：

```json
{
  "metric_name": {
    "target_min": 0.0,
    "target_max": 1.0,
    "severity_on_breach": "warning|severe",
    "required": true,
    "description": "..."
  }
}
```

## A.4 实现要求

1. 增加 target bands loader。
2. 对缺失字段做明确错误提示。
3. 支持版本字段，例如 `schema_version=calibration_target_bands.v0`。
4. 支持后续替换为真实市场 target，不把当前 engineering target 写死在代码里。

## A.5 验收标准

1. loader 能成功读取 target bands。
2. 缺失 P0 指标时测试失败。
3. target bands 结构错误时给出清晰异常。
4. 文档或注释明确当前为 `engineering_pass` 标准，不是 `research_pass`。

## A.6 测试建议

新增或修改测试：

```text
tests/evidence/test_calibration_target_bands.py
```

测试点：

```text
- loads_valid_target_bands
- rejects_missing_required_metric
- rejects_invalid_band_range
- exposes_schema_version
```

---

# Task B：Live Calibration Artifact Writer Hardening

## B.1 目标

让每个 `world_spec_v1` 都能从 live PostgreSQL/runtime facts 生成 `calibration_artifact_v1`。当前阶段先追求 `engineering_pass`：指标齐全、可复现、多 seed 稳定、无明显 runtime 异常。

## B.2 数据来源

artifact 必须优先从 PostgreSQL runtime facts 读取，不得依赖 injected summary。至少读取：

```text
orders
trades
snapshots_1s
bars_1m
agent_bindings
account_equity_snapshots
training_episodes / model_episode_results / model_transitions（如适用）
```

## B.3 Artifact 必须包含

```text
artifact_type = calibration_artifact_v1
world_hash
world_spec_version
seed_hashes
source_run_ids
metrics
metric_coverage
target_bands
observed_values
distance_by_metric
severity_by_metric
failed_metrics
missing_metrics
calibration_score
pass_gate
engineering_pass
research_pass = false 或 omitted
runner_version
artifact_hash
created_at
```

## B.4 指标计算要求

至少计算：

```text
spread：盘口买卖价差或 snapshot 派生价差
depth：盘口深度或可用替代深度指标
turnover：成交额/成交量相对账户或市场规模
volatility：bar return 波动
return_autocorrelation：收益自相关
fill_rate：成交量 / 委托量
cancel_rate：撤单数 / 总订单数
buy_sell_ratio：买单/卖单比例
holding_period：retail 平均持仓周期
retail_family_mix：retail family 分布
order_lifespan：订单从创建到成交/撤销/过期的生命周期
```

如果某指标当前无法严格计算，必须输出：

```text
status = missing
failure_type = missing_metric
next_action = 明确说明需要补哪个事实表或事件字段
```

不得静默填 0 或跳过。

## B.5 多 seed 聚合

实现或补齐：

```text
run_retail_only_world(world_spec, seed, duration)
extract_market_metrics(run_id)
aggregate_metrics(seed_metrics)
compare_to_target_bands(aggregate, target_bands)
```

若当前项目已有等价函数，应复用并硬化。

## B.6 Pass 逻辑

当前阶段建议：

```text
engineering_pass = 指标齐全 + schema/hash 正确 + 多 seed 可聚合 + 无 severe failure
research_pass = false
pass_gate = engineering_pass
```

注意：代码命名可保留 `pass_gate`，但 artifact 中应明确 `pass_level=engineering`，避免误解为真实市场 research pass。

## B.7 验收标准

1. 对每个 world 生成 `calibration_artifact_v1`。
2. artifact 读回后 hash 稳定。
3. P0 指标齐全时可计算 score。
4. 缺指标时 fail，并给出 `missing_metrics` 与 `next_action`。
5. 不依赖 injected summary。
6. 多 seed 聚合结果可读回。

## B.8 测试建议

```text
tests/evidence/test_calibration_artifact_writer.py
tests/evidence/test_calibration_metric_extractor.py
```

测试点：

```text
- writes_calibration_artifact_from_runtime_facts
- fails_when_required_metric_missing
- computes_metric_distances_and_severity
- aggregates_multiple_seeds
- artifact_hash_is_stable_after_readback
```

---

# Task C：Exploit Probe Metrics Completion

## C.1 目标

补齐 exploit runner 的六类 probe metrics，证明当前没有已知严重仿真漏洞路径，或者在发现漏洞时能结构化 fail。

## C.2 必须实现的 Probe

| Probe | 必须证明 |
|---|---|
| timestamp | observation 中没有未来价格、未来成交、未来排名、未来权益 |
| mark_to_market | 低流动性仓位不能被自推价格高估 |
| order_boundary | 无非法卖空、无超现金买入、无 T+1 违规、无越界订单 |
| fee_accounting | 买卖、部分成交、撤单、拒单后的费用和冻结释放完全可对账 |
| fill_rule | 订单不能无对手方成交，成交价、队列优先级、TIF 行为一致 |
| clock_boundary | 非交易阶段不能成交，bar/time boundary 不能泄漏未来信息 |

## C.3 Artifact 必须包含

```text
artifact_type = exploit_test_artifact_v1
candidate_id
candidate_checkpoint_hash
probe_world_hashes
probe_metrics
severe_flags
missing_metrics
failure_reproduction_payloads
source_run_ids
runner_version
pass_gate
artifact_hash
```

每个 probe metric 至少包含：

```text
status = pass|fail|missing|not_available
severity = info|warning|severe
observed_value 或 observed_events
expected_invariant
violations
failure_type
next_action
source_run_ids
```

## C.4 实现要求

1. 若某 probe 暂无法完整证明，必须 `status=missing`，并写明 `next_action`。
2. `pass_gate = no severe fail 且 no missing/not_available P0 probe`。
3. 不得用 “runner 执行成功” 代替 probe pass。
4. 对每个 severe fail 保留最小 reproduction payload，例如 run_id、order_id、symbol、timestamp、account_id、相关 ledger ids。

## C.5 验收标准

1. 六类 probe 均出现在 artifact。
2. 缺任何 P0 probe 时 exploit artifact fail。
3. severe flag 时 exploit artifact fail。
4. artifact 能被 Evidence Board 展示具体失败原因。
5. 测试覆盖至少一个 pass case、一个 missing case、一个 severe fail case。

## C.6 测试建议

```text
tests/evidence/test_exploit_probe_metrics.py
```

测试点：

```text
- includes_all_required_probes
- fails_when_probe_missing
- fails_on_severe_timestamp_leak
- fails_on_invalid_order_boundary_violation
- passes_when_all_probes_present_and_clean
```

---

# Task D：Paired Sensitivity Runner Hardening

## D.1 目标

补齐成对费用、冲击和流动性压力测试，证明策略不是靠低费用、无冲击或虚假流动性赚钱。

## D.2 场景要求

同一 candidate、同一 seed、同一 base world，只改变一个环境维度，至少跑：

```text
base
high_fee
high_impact
low_liquidity
```

后续可扩展：

```text
wide_spread
thin_depth
volatile_regime
```

## D.3 Artifact 必须包含

```text
artifact_type = paired_sensitivity_artifact_v1
candidate_id
base_world_hashes
scenario_world_hashes
seed_hashes
paired_results
candidate_metrics
baseline_metrics
scenario_deltas
catastrophic_collapse_flags
explainability_flags
source_run_ids
runner_version
pass_gate
artifact_hash
```

## D.4 每组结果至少记录

```text
gross_pnl
net_pnl
net_return
fee_drag
impact_cost
slippage
turnover
unfilled_ratio
max_drawdown
inventory_risk
execution_shortfall
```

并与以下基线同场比较：

```text
TWAP
VWAP
AC-lite
```

## D.5 Pass 逻辑建议

```text
pass_gate =
  no_catastrophic_collapse
  and fee_sensitivity_explainable
  and impact_sensitivity_explainable
  and low_liquidity_behavior_reasonable
  and no_missing_required_scenario
```

解释性规则示例：

```text
- high_fee 下收益下降可以接受，但 fee_drag 必须解释下降来源。
- high_impact 下高换手策略应降低优势或主动收敛换手。
- low_liquidity 下 unfilled_ratio 上升可以接受，但不能出现无对手方成交或收益异常升高。
- 如果策略只在 base/low_fee world 赚钱，压力场景全面崩溃，应 fail。
```

## D.6 验收标准

1. 四类 scenario 均可生成。
2. 每个 scenario 与 base world 存在 paired relationship。
3. candidate 与 TWAP/VWAP/AC-lite 在同一 scenario 下对比。
4. scenario delta 可解释，异常时结构化 fail。
5. artifact hash 可读回并被 aggregate 使用。

## D.7 测试建议

```text
tests/evidence/test_paired_sensitivity_runner.py
```

测试点：

```text
- creates_required_scenarios_from_base_world
- preserves_candidate_seed_and_base_world_pairing
- records_required_metrics
- fails_when_required_scenario_missing
- fails_on_catastrophic_collapse
```

---

# Task E：Hidden Evaluation Candidate Upgrade

## E.1 目标

修复 hidden evaluation 的候选评估路径。当前静态候选未打败 TWAP/VWAP/AC-lite。不要降低基线标准；应改为评估 frozen candidate，并优先收束为 Alpha-to-Execution 或至少加入规则 execution candidate。

## E.2 必须遵守

1. candidate 必须 frozen。
2. hidden worlds/seeds 必须来自训练外。
3. candidate、TWAP、VWAP、AC-lite 必须在同一 hidden world、同一 seed、同一流动性路径、同一费用模型下成对比较。
4. hidden eval 不得触发训练、PBT、checkpoint 选择或调参。
5. hidden eval artifact 必须记录 candidate training worlds，证明没有 hidden 污染。

## E.3 评价指标

至少包含：

```text
net_return
execution_shortfall
fee_drag
turnover
max_drawdown
inventory_risk
unfilled_ratio
```

如果当前任务是 Alpha-to-Execution，评价应相对：

```text
arrival price
TWAP
VWAP
AC-lite
```

而不是只看净值。

## E.4 Pass 逻辑建议

当前建议较稳妥：

```text
pass_gate =
  sample_size >= MIN_HIDDEN_WORLDS
  and win_rate_vs_baselines >= 0.67
  and beats_at_least_2_of_3_baselines_on_majority_worlds
  and no_risk_budget_breach
  and no_hidden_split_contamination
```

后续研究通过阶段可升级为要求优于 3/3 baselines。

## E.5 Artifact 必须包含

```text
artifact_type = hidden_eval_artifact_v1
candidate_id
candidate_checkpoint_hash
candidate_training_world_hashes
hidden_world_hashes
seed_hashes
baseline_names
paired_results
metric_summary
risk_budget_breaches
split_contamination_check
pass_gate
artifact_hash
```

## E.6 验收标准

1. hidden eval 拒绝非 frozen candidate。
2. hidden eval 检测并拒绝 hidden world 污染。
3. candidate 与三类 baseline 成对比较。
4. underperform 时保留 fail，不降低基线。
5. artifact 输出失败原因：`underperform_baseline`、`risk_budget_breach` 或 `split_contamination`。

## E.7 测试建议

```text
tests/evidence/test_hidden_eval_runner.py
```

测试点：

```text
- rejects_candidate_that_is_not_frozen
- rejects_hidden_world_seen_in_training
- records_paired_baseline_comparison
- fails_when_candidate_underperforms_baselines
- passes_when_candidate_beats_required_baselines_without_risk_breach
```

---

# Task F：Evidence Aggregate Strict Recompute

## F.1 目标

让 `SeriesEvidenceAggregate` 不信任手工 status，不信任 leaderboard，不信任 UI 状态，只从 artifact hash、artifact readback、`pass_gate` 和 blocking metrics 重算。

## F.2 实现要求

1. aggregate 输入必须是 artifact references / artifact hashes。
2. aggregate 读回 artifact 后重新计算每个 section status。
3. `status_counts` 必须由实际 artifact pass/fail/missing 计算。
4. `go_no_go = go` 仅当所有 required artifacts pass。
5. 如果 artifact hash mismatch，section 必须 fail 或 package incomplete。
6. 如果存在 `manual_override`、`injected_only`、`not_available`，必须进入 blocking sections。

## F.3 Required Artifacts

```text
baseline_artifact_v1
calibration_artifact_v1
hidden_eval_artifact_v1
exploit_test_artifact_v1
paired_sensitivity_artifact_v1
parent_gate_artifact_v2
research_acceptance_lock_v2
```

## F.4 验收标准

1. 当前状态应仍能表达 `1 pass + 6 fail`，但结果来自重算。
2. 删除或损坏任一 artifact 时 aggregate fail/incomplete。
3. 手工把 UI status 改成 pass 不影响 aggregate 结果。
4. aggregate 输出每个 fail 的原因和 next action。

## F.5 测试建议

```text
tests/evidence/test_series_evidence_aggregate.py
```

测试点：

```text
- recomputes_status_from_artifacts
- ignores_manual_status_override
- fails_on_artifact_hash_mismatch
- no_go_when_required_artifact_fails
- go_only_when_all_required_artifacts_pass
```

---

# Task G：Strict Parent Gate v2 Recompute-Only

## G.1 目标

确保 Strict Parent Gate 只根据上游 evidence bundle 重新计算父代资格，不读取 leaderboard，不读取人工标记，不因为 checkpoint 存在就放行。

## G.2 Required Upstream Evidence

```text
baseline pass
calibration pass
hidden_eval pass
exploit_test pass
paired_sensitivity pass
research_acceptance_lock status = open
research_acceptance blocking_sections = []
完整 lineage/hash 信息
```

## G.3 Candidate Hash/Lineage 必须校验

至少校验：

```text
candidate_checkpoint_hash
training_world_hashes
evaluation_world_hashes
reward_contract_hash
action_contract_hash
observation_contract_hash
code_version 或 runner_version
artifact_hashes
```

## G.4 Pass 逻辑

```python
pass_gate = (
    all_required_upstream_artifacts_pass
    and research_acceptance_lock_is_open
    and no_blocking_sections
    and lineage_and_hashes_valid
)
```

## G.5 验收标准

1. 任何上游 evidence fail，parent gate 必须 fail。
2. research lock 未打开，parent gate 必须 fail。
3. lineage/hash 缺失或不匹配，parent gate 必须 fail。
4. leaderboard 第一名不能绕过 parent gate。
5. 输出 `blocking_sections` 和 `required_artifact_hashes`。

## G.6 测试建议

```text
tests/evidence/test_strict_parent_gate_v2.py
```

测试点：

```text
- fails_when_calibration_fails
- fails_when_hidden_eval_fails
- fails_when_research_lock_closed
- fails_when_lineage_hash_missing
- ignores_leaderboard_rank
- passes_only_when_all_required_conditions_hold
```

---

# Task H：Research Acceptance Lock Scoped Opening

## H.1 目标

实现分级 research acceptance。即使上游 evidence 全 pass，也不要直接打开 alpha/research claim。当前阶段最多打开 `level_1_engineering_acceptance`。

## H.2 Acceptance Levels

```text
level_0_locked:
  默认状态。存在 missing/fail/blocking evidence。

level_1_engineering_acceptance:
  live runtime package complete，baseline/calibration/exploit/paired/hidden 全 pass，artifact hash 一致，无 manual_override/injected_only。

level_2_sim_research_acceptance:
  多 hidden world、多 seed、多 regime 上稳定击败强基线，风险预算无违规。

level_3_transfer_acceptance:
  replay/hybrid 或真实历史背景下仍不崩溃，并通过人工审计。
```

当前任务只要求实现 level 0 和 level 1；level 2/3 可以保留 schema 或 placeholder，但不得自动打开。

## H.3 Lock 必须检查

```text
所有 required artifact 均 pass
artifact hash 与 live package hash 一致
Evidence Board 与 Series Evidence Aggregate 读回一致
没有 missing / not_available / manual_override / injected_only
没有 severe exploit flag
hidden evaluation 无调参污染
claim_scope 不超过允许等级
```

## H.4 Artifact 必须包含

```text
artifact_type = research_acceptance_lock_v2
candidate_id
package_hash
acceptance_level
status = locked|open
allowed_claims
blocked_claims
blocking_sections
artifact_hashes
manual_override_detected
injected_only_detected
severe_flags
created_at
artifact_hash
```

## H.5 验收标准

1. 上游 evidence fail 时 lock = locked。
2. 上游 evidence pass 时最多打开 level_1_engineering_acceptance。
3. 不得自动打开 level_2 或 level_3。
4. 如果存在 manual_override / injected_only，lock 必须 locked。
5. 输出 allowed_claims 与 blocked_claims。

## H.6 测试建议

```text
tests/evidence/test_research_acceptance_lock_v2.py
```

测试点：

```text
- remains_locked_when_any_required_evidence_fails
- opens_level_1_when_engineering_evidence_passes
- does_not_open_level_2_without_sim_research_conditions
- rejects_manual_override
- rejects_injected_only_artifacts
```

---

# Task I：Evidence Board Failure Diagnostics

## I.1 目标

让 GUI Evidence Board 展示失败原因，而不是只显示红灯。每个 section 必须给出可执行诊断。

## I.2 每个 fail 至少显示

```text
section_name
status
failure_type
blocking_metrics
next_action
artifact_hash
runner_version
source_run_ids
last_updated
```

## I.3 Failure Type 枚举建议

```text
missing_metric
underperform_baseline
severe_flag
upstream_blocked
hash_mismatch
manual_override_detected
injected_only
not_available
risk_budget_breach
split_contamination
catastrophic_collapse
```

## I.4 验收标准

1. Evidence Board 能显示 1 pass + 6 fail 的具体原因。
2. upstream-derived fail 要标注 `upstream_blocked`，不要伪装成本地 runner 失败。
3. 点击或展开某 section 时能看到 blocking metrics 和 next action。
4. UI 不允许修改 artifact pass/fail，只能展示。

## I.5 测试建议

```text
tests/evidence/test_evidence_board_diagnostics.py
```

测试点：

```text
- builds_diagnostic_view_model_for_failed_sections
- includes_failure_type_and_next_action
- marks_parent_gate_as_upstream_blocked
- does_not_allow_ui_status_override
```

---

# 4. 总体验收标准

本轮完成后，允许的结果不是必须全 green，而是必须更可信。

## 4.1 最低完成标准

1. Calibration artifact 能从 live runtime facts 生成，缺指标时结构化 fail。
2. Exploit test artifact 包含六类 probe metrics，缺 probe 时结构化 fail。
3. Paired sensitivity artifact 包含 base/high_fee/high_impact/low_liquidity 成对结果。
4. Hidden eval 明确 frozen candidate、hidden split 和强基线 paired comparison。
5. SeriesEvidenceAggregate 从 artifact 重算状态，不信任人工 status。
6. StrictParentGate 只读 evidence bundle，任何上游 fail 都阻断。
7. ResearchAcceptanceLock 支持 level_1 engineering acceptance，但不自动打开更高 claim。
8. Evidence Board 显示失败原因、blocking metrics 和 next action。

## 4.2 允许的最终状态

如果上游指标仍未达到门槛，最终仍可以是 No-Go。只要失败原因更硬、更可复现、更可诊断，本轮就是成功。

合理最终状态示例：

```json
{
  "package_status": "complete",
  "go_no_go": "no_go",
  "status_counts": {
    "pass": 1,
    "fail": 6
  },
  "reason": "Required evidence artifacts are now recomputed from live runtime facts, but calibration/hidden/exploit/paired sensitivity gates still block promotion."
}
```

如果部分任务转 pass，也必须保证：

```text
- pass 来自真实 artifact 指标，不来自阈值降低。
- parent gate 和 research lock 是派生打开，不是手工打开。
- allowed_claims 不超过 engineering acceptance。
```

---

# 5. 建议运行命令

根据项目 README，优先使用项目 venv。Codex Agent 应先识别实际环境，再运行最小相关测试。

```powershell
..\Quent\.venv\Scripts\python.exe -m pytest -q
```

如全量测试过重，先运行 evidence 相关测试：

```powershell
..\Quent\.venv\Scripts\python.exe -m pytest -q tests -k "evidence or calibration or hidden or exploit or sensitivity or parent_gate or acceptance_lock"
```

数据库健康检查：

```powershell
..\Quent\.venv\Scripts\python.exe setup_frontend_entry.py --check-db --require-postgres
```

Arena smoke/integration 路径：

```powershell
..\Quent\.venv\Scripts\python.exe scripts\run_arena_experiment.py --generations 2 --duration 45 --retail-count 80 --symbols "001,002,003"
```

如果当前环境不是 Windows 或没有该 venv，Codex Agent 应使用仓库实际 Python 解释器，但不得跳过测试说明。

---

# 6. 推荐提交结构

建议拆成多个小提交，便于回滚和审查：

```text
commit 1: add calibration target bands v0 and loader tests
commit 2: harden live calibration artifact writer and metric extraction
commit 3: complete exploit probe metric schema and runner checks
commit 4: harden paired sensitivity runner scenarios and metrics
commit 5: enforce frozen candidate and split checks in hidden eval
commit 6: recompute series evidence aggregate from artifact hashes
commit 7: make strict parent gate recompute-only
commit 8: add scoped research acceptance lock levels
commit 9: add evidence board failure diagnostics
```

---

# 7. Codex Agent 最终交付物

完成任务后请输出：

```text
1. 修改文件列表
2. 新增文件列表
3. 每个 Task A-I 的完成情况
4. 未完成项和原因
5. 测试命令与测试结果
6. 当前 evidence package 的 go/no-go 状态
7. 是否存在任何 manual_override / injected_only / missing_metric / severe_flag
8. 下一步建议
```

不得只回复“已完成”。必须说明哪些 evidence 仍 fail，以及 fail 是否为正确的阻断。
