# No Signal Episode Payload Derivation

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `docs/tasks/model-training/no-signal-world-report-check.md`
- `app/services/arena_experiment_runner.py`

## Purpose

`no_signal_world` now has an explicit-input report check. The next safe step is to let Arena reports derive that input from an existing episode result when the episode is explicitly marked as `alpha_to_execution.no_signal.v1`.

This is a report harness only. It does not generate a new no-signal world, does not alter model observation, does not alter reward, and does not change PBT behavior.

## Scope

Implemented:

- Add report-side derivation for `no_signal_check` when:
  - `ArenaExperimentConfig.no_signal_check` is not supplied.
  - `ArenaExperimentConfig.task_name == alpha_to_execution.no_signal.v1`.
  - The completed episode has at least one candidate result.
- The derived payload uses:
  - fixed no-signal alpha contract fields:
    - `alpha_signal_source=no_signal`
    - `direction=0.0`
    - `confidence=0.0`
    - `target_weight_hint=null`
  - `ArenaExperimentConfig.no_signal_tolerance`
  - `ArenaExperimentConfig.no_signal_fee_model` or the active reward profile
  - episode id / config id as `world_seed_or_hash`
  - candidate `reward_total - fee_total` as `net_reward_after_fees`
  - candidate score minus `no_trade_cash` score as `excess_score_vs_no_trade_cash` when the no-trade baseline exists
  - `ArenaExperimentConfig.no_signal_observation_audit_status` when supplied
- Manual `ArenaExperimentConfig.no_signal_check` still takes precedence.

Explicitly not implemented:

- No synthetic no-signal world creation.
- No automatic observation audit.
- No hidden split.
- No fee/impact/timestamp/mark-to-market/order-anomaly checks.
- No strict PBT default behavior change.

## Status Rule

The derived payload is passed through the existing `no_signal_world` check:

- `pass` if the derived metrics and supplied observation audit remain within the no-signal rule.
- `fail` if the derived metrics exceed tolerance or supplied contract/audit fields fail.
- `warn` if required inputs are incomplete, such as when no observation audit status is available.

## Acceptance

- Normal `alpha_to_execution.v1` reports still show `no_signal_world: not_implemented` unless explicit `no_signal_check` is supplied.
- `alpha_to_execution.no_signal.v1` reports with candidate and no-trade results can derive a no-signal payload.
- Derived payload output includes `source=episode_result_derived` and candidate identity for traceability.
- Research acceptance remains incomplete.

## Follow-up

- Add a real observation audit result instead of manually setting `no_signal_observation_audit_status`.
- Add a controlled run setup that forces no-signal observations instead of relying only on the report task name.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/no-signal-payload-observation-audit.md` adds a narrow payload-level audit for the no-signal alpha contract fields. Derived payloads no longer need manual `no_signal_observation_audit_status` when those fields are complete and valid, but this is still not a full runtime observation audit.
