# Baseline Suite Inventory And Plan

_Created: 2026-05-03_

## Source

This document is derived from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/contracts/runtime/model-reward-contract.md`
- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `rl/reward_builder.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review states that model results are not meaningful unless they are compared with strong, task-matched baselines. The Alpha-to-Execution task card therefore requires baseline inventory before changing `ppo_lstm_v1` or adding new training logic.

This document records what the project already has, what is missing, and the safe implementation order for the baseline suite.

## Current Baseline Inventory

### Already Present

| Baseline / Reference | Current Evidence | Status | Notes |
| --- | --- | --- | --- |
| `hold_model_v1` | `ModelRegistryService` has `HoldModel`; `ArenaExperimentConfig` includes it by default. | present | Can serve as no-trade / cash-like baseline if report labels and initial cash semantics are made explicit. |
| `random_weight_v1` | `ModelRegistryService` has `RandomWeightModel`; `ArenaExperimentConfig` includes it by default. | present | Acts as a random long-only target-weight baseline. It is not yet explicitly named `random_constrained` in reports. |
| `target_weight_naive_rebalance_v1` | `ModelRegistryService` has `TargetWeightNaiveRebalanceModel`; `ArenaExperimentConfig` includes it by default. | present | Deterministic long-only equal-weight target rebalance using existing `act.v1 target_weight`. |
| PPO/LSTM trainable reference | `ArenaExperimentConfig` defaults to three `ppo_lstm_v1` online-training agents. | present | This is the trainable candidate, not a non-neural baseline. |
| Baseline exclusion from PBT | `ArenaExperimentConfig.pbt_excluded_model_ids` defaults to `hold_model_v1` and `random_weight_v1`. | present | Good guardrail: baseline agents are not selected as parents by default. |
| Execution-health metrics | `ArenaExperimentRunner` reports submitted/open/rejected/filled orders, fill ratio, notional fill ratio, and filled notional. | present | Useful for execution baseline comparison. |
| Reward benchmark hook | `RewardBuilder.build(... benchmark_return=...)` exists. | partial | `RuntimeModelAgent` currently passes `benchmark_return=0.0`, so benchmark comparison is not yet live. |

### Missing Or Not Yet Formalized

| Required Baseline / Feature | Status | Reason |
| --- | --- | --- |
| Explicit no-trade / cash report row | missing / implicit | `hold_model_v1` exists, but reports do not yet label it as the no-trade/cash acceptance baseline. |
| Random constrained report row | partial | `random_weight_v1` exists, but reports do not yet describe its constraint set or compare excess performance against it. |
| Target-weight naive rebalance | present | `target_weight_naive_rebalance_v1` now emits deterministic equal-weight `act.v1 target_weight` actions and appears as a baseline report row. |
| TWAP / VWAP execution baseline | present as scheduled target-weight baselines | `twap_execution_v1` and `vwap_execution_v1` are registered built-in policies and emit `act.v1 target_weight` actions with schedule metadata. True order-level slicing and implementation-shortfall wiring remain deferred. |
| Simplified Almgren-Chriss baseline | present as AC-lite scheduled target-weight baseline | `ac_lite_execution_v1` is registered as a built-in policy and emits `act.v1 target_weight` actions with AC-lite risk/cost schedule metadata. True order-level slicing and implementation-shortfall wiring remain deferred. |
| Oracle-alpha plus naive execution | deferred | Requires controlled alpha signal plumbing from `alpha_to_execution.v1`. |
| Baseline comparison section in Arena report | missing | Current report has model results and execution health, but no `baselines` / `benchmark_comparison` section. |
| Baseline-relative parent gate | missing | PBT has activity and exclusion gates, but not "must beat required baselines" under strict mode. |

## Required Report Semantics

Arena reports should eventually separate these concepts:

- `candidate_results`: trainable model results such as `ppo_lstm_v1`.
- `baseline_results`: no-trade, random constrained, naive rebalance, TWAP/VWAP.
- `benchmark_comparison`: per-candidate excess metrics against each required baseline.
- `research_acceptance`: pass/fail/warn status that is not the same as Arena rank.

Minimum future shape:

```text
baseline_suite:
  task_name: alpha_to_execution.v1
  required:
    - no_trade_cash
    - random_constrained
    - target_weight_naive_rebalance
  optional:
    - twap
    - vwap
  status: incomplete | complete

benchmark_comparison:
  candidate_agent_id:
    no_trade_cash:
      excess_score: number
      excess_equity_return: number
      excess_filled_notional: number
    random_constrained:
      excess_score: number
```

