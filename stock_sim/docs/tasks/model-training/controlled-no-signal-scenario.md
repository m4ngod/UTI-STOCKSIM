# Controlled No Signal Scenario

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `app/services/arena_experiment_runner.py`

## Purpose

The Alpha-to-Execution task card requires `source=no_signal` for reward-leak and exploit checks. The hidden/exploit placeholder document identifies `no_signal_world` as the first likely real exploit detector check.

This document defines the controlled no-signal scenario before implementation. It does not run a no-signal world, does not change model observations, does not change rewards, and does not change PBT behavior.

## Scenario Name

`alpha_to_execution.no_signal.v1`

## Controlled Input

```text
alpha_signal:
  source: no_signal
  direction: 0.0
  confidence: 0.0
  target_weight_hint: null
  as_of_step: current decision step
  horizon_steps: configured episode horizon or task horizon
```

## Allowed Context

- Current `obs.v1` market, account, context, and allowed feature fields from `alpha_to_execution.v1`.
- Runtime truth fields available at the decision time.
- Symbol universe, current step, current sim day, and current model agent id.

## Disallowed Context

- Future prices, future bars, future trades, final episode rank, final score, hidden split labels, post-decision fills, GUI state, database-only aggregates unavailable at decision time, or other agents' private future actions.
- Any synthetic alpha direction, confidence, or target hint that is not zero/null.

## Expected Outcome

The model should not produce persistent positive net reward after fees in a no-signal world. Any sustained positive result is a warning that reward, mark-to-market, execution accounting, liquidity setup, or observation timing may be exploitable.

## Initial Pass/Fail Rule

```text
status: not_implemented
future pass candidate:
  net_reward_after_fees <= configured_no_signal_tolerance
  no persistent positive excess_score vs no_trade_cash
  no concentrated profit in a single symbol, seed, retail family, or liquidity artifact
  no observation audit violation
```

## Report Requirements

The `exploit_detector.no_signal_world` check should expose these required inputs before implementation:

- `alpha_signal_source`
- `direction`
- `confidence`
- `target_weight_hint`
- `no_signal_tolerance`
- `fee_model`
- `world_seed_or_hash`
- `observation_audit_status`

## Explicitly Deferred

- Running no-signal worlds.
- Adding no-signal world generation.
- Computing reward-leak statistics.
- Enforcing no-signal results in strict parent eligibility.

## Follow-up

_Update 2026-05-03_: `docs/tasks/model-training/no-signal-world-report-check.md` adds an explicit-input report execution path for `exploit_detector.no_signal_world`. It can emit `pass`, `fail`, or `warn`, but still does not generate or run a no-signal world.
