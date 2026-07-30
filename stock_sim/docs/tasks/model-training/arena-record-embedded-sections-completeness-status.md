# Arena Record Embedded Sections Completeness Status

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

Arena record-kind metadata already exposes `record_kind.embedded_sections`. This task makes the embedded-section list visible in `experiment_record_completeness` so reports can distinguish explicit embedded-section boundaries from missing boundary metadata.

This is a status mapping only. It does not create separate calibration, hidden-evaluation, or exploit-test artifacts.

## Scope

Implemented:

- Add `record_embedded_sections` to `experiment_record_completeness.field_status`.
- Mark `record_embedded_sections=present` when `record_kind.embedded_sections` is non-empty.
- Mark `record_embedded_sections=missing` when the embedded-section list is empty or absent.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No embedded-section taxonomy changes.
- No separate calibration/hidden/exploit artifact generation.
- No hidden-world runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed for generation completeness, series completeness, record-kind summary, and record-kind aggregate.
- Direct assertion passed with `ARENA_RECORD_KIND_DETAIL_COMPLETENESS_BATCH_ASSERTIONS_OK`.
