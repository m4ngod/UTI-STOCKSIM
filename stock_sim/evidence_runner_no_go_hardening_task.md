# UTI-STOCKSIM Evidence Runner No-Go Hardening 任务文档

> 建议放置路径：`docs/tasks/model-training/evidence-runner-no-go-hardening.md`  
> 任务用途：交给 Codex agent 执行，用于把当前“健康的 No-Go”推进为更硬的 live evidence package，而不是通过降低门槛把红灯改绿。

---

## 0. 背景与当前状态

当前项目已经从 `metadata completeness / headless injected package` 阶段，推进到 `live PostgreSQL/runtime evidence package` 阶段。Python/runtime 阻塞已解除，`pg8000` fallback 使本地 PostgreSQL-backed Arena 路径可运行。Task 101 live package 已能写入并读回真实 runtime/database 证据，包括：

- `training_episodes`: 3 条
- `model_episode_results`: 21 条
- `model_transitions`: 38 条
- package 状态：`status=complete`
- Go/No-Go：`go_no_go=no_go`
- evidence 状态：`status_counts={"pass": 1, "fail": 6}`

当前 `baseline evidence` 已经 pass；其余 6 个 fail 是正确的健康 No-Go，不应通过人工标记或降低 gate 标准消除。

当前 6 个 fail 分为两类：

| Evidence | 类型 | 当前失败本质 |
|---|---|---|
| `calibration` | 上游世界质量证据 | 世界是否像目标市场还没有形成通过证据 |
| `hidden_evaluation` | 上游模型泛化证据 | live hidden runner 显示静态候选没有打败 TWAP/VWAP/AC-lite |
| `exploit_test` | 上游安全/反作弊证据 | exploit runner 缺关键 probe metrics |
| `paired_sensitivity` | 上游鲁棒性证据 | 费用、冲击、流动性成对压力测试还没有通过证据 |
| `strict_parent_gate` | 下游门控证据 | 因上游证据未过，父代资格必须失败 |
| `research_acceptance_lock` | 下游研究结论锁 | 因 blocking sections 未清空，研究接受锁必须保持 locked |

优先修复顺序：

```text
1. calibration
2. exploit_test
3. paired_sensitivity
4. hidden_evaluation
5. strict_parent_gate
6. research_acceptance_lock
```

重点：真正需要优先增强的是前四个上游证据；后两个是派生门控，不应手动放行。

---

## 1. 本轮任务目标

本轮目标不是“把 6 个 fail 全部改成 pass”，而是：

1. 让每个 evidence artifact 都来自 live PostgreSQL/runtime facts，而不是 injected summary 或手工状态。
2. 区分 `presence pass` 与 `research pass`：
   - `presence pass`: artifact 存在、schema 正确、hash 正确、runner 真实执行。
   - `research pass`: artifact 里的指标达到研究或工程验收门槛。
3. 为 calibration、exploit、paired sensitivity、hidden evaluation 生成更硬的 artifact、diagnostics 与 failure reason。
4. 让 Series Evidence Aggregate 只从 artifact hash 与 `pass_gate` 重算状态，不信任手工 status。
5. 让 Strict Parent Gate v2 与 Research Acceptance Lock v2 保持派生逻辑：上游不过，下游必须 fail/locked。
6. 继续阻止复杂模型路线：在 Evidence Runner Go/No-Go review 变为 Go 前，不升级 Transformer、GTrXL、复杂 MARL、historical replay、hybrid env 或 alpha-claim 路线。

---

## 2. 非目标与禁止事项

### 2.1 禁止为了“变绿”降低标准

禁止：

- 手动把 `fail` 改成 `pass`。
- 让 `strict_parent_gate` 绕过上游 evidence。
- 让 `research_acceptance_lock` 在 blocking sections 非空时打开。
- 把 `not_available`、`missing`、`injected_only` 包装成 `complete/pass`。
- 降低 TWAP/VWAP/AC-lite 基线难度来让候选过 hidden。
- 把 3 个 episode、21 条 result、38 条 transition 解释成模型研究有效性证据。它们只能证明 runtime/database integration smoke path 可用。

### 2.2 禁止扩大路线范围

当前仍使用：

- `ppo_lstm_v1`
- 外部静态候选
- 规则执行候选
- TWAP/VWAP/AC-lite 等强基线

