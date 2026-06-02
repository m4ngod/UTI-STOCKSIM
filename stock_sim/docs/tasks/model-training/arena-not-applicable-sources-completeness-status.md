# Arena Not Applicable Sources Completeness Status

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

Arena experiment metadata already records `experiment_record_metadata.not_applicable_sources`. This task makes the not-applicable-sources list visible in `experiment_record_completeness` so reports can distinguish explicit non-applicability from missing documentation.

This is a status mapping only. It does not make any source applicable or unavailable.

## Scope

Implemented:

- Add `not_applicable_sources` to `experiment_record_completeness.field_status`.
- Mark `not_applicable_sources=present` when a top-level or metadata not-applicable-sources list exists.
- Mark `not_applicable_sources=missing` when no not-applicable-sources list exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No data-cutoff semantics changes.
- No replay/hybrid data source changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, and identity summaries.
- Direct assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.
