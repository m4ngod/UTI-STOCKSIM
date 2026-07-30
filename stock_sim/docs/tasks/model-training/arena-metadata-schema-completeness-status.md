# Arena Metadata Schema Completeness Status

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

Arena experiment metadata already records `experiment_record_metadata.schema`. This task makes that metadata schema visible in `experiment_record_completeness` so reports can distinguish auditable metadata schema information from missing metadata schema information.

This is a status mapping only. It does not change metadata schema values or report identity values.

## Scope

Implemented:

- Add `metadata_schema` to `experiment_record_completeness.field_status`.
- Mark `metadata_schema=present` when a top-level `metadata_schema` value or metadata `schema` value exists.
- Mark `metadata_schema=missing` when no metadata schema value exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No metadata schema value changes.
- No report identity schema migration.
- No hash calculation changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, and identity summaries.
- Direct assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.
