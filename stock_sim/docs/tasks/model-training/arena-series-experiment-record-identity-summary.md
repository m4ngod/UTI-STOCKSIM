# Arena Series Experiment Record Identity Summary

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-experiment-code-identity-hash.md`
- `docs/tasks/model-training/arena-experiment-sim-version-source.md`
- `docs/tasks/model-training/arena-experiment-random-seed-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires generated reports to answer what code, world, reward, seed, model, and parent lineage produced a training result. Recent tasks added local identity sources and completeness tracking. The generation summary still needed a compact identity view so a multi-generation series can show the identity state of each generation without requiring readers to open every full report.

This task adds a report-only identity summary. It reads existing `experiment_record_metadata` and top-level report fields. It does not create new hashes, seed values, versions, model logic, reward logic, world logic, or training behavior.

## Scope

Implemented:

- Add `experiment_record_identity` to Arena generation summaries.
- Include existing identity values and statuses:
  - `metadata_schema`
  - `code_hash`
  - `code_identity_status`
  - `code_dirty`
  - `sim_version`
  - `sim_version_status`
  - `reward_hash`
  - `world_hash`
  - `random_seed`
  - `random_seed_status`
  - `random_seed_reason`
  - `missing_sources`
  - `not_applicable_sources`
- Add `aggregate.experiment_record_identity` to Arena series aggregates.
- Count code identity status, sim-version status, random-seed status, dirty-code observations, missing sources, and not-applicable sources across a series.

## Explicitly Not Implemented

- No new code hash source.
- No new sim version source.
- No new reward hash or world hash algorithm.
- No fake random seed.
- No RNG ownership or stochastic-service wiring.
- No replay/hybrid data cutoff support.
- No PostgreSQL data deletion or mutation.

## Acceptance

- A generation summary can answer the current code/sim/reward/world/seed identity state from existing report metadata.
- Series aggregate can show repeated identity-source gaps such as `random_seed`.
- Dirty-code status remains visible when provided by `experiment_record_metadata.code_identity`.
- Missing and not-applicable sources remain explicit.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct assertion passed with `ARENA_SERIES_EXPERIMENT_RECORD_IDENTITY_ASSERTIONS_OK`.

## Follow-up

- Add a real random seed only after Arena config, retail persona sampling, model training RNG, and market/world RNG consume and report the same seed ownership chain.
- Keep `data_cutoff` not applicable until replay/hybrid data is added through a documented task.

## Progress Update 2026-05-04: World Card

- `docs/tasks/model-training/arena-world-card-metadata.md` now adds `world_card` to Arena reports.
- Generation summaries expose `world_card` beside `experiment_record_identity`.
- Series aggregates expose `aggregate.world_card` for world-card observations, split status, calibration status, and missing calibration metrics.
