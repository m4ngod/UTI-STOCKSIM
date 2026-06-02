# Arena World Liquidity Seed Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

World-card metadata already exposes the current training-liquidity seed configuration. This task makes that configuration visible in `experiment_record_completeness` so reports can distinguish auditable liquidity-seed settings from missing metadata.

This is a status mapping only. It does not change liquidity seeding, matching, or market-world behavior.

## Scope

Implemented:

- Add `world_liquidity_seed` to `experiment_record_completeness.field_status`.
- Mark `world_liquidity_seed=present` when `seed_training_liquidity` is explicitly present in the world card, whether the value is `true` or `false`.
- Mark `world_liquidity_seed=missing` when no liquidity-seed setting is present.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No new liquidity seed behavior.
- No liquidity model changes.
- No matching-engine changes.
- No train/validation/hidden world split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with explicit liquidity-seed configuration mark `world_liquidity_seed` as `present`.
- Reports lacking liquidity-seed metadata remain `missing`.
- Series completeness aggregates count liquidity-seed status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_LIQUIDITY_SEED_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add more detailed liquidity or market-depth evidence only after the project documents metric ownership, data sources, and world-card artifact boundaries.
