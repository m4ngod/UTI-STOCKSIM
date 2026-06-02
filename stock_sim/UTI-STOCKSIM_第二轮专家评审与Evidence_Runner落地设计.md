# UTI-STOCKSIM 第二轮专家评审与 Evidence Runner 落地设计


从“可审计记录”推进到“可运行证据”的下一阶段方案

生成日期：2026-05-04

## 0. 执行摘要

你这轮改进是方向正确的。项目已经从“能跑训练闭环”推进到“实验结果可审计、可聚合、可复现”的阶段：reward/world/code hash、metadata schema、contract versions、world-card、record-kind detail、transition evidence、lineage evidence、baseline/benchmark/hidden/exploit summary、research acceptance lock、strict parent gate diagnostics 和 series aggregate 都已经进入 Arena 报告体系。这个阶段的价值很高，因为它把未来的模型收益从“看起来赚了”改造成“可以解释是在什么代码、什么世界、什么奖励、什么模型 lineage、什么评估边界下赚的”。

但我的第二轮判断也更明确：下一阶段不能继续主要扩展 completeness 字段。现在最关键的问题已经不是“报告里是否知道某个字段 present / missing / not_available”，而是“是否真的有独立 runner 生成 calibration、hidden evaluation、exploit test、fee/impact sensitivity 等证据”。也就是说，项目应当从 Metadata Completeness Phase 切换到 Evidence Runner Phase。

如果继续横向增加 field_status，项目会进入一种危险状态：实验记录越来越完整，但市场有效性证据仍然缺席。这个风险比第一轮更突出，因为你已经把可审计框架搭出来了，此时再不补证据生成器，工程进度会显得很快，但模型有效性判断仍会停在 not_available。

本文件建议下一阶段 P0 目标为：

1. 定义 separate calibration / hidden evaluation / exploit test / paired fee-impact artifacts 的正式 schema 和 ownership。
2. 实现 WorldSpec canonical hash 与真实 RandomSeedLedger。
3. 实现 Calibration Harness v0，用 stylized facts 和微观结构指标给 world 打分。
4. 实现 Baseline Runner v0，把 TWAP、VWAP、AC-lite 从 not_available 变成真实可跑基线。
5. 实现 Hidden-World Runner v0，只评估 frozen checkpoint，不训练、不 PBT、不更新策略。
6. 实现 Paired Fee/Impact Sensitivity Runner v0，用成对世界识别费用、冲击、成交规则依赖。
7. 把 strict parent gate 升级为 evidence-gated parent eligibility：没有独立证据，不允许成为父代，不允许自动晋升，不允许做研究结论。

## 1. 当前进度评价

### 1.1 做得好的地方

第一，你没有盲目上更复杂模型，而是优先把 Arena report、identity、hash、lineage、world-card、record-kind 和 acceptance lock 做成可审计体系。这对量化研究非常重要，因为交易模型失败往往不是因为神经网络不够复杂，而是因为实验边界不清、数据泄漏、参数选择过拟合、评估场景被训练污染。

第二，你保留了 Alpha-to-Execution 的方向，没有急着把项目变成“仿真市场内方向性 alpha 猜涨跌”。这很关键。执行、库存、成交质量、滑点和费用控制比纯方向预测更适合从高保真仿真中学习。

第三，你明确保留了 not_available 边界。很多项目会把缺失评估伪装成通过评估，你现在的做法反而更可信：hidden-world runner、calibration harness、paired-world fee/impact runner、separate artifacts 没做就是没做。

第四，严格 PBT 父代资格门控和 research acceptance lock 是正确方向。PBT 可以提高训练效率，但它也会放大选择偏差；如果没有父代资格门控，它会把“偶然在某个仿真世界赚钱”的模型快速扩散到整个种群。

### 1.2 当前最大短板

最大短板不是模型，而是证据生成能力仍缺席。当前 Task 77-81 完成的是 record-kind detail completeness status 的增强，本身没有改变训练、执行、奖励、账户、PBT 父代选择或 checkpoint 行为，也没有新增 separate calibration/hidden/exploit artifacts。

