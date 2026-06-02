# Arena Series Research Acceptance Summary

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/arena-series-strict-gate-summary.md`
- `docs/tasks/model-training/arena-series-strict-gate-aggregate.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review requires Arena leaderboard rank to stay separate from research acceptance. Arena episode reports already include `research_acceptance`, but multi-generation summaries and aggregates need to surface the same status so report readers do not infer acceptance only from PBT or strict gate fields.

This task carries research acceptance metadata into generation summaries and series aggregates. It is report-only and does not change PBT parent selection, strict gate decisions, or checkpoint promotion.

## Scope

Implemented:

- Add `research_acceptance` to generation summaries.
- Add `aggregate.research_acceptance` to series aggregates.
- Preserve research acceptance fields:
  - `status`
  - `is_research_accepted`
  - `strict_parent_eligibility_allowed`
  - `reasons`
  - `required_sections`
  - `acceptance_lock.status`
  - `acceptance_lock.blocking_sections`
  - `acceptance_lock.reason`
- Count research acceptance observations across generations.
- Count accepted and rejected reports.
- Count strict-parent-allowed reports.
- Count research acceptance statuses.
- Count acceptance-lock statuses.
- Count acceptance-lock blocking sections.
- Count required-section status pairs.

## Explicitly Not Implemented

- No change to PBT parent selection.
- No change to strict gate decision rules.
- No automatic checkpoint promotion.
- No hidden-world, fee-world, impact-world, or no-signal-world runner.
- No conversion of unavailable or partial report slots into completed evidence.

## Acceptance

- Generation summaries include research acceptance status and lock fields when episode reports contain them.
- Series aggregates count research accepted and rejected reports.
- Series aggregates count acceptance-lock status and blocking sections.
- Series aggregates count required-section status pairs.
- Existing aggregate execution, PBT, and strict-gate fields remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_research_acceptance_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_strict_parent_gate_diagnostics`
- Direct research acceptance summary assertion passed with `ARENA_SERIES_RESEARCH_ACCEPTANCE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Use `aggregate.research_acceptance.lock_blocking_section_counts` to see recurring research-acceptance blockers across a series.
- Do not treat summary or aggregate diagnostics as research acceptance; they only expose the current report state.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-baseline-suite-summary.md` adds direct baseline-suite summary and aggregate fields so baseline-suite completeness does not have to be inferred from research acceptance.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-hidden-exploit-summary.md` adds direct hidden-evaluation and exploit-detector summary and aggregate fields so those required sections do not have to be inferred from research acceptance.
