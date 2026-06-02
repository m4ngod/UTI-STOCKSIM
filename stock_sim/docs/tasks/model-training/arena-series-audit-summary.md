# Arena Series Audit Summary

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/runtime-observation-audit-report.md`
- `docs/tasks/model-training/timestamp-audit-report-check.md`
- `docs/tasks/model-training/mark-to-market-audit-report-check.md`
- `docs/tasks/model-training/order-anomaly-audit-report-check.md`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `docs/tasks/model-training/arena-series-hidden-exploit-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Several exploit-related audit sections now exist at the episode level: runtime observation audit, timestamp audit, mark-to-market audit, order anomaly audit, fee sensitivity, and impact sensitivity. The exploit detector aggregates their pass/fail/availability into check rows, but multi-generation summaries should also expose the audit sections directly.

This task carries episode audit metadata into generation summaries and series aggregates. It is report-only and does not add new audit logic or change training, execution, reward, account, PBT, or checkpoint behavior.

## Scope

Implemented:

- Add `audit_summary` to generation summaries.
- Add `aggregate.audit_summary` to series aggregates.
- Summarize these episode-level sections:
  - `runtime_observation_audit`
  - `fee_sensitivity`
  - `impact_sensitivity`
  - `timestamp_audit`
  - `mark_to_market_audit`
  - `order_anomaly_audit`
- Preserve audit summary fields:
  - `name`
  - `status`
  - `reason`
  - `scope`
  - `transition_count`
  - `checked_transition_count`
  - `result_count`
  - `checked_result_count`
  - `violation_count`
  - `required_input_count`
- Count audit observations, transition/result totals, violations, required inputs, status counts by audit, and reason counts by audit.

## Explicitly Not Implemented

- No new audit check.
- No hidden-world runner.
- No fee-world, impact-world, or no-signal-world runner.
- No reward benchmark rewiring.
- No change to PBT parent selection.
- No automatic checkpoint promotion.

## Acceptance

- Generation summaries include audit status and count fields for existing episode audit sections.
- Series aggregates count audit statuses by audit name.
- Series aggregates count audit reasons by audit name.
- Series aggregates sum transition, checked transition, result, checked result, violation, and required-input counts.
- Existing baseline-suite, benchmark-comparison, hidden/exploit, research-acceptance, strict-gate, execution, and PBT aggregate fields remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_episode_audit_summaries`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_hidden_and_exploit_diagnostics`
- Direct audit summary assertion passed with `ARENA_SERIES_AUDIT_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Use `aggregate.audit_summary.status_counts_by_audit` to identify recurring audit availability or failure states.
- Keep fee/impact sensitivity as `not_available` until paired-world inputs and runners are documented.
