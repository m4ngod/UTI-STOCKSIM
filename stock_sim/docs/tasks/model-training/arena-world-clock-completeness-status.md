# Arena World Clock Completeness Status

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

World-card metadata already exposes the Arena clock configuration. This task makes that configuration visible in `experiment_record_completeness` so reports can distinguish auditable clock settings from missing metadata.

This is a status mapping only. It does not start, stop, or change simulation clock behavior.

## Scope

Implemented:

- Add `world_clock` to `experiment_record_completeness.field_status`.
- Mark `world_clock=present` when these world-card fields are present:
  - `clock_start_day`
  - `clock_speed`
  - `run_clock`
- Mark `world_clock=missing` when any required clock field is absent.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No clock behavior changes.
- No time-step semantics changes.
- No train/validation/hidden world split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with complete world-card clock configuration mark `world_clock` as `present`.
- Reports lacking clock metadata remain `missing`.
- Series completeness aggregates count clock status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_CLOCK_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add additional clock or time-regime evidence only after the project documents metric ownership and world-card artifact boundaries.
