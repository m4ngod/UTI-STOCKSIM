# Arena Model Lineage Evidence Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-model-lineage-evidence-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Task 58 added compact model-lineage evidence summaries. This task makes that evidence visible in `experiment_record_completeness` so a single completeness view can show whether lineage evidence exists for a generation.

This is a status mapping only. It does not create lineage rows, change mutation logic, or change PBT parent selection.

## Scope

Implemented:

- Add `model_lineage_evidence` to `experiment_record_completeness.field_status`.
- Mark `model_lineage_evidence=present` when compact lineage evidence has a lineage row.
- Mark `model_lineage_evidence=not_available` when a generation has no PBT lineage row.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No new PBT lineage creation.
- No new mutation logic.
- No separate model-lineage artifact.
- No model registry or checkpoint loading changes.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with lineage rows can mark model-lineage evidence as present in completeness.
- Reports without lineage rows keep model-lineage evidence explicit as `not_available`.
- Series aggregates can count model-lineage evidence status without opening full reports.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_model_lineage_evidence`
- Direct assertion passed with `ARENA_MODEL_LINEAGE_EVIDENCE_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Keep model-lineage artifact expansion deferred until the project documents a separate artifact schema or additional mutation acceptance criteria.
