# Separate Artifact Schemas v1

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/current-work-status/model-training.md`

## Task

Task 83: Separate Artifact Schemas v1.

## Purpose

Define independent Evidence Runner artifact boundaries before artifact writers or runners claim pass/fail evidence.
Embedded Arena report sections may remain, but they do not replace separate artifacts.

## Common Required Fields

Every Evidence Runner artifact must include at least:

- `artifact_id`
- `artifact_kind`
- `artifact_schema_version`
- `created_at`
- `runner_name`
- `runner_version`
- `code_identity_hash`
- `sim_version_identity`
- `world_id`
- `world_hash`
- `reward_hash` or `reward_not_applicable`
- `contract_versions`
- `random_seed_ledger_hash`
- `dependencies`
- `metrics`
- `pass_fail`
- `failure_reasons`
- `artifact_hash`

## Artifact Kinds

- `calibration_artifact_v1`
- `baseline_artifact_v1`
- `hidden_eval_artifact_v1`
- `exploit_test_artifact_v1`
- `paired_sensitivity_artifact_v1`
- `parent_gate_artifact_v2`

## Parent Gate Separation

`parent_gate_artifact_v2` must keep these decisions separate:

- `eligible_for_pbt_parent`
- `eligible_for_checkpoint_promotion`
- `eligible_for_research_claim`

## Acceptance

- Each artifact kind has a stable schema boundary before code work.
- Failure reasons are explicit strings rather than implicit missing fields.
- Artifact hash excludes the `artifact_hash` field itself.

## Current Status

Schema boundary documented. Persistence tables, artifact writers, runners, GUI, and strict parent gate v2 are not
implemented by this task.
