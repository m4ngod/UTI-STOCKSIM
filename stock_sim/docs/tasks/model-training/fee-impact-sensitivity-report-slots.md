# Fee Impact Sensitivity Report Slots

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/order-anomaly-audit-report-check.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review requires fee and impact sensitivity checks before Arena leaderboard rank can be treated as research acceptance. Real sensitivity checks require paired worlds with altered fees or altered liquidity/impact assumptions. Those worlds do not exist yet in the current project documents.

This task replaces pure placeholders with explicit `not_available` report slots and required inputs. It does not run new worlds and does not change reward, execution, account, or PBT behavior.

## Scope

Implemented:

- Add `fee_sensitivity` report slot to Arena episode details and `exploit_detector.checks`.
- Add `impact_sensitivity` report slot to Arena episode details and `exploit_detector.checks`.
- Mark both slots as `not_available`.
- Include machine-readable reasons:
  - `fee_variant_worlds_not_implemented`
  - `liquidity_depth_variant_worlds_not_implemented`
- Include required inputs for future implementation.
- Keep research acceptance incomplete.

Fee sensitivity required inputs:

- `base_fee_model`
- `altered_fee_model`
- `same_policy_episode_result`
- `same_seed_or_world_hash`
- `base_net_reward_after_fees`
- `altered_net_reward_after_fees`
- `base_fill_and_turnover_metrics`
- `altered_fill_and_turnover_metrics`

Impact sensitivity required inputs:

- `base_liquidity_depth_or_impact_model`
- `altered_liquidity_depth_or_impact_model`
- `same_policy_episode_result`
- `same_seed_or_world_hash`
- `base_slippage_or_fill_price_metrics`
- `altered_slippage_or_fill_price_metrics`
- `base_fill_and_turnover_metrics`
- `altered_fill_and_turnover_metrics`

## Explicitly Not Implemented

- No altered fee world.
- No altered liquidity depth world.
- No impact model replay.
- No same-policy paired-world runner.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- `fee_sensitivity` appears under `exploit_detector.checks` with `status=not_available`.
- `impact_sensitivity` appears under `exploit_detector.checks` with `status=not_available`.
- Both slots expose required inputs for future implementation.
- Research acceptance remains incomplete.

## Follow-up

- Implement paired-world fee sensitivity only after the project has a documented altered-fee world runner.
- Implement paired-world impact sensitivity only after the project has documented liquidity-depth or impact-model variant inputs.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/hidden-evaluation-report-slots.md` applies the same explicit `not_available` pattern to hidden evaluation and its frozen-policy / cross-world-transfer checks.
