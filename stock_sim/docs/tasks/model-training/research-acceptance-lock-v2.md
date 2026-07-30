# Research Acceptance Lock v2

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 97: Research Acceptance Lock v2.

## Purpose

Prevent a model result from being written as a research conclusion unless the required evidence stack has passed and
Strict Parent Gate v2 explicitly allows `eligible_for_research_claim`.

## Lock Boundary

Implemented in `app/services/research_acceptance_lock.py`:

- `ResearchAcceptanceLockV2.evaluate(...)`
- `REQUIRED_RESEARCH_EVIDENCE_HASHES`

The lock consumes `parent_gate_artifact_v2` rather than reinterpreting Arena leaderboard rank. This keeps research
acceptance dependent on the evidence gate.

## Required Evidence Hashes

The lock requires hashes for:

- `checkpoint_hash`
- `lineage_evidence`
- `baseline_artifact`
- `calibration_artifact`
- `hidden_eval_artifact`
- `exploit_test_artifact`
- `paired_sensitivity_artifact`

## Pass Boundary

The lock opens only when:

- `candidate_id` is present,
- claim text is present,
- parent gate artifact kind is `parent_gate_artifact_v2`,
- parent gate `pass_fail=True`,
- parent gate `eligible_for_research_claim=True`,
- parent gate required evidence has no failures,
- required evidence hashes are present.

Otherwise the record is `status=locked` and `is_research_accepted=False`.

## Output

The lock writes a JSON record under `output/evidence_artifacts/research_acceptance_lock_v2/`.

The record includes:

- `record_kind=research_acceptance_lock_v2`
- `schema_version=2`
- `candidate_id`
- `claim_text`
- parent gate artifact id/hash
- required evidence map
- required evidence hashes
- `status`
- `is_research_accepted`
- `failure_reasons`
- canonical `lock_hash`

## Explicitly Deferred

- Mutating existing Arena research acceptance sections.
- Writing research conclusions into reports.
- Series Evidence Aggregate.
- GUI Evidence Board.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/research_acceptance_lock.py tests/runtime/test_research_acceptance_lock.py`
- Direct behavior assertion passed with `RESEARCH_ACCEPTANCE_LOCK_V2_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
