# Arena Sim Version Identity Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-sim-version-source.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.sim_version_identity`. This task makes the sim-version identity object visible in `experiment_record_completeness` separately from the derived `sim_version` value.

This is a status mapping only. It does not change the sim-version source or package version.

## Scope

Implemented:

- Add `sim_version_identity` to `experiment_record_completeness.field_status`.
- Mark `sim_version_identity=present` when a top-level or metadata sim-version identity object exists.
- Mark `sim_version_identity=missing` when no sim-version identity object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No sim-version source changes.
- No package version changes.
- No hash calculation changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, and identity summaries.
- Direct assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.
