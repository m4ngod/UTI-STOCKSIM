# Arena Transition Evidence Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-transition-evidence-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Task 56 added compact transition evidence summaries. This task makes that evidence visible in `experiment_record_completeness` so a single completeness view can show whether compact transition evidence exists for a generation.

This is a status mapping only. It does not change transition persistence or sample retention.

## Scope

Implemented:

- Add `transition_evidence` to `experiment_record_completeness.field_status`.
- Mark `transition_evidence=present` when transition evidence has a summary.
- Mark `transition_evidence=not_available` when an episode has no transitions.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No new transition persistence.
- No larger raw transition samples.
- No replay artifact.
- No failure reproduction runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with transitions can mark transition evidence as present in completeness.
- Reports without transitions keep transition evidence explicit as `not_available`.
- Series aggregates can count transition evidence status without opening full reports.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
- Direct assertion passed with `ARENA_TRANSITION_EVIDENCE_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add replay or failure reproduction artifacts only after their schema, retention policy, and data source boundaries are documented.