因此，当前系统已经很会记录“什么还没有”，但还没有真正开始回答以下问题：

- 这个 world 是否像目标市场？
- 模型是否只在训练 world 有效？
- 模型是否利用 no-signal 或时钟、账户、mark-to-market、费用边界漏洞？
- 模型收益是否对费用、滑点、成交概率、延迟、冲击成本高度脆弱？
- 模型是否真的打败强基线，而不是打败随机或弱规则？
- PBT 胜者是否能在 hidden worlds 和 exploit tests 中保持优势？

### 1.3 第二轮结论

项目比第一轮更有前景，因为你已经补上了“研究治理层”。但下一阶段如果不切换到证据生成，项目会停留在“审计平台”而不是“有效策略研究平台”。

我的建议是：从 Task 82 开始，停止继续横向扩展 completeness metadata，除非是修 bug 或补严重要害字段；新增工作应优先服务于独立 artifact 的生成、校验和 gate 接入。

## 2. 项目是否仍有前景

有前景，而且前景更清晰。现在的合理定位是：

UTI-STOCKSIM 是一个交易仿真与模型研究平台，用高保真 runtime、行为 agent、正式 contract、可复现实验记录、隐藏评估和漏洞检测，筛选可能具备真实迁移潜力的执行 / 风控 / 做市 / 仓位控制模型。

但仍不建议把近期目标定为“纯仿真训练出可实盘 alpha”。方向性 alpha 必须接入真实历史数据、订单流 replay、外部因子或真实统计目标。你的平台在近期最该验证的是：

1. 给定目标仓位，模型能否比 TWAP/VWAP/AC-lite 更好地执行。
2. 给定风险预算，模型能否控制库存、成交质量和回撤。
3. 给定多种流动性和费用场景，模型能否稳定保持行为合理。
4. 在隐藏世界里，模型是否仍然相对强基线有优势。

如果这四件事成立，项目就已经具备研究价值和工程价值。

## 3. 下一阶段总架构：Evidence Runner Stack

建议新增一个 Evidence Runner Stack。它不是一个大模型模块，而是一组独立、可复用、可被 Arena 调用的评估 runner 和 artifact writer。

```text
Arena Series
  ├─ Training Runner
  ├─ Baseline Runner
  ├─ Calibration Runner
  ├─ Hidden-World Runner
  ├─ Paired Fee/Impact Runner
  ├─ Exploit Test Runner
  └─ Evidence Gate Aggregator
          ├─ artifact hashes
          ├─ pass/fail flags
          ├─ metrics
          ├─ missing/not_available boundary
          └─ parent eligibility decision
```

核心原则：训练 runner 负责产生策略；evidence runners 负责证明策略没有明显作弊、没有只适配单一世界、没有只靠费用/冲击漏洞盈利。

## 4. Separate Artifact 边界设计

当前 embedded sections 可以继续保留，但它们不应替代 separate artifacts。Separate artifacts 的作用是让不同证据有独立 schema、独立 hash、独立 runner ownership 和独立生命周期。

### 4.1 建议 artifact 类型

| Artifact | 目的 | 最低通过条件 |
|---|---|---|
| calibration_artifact_v1 | 证明 world 与目标市场 profile 的统计距离可接受 | calibration_score 存在且 critical metrics 未越界 |
| baseline_artifact_v1 | 证明所有基线通过相同 runtime/contract 跑出结果 | HOLD/NOOP、target_weight、TWAP、VWAP、AC-lite 至少可运行 |
| hidden_eval_artifact_v1 | 证明 frozen checkpoint 在隐藏世界仍有效 | 相对强基线有优势，且风险未越界 |
| exploit_test_artifact_v1 | 证明模型没有利用明显漏洞 | no-signal、timestamp、MTM、order anomaly、action boundary 均通过 |
| paired_sensitivity_artifact_v1 | 证明收益不是费用/冲击/fill 规则的单点产物 | 高费/高冲击/延迟扰动下退化可解释、不崩溃 |
| parent_gate_artifact_v2 | 聚合以上证据并决定父代资格 | 所有 required evidence 通过 |

