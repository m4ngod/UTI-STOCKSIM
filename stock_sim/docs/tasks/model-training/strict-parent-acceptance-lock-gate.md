# Strict Parent Acceptance Lock Gate

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/hidden-evaluation-report-slots.md`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `app/services/model_population_service.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The strict PBT parent gate already exists as an opt-in path. Task 36 added `research_acceptance.acceptance_lock` to Arena reports so incomplete hidden/exploit evidence cannot be mistaken for research acceptance.

This task connects that report lock to the existing strict parent gate. The change applies only when `strict_parent_eligibility=true`; default PBT parent selection remains unchanged.

## Scope

Implemented:

- Strict parent eligibility now reads `research_acceptance.acceptance_lock`.
- Strict parent eligibility requires `acceptance_lock.status=open`.
- Strict parent eligibility rejects any non-empty `acceptance_lock.blocking_sections`.
- Strict parent eligibility requires `research_acceptance.strict_parent_eligibility_allowed=true`.
- Strict parent gate report output now includes:
  - `strict_parent_eligibility_allowed`
  - `acceptance_lock.status`
  - `acceptance_lock.blocking_sections`
  - `acceptance_lock.reason`
- Default `strict_parent_eligibility=false` behavior still passes the strict gate.

## Gate Rule

When strict parent eligibility is enabled, all of the following must hold:

```text
research_acceptance.is_research_accepted == true
research_acceptance.strict_parent_eligibility_allowed == true
research_acceptance.acceptance_lock.status == open
research_acceptance.acceptance_lock.blocking_sections is empty
research_acceptance.required_sections.baseline_suite == complete
research_acceptance.required_sections.hidden_evaluation == complete
research_acceptance.required_sections.exploit_detector == complete
```

If any condition fails, no model may become a PBT parent under strict mode.

## Explicitly Not Implemented

- No change to default PBT behavior.
- No automatic checkpoint promotion.
- No hidden-world runner.
- No fee-world, impact-world, or no-signal-world runner.
- No conversion of `not_available`, `partial`, or `failed` report slots into `complete`.

## Acceptance

- Strict mode rejects a report with `acceptance_lock.status=locked` even if required sections are manually marked `complete`.
- Strict mode passes only when research acceptance is true, strict eligibility is allowed, the lock is open, there are no blocking sections, and all required sections are complete.
- Default strict-disabled mode still passes the strict gate.

## Verification

- Direct strict parent acceptance-lock assertion passed with `STRICT_PARENT_ACCEPTANCE_LOCK_ASSERTIONS_OK`.
- `app/services/model_population_service.py` and `tests/runtime/test_pbt_lineage.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in `docs/current-work-status/model-training.md`.

## Follow-up

- Keep `strict_parent_eligibility_allowed=false` in Arena reports until hidden evaluation and exploit detector outputs can become complete.
- Only make strict parent eligibility useful for promotion after project documents define the missing hidden/exploit inputs and runners.

_Update 2026-05-03_: `docs/tasks/model-training/strict-parent-gate-diagnostics.md` adds `strict_parent_gate.reason` and `strict_parent_gate.blocking_reasons` so strict-gate failures are machine-readable without changing the gate decision.
