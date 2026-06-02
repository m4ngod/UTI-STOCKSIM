# Arena Series Benchmark Comparison Summary

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-series-baseline-suite-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review requires candidate models to be read relative to task-matched baselines, not only by Arena rank. Episode reports already include `benchmark_comparison`, but generation summaries and series aggregates should expose whether benchmark comparison is available and how many candidate-baseline comparisons were recorded.

This task carries benchmark comparison metadata into generation summaries and series aggregates. It is report-only and does not change model actions, rewards, runtime execution, PBT parent selection, strict gate decisions, or checkpoint promotion.

## Scope

Implemented:

- Add `benchmark_comparison` to generation summaries.
- Add `aggregate.benchmark_comparison` to series aggregates.
- Preserve benchmark comparison summary fields:
  - `status`
  - `baseline_kinds`
  - `candidate_count`
  - `candidate_ids`
  - `candidate_baseline_pair_count`
- Count benchmark comparison observations across generations.
- Count benchmark comparison statuses.
- Count baseline kinds used in benchmark comparisons.
- Sum candidate count across observed reports.
- Sum candidate-baseline pair count across observed reports.

## Explicitly Not Implemented

- No new baseline policy.
- No TWAP/VWAP schedule execution.
- No reward benchmark rewiring.
- No baseline-relative PBT parent gate.
- No change to strict gate decision rules.
- No automatic checkpoint promotion.

## Acceptance

- Generation summaries include benchmark comparison status and baseline kinds when episode reports contain them.
- Generation summaries include candidate and candidate-baseline pair counts.
- Series aggregates count `available` and `missing_baselines` benchmark comparison statuses.
- Series aggregates count baseline kinds used in benchmark comparisons.
- Existing baseline-suite, research-acceptance, strict-gate, execution, and PBT aggregate fields remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_benchmark_comparison_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_baseline_suite_diagnostics`
- Direct benchmark comparison summary assertion passed with `ARENA_SERIES_BENCHMARK_COMPARISON_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Use `aggregate.benchmark_comparison.status_counts` to identify recurring missing-baseline states.
- Keep reward benchmark rewiring deferred until project documents define the required reward semantics.