### 4.2 Artifact 基础字段

每个 artifact 至少包含：

- artifact_id
- artifact_kind
- artifact_schema_version
- created_at
- runner_name
- runner_version
- code_identity_hash
- sim_version_identity
- world_id
- world_hash
- reward_hash 或 reward_not_applicable
- contract_versions
- random_seed_ledger_hash
- dependencies
- metrics
- pass_fail
- failure_reasons
- artifact_hash

## 5. WorldSpec 与 RandomSeedLedger

World-card metadata 现在已经进入报告体系，但下一步要把它升级成可 hash、可复现、可 split 的 WorldSpec。

### 5.1 WorldSpec 建议字段

```python
WorldSpec = {
    "schema": "world_spec_v1",
    "world_name": "cn_equity_execution_visible_v1",
    "split": "train|validation|hidden|exploit",
    "universe": {"symbols": [...], "selection_rule": "..."},
    "clock": {"session": "09:30-11:30,13:00-15:00", "bar_seconds": 60},
    "market_rules": {"t_plus_1": True, "short_sell": False, "price_limit": "..."},
    "fee_model": {"commission_bps": 2.5, "min_fee": 5.0, "stamp_tax_bps": 5.0},
    "impact_model": {"temporary": "linear", "permanent": "off|linear", "params": {...}},
    "fill_model": {"queue_model": "price_time", "latency_ms": {...}},
    "retail_mix": {"mean_reversion": 0.25, "dip_buyer": 0.25, "noise": 0.30, "profit_taker": 0.20},
    "liquidity_seed_ref": "seed:liquidity:...",
    "calibration_target_profile": "cn_a_share_microstructure_v0",
    "scenario_family": "normal|low_liquidity|shock|no_signal|fee_stress"
}
```

### 5.2 SeedLedger 设计

不要只记录 random_seed_status。需要真实 seed identity：

```python
def derive_seed(master_seed: int, *labels: str) -> int:
    payload = str(master_seed) + "|" + "|".join(labels)
    return int(sha256(payload.encode()).hexdigest()[:16], 16) % (2**31 - 1)

SeedLedger = {
    "schema": "random_seed_ledger_v1",
    "master_seed": 20260504,
    "seed_method": "sha256_label_derivation_v1",
    "seeds": {
        "retail_population": derive_seed(master, "retail_population"),
        "liquidity_noise": derive_seed(master, "liquidity_noise"),
        "model_initialization": derive_seed(master, "model_initialization"),
        "episode_sampling": derive_seed(master, "episode_sampling"),
        "hidden_world_selection": derive_seed(master, "hidden_world_selection")
    }
}
```

## 6. Calibration Harness v0

Calibration Harness 是下一阶段最重要的模块。没有 calibration score，hidden evaluation 也会变弱，因为 hidden world 可能只是另一个任意合成世界。

### 6.1 指标分层

| 层级 | 指标 | 作用 |
|---|---|---|
| Price stylized facts | return volatility、kurtosis、skew、return autocorr、squared return autocorr、volatility clustering | 判断价格序列是否像真实市场 |
| Microstructure | spread mean/P90、depth、order imbalance、cancel rate、fill probability by price offset、trade-through anomaly | 判断订单簿和成交是否可信 |
| Liquidity | turnover、volume curve、active agent count、market/limit order ratio、empty-book ratio | 判断市场是否有足够流动性 |
| Behavior | holding period、buy/sell ratio、concentration、retail family contribution | 判断 retail 生态是否合理 |
| Rule consistency | T+1 rejection、short-sell rejection、fee ledger consistency、frozen cash/position release | 判断交易语义是否稳定 |

### 6.2 Score 计算建议

