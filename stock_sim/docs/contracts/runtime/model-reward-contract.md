# UTI-STOCKSIM Model Reward Contract

_Created: 2026-04-26_

## Purpose

`rew.v1` defines the reward payload returned by the platform after a model action is parsed and executed. The reward is not only final profit. It combines account equity change with risk and behavior penalties so model training does not collapse into pure gambling.

## Top-Level Shape

```python
{
  "reward_version": "rew.v1",
  "step_reward": 0.012,
  "components": {
    "delta_equity": 0.018,
    "relative_alpha": 0.006,
    "realized_pnl": 0.004,
    "unrealized_pnl": 0.014,
    "fee_penalty": -0.002,
    "drawdown_penalty": -0.003,
    "turnover_penalty": -0.001,
    "inventory_penalty": 0.0
  },
  "meta": {
    "reward_profile": "relative_equity_risk_adjusted_v1",
    "action_type": "target_weight"
  }
}
```

## Current Code Baseline

- `rl/reward_builder.py` implements the first `rew.v1` builder.
- The current default profile is `relative_equity_risk_adjusted_v1`.
- Inputs are previous/current account snapshots, parsed action, execution result, and optional benchmark return.
- Components currently include equity return, relative alpha, fees, drawdown, turnover, and inventory exposure.

## Design Rules

- Keep `reward_version` stable and explicit.
- Add new reward profiles through `meta.reward_profile` rather than silently changing old semantics.
- Do not use final equity alone as the training signal.
- Keep penalties inspectable as separate components so bad training behavior can be diagnosed.

## Next Steps

- Persist per-step reward records in episode reports.
- Add benchmark return from the same symbol universe instead of passing `0.0`.
- Add concentration and survival components once model episode state exists.
