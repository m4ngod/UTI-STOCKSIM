# Arena Experiment Sim Version Source

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-experiment-code-identity-hash.md`
- `stock_sim/__init__.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires generated reports to state the simulation version. The project already exposes `stock_sim.__version__ = "0.0.1"`. This task wires that existing local version value into Arena experiment reports without creating a new versioning scheme.

## Implemented

Arena experiment metadata now includes:

- `sim_version`
- `sim_version_identity`

`sim_version_identity` includes:

- `schema=stock_sim.sim_version_identity.v1`
- `status`
- `source=stock_sim.__version__`
- `sim_version`

Arena experiment reports now include top-level `sim_version` when `stock_sim.__version__` is available.

`experiment_record_completeness` already reads top-level `sim_version`, so new reports can mark `sim_version` as present.

## Explicitly Not Implemented

- No new versioning policy.
- No package release process.
- No dependency/environment version hash.
- No runtime random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- `experiment_record_metadata.sim_version_identity` exists in new Arena reports.
- `sim_version` is present when `stock_sim.__version__` is available.
- `missing_sources` no longer includes `sim_version` when the version is available.
- If `stock_sim.__version__` cannot be read, `sim_version` remains missing instead of being fabricated.
- `random_seed` remains missing until the underlying stochastic services can consume and report it.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct assertion passed with `ARENA_EXPERIMENT_SIM_VERSION_ASSERTIONS_OK`.

## Follow-up

- Add `random_seed` only after the underlying stochastic services can consume and report it.
- Define broader dependency/environment identity only if a project-local task requires it.

## Progress Update 2026-05-03

- `docs/tasks/model-training/arena-experiment-random-seed-status.md` documents why `random_seed` is still not available.
- New Arena reports include `random_seed_identity.status=not_available`.
- `random_seed` remains missing until stochastic services consume and report a real seed.
