# Arena Reward Identity Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.reward_identity` as the canonical input used for `reward_hash`. This task makes that identity visible in `experiment_record_completeness` so reports can distinguish an auditable reward identity object from a derived hash alone.

This is a status mapping only. It does not change reward-hash calculation or reward behavior.

## Scope

Implemented:

- Add `reward_identity` to `experiment_record_completeness.field_status`.
- Mark `reward_identity=present` when a top-level or metadata `reward_identity` object exists.
- Mark `reward_identity=missing` when no reward-identity object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No reward-hash calculation changes.
- No reward identity schema change.
- No reward function or reward benchmark changes.
- No Alpha-to-Execution logic changes.
- No hidden-world runner.
- No calibration harness.
- No training, execution, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with `experiment_record_metadata.reward_identity` mark `reward_identity` as `present`.
- Reports lacking reward-identity metadata remain `missing`.
- Series completeness aggregates count reward-identity status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct assertion passed with `ARENA_REWARD_IDENTITY_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add deeper reward-identity validation only after the project documents validation ownership and allowed reward identity schema evolution.
