# Unified Baseline Runner

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/calibration-artifact-writer.md`
- `docs/current-work-status/model-training.md`
- `app/services/arena_experiment_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Task

Task 89: Unified Baseline Runner.

## Purpose

Convert the current Arena baseline suite into a separate `baseline_artifact_v1` output without creating a second
baseline path that bypasses runtime, model registry, action parsing, order execution, account, reward, or report
contracts.

## Current Runtime Boundary

The project already has three default required baselines that run through the same Arena/model/runtime path as
trainable candidates:

- `hold_model_v1` as `no_trade_cash`
- `random_weight_v1` as `random_constrained`
- `target_weight_naive_rebalance_v1` as `target_weight_naive_rebalance`

These are already labeled in Arena report rows with `result_role=baseline` and `baseline_kind`.

## Artifact Boundary

`baseline_artifact_v1` is written from existing Arena report outputs:

- `baseline_suite`
- baseline result rows
- `benchmark_comparison`
- Evidence Runner identity fields
- dependency list

The writer does not execute the Arena itself. The Arena runtime remains the owner of baseline execution.

## Pass Boundary

For Task 89, pass requires:

- required identity fields are present.
- `baseline_suite` is present.
- baseline result rows are present.
- `benchmark_comparison` is present.
- current required baseline kinds are present:
  - `no_trade_cash`
  - `random_constrained`
  - `target_weight_naive_rebalance`

TWAP, VWAP, and AC-lite remain outside Task 89 and should be handled by later tasks.

## Current Status

Implemented in `EvidenceArtifactWriter.write_baseline_artifact(...)` with focused tests in
`tests/runtime/test_evidence_artifact_writer.py`.

No new baseline policy, schedule executor, TWAP/VWAP/AC-lite implementation, PostgreSQL persistence, GUI behavior,
PBT parent-gate change, or PostgreSQL data deletion was added.
