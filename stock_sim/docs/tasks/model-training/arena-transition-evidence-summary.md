# Arena Transition Evidence Summary

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires transition storage to stay compact while preserving enough samples and summaries to reproduce failures. Existing Arena reports already include transition counts and audit sections with bounded samples. This task exposes those existing evidence signals in generation summaries and series aggregates.

This is a report-summary change only. It does not store more transitions or change transition persistence.

## Scope

Implemented:

- Add `transition_evidence` to Arena generation summaries.
- Add `aggregate.transition_evidence` to Arena series aggregates.
- Summarize existing evidence from:
  - `runtime_observation_audit`
  - `timestamp_audit`
  - `mark_to_market_audit`
  - `order_anomaly_audit`
- Preserve the compact evidence policy:
  - `policy=compact_summary_with_bounded_audit_samples`
  - `sample_limit_per_audit=5`
- Generation summaries now expose:
  - transition count
  - total audit sample count
  - total audit violation count
  - per-audit status
  - per-audit checked transition count
  - per-audit sample count
  - per-audit violation count
- Series aggregates now count:
  - observed evidence reports
  - total transitions
  - total audit samples
  - total audit violations
  - evidence status counts
  - per-audit status counts

## Explicitly Not Implemented

- No new transition persistence.
- No larger transition sample storage.
- No replay artifact.
- No failure reproduction runner.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Multi-generation summaries can state whether transition evidence exists.
- Series aggregates can count audit samples and violations without opening every full report.
- Reports remain compact because this task summarizes existing audit samples instead of adding raw transition dumps.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
- Direct assertion passed with `ARENA_TRANSITION_EVIDENCE_SUMMARY_ASSERTIONS_OK`.

## Follow-up

- Add replay or failure reproduction artifacts only after their schema, retention policy, and data source boundaries are documented.

## Progress Update 2026-05-04: Completeness Status

- `docs/tasks/model-training/arena-transition-evidence-completeness-status.md` now tracks `transition_evidence` in `experiment_record_completeness`.
- Episodes with compact transition evidence mark the field as `present`.
- Episodes without transitions keep the field explicit as `not_available`.
