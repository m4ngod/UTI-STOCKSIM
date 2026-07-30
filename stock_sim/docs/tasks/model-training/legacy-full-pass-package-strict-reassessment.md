# Legacy Full-Pass Package Strict Reassessment

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- existing generated Task 101 evidence artifacts under `output/evidence_artifacts`
- current `SeriesEvidenceAggregate` and `LongArenaDryRunRunner` code.

## Purpose

Reassess the latest legacy `full-pass-engineering-attempt` package under the current hardened evidence rules. The goal
is to prevent an older `go` package from being mistaken for a valid hardened Go after the project added strict source,
hash, runner, and `pass_gate` checks.

## Input Package

- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-full-pass-engineering-attempt-afe4fd634f2a212a.json`
- Embedded package state: `status=complete`, `go_no_go=go`
- Embedded evidence status: seven pass rows

## Reassessment Finding

The input package is not accepted as a hardened Go package. The embedded artifacts predate the current strict evidence
contract and are missing required fields:

- `source=live_postgresql_runtime`
- explicit `pass_gate`
- current paired sensitivity scenario coverage
- current exploit probe naming and metrics contract
- current hidden-evaluation freeze/baseline/contamination diagnostics

Because those fields are missing, the current strict aggregate recomputes every evidence row as `fail`.

## Generated Strict Recompute Package

- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-strict-recomputed-legacy-full-pass-92fe0b788974c59a.json`
- Recomputed package state: `status=complete`
- Recomputed Go / No-Go: `no_go`
- Recomputed evidence status:
  - `baseline_artifact=fail`
  - `calibration_artifact=fail`
  - `hidden_eval_artifact=fail`
  - `exploit_test_artifact=fail`
  - `paired_sensitivity_artifact=fail`
  - `parent_gate_artifact=fail`
  - `research_acceptance_lock=fail`

## Failure Details

The strict recompute reports:

- `missing_live_runtime_source`
- `missing_pass_gate`
- `missing_runner_version` for the legacy research lock

These are schema/source failures, not proof that the candidate is bad. They mean the legacy all-pass package does not
meet the current hardened evidence contract and must not be used for parent promotion or research acceptance.

## Explicitly Not Done

- Did not rewrite the old package in place.
- Did not delete old generated artifacts.
- Did not delete PostgreSQL historical data.
- Did not convert the strict recomputed No-Go back to Go.
- Did not claim level-2 or level-3 research acceptance.

## Verification

- `.venv\Scripts\python.exe -m pytest tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `6 passed`
- Follow-up implementation added `EvidencePackageReassessmentRunner` so this strict recompute is repeatable.
- Service-generated strict recompute output:
  `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-service-recomputed-legacy-full-pass-f3152127052f7b58.json`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `8 passed`
- Evidence-focused regression after the service addition: `52 passed`

## Current Progress Meaning

The project has moved from "can produce pass-looking legacy packages" to "can reject legacy pass-looking packages under
the current evidence rules." The next real progress step is still to run fresh live PostgreSQL/runtime artifacts that
already contain the hardened fields, not to rely on older full-pass outputs.
