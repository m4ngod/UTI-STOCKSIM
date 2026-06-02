# Arena Record Primary Stage Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庚惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`
- `docs/tasks/model-training/arena-record-kind-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena record-kind metadata already exposes `record_kind.primary_stage`. This task makes the primary stage visible in `experiment_record_completeness` so reports can distinguish explicit training-stage labeling from missing stage metadata.

This is a status mapping only. It does not change stage semantics.

## Scope

Implemented:

- Add `record_primary_stage` to `experiment_record_completeness.field_status`.
- Mark `record_primary_stage=present` when `record_kind.primary_stage` exists.
- Mark `record_primary_stage=missing` when the primary-stage value is absent.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No stage taxonomy changes.
- No separate calibration/hidden/exploit artifact generation.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, record-kind summary, and record-kind aggregate.
- Direct assertion passed with `ARENA_RECORD_KIND_DETAIL_COMPLETENESS_BATCH_ASSERTIONS_OK`.
