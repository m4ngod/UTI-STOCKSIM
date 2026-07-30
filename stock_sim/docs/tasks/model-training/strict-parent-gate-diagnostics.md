# Strict Parent Gate Diagnostics

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`
- `app/services/model_population_service.py`
- `tests/runtime/test_pbt_lineage.py`

## Purpose

The strict PBT parent gate now reads `research_acceptance.acceptance_lock`. When strict mode blocks parent eligibility, callers should not have to infer the cause from several separate fields.

This task adds report-side diagnostics to the existing strict parent gate output. It does not change the gate decision; it only exposes the reasons already implied by the documented gate rule.

## Scope

Implemented:

- Add `strict_parent_gate.blocking_reasons`.
- Add `strict_parent_gate.reason`.
- Preserve `strict_parent_gate.passes` behavior.
- Preserve default `strict_parent_eligibility=false` behavior.
- Keep the strict gate opt-in only.

Diagnostic reasons:

- `strict_parent_gate_disabled`
- `strict_parent_gate_passed`
- `strict_parent_gate_blocked`
- `research_acceptance_not_true`
- `strict_parent_eligibility_not_allowed`
- `acceptance_lock_not_open`
- `acceptance_lock_has_blocking_sections`
- `baseline_suite_not_complete`
- `hidden_evaluation_not_complete`
- `exploit_detector_not_complete`

## Explicitly Not Implemented

- No change to default PBT behavior.
- No automatic checkpoint promotion.
- No hidden-world runner.
- No fee-world, impact-world, or no-signal-world runner.
- No conversion of unavailable or partial report slots into completed evidence.

## Acceptance

- Strict-disabled mode reports `reason=strict_parent_gate_disabled` and empty `blocking_reasons`.
- Locked strict mode reports `reason=strict_parent_gate_blocked`.
- Locked strict mode includes lock-related blocking reasons.
- Fully open and accepted strict mode reports `reason=strict_parent_gate_passed` and empty `blocking_reasons`.

## Verification

- Direct strict parent gate diagnostic assertion passed with `STRICT_PARENT_GATE_DIAGNOSTIC_ASSERTIONS_OK`.
- `app/services/model_population_service.py` and `tests/runtime/test_pbt_lineage.py` passed `py_compile`.
- Targeted pytest collection for the two strict-gate tests is still blocked in this environment because bundled Python 3.12 cannot load the NumPy C extensions from the project `.venv`.

## Follow-up

- Keep using `blocking_reasons` in future reports and UI summaries instead of inferring failures from free-text messages.
- Do not make strict parent eligibility useful for promotion until hidden evaluation and exploit detector outputs can become complete.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-strict-gate-summary.md` carries `strict_parent_gate.reason`, `blocking_reasons`, and acceptance-lock summary fields into Arena generation summaries. This is report-only and does not change strict gate decisions.
