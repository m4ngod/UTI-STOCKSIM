# Strict Parent Eligibility Opt In

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `app/services/model_population_service.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review requires PBT parent eligibility to depend on baseline comparison, hidden evaluation, risk/activity gates, and exploit flags. The project now has report sections for baseline suite, hidden evaluation, exploit detector, and research acceptance, but hidden/exploit checks are placeholders.

This task adds strict parent eligibility as an opt-in gate only. Default PBT behavior must remain unchanged.

## Strict Gate Rule

When strict mode is enabled:

```text
research_acceptance.is_research_accepted must be true
research_acceptance.required_sections.baseline_suite must be complete
research_acceptance.required_sections.hidden_evaluation must be complete
research_acceptance.required_sections.exploit_detector must be complete
```

If any condition fails, no model may become a PBT parent under strict mode.

## Scope Rules

- Do not change default PBT parent selection.
- Do not run hidden worlds.
- Do not run exploit checks.
- Do not treat placeholder sections as complete.
- Keep existing activity gates such as filled trades and notional fill ratio.

## Acceptance

- `PopulationEvolutionConfig` exposes strict mode as disabled by default.
- Strict mode can receive a research acceptance report.
- Strict mode rejects parents when hidden/exploit sections are `not_implemented`.
- Default mode keeps existing parent eligibility behavior.

## Explicitly Deferred

- Making strict mode the default.
- Computing real hidden evaluation results.
- Computing real exploit detector results.
- Baseline-relative score thresholds.

_Update 2026-05-03_: `docs/tasks/model-training/research-acceptance-lock-report.md` adds `research_acceptance.acceptance_lock` and `strict_parent_eligibility_allowed=false` to Arena reports. Strict parent eligibility remains opt-in only, and the lock stays `locked` until `baseline_suite`, `hidden_evaluation`, and `exploit_detector` are all `complete`.

_Update 2026-05-03_: `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md` makes the opt-in strict gate read `acceptance_lock`. Strict mode now requires an open lock, no blocking sections, `strict_parent_eligibility_allowed=true`, research acceptance true, and all required sections complete.
