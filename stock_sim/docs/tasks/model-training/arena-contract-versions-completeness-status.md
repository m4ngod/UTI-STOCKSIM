# Arena Contract Versions Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `rl/contracts.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Arena experiment metadata already records `experiment_record_metadata.contract_versions` for observation, action, and reward contracts. This task makes that contract-version bundle visible in `experiment_record_completeness` so reports can distinguish auditable contract-version metadata from missing contract metadata.

This is a status mapping only. It does not change any contract version constants or contract behavior.

## Scope

Implemented:

- Add `contract_versions` to `experiment_record_completeness.field_status`.
- Mark `contract_versions=present` when a top-level or metadata contract-version object exists.
- Mark `contract_versions=missing` when no contract-version object exists.
- Carry the field into `aggregate.experiment_record_completeness.field_status_counts`.

## Explicitly Not Implemented

- No contract-version constant changes.
- No observation/action/reward schema changes.
- No reward-hash or world-hash calculation changes.
- No reward function or reward benchmark changes.
- No hidden-world runner.
- No calibration harness.
- No training, execution, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with `experiment_record_metadata.contract_versions` mark `contract_versions` as `present`.
- Reports lacking contract-version metadata remain `missing`.
- Series completeness aggregates count contract-version status without opening every full report.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct assertion passed with `ARENA_CONTRACT_VERSIONS_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add deeper contract-version validation only after the project documents validation ownership and allowed contract-version schema evolution.
