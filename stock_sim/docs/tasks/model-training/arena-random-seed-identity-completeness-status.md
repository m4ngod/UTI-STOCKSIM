# Arena Random Seed Identity Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-random-seed-status.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.random_seed_identity` with an explicit `not_available` reason. This task makes that identity object visible in `experiment_record_completeness` separately from the still-missing real `random_seed`.

This is a status mapping only. It does not add a runtime random seed.

## Scope

Implemented:

- Add `random_seed_identity` to `experiment_record_completeness.field_status`.
- Mark `random_seed_identity=present` when a top-level or metadata random-seed identity object exists.
- Mark `random_seed_identity=missing` when no random-seed identity object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No runtime random seed injection.
- No stochastic-service seed wiring.
- No change to `random_seed` remaining missing until the documented prerequisites exist.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, and identity summaries.
- Direct assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.
