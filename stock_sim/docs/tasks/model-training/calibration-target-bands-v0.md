# Calibration Target Bands v0

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- existing `MarketMetricsExtractor`, `CalibrationArtifactWriter`, and runtime tests.

## Purpose

Provide the first executable calibration target-band boundary for `calibration_artifact_v1`. This does not claim real
market calibration. It creates an `engineering_default_v0` target source and separates `engineering_pass` from
`research_pass`.

## Implemented

- Added P0 calibration metric names:
  - `spread`
  - `depth`
  - `turnover`
  - `volatility`
  - `return_autocorrelation`
  - `fill_rate`
  - `cancel_rate`
  - `buy_sell_ratio`
  - `holding_period`
  - `retail_family_mix`
  - `order_lifespan`
- Added `engineering_default_target_bands_v0()`.
- Added `normalize_calibration_observed_metrics(...)`.
- Added `compare_to_calibration_target_bands(...)`.
- Extended `MarketMetricsExtractor` to derive `fill_rate`, `cancel_rate`, `retail_family_mix`, and
  `order_lifespan_mean` when runtime facts contain the required fields.
- Missing metrics now produce explicit `missing` status and block `engineering_pass`.

## Acceptance Boundary

The current target source is `engineering_default_v0`. A pass here means only:

- live runtime facts were supplied
- required P0 metrics were present
- values were inside broad engineering bands
- no severe missing/out-of-band condition existed

It does not mean real-market calibration or research validity.

## Verification

- `pytest tests/runtime/test_evidence_core.py -q`
- Covered target-band pass, missing metric failure, and P0 metric normalization.

## Remaining Work

- Replace broad engineering defaults with documented market target profiles when available.
- Wire direct PostgreSQL fact extraction from concrete runtime tables instead of relying on injected test callbacks.
- Run multi-world, multi-seed live calibration against Task 101 worlds before claiming `calibration_artifact=pass`.