```python
def normalized_distance(sim_value, target_mean, target_scale, cap=5.0):
    if target_scale <= 0:
        return 0.0 if abs(sim_value - target_mean) < 1e-12 else cap
    return min(abs(sim_value - target_mean) / target_scale, cap)


def compute_calibration_score(sim_metrics, target_profile, weights):
    parts = {}
    for name, weight in weights.items():
        target = target_profile[name]
        d = normalized_distance(
            sim_metrics[name],
            target["mean"],
            target.get("scale", target.get("std", 1.0)),
            cap=target.get("cap", 5.0),
        )
        parts[name] = {"distance": d, "weight": weight, "weighted": d * weight}
    total = sum(x["weighted"] for x in parts.values()) / max(sum(weights.values()), 1e-12)
    critical_failures = [
        name for name, item in parts.items()
        if item["distance"] > target_profile[name].get("critical_max_distance", 3.0)
    ]
    return {
        "score": total,
        "parts": parts,
        "pass": total <= 1.0 and not critical_failures,
        "critical_failures": critical_failures,
    }
```

### 6.3 Calibration Runner 伪代码

```python
def run_calibration(world_spec, target_profile, seed_ledger):
    world = build_world(world_spec, seed_ledger)
    result = run_retail_only_or_background_episode(world)

    raw = collect_runtime_facts(
        orders=result.orders,
        trades=result.trades,
        snapshots=result.snapshots,
        accounts=result.accounts,
        bars=result.bars,
    )
    sim_metrics = compute_market_metrics(raw)
    score = compute_calibration_score(
        sim_metrics=sim_metrics,
        target_profile=target_profile,
        weights=target_profile["weights"],
    )
    artifact = CalibrationArtifactV1(
        world_id=world_spec.world_id,
        target_profile_id=target_profile.id,
        metrics=sim_metrics,
        score=score,
        pass_fail=score["pass"],
        failure_reasons=score["critical_failures"],
    )
    persist_artifact(artifact)
    return artifact
```

## 7. Baseline Runner v0

基线必须走同一套 Observation/Action/Reward contract 和 runtime truth，不能绕过账户、订单、撮合、费用、T+1。

### 7.1 最低基线组合

1. HOLD/NOOP：不交易，检验市场自身漂移。
2. random_valid_order_v1：随机但合法动作，检验 reward 是否鼓励乱动。
3. target_weight_naive_rebalance_v1：已有基线，继续保留。
4. TWAP execution v1：等时间切片执行目标交易。
5. VWAP execution v1：按成交量曲线或目标 volume profile 执行。
6. AC-lite execution v1：使用简化 Almgren-Chriss 风格风险/成本权衡。
7. rule_market_maker_v1：如果做市任务进入 P1，再加入。

### 7.2 TWAP/VWAP 伪代码

```python
class TWAPPolicy:
    def __init__(self, target_qty, start_step, end_step):
        self.target_qty = target_qty
        self.steps = max(end_step - start_step + 1, 1)
        self.slice_qty = target_qty / self.steps

    def act(self, obs):
        remaining = self.target_qty - obs.executed_qty
        if remaining <= 0:
            return Hold()
        qty = min(abs(self.slice_qty), abs(remaining)) * sign(remaining)
        return SubmitOrder(side=side_from_qty(qty), qty=abs(qty), style="limit_or_marketable")


class VWAPPolicy:
    def __init__(self, target_qty, volume_curve):
        self.target_qty = target_qty
        self.volume_curve = normalize(volume_curve)

    def act(self, obs):
        desired_cum = self.target_qty * self.volume_curve.cumulative_at(obs.step)
        shortfall = desired_cum - obs.executed_qty
        if abs(shortfall) < obs.min_lot:
            return Hold()
        return SubmitOrder(side=side_from_qty(shortfall), qty=round_lot(abs(shortfall)))
```

### 7.3 AC-lite 伪代码

```python
def ac_lite_schedule(target_qty, horizon, sigma, eta, risk_aversion):
    # eta: temporary impact proxy; sigma: volatility proxy
    # kappa 越大，越前置交易；低流动性或高冲击时更慢，高风险时更快。
    kappa = sqrt(max(risk_aversion * sigma * sigma / max(eta, 1e-9), 1e-12))
    times = [i / horizon for i in range(horizon + 1)]
    holdings = []
    for t in times:
        numerator = sinh(kappa * (1 - t))
        denominator = max(sinh(kappa), 1e-9)
        holdings.append(target_qty * numerator / denominator)
    trades = [holdings[i] - holdings[i + 1] for i in range(horizon)]
    return trades
```

