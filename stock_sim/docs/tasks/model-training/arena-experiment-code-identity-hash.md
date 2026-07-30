# Arena Experiment Code Identity Hash

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- Git metadata available in the local project checkout
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E asks generated reports to answer what code produced a result. Task 47 added reward and world/config hashes but left `code_hash` missing until a local source was documented. This task defines the first local source: Git code identity.

The goal is auditability, not source packaging. The report records the Git HEAD and whether the working tree was dirty. Dirty state remains visible so readers do not mistake the hash for a clean release artifact.

## Implemented

Arena experiment metadata now includes a `code_identity` section:

- `schema=stock_sim.git_code_identity.v1`
- `status`
- `method=git_head_plus_status_sha256_v1` when available
- `head`
- `branch`
- `is_dirty`
- `status_entry_count`
- `status_porcelain_hash`
- `code_hash`

Arena experiment reports now include top-level `code_hash` when Git identity is available.

`code_hash` is a canonical SHA-256 hash over:

- Git HEAD
- current branch
- dirty/clean flag
- count of `git status --porcelain` entries
- SHA-256 hash of the porcelain status lines

`experiment_record_completeness` already reads top-level `code_hash`, so new reports can mark `code_hash` as present when Git identity is available.

## Explicitly Not Implemented

- No full source archive hash.
- No dependency lockfile hash.
- No runtime environment hash.
- No sim version source.
- No runtime random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Dirty Worktree Semantics

When `is_dirty=true`, the hash identifies the Git HEAD plus dirty-state summary, not a clean release. This is still useful because the report can state that the run was produced from a dirty checkout. It should not be used as proof of an immutable source bundle.

## Acceptance

- `experiment_record_metadata.code_identity` exists in new Arena reports.
- `code_hash` is present when Git identity is available.
- `missing_sources` no longer includes `code_hash` when Git identity is available.
- If Git identity cannot be read, `code_hash` remains missing instead of being fabricated.
- `sim_version` and `random_seed` remain missing until their local sources are documented and wired.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct assertion passed with `ARENA_EXPERIMENT_CODE_IDENTITY_ASSERTIONS_OK`.

## Follow-up

- Add `random_seed` only after the underlying stochastic services can consume and report it.
- Add dependency/environment hashes only after the expert-review task requires them or a local project document defines them.

## Progress Update 2026-05-03

- `docs/tasks/model-training/arena-experiment-sim-version-source.md` documents `stock_sim.__version__` as the first local sim version source.
- New Arena reports now include top-level `sim_version` when that version is available.
- `random_seed` remains missing until stochastic services can consume and report it.
