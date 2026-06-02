# Strict Parent Gate v2

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 96: Strict Parent Gate v2.

## Purpose

Upgrade parent eligibility from report-layer diagnostics to evidence-gated eligibility. Without independent evidence,
a candidate cannot become a PBT parent, cannot be promoted automatically, and cannot support a research claim.

## Required Evidence

The gate requires:

- `experiment_record_completeness`
- `checkpoint_hash`
- `lineage_evidence`
- `baseline_artifact`
- `calibration_artifact`
- `hidden_eval_artifact`
- `exploit_test_artifact`
- `paired_sensitivity_artifact`

## Eligibility Boundary

Implemented in `app/services/strict_parent_gate.py`:

- `StrictParentGateV2.evaluate(...)`
- `required_evidence_status(...)`
- `collect_evidence_hashes(...)`

The three eligibility decisions are intentionally separate:

- `eligible_for_pbt_parent`: all required evidence passes.
- `eligible_for_checkpoint_promotion`: all required evidence passes and `hidden_rank_ok=True`.
- `eligible_for_research_claim`: all required evidence passes and `statistical_confidence_ok=True`.

## Artifact Output

The artifact uses:

- `artifact_kind=parent_gate_artifact_v2`
- `artifact_schema_version=2`
- `runner_name=strict_parent_gate_v2`
- `runner_version=v2`
- `candidate_id`
- `checkpoint_hash`
- required evidence map
- separate eligibility flags
- evidence hashes
- pass/fail and failure reasons
- canonical `artifact_hash`

## Explicitly Deferred

- Mutating existing PBT parent selection.
- Automatic checkpoint promotion.
- Research acceptance lock v2.
- Series-level evidence aggregate.
- GUI Evidence Board.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/strict_parent_gate.py app/services/evidence_artifact_writer.py tests/runtime/test_strict_parent_gate.py`
- Direct behavior assertion passed with `STRICT_PARENT_GATE_V2_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
