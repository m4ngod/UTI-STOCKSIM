# Calibration Artifact Writer

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/tasks/model-training/calibration-scorecard-v0.md`
- `docs/current-work-status/model-training.md`

## Task

Task 88: Calibration Artifact Writer.

## Purpose

Create the first separate Evidence Runner writer for `calibration_artifact_v1`. The writer is intentionally narrow:
it writes a canonical JSON artifact from already-produced calibration metrics and scorecard output. It does not run
the market, compute metrics, compute the scorecard, or create a target profile.

## Required Inputs

- world identity: `world_id` and `world_hash`.
- target profile id.
- code identity hash.
- sim version identity.
- random seed ledger hash.
- contract versions.
- metrics from Market Metrics Extractor v0.
- scorecard output from Calibration Scorecard v0.
- dependencies list.

## Blocking Rules

The writer must not mark the artifact as passed when any required identity is missing:

- `code_identity_hash`
- `sim_version_identity`
- `world_hash`
- `random_seed_ledger_hash`
- `contract_versions`
- `scorecard`

The writer may still persist a failed artifact so the missing evidence is auditable.

## Artifact Hash

`artifact_hash` is `sha256_json_canonical_v1` over the artifact payload with `artifact_hash` excluded.

## Current Status

Implemented as `app/services/evidence_artifact_writer.py` with focused runtime tests in
`tests/runtime/test_evidence_artifact_writer.py`. The writer creates a separate JSON artifact but does not add
database persistence, calibration runner execution, metric extraction, scorecard computation, GUI behavior, or
PostgreSQL data deletion.
