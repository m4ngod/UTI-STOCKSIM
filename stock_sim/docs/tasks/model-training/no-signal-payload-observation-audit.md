# No Signal Payload Observation Audit

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `docs/tasks/model-training/no-signal-world-report-check.md`
- `docs/tasks/model-training/no-signal-episode-payload-derivation.md`
- `docs/contracts/runtime/model-observation-contract.md`
- `app/services/arena_experiment_runner.py`

## Purpose

The no-signal report check previously required `observation_audit_status`, but the derived episode payload could only pass that field through manual config.

This task adds a minimal payload-level observation audit. It audits only whether the no-signal payload alpha contract fields match the documented no-signal shape. It does not audit every runtime observation step and does not inspect GUI, database-only, or future fields.

## Scope

Implemented:

- Add `_audit_no_signal_payload`.
- Add `_with_no_signal_observation_audit`.
- Attach `observation_audit` to the `no_signal_world` report check.
- If `observation_audit_status` is absent, derive it from the payload audit.
- Keep manual `observation_audit_status` accepted when supplied.
- Keep normal `alpha_to_execution.v1` reports as placeholders unless explicit no-signal input exists.

The audit checks:

- `alpha_signal_source == no_signal`
- `direction == 0.0`
- `confidence == 0.0`
- `target_weight_hint == null`

Audit statuses:

- `pass`: all no-signal alpha contract fields are present and valid.
- `warn`: one or more no-signal alpha contract fields are missing.
- `fail`: one or more no-signal alpha contract fields violate the no-signal shape.

## Explicitly Not Implemented

- No full observation sequence audit.
- No future-field scan.
- No GUI-field scan.
- No database-only aggregate audit.
- No runtime observation builder changes.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- Derived `alpha_to_execution.no_signal.v1` payload can pass the no-signal check without manually setting `no_signal_observation_audit_status`.
- `no_signal_world.observation_audit` records status, reason, scope, missing fields, and violations.
- Research acceptance remains incomplete because hidden evaluation and other exploit checks are still incomplete.

## Follow-up

- Add a real runtime observation audit that checks actual `obs.v1` payloads against allowed/disallowed fields.
- Keep payload audit as a narrow precondition, not as final research acceptance.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/runtime-observation-audit-report.md` adds a report-side audit over persisted `ModelTransition.observation_json` rows. The payload audit remains a narrow fallback/precondition; runtime audit status can now feed derived `no_signal_world` checks when transition rows exist.
