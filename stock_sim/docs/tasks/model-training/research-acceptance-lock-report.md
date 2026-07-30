# Research Acceptance Lock Report

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `docs/tasks/model-training/hidden-evaluation-report-slots.md`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `app/services/arena_experiment_runner.py`
- `app/services/model_population_service.py`

## Purpose

The project now reports many required sections as `not_available`, `partial`, or `failed`. These statuses must not be mistaken for research acceptance or strict PBT parent eligibility.

This task adds an explicit `research_acceptance.acceptance_lock` object to Arena reports. The lock lists which required sections are still blocking research acceptance and strict parent eligibility.

This does not change PBT default behavior and does not promote any checkpoint.

## Scope

Implemented:

- Add `research_acceptance.acceptance_lock`.
- Preserve `research_acceptance.status=incomplete`.
- Preserve `research_acceptance.is_research_accepted=false`.
- Add `research_acceptance.strict_parent_eligibility_allowed=false`.
- Record the required sections:
  - `baseline_suite`
  - `hidden_evaluation`
  - `exploit_detector`
- Record blocking sections when any required section is not `complete`.
- Keep strict parent eligibility default as `opt_in_only`.

Lock fields:

- `status`: `locked` or `open`.
- `required_for`: `research_acceptance`, `strict_parent_eligibility`.
- `complete_required_sections`: the sections that must be complete.
- `blocking_sections`: required sections that are not complete.
- `strict_parent_eligibility_default`: `opt_in_only`.
- `reason`: lock reason.

## Explicitly Not Implemented

- No change to default PBT behavior.
- No automatic checkpoint promotion.
- No conversion of `not_available` / `partial` / `failed` into `complete`.
- No hidden-world, fee-world, impact-world, or no-signal-world execution.

## Acceptance

- Reports include `research_acceptance.acceptance_lock`.
- `acceptance_lock.status=locked` when hidden evaluation or exploit detector is not complete.
- `acceptance_lock.blocking_sections` lists non-complete sections.
- `strict_parent_eligibility_allowed=false`.
- Research acceptance remains incomplete.

## Verification

- Direct research acceptance lock assertion passed with `RESEARCH_ACCEPTANCE_LOCK_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in `docs/current-work-status/model-training.md`.

## Follow-up

- Keep updating blocking sections as hidden/exploit checks become real.
- Only allow strict parent eligibility when all required sections are complete and `is_research_accepted=true`.

_Update 2026-05-03_: `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md` connects this report lock to the opt-in strict PBT parent gate. The default PBT path remains unchanged, and strict mode now rejects locked or blocked research acceptance reports.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-research-acceptance-summary.md` carries research acceptance status and acceptance-lock blockers into Arena generation summaries and series aggregates. This is report-only and does not change acceptance or PBT behavior.
