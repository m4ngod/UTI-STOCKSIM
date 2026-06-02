# TWAP VWAP Report Slots

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/target-weight-naive-rebalance-baseline.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

The expert review lists TWAP and VWAP as core execution baselines. The baseline plan says the safe next step is to add report slots for TWAP/VWAP as `not_available` before implementing schedule execution.

This task adds only report semantics. It does not implement TWAP/VWAP order schedules, does not change model actions, does not change rewards, and does not change PBT parent selection.

## Report Slot Shape

Each optional execution baseline slot should expose:

```text
kind: twap | vwap
status: present | not_available
reason: schedule_execution_not_implemented
required_inputs:
  - arrival_price
  - target_quantity_or_notional
  - horizon_steps_or_seconds
  - realized_fill_price
  - benchmark_fill_price
```

## Scope Rules

- Do not fabricate TWAP/VWAP benchmark values.
- Do not fail Arena experiments only because TWAP/VWAP is unavailable.
- Keep `baseline_suite.status` based on the required initial baselines:
  - no_trade_cash
  - random_constrained
  - target_weight_naive_rebalance
- Keep `research_acceptance.status=incomplete` until hidden evaluation and exploit detector outputs exist.

## Acceptance

- Arena reports show TWAP and VWAP optional baseline slots.
- Each slot has `status=not_available` until schedule logic exists.
- Each slot lists the required inputs needed before implementation.
- Tests confirm these fields exist without changing runtime behavior.

## Explicitly Deferred

- TWAP/VWAP schedule execution.
- Arrival-price capture.
- Implementation shortfall reward wiring.
- Benchmark-relative PBT parent gate.

## Progress Update 2026-05-05: Runnable TWAP/VWAP Baselines

Task 90 now moves TWAP/VWAP from pure `not_available` report slots to runnable built-in baseline policies.

Implemented files:

- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_model_registry_external.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `tests/runtime/test_evidence_artifact_writer.py`

Current behavior:

- `twap_execution_v1` is registered in `ModelRegistryService`.
- `vwap_execution_v1` is registered in `ModelRegistryService`.
- Both emit `act.v1` `target_weight` actions through the existing model action contract.
- TWAP emits `payload.rebalance_mode=twap`.
- VWAP emits `payload.rebalance_mode=vwap`.
- Both include schedule metadata in `payload.schedule`.
- Arena default `model_specs` now include both as `collect_only` baselines.
- Arena default `pbt_excluded_model_ids` excludes both from PBT parent selection.
- `_baseline_kind(...)` maps them to `twap` and `vwap`.
- `baseline_artifact_v1` now requires `twap` and `vwap` alongside existing required baseline kinds.

Still deferred:

- True order-level TWAP/VWAP slicing.
- Arrival-price capture.
- Realized implementation shortfall metrics.
- Reward wiring from TWAP/VWAP shortfall.
- Strict parent gate use of TWAP/VWAP evidence.

Verification:

- `python -m py_compile app/services/model_registry_service.py app/services/arena_experiment_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_model_registry_external.py tests/runtime/test_arena_experiment_runner.py tests/runtime/test_evidence_artifact_writer.py`
- Direct behavior assertion passed with `TWAP_VWAP_MODEL_AND_ARTIFACT_DIRECT_ASSERTIONS_OK`.

Pytest note:

- Targeted pytest could not run in this environment because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.
