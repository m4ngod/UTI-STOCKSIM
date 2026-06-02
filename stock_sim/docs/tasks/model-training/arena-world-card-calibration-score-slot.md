# Arena World Card Calibration Score Slot

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

Work Package C asks for world-card and calibration-score metadata before synthetic Arena rankings are interpreted. Existing world-card metadata already reports calibration status and missing calibration metrics, but it did not expose an explicit calibration-score slot.

This task adds a `not_available` calibration-score slot. It does not compute calibration scores.

## Scope

Implemented:

- Add `world_card.calibration.score=None`.
- Add `world_card.calibration.score_status=not_available`.
- Add `world_card.calibration.score_reason=calibration_harness_not_implemented`.
- Add calibration-score fields to Arena generation `world_card` summaries:
  - `calibration_score`
  - `calibration_score_status`
  - `calibration_score_reason`
- Add `aggregate.world_card.calibration_score_status_counts`.

## Explicitly Not Implemented

- No calibration score computation.
- No calibration pass/fail threshold.
- No calibration harness.
- No world-pool split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- New world-card metadata has an explicit calibration-score slot.
- Generation summaries surface that calibration score is not available.
- Series aggregates can count calibration-score availability without opening every full report.
- Reports do not imply a calibration score or pass/fail result exists.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct assertion passed with `ARENA_WORLD_CARD_CALIBRATION_SCORE_SLOT_ASSERTIONS_OK`.
- `tests/runtime/test_arena_experiment_runner.py::test_runner_orchestrates_arena_clock_and_writes_report` remains blocked in this environment by Windows pytest temporary-directory lock permissions, not by the calibration-score assertions.

## Follow-up

- Add real calibration scores only after the project documents metric ownership, data sources, pass/fail thresholds, and artifact boundaries.

## Progress Update 2026-05-04: Completeness Status

- `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md` now tracks `world_calibration_score` in `experiment_record_completeness`.
- Explicit unavailable score slots mark the field as `not_available`.
- Missing score slots remain `missing`.
- Future real calibration scores can become `present` without changing the aggregate shape.
