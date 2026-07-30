# Hidden Evaluation Report Slots

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review requires hidden evaluation before Arena leaderboard rank can be treated as research acceptance or strict PBT parent eligibility. The current project has no documented hidden-world runner. This task replaces pure `not_implemented` hidden evaluation placeholders with explicit `not_available` report slots and required inputs.

This task does not run hidden worlds, paired worlds, or policy transfer experiments.

## Scope

Implemented:

- Change `hidden_evaluation.status` from `not_implemented` to `not_available`.
- Add `hidden_evaluation.reason=hidden_world_runner_not_implemented`.
- Preserve hidden split-level required inputs:
  - `unseen_seed`
  - `unseen_retail_mix`
  - `altered_fees`
  - `altered_liquidity_depth`
  - `altered_tick_or_spread_regime`
- Make `frozen_policy_hidden_seed` an explicit `not_available` check.
- Make `cross_world_transfer` an explicit `not_available` check.
- Add required inputs for both checks.
- Keep `research_acceptance.is_research_accepted=false`.
- Keep strict parent eligibility opt-in behavior unchanged.

`frozen_policy_hidden_seed` required inputs:

- `frozen_policy_checkpoint`
- `unseen_seed`
- `same_policy_episode_result`
- `hidden_world_episode_result`
- `base_world_hash`
- `hidden_world_hash`

`cross_world_transfer` required inputs:

- `source_world_result`
- `target_world_result`
- `same_policy_checkpoint`
- `source_world_hash`
- `target_world_hash`
- `transfer_metric_threshold`

## Explicitly Not Implemented

- No hidden-world runner.
- No frozen-policy hidden-seed episode execution.
- No paired-world transfer runner.
- No hidden split generation.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- `hidden_evaluation.status=not_available`.
- `frozen_policy_hidden_seed.status=not_available`.
- `cross_world_transfer.status=not_available`.
- Required inputs are machine-readable in the report.
- Research acceptance remains incomplete.

## Follow-up

- Implement hidden-world runner only after project documents define world-pool and hidden seed inputs.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-hidden-exploit-summary.md` carries hidden evaluation status, check status counts, and required input counts into Arena generation summaries and series aggregates. This is report-only and does not implement a hidden-world runner.