禁止新增或推进：

- Transformer / GTrXL
- 复杂 MARL
- Historical replay / hybrid env
- alpha-claim 路线
- 自动 checkpoint 晋升
- 父代继承放行
- 真实市场迁移结论

### 2.3 数据与存储约束

除非明确需要并经过边界设计，否则不要：

- 删除 PostgreSQL 中 `stock_sim` 项目数据库历史数据。
- 扩大 raw transition sample storage。
- 新增无限制 raw replay artifact。
- 改变训练、执行、奖励、账户、撮合、PBT 父代选择或 checkpoint loading 行为。

如果需要保留 replay/failure payload，必须使用 bounded summary 或明确 artifact 边界。

---

## 3. Work Package A：Calibration Target Bands v0

### 3.1 目标

定义 `target_bands.json` 或等价配置，用于让 `calibration_artifact_v1` 可以从 live runtime/database facts 计算 `engineering_pass`。

当前阶段不要声称“真实市场研究通过”。先实现两级语义：

```text
engineering_pass:
  指标齐全、可复现、多 seed 稳定、无明显 runtime 异常。

research_pass:
  指标齐全，且与真实市场或目标市场统计分布接近。
```

本轮优先实现 `engineering_pass`。

### 3.2 必须覆盖的 P0 指标

每个 `world_spec_v1` 至少覆盖：

- `spread`
- `depth`
- `turnover`
- `volatility`
- `return_autocorrelation`
- `fill_rate`
- `cancel_rate`
- `buy_sell_ratio`
- `holding_period`
- `retail_family_mix`
- `order_lifespan`

每个指标必须包含：

```json
{
  "metric_name": "spread",
  "target_band": {"min": 0.0, "max": 1.0, "source": "engineering_default_v0"},
  "observed_value": 0.0,
  "distance": 0.0,
  "severity": "none|warning|severe",
  "status": "pass|fail|missing"
}
```

### 3.3 实现要求

1. 从 live PostgreSQL/runtime facts 读取数据，不允许使用 injected summary。
2. 允许初版 target bands 使用 engineering default，但必须显式标记 `target_source=engineering_default_v0`。
3. 多 seed 运行后必须 aggregate，不能只看单 seed。
4. 如果某指标缺少数据，必须标记 `missing`，不能默认为 pass。
5. 如果存在 severe failure，`calibration_artifact_v1.pass_gate=false`。

### 3.4 建议伪代码

```python
def run_calibration(world_specs, target_bands, seeds):
    artifacts = []

    for world in world_specs:
        seed_metrics = []

        for seed in seeds:
            run_id = run_retail_only_world(
                world_spec=world,
                seed=seed,
                duration_days=CALIBRATION_DAYS,
                backend="postgresql_runtime",
            )

            metrics = extract_market_metrics(
                run_id=run_id,
                sources=[
                    "orders",
                    "trades",
                    "snapshots_1s",
                    "bars_1m",
                    "agent_bindings",
                    "account_equity_snapshots",
                ],
            )
            seed_metrics.append(metrics)

        aggregate = aggregate_metrics(seed_metrics)
        scorecard = compare_to_target_bands(aggregate, target_bands)

        artifact = CalibrationArtifactV1(
            world_hash=world.hash,
            seed_hashes=[hash_seed(s) for s in seeds],
            metrics=aggregate,
            target_bands=target_bands,
            score=scorecard.total_score,
            failed_metrics=scorecard.failed_metrics,
            pass_gate=scorecard.total_score <= CALIBRATION_THRESHOLD
                      and not scorecard.has_severe_failure,
        )

        persist_artifact(artifact)
        artifacts.append(artifact)

    return artifacts
```

### 3.5 验收条件

- 能为每个 `world_spec_v1` 生成 `calibration_artifact_v1`。
- artifact 有 `artifact_hash`、`world_hash`、`seed_hashes`、`runner_version`、`source_run_ids`。
- P0 指标齐全；缺失指标必须显示为 `missing`。
- `engineering_pass` 与 `research_pass` 分开记录。
- Series Evidence Aggregate 能读取并显示 calibration 的 failure reason。

---

## 4. Work Package B：Live Calibration Artifact Writer Hardening

### 4.1 目标

