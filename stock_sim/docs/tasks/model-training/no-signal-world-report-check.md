# No Signal World Report Check

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `app/services/arena_experiment_runner.py`

## Purpose

The controlled no-signal scenario defines the first real exploit detector target: `exploit_detector.no_signal_world`.

This task adds a minimal report execution path for that check. The path is intentionally explicit-input only: normal Arena runs continue to emit the previous placeholder unless a caller supplies `ArenaExperimentConfig.no_signal_check`.

## Scope

Implemented:

- Add `ArenaExperimentConfig.no_signal_check`, defaulting to `None`.
- Keep default `exploit_detector.no_signal_world` as `not_implemented` when no check input exists.
- When `no_signal_check` is provided, emit a machine-readable `no_signal_world` check with `pass`, `fail`, or `warn`.
- Keep `exploit_detector.status` as non-complete:
  - `partial` when the no-signal check runs and does not fail.
  - `failed` when the no-signal check fails.
- Keep `research_acceptance.is_research_accepted=false`.

Explicitly not implemented:

- No no-signal world generation.
- No reward or accounting changes.
- No hidden evaluation.
- No fee, impact, timestamp, mark-to-market, or order-anomaly checks.
- No strict PBT default behavior change.

## Check Contract

Required contract inputs:

- `alpha_signal_source`
- `direction`
- `confidence`
- `target_weight_hint`
- `no_signal_tolerance`
- `fee_model`
- `world_seed_or_hash`
- `observation_audit_status`

Metric inputs:

- `net_reward_after_fees`
- `excess_score_vs_no_trade_cash`

## Status Rule

`pass`:

- `alpha_signal_source=no_signal`
- `direction=0.0`
- `confidence=0.0`
- `target_weight_hint=null`
- `observation_audit_status` is pass-like.
- `net_reward_after_fees <= no_signal_tolerance`
- `excess_score_vs_no_trade_cash <= no_signal_tolerance`

`fail`:

- Any supplied alpha contract field violates the no-signal shape.
- Observation audit is supplied and not pass-like.
- Net reward after fees is above tolerance.
- Excess score versus no-trade cash is above tolerance.

`warn`:

- No explicit failure exists, but required contract inputs or metric inputs are missing.

## Acceptance

- Default reports remain compatible with the previous placeholder shape.
- Explicit no-signal check input produces `pass`.
- Bad no-signal check input produces `fail`.
- Research acceptance remains incomplete because hidden evaluation and other exploit checks are still incomplete.

## Follow-up

- Add a minimal no-signal run harness so the input payload can be produced by an actual controlled run rather than supplied explicitly.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/no-signal-episode-payload-derivation.md` adds a first report-side derivation harness for episodes explicitly marked `alpha_to_execution.no_signal.v1`. It derives a payload from completed episode results, but still does not create a no-signal world or automatic observation audit.
