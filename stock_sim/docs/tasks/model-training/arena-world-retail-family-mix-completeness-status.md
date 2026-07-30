# Arena World Retail Family Mix Completeness Status

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

Work Package C lists retail family mix as part of the world-card schema. Current world-card metadata already exposes `retail_profile.family_mix_status=not_available`. This task makes that status visible in `experiment_record_completeness`.

This is a status mapping only. It does not implement retail family mix reporting or retail calibration.

## Scope

Implemented:

- Add `world_retail_family_mix` to `experiment_record_completeness.field_status`.
- Mark `world_retail_family_mix=present` when retail family mix status is one of:
  - `pass`
  - `available`
  - `complete`
  - `present`
- Mark `world_retail_family_mix=not_available` when `retail_family_mix_status=not_available`.
- Mark `world_retail_family_mix=missing` when no retail family mix status is present.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No retail family mix calculation.
- No retail calibration harness.
- No persona distribution report.
- No train/validation/hidden world split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Current world cards with explicit unavailable retail family mix status mark `world_retail_family_mix` as `not_available`.
- Reports lacking retail family mix status remain `missing`.
- Future reports with real retail family mix evidence can become `present` without changing the aggregate shape.
- Series completeness aggregates count retail family mix status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_RETAIL_FAMILY_MIX_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add real retail family mix evidence only after the project documents metric ownership, data sources, and world-card artifact boundaries.
