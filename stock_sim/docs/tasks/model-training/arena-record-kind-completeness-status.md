# Arena Record Kind Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Task 54 added record-kind metadata so Arena reports can distinguish training records from future calibration, hidden-evaluation, and exploit-test artifacts. This task makes that distinction part of `experiment_record_completeness` so the same completeness view can track whether record type and separate artifact statuses are auditable.

This is a completeness/status change only. It does not create the separate artifacts.

## Scope

Implemented:

- Add `record_kind` to `experiment_record_completeness.field_status`.
- Add `separate_calibration_record` to `experiment_record_completeness.field_status`.
- Add `separate_hidden_evaluation_record` to `experiment_record_completeness.field_status`.
- Add `separate_exploit_test_record` to `experiment_record_completeness.field_status`.
- Treat `record_kind` as `present` only when a real record-kind object exists in the report or metadata.
- Treat separate artifact statuses as:
  - `present` for `pass`, `available`, `complete`, or `present`
  - `not_available` for explicit `not_available`
  - `not_applicable` for explicit `not_applicable`
  - `missing` when no status exists
- Carry the new fields into `aggregate.experiment_record_completeness` status counts.

## Explicitly Not Implemented

- No separate calibration artifact.
- No separate hidden-evaluation artifact.
- No separate exploit-test artifact.
- No hidden-world runner.
- No calibration metric computation.
- No random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with record-kind metadata can mark `record_kind` as present in completeness.
- Reports with explicit separate artifact `not_available` statuses keep those statuses visible.
- Reports without record-kind metadata do not silently count artifact boundaries as complete.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
- Direct assertion passed with `ARENA_RECORD_KIND_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add separate calibration, hidden-evaluation, and exploit-test artifacts only after their schemas, runners, and artifact boundaries are documented.