强化 `calibration_artifact_v1` writer，使其仅基于 PostgreSQL/runtime facts 写入 evidence package，并能解释 fail 的具体原因。

### 4.2 数据源要求

优先从以下 runtime/database facts 读取：

- orders
- trades
- order book snapshots 或 synthetic snapshots
- 1m bars
- agent bindings
- account/equity snapshots
- model transitions 只用于辅助，不作为市场事实主源

### 4.3 输出要求

`calibration_artifact_v1` 至少包含：

```json
{
  "artifact_type": "calibration_artifact_v1",
  "artifact_hash": "...",
  "source": "live_postgresql_runtime",
  "world_hash": "...",
  "seed_hashes": ["..."],
  "source_run_ids": ["..."],
  "metrics": {},
  "target_bands": {},
  "score": 0.0,
  "failed_metrics": [],
  "missing_metrics": [],
  "severity_counts": {},
  "engineering_pass": false,
  "research_pass": false,
  "pass_gate": false,
  "failure_type": "missing_metric|target_distance|severe_runtime_anomaly|none",
  "next_action": "..."
}
```

### 4.4 验收条件

- artifact 不依赖 injected summary。
- 缺失数据不会被静默忽略。
- fail 时 Evidence Board 能显示 `failed_metrics`、`missing_metrics`、`next_action`。

---

## 5. Work Package C：Exploit Probe Metrics Completion

### 5.1 目标

补齐 exploit runner 的六类关键 probe metrics，使 `exploit_test_artifact_v1` 能证明当前 runtime/reward/observation/fill/ledger 没有明显可交易漏洞。

### 5.2 必须补齐的 probes

| Probe | 必须证明 |
|---|---|
| `timestamp` | observation 中无未来价格、未来成交、未来排名、未来权益 |
| `mark_to_market` | 低流动性仓位不能被自推价格高估 |
| `order_boundary` | 无非法卖空、无超现金买入、无 T+1 违规、无越界订单 |
| `fee_accounting` | 买卖、部分成交、撤单、拒单后的费用和冻结释放可对账 |
| `fill_rule` | 订单不能无对手方成交，成交价、队列优先级、TIF 行为一致 |
| `clock_boundary` | 非交易阶段不能成交，bar/time boundary 不能泄漏未来信息 |

### 5.3 输出要求

`exploit_test_artifact_v1` 至少包含：

```json
{
  "artifact_type": "exploit_test_artifact_v1",
  "artifact_hash": "...",
  "candidate_id": "...",
  "probe_metrics": {
    "timestamp": {"status": "pass|fail|missing", "severity": "none|warning|severe"},
    "mark_to_market": {"status": "pass|fail|missing", "severity": "none|warning|severe"},
    "order_boundary": {"status": "pass|fail|missing", "severity": "none|warning|severe"},
    "fee_accounting": {"status": "pass|fail|missing", "severity": "none|warning|severe"},
    "fill_rule": {"status": "pass|fail|missing", "severity": "none|warning|severe"},
    "clock_boundary": {"status": "pass|fail|missing", "severity": "none|warning|severe"}
  },
  "severe_flags": [],
  "missing_metrics": [],
  "source_run_ids": [],
  "pass_gate": false,
  "failure_type": "missing_metric|severe_flag|none",
  "next_action": "..."
}
```

### 5.4 建议伪代码

```python
def run_exploit_tests(candidate, probe_worlds):
    probe_results = {}

    probe_results["timestamp"] = probe_timestamp_no_future(candidate, probe_worlds)
    probe_results["mark_to_market"] = probe_conservative_mtm(candidate, probe_worlds)
    probe_results["order_boundary"] = probe_invalid_order_rejection(candidate, probe_worlds)
    probe_results["fee_accounting"] = probe_fee_ledger_reconciliation(candidate, probe_worlds)
    probe_results["fill_rule"] = probe_fill_requires_valid_counterparty(candidate, probe_worlds)
    probe_results["clock_boundary"] = probe_clock_and_phase_boundaries(candidate, probe_worlds)

    severe_flags = [
        name for name, result in probe_results.items()
        if result.status == "fail" and result.severity == "severe"
    ]

    missing_metrics = [
        name for name, result in probe_results.items()
        if result.status in ("missing", "not_available")
    ]

    return ExploitTestArtifactV1(
        candidate_id=candidate.id,
        probe_metrics=probe_results,
        severe_flags=severe_flags,
        missing_metrics=missing_metrics,
        pass_gate=len(severe_flags) == 0 and len(missing_metrics) == 0,
    )
```

