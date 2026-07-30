# Arena Experiment Random Seed Status

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-experiment-sim-version-source.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires reports to state the random seed that produced a result. The current Arena configuration does not expose a single seed that controls all stochastic services. Adding a report-only numeric seed would be misleading because retail persona sampling, model training randomness, and future world generation would not be guaranteed to consume it.

This task therefore makes the missing state explicit instead of fabricating a seed.

## Implemented

Arena experiment metadata now includes:

- `random_seed`
- `random_seed_identity`

Current values:

- `random_seed=None`
- `random_seed_identity.status=not_available`
- `random_seed_identity.reason=random_seed_not_wired_to_stochastic_services`

The identity also records prerequisites before `random_seed` can become present:

- `arena_config_random_seed`
- `retail_persona_rng_seed`
- `model_training_rng_seed`
- `market_world_rng_seed`

`missing_sources` continues to include `random_seed`.

`experiment_record_completeness` continues to mark `random_seed` as missing unless a real seed appears in the report, config, or episode.

## Explicitly Not Implemented

- No fake or report-only seed value.
- No Arena config random seed field.
- No retail persona RNG wiring.
- No model training RNG wiring.
- No market/world RNG wiring.
- No hidden-world seed implementation.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- `experiment_record_metadata.random_seed_identity` exists in new Arena reports.
- The random seed status is explicitly `not_available`.
- The report explains why `random_seed` is still missing.
- `experiment_record_completeness` continues to count `random_seed` as missing.
- Future implementation prerequisites are machine-readable.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct assertion passed with `ARENA_EXPERIMENT_RANDOM_SEED_STATUS_ASSERTIONS_OK`.

## Follow-up

- Add a real `ArenaExperimentConfig.random_seed` only when the underlying stochastic services consume it.
- Route that seed through retail persona sampling, model training RNG, and world generation before marking `random_seed` present.