## 8. Hidden-World Runner v0

Hidden-world runner 的核心纪律是：只评估 frozen checkpoint，不更新策略、不参与 PBT、不调 reward、不改超参。

```python
def run_hidden_eval(checkpoint, hidden_world_specs, baseline_policies, seed_ledger):
    results = []
    frozen_policy = load_policy(checkpoint, train_mode=False)

    for spec in hidden_world_specs:
        assert spec.split == "hidden"
        world = build_world(spec, seed_ledger.for_world(spec.world_id))

        model_result = evaluate_policy_once(world, frozen_policy, allow_learning=False)
        baseline_results = {}
        for baseline in baseline_policies:
            world_clone = rebuild_same_world(spec, seed_ledger.for_world(spec.world_id))
            baseline_results[baseline.name] = evaluate_policy_once(
                world_clone, baseline, allow_learning=False
            )

        comparison = compare_to_baselines(model_result, baseline_results)
        results.append({
            "world_id": spec.world_id,
            "model": model_result.metrics,
            "baselines": {k: v.metrics for k, v in baseline_results.items()},
            "comparison": comparison,
        })

    artifact = HiddenEvalArtifactV1(
        checkpoint_hash=checkpoint.hash,
        results=results,
        pass_fail=hidden_eval_pass(results),
        failure_reasons=hidden_eval_failures(results),
    )
    persist_artifact(artifact)
    return artifact
```

建议 hidden pass 条件采用相对标准，而不是只看绝对收益：

- 在至少 60% hidden worlds 中优于 baseline median。
- 在至少 40% hidden worlds 中优于 strongest execution baseline。
- 最大回撤、换手、费用占收益比例不越界。
- no-signal hidden world 中不能产生显著正 alpha。
- 收益退化曲线不能只在一个 seed 上成立。

## 9. Paired Fee/Impact Sensitivity Runner v0

Paired runner 的目的不是要求模型在高费用下仍然赚钱，而是识别“模型是否只靠低费用/乐观成交规则赚钱”。

```python
def run_paired_sensitivity(checkpoint, base_world_spec, perturbations, seed_ledger):
    base_world = build_world(base_world_spec, seed_ledger.for_world(base_world_spec.world_id))
    base_result = evaluate_policy_once(base_world, load_policy(checkpoint), allow_learning=False)

    paired = []
    for p in perturbations:
        stressed_spec = apply_perturbation(base_world_spec, p)
        stressed_world = build_world(stressed_spec, seed_ledger.for_world(base_world_spec.world_id))
        stressed_result = evaluate_policy_once(stressed_world, load_policy(checkpoint), allow_learning=False)
        paired.append({
            "perturbation": p,
            "base_metrics": base_result.metrics,
            "stressed_metrics": stressed_result.metrics,
            "delta": metric_delta(base_result.metrics, stressed_result.metrics),
        })

    artifact = PairedSensitivityArtifactV1(
        checkpoint_hash=checkpoint.hash,
        base_world_id=base_world_spec.world_id,
        paired_results=paired,
        pass_fail=sensitivity_pass(paired),
        failure_reasons=sensitivity_failures(paired),
    )
    persist_artifact(artifact)
    return artifact
```

推荐扰动：

- commission_bps × 2
- temporary impact × 2
- fill latency + 1 to 3 ticks
- queue priority worse by one level
- spread widening regime
- low-liquidity regime
- partial fill probability lower by 20%

## 10. Exploit Test Runner v0

Exploit tests 是防止模型学到模拟器漏洞的核心。

### 10.1 必做 exploit tests

