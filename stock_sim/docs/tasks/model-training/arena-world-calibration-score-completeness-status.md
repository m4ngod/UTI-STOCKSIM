# Arena World Calibration Score Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Task 60 added an explicit calibration-score slot to world-card metadata. This task makes that score slot visible in `experiment_record_completeness` so a single completeness view can distinguish present, missing, and not-available calibration-score evidence.

This is a status mapping only. It does not compute calibration scores.

## Scope

Implemented:

- Add `world_calibration_score` to `experiment_record_completeness.field_status`.
- Mark `world_calibration_score=present` when:
  - `calibration_score_status` is `pass`, `available`, `complete`, or `present`; or
  - a non-empty `calibration_score` value exists.
- Mark `world_calibration_score=not_available` when `calibration_score_status=not_available`.
- Mark `world_calibration_score=missing` when no calibration-score slot/status is present.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No calibration score computation.
- No calibration pass/fail threshold.
- No calibration harness.
- No world-pool split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with explicit unavailable calibration-score slots mark `world_calibration_score` as `not_available`.
- Reports with real calibration scores can mark `world_calibration_score` as `present`.
- Reports lacking the score slot remain `missing`.
- Series completeness aggregates count calibration-score status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_CALIBRATION_SCORE_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add real calibration scores only after the project documents metric ownership, data sources, pass/fail thresholds, and artifact boundaries.
