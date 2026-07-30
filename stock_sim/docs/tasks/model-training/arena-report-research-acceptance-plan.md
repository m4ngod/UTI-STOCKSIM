# Arena Report Research Acceptance Plan

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `app/services/arena_experiment_runner.py`
- `app/services/model_population_service.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review says Arena rank must not be treated as research acceptance. The baseline inventory therefore identified the next safe step: define the report structure for `baseline_suite`, `benchmark_comparison`, and `research_acceptance` before changing `ppo_lstm_v1` behavior.

This task keeps the change at report-semantics level. It labels existing baseline rows, computes simple baseline-relative comparisons from already recorded episode results, and marks research acceptance as incomplete until hidden evaluation and exploit checks exist.

_Update 2026-05-03_: `target_weight_naive_rebalance_v1` has been implemented as a deterministic `act.v1 target_weight` baseline. `research_acceptance` still remains incomplete because hidden evaluation and exploit detector outputs do not exist yet.

_Update 2026-05-03_: TWAP/VWAP optional report slots now expose `status=not_available`, `reason=schedule_execution_not_implemented`, and the required inputs needed before schedule execution can be implemented.

_Update 2026-05-03_: Hidden evaluation and exploit detector placeholder sections now exist. They are intentionally `not_implemented` and feed `research_acceptance.required_sections` so the report remains machine-readable before real checks land.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-benchmark-comparison-summary.md` carries `benchmark_comparison` status, baseline kinds, candidate counts, and candidate-baseline pair counts into Arena generation summaries and series aggregates. This is report-only and does not change reward or PBT behavior.

## Scope Rules

- Do not change model actions, reward calculation, runtime matching, account semantics, or PBT selection in this step.
- Do not add a new model family.
- Do not claim Alpha-to-Execution success from Arena leaderboard rank.
- Keep existing `hold_model_v1` and `random_weight_v1` excluded from default PBT parent selection.
- Treat missing TWAP, VWAP, hidden evaluation, and exploit detector as explicit report gaps, not silent pass conditions.

## Report Sections

### `baseline_suite`

Goal: tell report readers whether the minimum Alpha-to-Execution baselines are present.

Required fields:

- `task_name`
- `status`: `complete` or `incomplete`
- `required`: baseline status records
- `optional`: optional baseline status records
- `present_kinds`
- `missing_required`

Baseline mapping:

| `model_id` | `baseline_kind` | Meaning |
| --- | --- | --- |
| `hold_model_v1` | `no_trade_cash` | No-trade / cash-like baseline row. |
| `random_weight_v1` | `random_constrained` | Random long-only constrained target-weight baseline row. |
| `target_weight_naive_rebalance_v1` | `target_weight_naive_rebalance` | Deterministic equal-weight target-weight executor. |

Initial required set:

- `no_trade_cash`
- `random_constrained`
- `target_weight_naive_rebalance`

Initial optional set:

- `twap`
- `vwap`

### `benchmark_comparison`

Goal: make candidate performance explicitly relative to baseline rows.

For each candidate model result, report excess metrics against each present baseline kind:

- `excess_score`
- `excess_equity_return`
- `excess_reward_total`
- `excess_filled_notional`

If a baseline is missing, the section should not fabricate a value.

### `research_acceptance`

Goal: separate "ranked well in this Arena episode" from "acceptable research candidate".

Initial status should be `incomplete` unless all required report gates exist and pass. Current expected reasons include:

- hidden evaluation not implemented
- exploit detector not implemented

This section is advisory metadata only in the first pass. It should not change PBT behavior until hidden evaluation and exploit detector outputs are present.

Current required sections:

```text
research_acceptance:
  required_sections:
    baseline_suite: complete | incomplete
    hidden_evaluation: complete | not_implemented
    exploit_detector: complete | not_implemented
```

## Implementation Steps

1. Add helper functions in `ArenaExperimentRunner` to label baseline rows by `model_id`.
2. Add `result_role` and `baseline_kind` to each episode result row.
3. Add `baseline_suite`, `benchmark_comparison`, and `research_acceptance` to Arena reports.
4. Add regression tests that existing baseline labels appear without changing runtime behavior.
5. Update `docs/current-work-status/model-training.md` after implementation.

## Acceptance

- Arena reports distinguish trainable candidates from baseline rows.
- Existing `hold_model_v1` is labeled as `no_trade_cash`.
- Existing `random_weight_v1` is labeled as `random_constrained`.
- Missing required baselines are visible in `baseline_suite.missing_required`.
- `research_acceptance.status` remains `incomplete` until hidden evaluation and exploit detector work lands.

## Explicitly Deferred

- Implementing TWAP/VWAP schedules.
- Wiring benchmark return into reward calculation.
- Strict baseline-relative PBT parent eligibility.
- Hidden evaluation and exploit detector execution.
