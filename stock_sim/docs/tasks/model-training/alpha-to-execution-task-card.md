# Alpha-to-Execution Task Card

_Created: 2026-05-03_

## Source

This task card is derived from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/contracts/runtime/model-observation-contract.md`
- `docs/contracts/runtime/model-action-contract.md`
- `docs/contracts/runtime/model-reward-contract.md`
- `docs/design/model-training-design.md`
- `docs/plan/multi-agent-training-roadmap.md`

## Task Name

`alpha_to_execution.v1`

## Purpose

The expert review recommends making the first production-grade model task an Alpha-to-Execution task, not a direct direction-alpha task.

This means `ppo_lstm_v1` should first learn how to convert a controlled alpha signal or target position into executable, lower-cost, lower-risk orders under the existing runtime constraints. The task is useful only if it improves execution quality against simple execution baselines. It is not evidence that the model has discovered real-market directional alpha.

## Non-Goals

- Do not add a new model family.
- Do not claim real-market alpha from synthetic Arena profit.
- Do not let the model directly modify price, account, position, order book, checkpoint, database rows, or GUI state.
- Do not bypass `services/order_service.py`, `services/account_service.py`, risk checks, matching, fees, settlement, T+1, or short-sale constraints.
- Do not use Arena leaderboard rank as research acceptance.

## Controlled Input

The task receives a controlled signal, not an unrestricted future return target.

### Initial Signal Shape

```text
alpha_signal:
  symbol: string
  as_of_step: integer or timestamp
  horizon_steps: integer
  direction: -1.0..1.0
  confidence: 0.0..1.0
  target_weight_hint: optional float
  source: oracle | noisy_oracle | rule | no_signal
```

### Rules

- `as_of_step` must be at or before the decision step.
- `source=no_signal` is required for reward-leak and exploit checks.
- `target_weight_hint` is an input hint, not a permission to bypass action validation.
- Future prices, final episode rank, hidden evaluation labels, and post-trade accounting fields are not allowed in the signal.

## Observation Mapping

The task uses existing `obs.v1` sections.

### Allowed `market`

- `symbol`
- `last_price`
- `volume`
- `turnover`
- `bid_levels`
- `ask_levels`
- `best_bid`
- `best_ask`
- `spread`
- `market_phase`
- time-valid bars or recent trade windows when already available through the observation builder

### Allowed `account`

- `account_id`
- `cash`
- `frozen_cash`
- `frozen_fee`
- `equity`
- `gross_exposure`
- `net_exposure`
- `positions`
- `frozen_qty`
- `borrowed_qty`
- available sell / short-related fields if supplied by runtime truth

### Allowed `context`

- `run_id`
- `arena_id`
- `episode_id`
- `step_index`
- `sim_day`
- `clock_running`
- `symbol_universe`
- `agent_id`
- `generation`
- controlled `alpha_signal` metadata

### Allowed `features`

- normalized return windows
- realized volatility proxies
- spread / imbalance features
- previous action summary
- execution progress summary for the same target

### Disallowed Observation Inputs

- GUI panel state, widget labels, selected row, or adapter rendering details.
- Final rank, final score, future bar, future trade, next snapshot, or post-decision fill data.
- Hidden evaluation split labels.
- Database-only aggregate fields unavailable at the decision time.
- Other agents' private future actions.

## Action Mapping

The task starts with existing `act.v1` actions.

### Phase A: Target Weight Execution

Use `action_type=target_weight` for the first pass because it is already supported by the current model-training path.

Required semantics:

- `target.account_id` must be the model account.
- `target.symbols` must be within the Arena universe.
- `payload.weights` expresses desired exposure, not an already accepted order.
- `constraints.max_gross_leverage`, `constraints.allow_short`, and `constraints.clip_to_limits` must be validated before dispatch.

### Phase B: Order Intent Execution

Use `action_type=order` when the task moves from portfolio rebalance to microstructure execution.

Required semantics:

- side
- order type
- price or limit offset
- quantity
- TIF
- optional cancel/replace fields once already supported by action contract/runtime flow

### Required Runtime Path

```text
model action
 -> act.v1 parse
 -> schema/semantic validation
 -> ModelBridge / runtime command translation
 -> order service
 -> risk/account/matching truth
 -> execution result
 -> rew.v1
 -> episode report
```

## Reward Mapping

The task uses `rew.v1` with an execution-aware profile.

### Required Components

- `delta_equity`
- `relative_alpha`
- `fee_penalty`
- `drawdown_penalty`
- `turnover_penalty`
- `inventory_penalty`
- execution-health metrics already present in Arena reports:
  - submitted order count
  - open order count
  - rejected order count
  - filled order count
  - fill ratio
  - notional fill ratio
  - filled notional

### Execution-Aware Additions To Specify Before Code Work

- arrival price
- realized fill price
- benchmark fill price
- implementation shortfall
- unfilled target penalty
- adverse selection proxy where data exists

These additions should be documented before implementation. They should extend reward/report semantics without silently changing the existing `relative_equity_risk_adjusted_v1` profile.

## Required Benchmarks

An Alpha-to-Execution experiment is incomplete unless it reports at least:

- no-trade / cash
- random constrained
- target-weight naive rebalance
- TWAP or VWAP when an execution schedule is available

Optional later baselines from the expert review:

- simplified Almgren-Chriss execution
- oracle-alpha plus naive execution
- rule-based market maker, only for a market-making task
- linear/logistic/GBDT, only for predictive feature tasks

## Failure Conditions

The task fails if any of the following is true:

- The model beats PPO peers but does not beat basic execution baselines.
- `source=no_signal` produces persistent high net reward after fees.
- Hidden seed/world performance collapses relative to training worlds.
- Profits concentrate in one symbol, one seed, one retail family, or one liquidity artifact.
- Reward improves mainly by increasing rejected orders, churn, mark-to-market artifacts, or unfilled exposure.
- Observation audit finds future or GUI-only fields.
- The model becomes PBT-parent eligible without hidden evaluation and exploit checks.

## Acceptance Criteria

- The task card is linked from future model-training implementation work.
- Experiments using this task clearly label themselves as `alpha_to_execution.v1`.
- Reports separate training leaderboard rank from research acceptance.
- Each report states the controlled signal source, benchmark set, reward profile, and world/seed identity.
- Model actions remain contract-valid and runtime-executed.
- No checkpoint is promoted as a robust parent solely from synthetic Arena leaderboard rank.

## First Implementation Checklist

- [ ] Add a docs-level mapping note from `alpha_to_execution.v1` to current `obs.v1`, `act.v1`, and `rew.v1`.
- [ ] Inventory current baseline support before adding new baseline code.
- [ ] Add report slots for benchmark comparison before changing `ppo_lstm_v1`.
- [ ] Add `source=no_signal` scenario support for reward-leak checks.
- [ ] Add hidden evaluation / exploit detector result placeholders to Arena experiment reports.
- [ ] Tighten strict PBT parent eligibility to require those placeholders once implemented.
