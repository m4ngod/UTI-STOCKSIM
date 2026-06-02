# Arena Series Strict Gate Aggregate

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-series-strict-gate-summary.md`
- `docs/tasks/model-training/strict-parent-gate-diagnostics.md`
- `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena generation summaries now expose `pbt.strict_parent_gate` diagnostics per generation. A multi-generation series also has an `aggregate` section, but it previously did not count strict gate outcomes or blocker frequencies.

This task adds aggregate counters for strict PBT parent gate diagnostics. The counters are report-only and do not change PBT parent selection, strict gate decisions, or checkpoint promotion.

## Scope

Implemented:

- Add `aggregate.strict_parent_gate`.
- Count strict gate observations across reports.
- Count strict gate enabled, passed, blocked, and disabled cases.
- Count `blocking_reasons` across generations.
- Count acceptance-lock blocking sections across generations.
- Preserve existing aggregate totals for transitions, execution health, checkpoints, lineage, applied agents, winners, losers, and final models.

Aggregate fields:

- `observed_count`
- `enabled_count`
- `passed_count`
- `blocked_count`
- `disabled_count`
- `blocking_reason_counts`
- `lock_blocking_section_counts`

## Explicitly Not Implemented

- No change to PBT parent selection.
- No change to strict gate decision rules.
- No automatic checkpoint promotion.
- No hidden-world, fee-world, impact-world, or no-signal-world runner.
- No conversion of unavailable or partial report slots into completed evidence.

## Acceptance

- Series aggregate counts strict gate observations when PBT results include `strict_parent_gate`.
- Series aggregate records blocked and passed counts separately.
- Series aggregate counts `blocking_reasons`.
- Series aggregate counts acceptance-lock blocking section names.
- Existing aggregate execution and PBT counts remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
- Direct series aggregate assertion passed with `ARENA_SERIES_STRICT_GATE_AGGREGATE_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Use `aggregate.strict_parent_gate.blocking_reason_counts` to see recurring strict-gate blockers across multiple generations.
- Do not treat aggregate diagnostics as research acceptance; they only summarize report-side gate outcomes.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-research-acceptance-summary.md` adds direct `research_acceptance` summary and aggregate fields so research acceptance does not have to be inferred from strict-gate diagnostics.
