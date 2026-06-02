# Target Weight Naive Rebalance Baseline

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/contracts/runtime/model-action-contract.md`
- `app/services/model_registry_service.py`
- `rl/model_bridge.py`

## Purpose

The expert review requires Alpha-to-Execution results to be compared with simple, task-matched baselines before PPO/LSTM output is treated as useful. The baseline inventory lists `target_weight_naive_rebalance` as the next required baseline after no-trade and random-constrained rows.

This task defines the first deterministic target-weight baseline without adding a new model family. It emits an existing `act.v1 target_weight` action and uses the same runtime order/account/matching path as trainable models.

## Baseline Id

`target_weight_naive_rebalance_v1`

## Semantics

- Use the current `obs.v1.context.symbol_universe`.
- Allocate a fixed long-only gross budget equally across all visible symbols.
- Keep a cash buffer to avoid full-equity churn.
- Emit only `act.v1 target_weight`.
- Do not learn.
- Do not become a PBT parent.
- Do not bypass `ActionParser`, `ModelBridge`, order service, risk/account semantics, matching, fees, settlement, or T+1 constraints.

## Initial Action Shape

```text
contract_version: act.v1
action_type: target_weight
target:
  account_id: context.agent_id
  symbols: context.symbol_universe
payload:
  weights:
    <symbol>: equal_budget_per_symbol
  cash_buffer_ratio: 0.05
  rebalance_mode: market
constraints:
  allow_short: false
  max_gross_leverage: 1.0
  clip_to_limits: true
meta:
  model_id: target_weight_naive_rebalance_v1
  baseline_kind: target_weight_naive_rebalance
```

## Acceptance

- `ModelRegistryService.list_models()` includes `target_weight_naive_rebalance_v1`.
- `ModelRegistryService.create_policy("target_weight_naive_rebalance_v1")` returns a policy that emits valid `act.v1 target_weight`.
- Default Arena experiments include this model as a baseline row.
- Default PBT exclusions include this model id.
- Arena `baseline_suite.required` can mark `target_weight_naive_rebalance` as present when the baseline participates in the episode.

## Explicitly Deferred

- TWAP/VWAP scheduling.
- Arrival-price and implementation-shortfall reward wiring.
- Oracle-alpha plus naive execution.
- Strict baseline-relative PBT parent eligibility.
