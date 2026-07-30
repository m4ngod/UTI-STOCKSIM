# Order Anomaly Audit Report Check

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/mark-to-market-audit-report-check.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `persistence/models_training.py`
- `services/training_episode_service.py`
- `rl/reward_builder.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review warns that Arena reward can be exploited by rejected orders, churn, unfilled exposure, and execution artifacts. `order_anomaly_audit` was previously only a placeholder. This task adds the first report-side order anomaly check using existing persisted transition execution payloads and episode result execution-health metrics.

This task does not change order execution, matching, account state, risk control, or rewards.

## Scope

Implemented:

- Add `order_anomaly_audit` to Arena episode details.
- Read persisted `ModelTransition.execution_json` rows.
- Recompute minimal execution-health metrics from persisted execution payloads:
  - submitted order count
  - filled order count
  - open order count
  - rejected order count
  - trade count
  - submitted notional
  - filled notional
  - open order notional
- Flag malformed execution payloads:
  - execution is not an object
  - `orders` is not a list
  - `trades` is not a list
  - order is not an object
  - negative order qty or price
  - negative filled qty
  - negative trade qty or price
  - filled/open/rejected counts exceed submitted order count
- Compare recomputed metrics with episode result `execution_health` when result rows exist for the agent.
- Add `order_anomaly_audit` to `exploit_detector.checks`.
- Set `exploit_detector.status=failed` when this audit fails.
- Keep research acceptance incomplete.

Status values:

- `not_available`: no persisted model transitions exist.
- `pass`: all implemented execution-health checks pass.
- `fail`: one or more implemented checks fail.

## Explicitly Not Implemented

- No matching-engine replay.
- No risk-control replay.
- No cancellation lifecycle reconstruction.
- No churn-rate threshold.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- Episodes with no transitions report `order_anomaly_audit.status=not_available`.
- Episodes with internally consistent execution payloads and result metrics report `order_anomaly_audit.status=pass`.
- Episodes with malformed execution payloads or result metric mismatches report `order_anomaly_audit.status=fail`.
- `order_anomaly_audit` is visible under `exploit_detector.checks`.
- Research acceptance remains incomplete.

## Follow-up

- Add churn-rate thresholds only after project documents define safe limits.
- Add fee and impact sensitivity report checks next.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md` replaces pure fee and impact placeholders with explicit `not_available` report slots and required inputs. No altered fee or liquidity-depth worlds have been implemented.