| 测试 | 目标 | 失败信号 |
|---|---|---|
| no_signal_world | 无方向信号世界中不应稳定盈利 | 多 seed 显著正收益或高 Sharpe |
| timestamp_leakage | observation 不应含未来时间或未来 bar | action 与未来收益异常相关 |
| mark_to_market_leakage | MTM 不应提前反映未来成交或价格 | 决策前权益变化异常 |
| order_boundary | 非法动作不能变成有利成交 | 拒单/截断产生正 reward |
| fee_accounting | 费用不能漏扣或重复释放冻结 | PnL 与账本不一致 |
| fill_rule_exploit | 模型不能通过微小订单刷 fill 或 reward | 高频小单、撤单、无风险正 reward |
| clock_boundary | 午休、开收盘、T+1 边界不能套利 | 边界时段收益集中异常 |

### 10.2 Exploit Runner 伪代码

```python
def run_exploit_tests(checkpoint, exploit_world_specs, probes):
    failures = []
    details = []
    policy = load_policy(checkpoint, train_mode=False)

    for spec in exploit_world_specs:
        world = build_world(spec, seed_ledger_for(spec))
        result = evaluate_policy_once(world, policy, allow_learning=False)
        audit = run_runtime_audits(result)
        probe_results = [probe(result) for probe in probes]

        details.append({
            "world_id": spec.world_id,
            "metrics": result.metrics,
            "audit": audit,
            "probe_results": probe_results,
        })
        failures.extend(extract_failures(audit, probe_results))

    artifact = ExploitTestArtifactV1(
        checkpoint_hash=checkpoint.hash,
        details=details,
        pass_fail=(len(failures) == 0),
        failure_reasons=failures,
    )
    persist_artifact(artifact)
    return artifact
```

## 11. Strict Parent Gate v2

当前 strict parent gate 已经有 diagnostics 和 aggregate。下一步要从“报告层 gate”升级为“证据层 gate”。

```python
def strict_parent_gate_v2(candidate):
    required = {
        "experiment_record_completeness": candidate.record_completeness.critical_pass,
        "checkpoint_hash": candidate.checkpoint_hash is not None,
        "lineage_evidence": candidate.lineage_evidence.pass_fail,
        "baseline_artifact": candidate.baseline_artifact.pass_fail,
        "calibration_artifact": candidate.world.calibration_artifact.pass_fail,
        "hidden_eval_artifact": candidate.hidden_eval_artifact.pass_fail,
        "exploit_test_artifact": candidate.exploit_test_artifact.pass_fail,
        "paired_sensitivity_artifact": candidate.paired_sensitivity_artifact.pass_fail,
    }
    failure_reasons = [k for k, ok in required.items() if not ok]

    return ParentGateArtifactV2(
        candidate_id=candidate.id,
        eligible_for_pbt_parent=(len(failure_reasons) == 0),
        eligible_for_checkpoint_promotion=(len(failure_reasons) == 0 and candidate.hidden_rank_ok),
        eligible_for_research_claim=(len(failure_reasons) == 0 and candidate.statistical_confidence_ok),
        failure_reasons=failure_reasons,
        evidence_hashes=candidate.collect_evidence_hashes(),
    )
```

### 11.1 三种资格必须分开

- eligible_for_pbt_parent：是否能被失败者继承。
- eligible_for_checkpoint_promotion：是否能进入 Hall-of-Fame 或默认模型池。
- eligible_for_research_claim：是否能被写进研究结论。

这三者不能混用。一个模型可以被允许继续训练，但不允许晋升；也可以作为候选进入下一轮，但不能作为研究结论。

## 12. 数据库与持久化建议

建议不要为每个 artifact 都建一堆高度定制表。初期可用通用 artifact 表 + JSONB metrics，同时保留核心索引字段。