### 5.5 验收条件

- 六类 probe 全部有 status。
- 任何 missing probe 都导致 `pass_gate=false`。
- 任何 severe flag 都导致 `pass_gate=false`。
- Evidence Board 能显示 probe-level failure reason。

---

## 6. Work Package D：Paired Sensitivity Runner Hardening

### 6.1 目标

实现或强化费用、冲击、流动性反事实成对压力测试，证明策略不是靠低费用、低冲击、过度流动性或撮合宽松性赚钱。

### 6.2 必跑场景

同一 candidate、同一 seed、同一 base world，只改变一个环境维度：

```text
base
high_fee
high_impact
low_liquidity
```

### 6.3 比较对象

每组都必须同场跑：

- candidate
- TWAP
- VWAP
- AC-lite

### 6.4 记录指标

至少记录：

- gross PnL
- net PnL / net return
- fee drag
- impact cost
- slippage
- turnover
- unfilled ratio
- max drawdown
- inventory risk
- delta vs base

### 6.5 通过逻辑

策略可以变差，但必须解释得通：

- 高费用下收益下降合理。
- 高冲击下换手应收敛或成本上升可解释。
- 低流动性下成交率下降合理。
- 如果只在低费用/无冲击/高流动性世界赚钱，应 fail。

### 6.6 建议伪代码

```python
def run_paired_sensitivity(candidate, base_worlds):
    scenarios = [
        "base",
        "high_fee",
        "high_impact",
        "low_liquidity",
    ]

    paired_results = []

    for base_world in base_worlds:
        for scenario in scenarios:
            world = clone_world_with_single_change(
                base_world=base_world,
                scenario=scenario,
            )

            result = evaluate_frozen_policy(candidate, world)
            baselines = run_baselines(world, names=["twap", "vwap", "ac_lite"])

            paired_results.append({
                "base_world_hash": base_world.hash,
                "scenario": scenario,
                "candidate": result,
                "baselines": baselines,
                "delta_vs_base": compute_delta(result, reference="base"),
            })

    summary = summarize_sensitivity(paired_results)

    return PairedSensitivityArtifactV1(
        candidate_id=candidate.id,
        paired_results=paired_results,
        pass_gate=summary.no_catastrophic_collapse
                  and summary.fee_sensitivity_explainable
                  and summary.impact_sensitivity_explainable
                  and summary.low_liquidity_behavior_reasonable,
    )
```

### 6.7 验收条件

- 每个 base world 都能生成 4 个 paired scenario。
- 每个 scenario 都与 TWAP/VWAP/AC-lite 成对比较。
- Artifact 输出 `scenario_results`、`delta_vs_base`、`failure_type`、`next_action`。
- 如果 runner 无法构造某个 scenario，必须显示 `missing`，不能 pass。

---

## 7. Work Package E：Hidden Evaluation Candidate Upgrade

### 7.1 目标

强化 hidden evaluation，使其能公正评估 frozen candidate 是否在隐藏世界打败强基线。当前静态候选未打败 TWAP/VWAP/AC-lite，这是有效反馈，不应降低基线或手工放行。

### 7.2 候选要求

优先候选：

1. frozen `ppo_lstm_v1` Alpha-to-Execution candidate；或
2. 一个规则 execution candidate，用于验证 hidden runner 与比较逻辑。

要求：

- candidate checkpoint 必须 frozen。
- hidden worlds/seeds 必须来自训练外。
- hidden worlds 不能被 PBT、validation、manual tuning 用过。
- candidate、TWAP、VWAP、AC-lite 必须在同一 hidden world、同一 seed、同一流动性路径、同一费用模型下比较。

### 7.3 评价指标

不要只看最终 PnL。至少包含：

- net return
- execution shortfall
- turnover
- fee drag
- max drawdown
- inventory risk
- unfilled ratio
- win rate vs baselines

如果任务是 Alpha-to-Execution，reward 和评价应相对：

- arrival price
- TWAP
- VWAP
- AC-lite

### 7.4 建议通过条件

