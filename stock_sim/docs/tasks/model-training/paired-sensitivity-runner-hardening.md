# Paired Sensitivity Runner Hardening

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- existing `PairedSensitivityRunner`, evidence artifact writer, and runtime tests.

## Purpose

Implement the expert-required paired sensitivity boundary without turning current No-Go artifacts green by hand. The
runner now has an explicit scenario mode for `base`, `high_fee`, `high_impact`, and `low_liquidity`, and each scenario
must compare the candidate against TWAP, VWAP, and AC-lite baselines when this mode is used.

## Implemented

- Added required paired scenarios: `base`, `high_fee`, `high_impact`, `low_liquidity`.
- Added required paired baselines: `twap`, `vwap`, `ac_lite`.
- Preserved the existing perturbation mode for backward-compatible tests and callers.
- Added scenario world construction:
  - `base` marks `scenario_family=base`.
  - `high_fee` increases the fee model.
  - `high_impact` increases the impact model.
  - `low_liquidity` reduces the market liquidity multiplier.
- Scenario summaries now record present/missing scenarios, present/missing baselines, scenario results, degradation
  curve data, `pass`, `failure_reasons`, and `next_action`.
- Missing required scenario or required baseline now blocks `pass_gate` instead of being silently accepted.

## Explicitly Not Done

- Did not claim the current Task 101 paired sensitivity artifact passes.
- Did not re-run a fresh Task 101 live paired sensitivity package from PostgreSQL rows.
- Did not lower TWAP/VWAP/AC-lite or sensitivity thresholds.
- Did not add historical replay, hybrid env, Transformer, GTrXL, complex MARL, or alpha-claim routes.
- Did not delete PostgreSQL historical data.

## Verification

- `.venv\Scripts\python.exe -m py_compile app\services\paired_sensitivity_runner.py app\services\evidence_artifact_writer.py tests\runtime\test_paired_sensitivity_runner.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `12 passed`
- Full evidence regression:
  `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `49 passed`

## Current No-Go Meaning

Paired sensitivity is now harder to fake and easier to diagnose. The current Task 101 No-Go remains correct until a live
artifact proves acceptable behavior across all required paired scenarios and strong baselines.