```sql
CREATE TABLE arena_artifact (
    artifact_id TEXT PRIMARY KEY,
    artifact_kind TEXT NOT NULL,
    artifact_schema_version TEXT NOT NULL,
    runner_name TEXT NOT NULL,
    runner_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    world_id TEXT,
    checkpoint_hash TEXT,
    code_identity_hash TEXT,
    sim_version_identity TEXT,
    random_seed_ledger_hash TEXT,
    pass_fail BOOLEAN,
    failure_reasons JSONB NOT NULL DEFAULT '[]',
    metrics JSONB NOT NULL DEFAULT '{}',
    dependencies JSONB NOT NULL DEFAULT '[]',
    artifact_hash TEXT NOT NULL
);

CREATE INDEX idx_arena_artifact_kind ON arena_artifact(artifact_kind);
CREATE INDEX idx_arena_artifact_world ON arena_artifact(world_id);
CREATE INDEX idx_arena_artifact_checkpoint ON arena_artifact(checkpoint_hash);
```

## 13. 建议从 Task 82 开始的任务拆分

| Task | 名称 | 交付物 |
|---|---|---|
| 82 | Evidence Runner Phase Charter | 冻结 completeness 横向扩展，定义证据优先原则 |
| 83 | Separate Artifact Schemas v1 | calibration/hidden/exploit/paired/baseline/parent gate schema |
| 84 | WorldSpec Canonical Hash | world_spec_v1、canonical_json、world_hash 测试 |
| 85 | RandomSeedLedger v1 | master seed、derived seeds、seed hash、缺失 seed 禁止通过 |
| 86 | Market Metrics Extractor v0 | 从 orders/trades/snapshots/bars/accounts 提取指标 |
| 87 | Calibration Scorecard v0 | target profile、distance、critical metric、pass/fail |
| 88 | Calibration Artifact Writer | 生成 separate calibration_artifact_v1 |
| 89 | Unified Baseline Runner | 所有 baseline 走同一 runtime/contract |
| 90 | TWAP/VWAP Baselines | 把 not_available 改成可运行结果 |
| 91 | AC-lite Baseline | 简化风险/成本执行基线 |
| 92 | Hidden World Registry | visible/validation/hidden/exploit split registry |
| 93 | Hidden-World Runner v0 | frozen checkpoint 评估，不训练不 PBT |
| 94 | Paired Fee/Impact Runner v0 | 成对世界费用/冲击/延迟敏感性 |
| 95 | Exploit Test Runner v0 | no-signal、timestamp、MTM、order boundary、fee audit |
| 96 | Strict Parent Gate v2 | evidence-gated parent eligibility |
| 97 | Research Acceptance Lock v2 | 研究结论必须依赖 required evidence |
| 98 | Series Evidence Aggregate | series 级 evidence pass/fail、missing、not_available 聚合 |
| 99 | GUI Evidence Board | Arena 面板显示证据状态，不只显示收益排名 |
| 100 | Evidence Contract Tests | schema/hash/seed/reproducibility/runner no-learning 测试 |
| 101 | Long Arena Dry Run | 运行多代 series，输出完整 evidence package |

## 14. 4 周落地节奏

### Week 1：Schema 与 identity

- 完成 Task 82-85。
- 所有 artifact schema 文档化。
- WorldSpec 和 SeedLedger 可 hash，可复现。
- 单元测试覆盖 canonical_json、hash stability、seed derivation。

### Week 2：Calibration 与 baseline

- 完成 Task 86-91。
- 至少 retail-only world 能生成 calibration_artifact。
- TWAP/VWAP/AC-lite 能通过同一 runtime 跑出结果。
- Baseline artifact 纳入 series aggregate。

### Week 3：Hidden / paired / exploit

- 完成 Task 92-95。
- hidden runner 保证 no-learning。
- paired runner 支持 fee、impact、latency 三类扰动。
- exploit runner 至少覆盖 no_signal、timestamp、MTM、fee_accounting、order_boundary。

### Week 4：Gate 与长跑

- 完成 Task 96-101。
- strict parent gate v2 接入 required evidence。
- 跑至少一个长 Arena series。
- 生成完整 evidence package，并审查是否有模型能通过 gate。

## 15. Go / No-Go 标准

### 15.1 Go 标准

进入更复杂模型之前，至少满足：