初版建议：

```text
pass_gate =
  win_rate_vs_baselines >= 0.67
  and no_risk_budget_breach
  and sample_size >= MIN_HIDDEN_WORLDS
```

更严格阶段再要求优于 3/3 强基线。

### 7.5 建议伪代码

```python
def run_hidden_eval(candidate, hidden_worlds, baselines):
    results = []

    for world in hidden_worlds:
        assert world.split == "hidden"
        assert world.hash not in candidate.training_world_hashes

        candidate_result = evaluate_frozen_policy(candidate, world)

        baseline_results = {
            b.name: evaluate_frozen_policy(b, world)
            for b in baselines
        }

        paired = paired_compare(
            candidate=candidate_result,
            baselines=baseline_results,
            metrics=[
                "net_return",
                "execution_shortfall",
                "fee_drag",
                "turnover",
                "max_drawdown",
                "inventory_risk",
                "unfilled_ratio",
            ],
        )

        results.append(paired)

    summary = aggregate_hidden_results(results)

    return HiddenEvalArtifactV1(
        candidate_id=candidate.id,
        hidden_world_hashes=[w.hash for w in hidden_worlds],
        baseline_names=[b.name for b in baselines],
        paired_results=results,
        pass_gate=summary.win_rate_vs_baselines >= 0.67
                  and summary.no_risk_budget_breach
                  and summary.sample_size >= MIN_HIDDEN_WORLDS,
    )
```

### 7.6 验收条件

- Hidden eval 必须能解释 fail：`underperform_baseline`、`risk_budget_breach`、`sample_size_too_small`、`split_contamination` 等。
- 不得把 hidden fail 视为工程失败；如果候选确实打不过强基线，应保留 fail。
- Evidence Board 显示候选相对每个 baseline 的 paired metrics。

---

## 8. Work Package F：Evidence Aggregate Strict Recompute

### 8.1 目标

Series Evidence Aggregate 不信任手工 status，只从 artifact hash、artifact source、runner version 和 `pass_gate` 重新计算状态。

### 8.2 实现要求

Aggregate 每个 evidence 的 status 必须来自：

- artifact 是否存在；
- artifact 是否来自 live runtime source；
- artifact schema 是否 valid；
- artifact hash 是否可复算；
- artifact 的 `pass_gate` 是否 true；
- 是否存在 missing/not_available/injected_only/manual_override。

### 8.3 输出要求

每个 evidence 在 aggregate 中至少显示：

```json
{
  "evidence_name": "calibration",
  "status": "pass|fail|missing|not_available",
  "failure_type": "missing_metric|underperform_baseline|severe_flag|upstream_blocked|none",
  "blocking_metrics": [],
  "next_action": "...",
  "artifact_hash": "...",
  "runner_version": "...",
  "source_run_ids": [],
  "source": "live_postgresql_runtime|injected_summary|manual"
}
```

### 8.4 验收条件

- 手工修改 status 不影响 aggregate 结果。
- 缺 artifact 或 artifact hash 无法验证时 status 必须 fail/missing。
- injected-only artifact 不得 research pass。
- Aggregate 和 Evidence Board 读回一致。

---

## 9. Work Package G：Strict Parent Gate v2 Recompute-Only

### 9.1 目标

Strict Parent Gate v2 只读上游 artifacts，不读 leaderboard，不读人工 status，不读手工标记。上游 evidence 未通过时，strict parent gate 必须 fail。

### 9.2 必需上游证据

```text
baseline
calibration
hidden_eval
exploit_test
paired_sensitivity
```

所有上游均需 `pass_gate=true`，且 candidate 需要完整：

- lineage
- training world hash
- evaluation world hash
- reward hash
- code hash
- checkpoint hash

### 9.3 建议伪代码

```python
def strict_parent_gate_v2(candidate, evidence_bundle):
    required = [
        "baseline",
        "calibration",
        "hidden_eval",
        "exploit_test",
        "paired_sensitivity",
    ]

    blocking = [
        name for name in required
        if evidence_bundle[name].pass_gate is not True
    ]

    blocking += validate_lineage_and_hashes(candidate, evidence_bundle)

    pass_gate = (
        len(blocking) == 0
        and evidence_bundle["research_acceptance"].lock_status == "open"
        and evidence_bundle["research_acceptance"].blocking_sections == []
    )

    return ParentGateArtifactV2(
        candidate_id=candidate.id,
        required_artifact_hashes={
            name: evidence_bundle[name].artifact_hash
            for name in required
        },
        blocking_sections=blocking,
        pass_gate=pass_gate,
    )
```

