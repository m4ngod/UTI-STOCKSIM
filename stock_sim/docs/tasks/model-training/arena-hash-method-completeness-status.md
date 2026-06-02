# Arena Hash Method Completeness Status

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

Arena experiment metadata already records `experiment_record_metadata.hash_method` for deterministic report hashes. This task makes the hash method visible in `experiment_record_completeness` so reports can distinguish auditable hash-method metadata from missing hash-method metadata.

This is a status mapping only. It does not change hash calculation or any report identity values.

## Scope

Implemented:

- Add `hash_method` to `experiment_record_completeness.field_status`.
- Mark `hash_method=present` when a top-level or metadata hash-method value exists.
- Mark `hash_method=missing` when no hash-method value exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No hash-method value changes.
- No reward-hash or world-hash calculation changes.
- No code-hash calculation changes.
- No reward function or reward benchmark changes.
- No hidden-world runner.
- No calibration harness.
- No training, execution, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with `experiment_record_metadata.hash_method` mark `hash_method` as `present`.
- Reports lacking hash-method metadata remain `missing`.
- Series completeness aggregates count hash-method status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct assertion passed with `ARENA_HASH_METHOD_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add deeper hash-method validation only after the project documents validation ownership and allowed hash-method schema evolution.
