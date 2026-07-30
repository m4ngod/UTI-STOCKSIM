# Evidence Package Reassessment Runner

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- `docs/tasks/model-training/legacy-full-pass-package-strict-reassessment.md`
- existing `LongArenaDryRunRunner`, `SeriesEvidenceAggregate`, generated artifacts, and tests.

## Purpose

Turn strict reassessment of saved long Arena packages into a repeatable project service. This avoids relying on one-off
scripts when deciding whether an older pass-looking package still satisfies the current hardened evidence contract.

## Implemented

- Added `app/services/evidence_package_reassessment.py`.
- Added `EvidencePackageReassessmentRunner`.
- The runner:
  - reads a saved `long_arena_dry_run_package_v1`
  - extracts candidate evidence hashes from embedded `series_evidence_aggregate`
  - resolves those hashes back to artifact JSON files under `output/evidence_artifacts`
  - rebuilds candidate evidence payloads
  - reruns `LongArenaDryRunRunner` and `SeriesEvidenceAggregate`
  - writes a new strict recompute package
- Added tests covering:
  - legacy all-pass artifacts without `source`/`pass_gate` recompute to `no_go`
  - strict live artifacts with required fields preserve `go`

## Real Package Reassessment

Input:

- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-full-pass-engineering-attempt-afe4fd634f2a212a.json`

Generated with the service:

- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-service-recomputed-legacy-full-pass-f3152127052f7b58.json`

Readback:

- `status=complete`
- `go_no_go=no_go`
- all seven evidence rows fail strict recompute
- main reasons: `missing_live_runtime_source`, `missing_pass_gate`
- legacy research lock also reports `missing_runner_version`

## Explicitly Not Done

- Did not rewrite old packages in place.
- Did not delete old generated artifacts.
- Did not delete PostgreSQL historical data.
- Did not convert strict recompute failures to pass.
- Did not claim level-2 or level-3 acceptance.

## Verification

- `.venv\Scripts\python.exe -m pytest tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `8 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `52 passed`

## Current Progress Meaning

The current gap is no longer "can we detect stale pass-looking evidence?" The project now has a reusable reassessment
runner for that. The remaining real work is fresh live PostgreSQL/runtime artifact generation under the hardened
contract.
