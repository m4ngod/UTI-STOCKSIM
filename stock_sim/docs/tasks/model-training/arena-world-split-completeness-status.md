# Arena World Split Completeness Status

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

Work Package C requires train, validation, and hidden world separation before hidden evaluation or calibration claims can be interpreted. Current world-card metadata already exposes `split.status=training_only` with a reason. This task makes that split state visible in `experiment_record_completeness`.

This is a status mapping only. It does not implement world splitting.

## Scope

Implemented:

- Add `world_split` to `experiment_record_completeness.field_status`.
- Mark `world_split=present` when split status is one of:
  - `train_validation_hidden`
  - `validation`
  - `hidden`
  - `available`
  - `complete`
- Mark `world_split=not_available` when split status is:
  - `training_only`
  - `not_available`
- Mark `world_split=missing` when no split status is present.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No train/validation/hidden world split.
- No seed/config hash split rules.
- No hidden-world runner.
- No calibration score computation.
- No calibration harness.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Current training-only world cards are explicit as `world_split=not_available`.
- Reports lacking split metadata remain `missing`.
- Future validation/hidden split statuses can become `present` without changing the aggregate shape.
- Series completeness aggregates count world-split status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_SPLIT_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add real train/validation/hidden split only after seed/config hash split rules and artifact boundaries are documented.