1. 三类 world split 存在：train、validation、hidden。
2. calibration_artifact_v1 不再是 not_available。
3. TWAP/VWAP/AC-lite 至少两个基线可运行。
4. hidden_eval_artifact_v1 可以评估 frozen checkpoint。
5. exploit_test_artifact_v1 能识别 no-signal 或边界作弊。
6. paired_sensitivity_artifact_v1 能输出退化曲线。
7. strict_parent_gate_v2 能拒绝缺证据的高收益模型。
8. series aggregate 能清楚显示 pass/fail/missing/not_available。

### 15.2 No-Go 信号

出现以下情况应暂停模型复杂化：

- 模型只在训练 world 盈利，hidden world 崩溃。
- no-signal world 中模型稳定盈利。
- 费用或冲击轻微提高后收益完全消失，且没有合理执行解释。
- 高收益集中在开收盘、午休、T+1、冻结释放等边界。
- 模型无法打败 TWAP/VWAP/AC-lite。
- calibration score 缺失或 world critical metrics 越界。
- PBT 父代资格仍只看训练排名。

## 16. 对模型路线的建议

近期仍不要升级 Transformer 或复杂 MARL。先用 ppo_lstm_v1 和规则基线跑通 evidence stack。原因是：如果证据栈未完成，复杂模型只会更快地找到仿真器漏洞。

模型路线建议：

1. P0：ppo_lstm_v1 作为研究对象，不追求最强，只追求可诊断。
2. P0：baseline suite 作为硬门槛。
3. P1：risk-constrained PPO，加入 drawdown、inventory、turnover、fee-aware reward。
4. P1：league/self-play 只用于训练，不用于最终评估。
5. P2：Transformer temporal encoder，前提是 hidden/exploit/paired gates 已稳定。
6. P2：historical replay / hybrid env，引入真实订单流或真实行情锚定。

## 17. 最关键的建设性想法

### 17.1 把 Arena 排行榜降级，把 Evidence Board 升级

排行榜容易制造错觉。下一阶段 GUI 中最重要的不是谁收益最高，而是谁通过了证据门。建议 Arena 首页显示：

```text
Candidate checkpoint
  return rank: #2
  baseline: pass
  calibration: pass
  hidden: fail
  exploit: pass
  fee/impact sensitivity: warning
  parent eligible: no
  research claim eligible: no
```

### 17.2 把 not_available 变成倒计时债务

not_available 是诚实边界，但不能长期停留。建议每个 not_available 字段都关联：

- owner
- required input
- blocking reason
- planned task id
- target date
- replacement artifact kind

### 17.3 先证明“坏模型会被拒绝”

很多系统只证明好模型能通过，却没有证明坏模型会被拒绝。你应该专门构造 bad policies：

- future-leak oracle policy
- fee-exploit policy
- overtrade policy
- random high-turnover policy
- no-signal overfit policy

如果这些坏模型不能被 exploit/gate 拒绝，说明证据系统还不可信。

### 17.4 将训练 reward 与研究评价指标彻底分离

训练 reward 可以是 dense 的、可塑形的；研究评价必须是稀疏、外部、冻结的。不要让模型直接优化 hidden_eval_score 或 calibration_score，否则会污染评估。

## 18. 参考资料

[R1] Amrouni et al. (2021), ABIDES-Gym: Gym Environments for Multi-Agent Discrete Event Simulation and Application to Financial Markets.

[R2] Cheridito, Dupret and Wu (2025), ABIDES-MARL: A Multi-Agent Reinforcement Learning Environment for Endogenous Price Formation and Execution in a Limit Order Book.

[R3] Jaderberg et al. (2017), Population Based Training of Neural Networks.

[R4] Bailey, Borwein, López de Prado and Zhu (2015), The Probability of Backtest Overfitting.

[R5] Chen et al. (2021/2022), Understanding Domain Randomization for Sim-to-real Transfer.

[R6] Gao and Li (2022), Understanding Intra-day Price Formation Process by Agent-Based Financial Market Simulation.

[R7] Almgren and Chriss (2000), Optimal Execution of Portfolio Transactions.

[R8] 项目内部文档：PROJECT_BACKGROUND_AND_GOALS(1).md；UTI-STOCKSIM_专家评审与落地设计_做得怎样(3).docx。
