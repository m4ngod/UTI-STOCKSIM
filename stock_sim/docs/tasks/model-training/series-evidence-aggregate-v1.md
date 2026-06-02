# Series Evidence Aggregate v1

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 98: Series Evidence Aggregate.

## Purpose

Aggregate candidate-level evidence into a series-level pass/fail/missing/not_available view. The aggregate is meant to
make the evidence package readable before GUI work or long Arena dry runs.

## Aggregate Boundary

Implemented in `app/services/series_evidence_aggregate.py`:

- `SeriesEvidenceAggregate.aggregate(...)`
- `REQUIRED_SERIES_EVIDENCE`

The aggregate consumes candidate evidence records and does not re-run models or evidence runners.

## Required Evidence

Each candidate is tracked across:

- `baseline_artifact`
- `calibration_artifact`
- `hidden_eval_artifact`
- `exploit_test_artifact`
- `paired_sensitivity_artifact`
- `parent_gate_artifact`
- `research_acceptance_lock`

## Status Boundary

Each required evidence slot is classified as:

- `pass`
- `fail`
- `missing`
- `not_available`

The series is `go` only when at least one candidate exists and every required evidence slot for every candidate is
`pass`. Otherwise it is `no_go` and blocking reasons are explicit.

## Output

The aggregate writes a JSON record under `output/evidence_artifacts/series_evidence_aggregate_v1/`.

The record includes:

- `record_kind=series_evidence_aggregate_v1`
- `schema_version=1`
- `series_id`
- required evidence list
- per-candidate evidence status
- per-candidate evidence hashes
- parent eligibility and research acceptance summary
- series status counts
- evidence status counts by evidence kind
- `go_no_go`
- `failure_reasons`
- canonical `aggregate_hash`

## Explicitly Deferred

- Running a long Arena series.
- Wiring this aggregate into existing Arena report generation.
- GUI Evidence Board.
- Evidence Contract Tests.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/series_evidence_aggregate.py tests/runtime/test_series_evidence_aggregate.py`
- Direct behavior assertion passed with `SERIES_EVIDENCE_AGGREGATE_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
