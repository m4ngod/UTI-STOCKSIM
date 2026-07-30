# Runtime Observation Audit Report

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `docs/tasks/model-training/no-signal-payload-observation-audit.md`
- `docs/contracts/runtime/model-observation-contract.md`
- `persistence/models_training.py`
- `services/training_episode_service.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The no-signal payload audit checks only the derived payload contract. The next safe step is to audit persisted runtime model observations when an Arena episode has `ModelTransition.observation_json` rows.

This task adds a report-side runtime observation audit. It reads existing persisted transition observations and reports structural or disallowed-field violations. It does not alter observation generation, model actions, rewards, execution, account state, or PBT behavior.

## Scope

Implemented:

- Add `runtime_observation_audit` to Arena episode details.
- Read persisted `ModelTransition.observation_json` rows for the episode.
- Check that each observation is an object.
- Check `contract_version == obs.v1`.
- Check required top-level sections:
  - `market`
  - `account`
  - `context`
  - `features`
- Check that required sections are objects.
- Flag unexpected top-level keys outside:
  - `contract_version`
  - `market`
  - `account`
  - `context`
  - `features`
- Flag disallowed field paths matching the Alpha-to-Execution disallowed input classes:
  - GUI panel/widget/selected-row/render fields
  - final rank / final score
  - future bar / future trade / next snapshot
  - post-decision or post-trade fields
  - hidden split labels
  - database-only or db-only aggregates
  - private future action fields
- Attach runtime observation audit status to derived `no_signal_world` payloads when available.

Status values:

- `not_available`: no persisted model transitions exist for the episode.
- `pass`: persisted observations passed the implemented structural and disallowed-field checks.
- `fail`: one or more persisted observations violated the implemented checks.

## Explicitly Not Implemented

- No runtime observation builder change.
- No full semantic validation of every allowed field value.
- No timestamp causality proof.
- No future-data detection beyond field-name/path audit.
- No hidden split execution.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- Episodes with no transitions report `runtime_observation_audit.status=not_available`.
- Episodes with valid persisted `obs.v1` observations report `runtime_observation_audit.status=pass`.
- Episodes with disallowed top-level or nested paths report `runtime_observation_audit.status=fail`.
- Derived `no_signal_world` checks can use runtime audit status as their observation audit input.
- Research acceptance remains incomplete.

## Follow-up

- Add deeper semantic checks for time-valid bars and recent trade windows.
- Add timestamp audit as a separate exploit detector check.
- Keep strict parent eligibility opt-in until all required hidden/exploit checks can become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/timestamp-audit-report-check.md` promotes `timestamp_audit` from a placeholder to a minimal report-side check over persisted `ModelTransition.step_index` ordering. It still does not prove market-data timestamp causality.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-audit-summary.md` carries runtime observation audit status and counts into Arena generation summaries and series aggregates. This is report-only and does not change observation generation.
