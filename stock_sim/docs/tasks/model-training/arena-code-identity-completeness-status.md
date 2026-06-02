# Arena Code Identity Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-code-identity-hash.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.code_identity`. This task makes the code identity object visible in `experiment_record_completeness` separately from the derived `code_hash`.

This is a status mapping only. It does not change Git identity collection or code-hash behavior.

## Scope

Implemented:

- Add `code_identity` to `experiment_record_completeness.field_status`.
- Mark `code_identity=present` when a top-level or metadata code-identity object exists.
- Mark `code_identity=missing` when no code-identity object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No Git command behavior changes.
- No code-hash calculation changes.
- No dirty-worktree policy changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, and identity summaries.
- Direct assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.