## Implementation Order

### Step 1: Label Existing Baselines

Goal: make existing `hold_model_v1` and `random_weight_v1` explicit in reports before adding new baseline policies.

Tasks:

1. Add report metadata that marks `hold_model_v1` as `baseline_kind=no_trade_cash`.
2. Add report metadata that marks `random_weight_v1` as `baseline_kind=random_constrained`.
3. Keep both excluded from default PBT parent selection.
4. Add tests that report labels do not change runtime behavior.

Acceptance:

- Arena report readers can distinguish baseline rows from trainable candidate rows.

### Step 2: Add Target-Weight Naive Rebalance Baseline

Goal: create a deterministic target-weight baseline using existing `act.v1 target_weight` semantics.

Status: done.

Tasks:

1. Define target-weight naive rebalance as a docs contract first.
2. Reuse current `target_weight` action path.
3. Use the same runtime services as models.
4. Add it as a baseline row, not a PBT parent.

Acceptance:

- `ppo_lstm_v1` can be compared against a deterministic target-weight executor before being called useful for Alpha-to-Execution.

### Step 3: Add TWAP / VWAP Report Slots

Goal: prepare execution baseline reporting before implementing full schedule execution.

Status: done for report slots and runnable scheduled target-weight baselines; true order-level schedule execution remains deferred.

Tasks:

1. Add report slots for TWAP/VWAP as `not_available` until schedule logic exists.
2. Define required input fields:
   - arrival price
   - target quantity/notional
   - horizon
   - realized fill price
   - benchmark fill price
3. Do not fail experiments only because TWAP/VWAP is unavailable until the task reaches order-intent execution.

Acceptance:

- Reports clearly state whether TWAP/VWAP comparison is available, missing, or not applicable.
- `twap_execution_v1` and `vwap_execution_v1` can run through the same model registry and `act.v1` path as other baselines.

### Step 4: Feed Benchmark Return / Shortfall

Goal: stop using only `benchmark_return=0.0` once the task has baseline outputs.

Tasks:

1. Wire benchmark return or execution shortfall into reward/report code only after baseline outputs exist.
2. Keep reward profile version explicit.
3. Preserve separate reward components so reward hacking can be diagnosed.

Acceptance:

- `rew.v1` can report candidate performance relative to the required baseline without silently changing old reward semantics.

### Step 5: Strict Parent Eligibility

Goal: align PBT parent eligibility with the expert review.

Tasks:

1. Add a strict mode that requires candidate models to beat required baselines.
2. Combine this with hidden evaluation and exploit detector results once those placeholders exist.
3. Keep activity gates such as filled trades and fill ratio.

Acceptance:

- A model cannot become a robust parent solely by ranking above weak peers in one synthetic Arena run.

### Step 3b: Add AC-lite Baseline

Goal: add a simplified risk/cost execution baseline after TWAP/VWAP are runnable.

Status: done for scheduled target-weight baseline; order-level AC slicing remains deferred.

Tasks:

1. Register `ac_lite_execution_v1` as a built-in model.
2. Emit `act.v1 target_weight` through the same model registry path.
3. Include `sigma`, `eta`, `risk_aversion`, horizon, and progress in schedule metadata.
4. Include AC-lite as a baseline row, not a PBT parent.
5. Include AC-lite in `baseline_artifact_v1` required baseline kinds.

Acceptance:

- `ac_lite_execution_v1` can run through the same model registry and `act.v1` path as other baselines.
- Arena can include AC-lite as a collect-only baseline.

## Explicitly Deferred

- Linear/logistic/GBDT prediction baselines.
- Oracle-alpha plus naive execution.
- Replay/hybrid benchmark comparison.

These are valid later items from the expert review, but they should follow explicit no-trade, random constrained, naive rebalance, and TWAP/VWAP report structure.

## Next Task

The next safe task is to start wiring strict PBT parent-eligibility in a disabled or opt-in strict mode, using the now-visible baseline, hidden-evaluation, and exploit-detector report sections.

No default PBT behavior should change until the strict gate has tests and remains opt-in.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-baseline-suite-summary.md` carries baseline-suite completeness, present kinds, missing required baselines, and TWAP/VWAP availability into Arena generation summaries and series aggregates. This is report-only and does not implement new baselines or schedules.
