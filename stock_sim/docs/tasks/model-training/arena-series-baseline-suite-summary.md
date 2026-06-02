# Arena Series Baseline Suite Summary

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/arena-series-research-acceptance-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review requires model results to be compared against a task-matched baseline suite. Arena episode reports already include `baseline_suite`, and research acceptance depends on it. Multi-generation summaries and aggregates should expose the same baseline-suite state directly so missing baselines are not hidden behind research acceptance failures.

This task carries baseline-suite metadata into generation summaries and series aggregates. It is report-only and does not change runtime execution, PBT parent selection, strict gate decisions, or checkpoint promotion.

## Scope

Implemented:

- Add `baseline_suite` to generation summaries.
- Add `aggregate.baseline_suite` to series aggregates.
- Preserve baseline-suite summary fields:
  - `task_name`
  - `status`
  - `present_kinds`
  - `missing_required`
  - required baseline kind/status rows
  - optional baseline kind/status/reason rows
- Count baseline-suite observations across generations.
- Count complete and incomplete baseline suites.
- Count baseline-suite statuses.
- Count present baseline kinds.
- Count missing required baseline kinds.
- Count required baseline kind/status pairs.
- Count optional baseline kind/status pairs.

## Explicitly Not Implemented

- No new baseline policy.
- No TWAP/VWAP schedule execution.
- No reward benchmark rewiring.
- No change to PBT parent selection.
- No change to strict gate decision rules.
- No automatic checkpoint promotion.

## Acceptance

- Generation summaries include baseline-suite status, present kinds, missing required kinds, and required/optional slots.
- Series aggregates count complete and incomplete baseline suites.
- Series aggregates count missing required baseline kinds.
- Series aggregates count optional TWAP/VWAP `not_available` slots.
- Existing research acceptance, strict gate, execution, and PBT aggregate fields remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_baseline_suite_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_research_acceptance_diagnostics`
- Direct baseline-suite summary assertion passed with `ARENA_SERIES_BASELINE_SUITE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Use `aggregate.baseline_suite.missing_required_counts` to identify recurring baseline-suite gaps.
- Keep TWAP/VWAP as explicit `not_available` slots until schedule execution inputs and runner are documented.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-benchmark-comparison-summary.md` adds benchmark-comparison summary and aggregate fields so candidate-baseline comparison availability can be read without opening each episode report.
