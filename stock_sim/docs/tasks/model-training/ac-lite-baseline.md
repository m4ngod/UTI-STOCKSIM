# AC-lite Baseline

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 91: AC-lite Baseline.

## Purpose

Add a simplified Almgren-Chriss style execution baseline that runs through the existing model registry, `act.v1`
contract, Arena baseline reporting, and Evidence Runner baseline artifact boundary.

## Implementation Boundary

Current implementation is a scheduled `target_weight` baseline:

- model id: `ac_lite_execution_v1`
- baseline kind: `ac_lite`
- action type: `target_weight`
- rebalance mode: `ac_lite`
- schedule metadata: `sigma`, `eta`, `risk_aversion`, `horizon_steps`, `progress`

The progress curve follows the second expert review's AC-lite idea:

```text
kappa = sqrt(risk_aversion * sigma^2 / eta)
remaining = sinh(kappa * (1 - t)) / sinh(kappa)
progress = 1 - remaining
```

## Runtime Boundary

The baseline does not bypass runtime truth. It is registered in `ModelRegistryService` and produces the same action
contract shape as other model policies. Arena can include it as a `collect_only` baseline.

## Current Status

Implemented files:

- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_model_registry_external.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `tests/runtime/test_evidence_artifact_writer.py`

## Explicitly Deferred

- Order-level Almgren-Chriss slicing.
- Real temporary/permanent impact calibration.
- Arrival-price capture.
- Implementation shortfall reward wiring.
- Strict parent gate use of AC-lite evidence.
- GUI behavior.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/model_registry_service.py app/services/arena_experiment_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_model_registry_external.py tests/runtime/test_arena_experiment_runner.py tests/runtime/test_evidence_artifact_writer.py`
- Direct behavior assertion passed with `AC_LITE_BASELINE_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
