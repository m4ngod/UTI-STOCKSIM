# Live Calibration Artifact Hardening

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- `docs/tasks/model-training/calibration-target-bands-v0.md`
- existing Evidence Runner artifact writer and metrics extractor code.

## Purpose

Create the first `CalibrationRunner` boundary that turns live PostgreSQL/runtime fact payloads into
`calibration_artifact_v1` without using injected summary status.

## Implemented

- Added `app/services/calibration_runner.py`.
- `CalibrationRunner.run_calibration(...)` runs each `world_spec_v1` across explicit seeds.
- Each world/seed call must go through `run_world_once(..., backend="postgresql_runtime")`.
- Runtime facts are read through `fetch_runtime_facts(run_id)` and then passed into `MarketMetricsExtractor`.
- Per-seed metrics are aggregated before target-band comparison.
- The written `calibration_artifact_v1` includes:
  - `source=live_postgresql_runtime`
  - `source_run_ids`
  - P0 observed metrics
  - target bands
  - missing metrics
  - failed metrics
  - severity counts
  - `engineering_pass`
  - `research_pass`
  - `pass_gate`
  - `failure_type`
  - `next_action`

## Explicitly Not Done

- Did not read concrete PostgreSQL ORM tables directly in this round.
- Did not run a fresh live Task 101 calibration package.
- Did not convert the existing Task 101 calibration fail into pass.
- Did not claim `research_pass`; engineering defaults remain `research_pass=false`.

## Verification

- `pytest tests/runtime/test_calibration_runner.py -q`
- Covered live backend invocation, source run id propagation, P0 metric completeness, and missing-metric gate failure.

## Remaining Work

- Replace the test fact callback with a direct live PostgreSQL fact reader for orders, trades, snapshots, bars,
  holdings, and account/equity samples.
- Generate a real Task 101 calibration artifact from the live database/runtime run.
