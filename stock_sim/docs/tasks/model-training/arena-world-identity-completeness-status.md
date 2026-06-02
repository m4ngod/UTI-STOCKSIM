# Arena World Identity Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_娑撴挸顔嶇拠鍕吀娑撳氦鎯ら崷鎷岊啎鐠?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.world_identity` as the canonical input used for `world_hash` and world-card metadata. This task makes that identity visible in `experiment_record_completeness` so reports can distinguish an auditable world identity object from missing world identity metadata.

This is a status mapping only. It does not change world-hash calculation or world generation.

## Scope

Implemented:

- Add `world_identity` to `experiment_record_completeness.field_status`.
- Mark `world_identity=present` when a top-level or metadata `world_identity` object exists.
- Mark `world_identity=missing` when no world-identity object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No world-hash calculation changes.
- No world-identity schema change.
- No world generation changes.
- No world-pool split.
- No hidden-world runner.
- No calibration harness.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with `experiment_record_metadata.world_identity` mark `world_identity` as `present`.
- Reports lacking world-identity metadata remain `missing`.
- Series completeness aggregates count world-identity status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct assertion passed with `ARENA_WORLD_IDENTITY_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add deeper world-identity validation only after the project documents validation ownership and allowed world-identity schema evolution.
