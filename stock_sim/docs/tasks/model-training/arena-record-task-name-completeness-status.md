# Arena Record Task Name Completeness Status

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

Arena record-kind metadata already exposes `record_kind.task_name`. This task makes the record-kind task name visible in `experiment_record_completeness` separately from config-level `task_name`.

This is a status mapping only. It does not change task routing or reward selection.

## Scope

Implemented:

- Add `record_task_name` to `experiment_record_completeness.field_status`.
- Mark `record_task_name=present` when `record_kind.task_name` exists.
- Mark `record_task_name=missing` when the record-kind task-name value is absent.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No task-name semantics changes.
- No reward profile changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, record-kind summary, and record-kind aggregate.
- Direct assertion passed with `ARENA_RECORD_KIND_DETAIL_COMPLETENESS_BATCH_ASSERTIONS_OK`.