### 9.4 验收条件

- 上游任一 fail/missing/not_available，parent gate 必须 fail。
- leaderboard 排名不能影响 parent gate pass。
- manual override 不能让 parent gate pass。
- gate artifact 必须列出 blocking sections。

---

## 10. Work Package H：Research Acceptance Lock Scoped Opening

### 10.1 目标

Research Acceptance Lock 只在完整上游 evidence pass 后打开，并且只打开到合适 claim level。当前不得直接打开 alpha/research claim。

### 10.2 Acceptance Level

实现或显式记录三级 acceptance：

```text
level_1_engineering_acceptance:
  live runtime package complete，baseline/calibration/exploit/paired/hidden 全 pass。

level_2_sim_research_acceptance:
  多 hidden world、多 seed、多 regime 上稳定击败强基线。

level_3_transfer_acceptance:
  replay/hybrid 或真实历史背景下仍不崩溃，并通过人工审计。
```

当前最多允许打开：

```text
level_1_engineering_acceptance
```

禁止在没有 replay/hybrid 或真实历史背景验证时打开 `level_3_transfer_acceptance`。

### 10.3 验收条件

- blocking sections 非空时 lock 必须 `locked`。
- artifact hash 与 live package hash 不一致时 lock 必须 `locked`。
- 有 `missing`、`not_available`、`manual_override`、`injected_only` 时 lock 必须 `locked`。
- hidden evaluation 被调参污染时 lock 必须 `locked`。
- lock 打开时必须写入 acceptance level、artifact hashes、source run ids。

---

## 11. Evidence Board 失败原因展示

### 11.1 目标

Evidence Board 不应只显示红灯/绿灯，而应显示失败原因与下一步动作。

### 11.2 每个 fail 至少显示

```json
{
  "status": "fail",
  "failure_type": "missing_metric|underperform_baseline|severe_flag|upstream_blocked",
  "blocking_metrics": [],
  "next_action": "...",
  "artifact_hash": "...",
  "runner_version": "...",
  "source_run_ids": []
}
```

### 11.3 建议 next_action 示例

- calibration: `Add target band or fix missing runtime metric source.`
- hidden_eval: `Candidate underperformed TWAP/VWAP/AC-lite; keep fail and improve candidate/reward/action space.`
- exploit_test: `Complete missing probe metrics: timestamp, mark-to-market, order-boundary, fee-accounting, fill-rule, clock-boundary.`
- paired_sensitivity: `Run base/high_fee/high_impact/low_liquidity paired worlds with same seed.`
- strict_parent_gate: `Upstream evidence still blocking; do not override.`
- research_acceptance_lock: `Blocking sections non-empty; keep locked.`

---

## 12. 最小完整 evidence package 判定逻辑

```python
def build_live_evidence_package(candidate_id, world_registry):
    candidate = load_frozen_candidate(candidate_id)

    calibration = run_calibration(
        world_specs=world_registry.validation_and_hidden_worlds,
        target_bands=load_target_bands(),
        seeds=world_registry.calibration_seeds,
    )

    baseline = run_baseline_suite(
        worlds=world_registry.validation_and_hidden_worlds,
        baselines=["twap", "vwap", "ac_lite"],
    )

    hidden = run_hidden_eval(
        candidate=candidate,
        hidden_worlds=world_registry.hidden_worlds,
        baselines=["twap", "vwap", "ac_lite"],
    )

    exploit = run_exploit_tests(
        candidate=candidate,
        probe_worlds=world_registry.probe_worlds,
    )

    paired = run_paired_sensitivity(
        candidate=candidate,
        base_worlds=world_registry.validation_worlds,
    )

    research_lock = compute_research_acceptance_lock(
        calibration=calibration,
        baseline=baseline,
        hidden=hidden,
        exploit=exploit,
        paired=paired,
    )

    parent_gate = strict_parent_gate_v2(
        candidate=candidate,
        evidence_bundle={
            "calibration": calibration,
            "baseline": baseline,
            "hidden_eval": hidden,
            "exploit_test": exploit,
            "paired_sensitivity": paired,
            "research_acceptance": research_lock,
        },
    )

    package = EvidencePackageV1(
        candidate_id=candidate.id,
        artifacts=[
            calibration,
            baseline,
            hidden,
            exploit,
            paired,
            parent_gate,
            research_lock,
        ],
    )

    package.status = "complete" if package.has_no_missing_artifacts() else "incomplete"
    package.go_no_go = "go" if package.all_artifacts_pass() else "no_go"

    persist_package(package)
    return package
```

