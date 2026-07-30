# Arena World Universe Completeness Status

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

World-card metadata already exposes the world universe through symbols and symbol count. This task makes that universe visible in `experiment_record_completeness` so reports can distinguish auditable universe metadata from missing world-card universe metadata.

This is a status mapping only. It does not change symbol selection or world generation.

## Scope

Implemented:

- Add `world_universe` to `experiment_record_completeness.field_status`.
- Mark `world_universe=present` when world-card symbols are non-empty and `symbol_count` is greater than zero.
- Mark `world_universe=missing` when world-card universe metadata is empty or absent.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No symbol selection changes.
- No universe expansion or filtering.
- No world-pool split.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with non-empty world-card universe metadata mark `world_universe` as `present`.
- Reports lacking world-card universe metadata remain `missing`.
- Series completeness aggregates count world-universe status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_UNIVERSE_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add universe validation or hidden-world universe split only after the project documents symbol-pool ownership and world-card artifact boundaries.
