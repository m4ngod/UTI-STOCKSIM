# Arena Series Strict Gate Summary

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/strict-parent-gate-diagnostics.md`
- `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `app/services/arena_experiment_runner.py`
- `app/services/model_population_service.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The strict PBT parent gate already reports `reason` and `blocking_reasons`. Arena multi-generation reports summarize each generation through `_generation_summary`, but the summary previously exposed only winners, losers, checkpoint counts, and skip reason.

This task carries the existing strict gate diagnostics into the generation summary so series reports can show why strict PBT parent eligibility was blocked without requiring callers to open each full episode report.

## Scope

Implemented:

- Add `pbt.strict_parent_gate` to generation summaries.
- Preserve existing PBT summary fields:
  - winners
  - losers
  - parent eligible agents
  - checkpoint count
  - lineage count
  - applied count
  - skipped
  - reason
- Include strict gate summary fields:
  - `enabled`
  - `passes`
  - `reason`
  - `blocking_reasons`
  - `acceptance_lock.status`
  - `acceptance_lock.blocking_sections`
  - `acceptance_lock.reason`

## Explicitly Not Implemented

- No change to PBT parent selection.
- No change to strict gate decision rules.
- No automatic checkpoint promotion.
- No hidden-world, fee-world, impact-world, or no-signal-world runner.
- No conversion of unavailable or partial report slots into completed evidence.

## Acceptance

- A generation summary includes strict parent gate diagnostics when the PBT result contains them.
- Locked strict gate summaries preserve `blocking_reasons`.
- Locked strict gate summaries preserve `acceptance_lock.blocking_sections`.
- Existing generation summary PBT counts remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
- Direct generation summary assertion passed with `ARENA_SERIES_STRICT_GATE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Keep using summary-level `pbt.strict_parent_gate.blocking_reasons` for future report readers.
- Do not treat summary diagnostics as research acceptance; they only explain why strict parent eligibility did or did not pass.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-strict-gate-aggregate.md` adds `aggregate.strict_parent_gate` counters so repeated strict-gate blockers can be seen across a multi-generation series.