---

## 13. 测试要求

Codex agent 应先检索现有测试结构，再添加或更新最小测试。不要盲目新建重复测试。

### 13.1 建议测试类别

1. `test_calibration_artifact_from_live_runtime_facts`
2. `test_calibration_missing_metric_fails_gate`
3. `test_exploit_artifact_requires_all_probe_metrics`
4. `test_exploit_severe_flag_fails_gate`
5. `test_paired_sensitivity_runs_base_high_fee_high_impact_low_liquidity`
6. `test_hidden_eval_requires_frozen_candidate_and_hidden_split`
7. `test_evidence_aggregate_recomputes_from_artifact_pass_gate`
8. `test_strict_parent_gate_blocks_when_upstream_fails`
9. `test_research_acceptance_lock_remains_locked_with_blocking_sections`
10. `test_evidence_board_includes_failure_type_next_action_and_source_run_ids`

### 13.2 建议运行命令

根据项目实际环境调整：

```bash
python -m py_compile app/services/*.py tests/runtime/*.py
pytest tests/runtime/test_arena_experiment_runner.py -q
pytest tests/runtime -q -k "evidence or calibration or exploit or paired or hidden or parent_gate or acceptance_lock"
```

若环境限制导致完整 pytest 无法运行，必须在任务结果中记录：

- 已运行的命令
- 通过的测试
- 未能运行的测试
- 阻塞原因
- 是否存在风险

---

## 14. 文档更新要求

完成后更新或新增：

- `docs/current-work-status/model-training.md`
- 对应 task 文档，例如：
  - `docs/tasks/model-training/calibration-target-bands-v0.md`
  - `docs/tasks/model-training/live-calibration-artifact-hardening.md`
  - `docs/tasks/model-training/exploit-probe-metrics-completion.md`
  - `docs/tasks/model-training/paired-sensitivity-runner-hardening.md`
  - `docs/tasks/model-training/hidden-eval-candidate-upgrade.md`
  - `docs/tasks/model-training/evidence-aggregate-strict-recompute.md`
  - `docs/tasks/model-training/strict-parent-gate-v2-recompute-only.md`
  - `docs/tasks/model-training/research-acceptance-lock-scoped-opening.md`

文档必须说明：

- 本轮做了什么。
- 明确未做什么。
- 哪些 fail 是上游真实 fail。
- 哪些 fail 是派生 fail。
- 当前 `go_no_go` 是否仍为 `no_go`。
- 如果仍是 `no_go`，为什么这是正确状态。

---

## 15. 最终交付物

Codex agent 完成后应输出：

1. 代码改动摘要。
2. 新增/更新 artifact schema 摘要。
3. Evidence 状态表：baseline、calibration、hidden_eval、exploit_test、paired_sensitivity、strict_parent_gate、research_acceptance_lock。
4. 每个 fail 的 `failure_type`、`blocking_metrics`、`next_action`。
5. 测试命令与结果。
6. 明确说明是否仍为 `no_go`。
7. 若变为 `go`，必须说明是哪个 acceptance level，不得越级声明真实市场迁移有效。

---

## 16. 最重要的执行原则

当前 6 个 fail 是资产，不是瑕疵。它们说明 Evidence Gate 已经开始发挥作用。下一步应让 artifact 变硬，而不是让 gate 变软。

正确目标是：

```text
先让 calibration 和 exploit pass，
再让 paired sensitivity pass，
最后才追 hidden evaluation pass。

strict parent gate 和 research acceptance lock 只能作为上游证据的派生结果，不能手动放行。
```

当前项目最大的进步是：No-Go 已经从“工程没跑通”升级成“研究证据未满足”。这正是严肃量化研究平台应该达到的状态。
