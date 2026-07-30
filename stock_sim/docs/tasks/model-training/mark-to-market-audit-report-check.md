# Mark To Market Audit Report Check

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/timestamp-audit-report-check.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `persistence/models_training.py`
- `services/training_episode_service.py`
- `rl/reward_builder.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review requires exploit checks before Arena leaderboard rank can be treated as research acceptance. `mark_to_market_audit` was previously only a placeholder. This task adds the first report-side accounting consistency check using existing episode result and transition reward data.

This is not a new valuation engine. It does not recompute order books, prices, account equity, or rewards.

## Scope

Implemented:

- Add `mark_to_market_audit` to Arena episode details.
- Read existing Arena episode result rows.
- Optionally read persisted transition `reward_json` rows when available.
- Check:
  - `equity_start` exists and is positive.
  - `equity_end` exists.
  - `reward_total` exists.
  - `fee_total` exists and is non-negative.
  - `max_drawdown` is non-negative.
  - `equity_return == (equity_end - equity_start) / equity_start`.
  - `score == equity_return + reward_total - max_drawdown`.
  - `reward_total` matches summed transition `step_reward` when transition rewards exist for the agent.
- Add `mark_to_market_audit` to `exploit_detector.checks`.
- Set `exploit_detector.status=failed` when this audit fails.
- Keep research acceptance incomplete.

Status values:

- `not_available`: no episode result rows exist.
- `pass`: all implemented accounting checks pass.
- `fail`: one or more implemented accounting checks fail.

## Explicitly Not Implemented

- No independent market-price replay.
- No account ledger reconstruction.
- No order-book valuation.
- No reward-builder rewrite.
- No mark-to-market recalculation from raw positions.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- Episodes with no result rows report `mark_to_market_audit.status=not_available`.
- Episodes with internally consistent result rows report `mark_to_market_audit.status=pass`.
- Episodes with score, equity-return, fee, drawdown, or transition reward mismatches report `mark_to_market_audit.status=fail`.
- `mark_to_market_audit` is visible under `exploit_detector.checks`.
- Research acceptance remains incomplete.

## Follow-up

- Add deeper account ledger reconstruction only if project documents define the required ledger inputs.
- Add order anomaly audit as the next report-side exploit detector check.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/order-anomaly-audit-report-check.md` promotes `order_anomaly_audit` from a placeholder to a minimal report-side execution-health consistency check over persisted transition execution payloads and episode result metrics.
