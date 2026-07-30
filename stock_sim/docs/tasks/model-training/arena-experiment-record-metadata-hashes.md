# Arena Experiment Record Metadata Hashes

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `rl/contracts.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E asks generated reports to state what reward and what world/config produced a result. Task 46 made missing reproducibility fields visible. This task closes the safe part of that gap by deriving deterministic report-level hashes from existing Arena config and reward identity fields.

These hashes are report metadata only. They do not claim hidden-world calibration, replay data provenance, or real-market validation.

## Implemented

Arena experiment reports now include:

- `reward_hash`
- `world_hash`
- `world_card`
- `experiment_record_metadata`

`experiment_record_metadata` includes:

- `schema=stock_sim.experiment_record_metadata.v1`
- `hash_method=sha256_json_canonical_v1`
- `code_identity`
- `reward_identity`
- `world_identity`
- `world_card`
- `contract_versions`
- `missing_sources`
- `not_applicable_sources`

`reward_hash` is computed from canonical JSON over:

- `schema=stock_sim.reward_identity.v1`
- `reward_profile`
- `task_name`
- `reward_contract_version`

`world_hash` is computed from canonical JSON over:

- `schema=stock_sim.arena_world_identity.v1`
- `symbols`
- `retail_count`
- `retail_initial_cash`
- `clock_start_day`
- `clock_speed`
- `run_clock`
- `seed_training_liquidity`
- `liquidity_account_id`
- `liquidity_order_qty`
- `liquidity_spread_ticks`

The generated hashes are then picked up by `experiment_record_completeness`, so `reward_hash` and `world_hash` can move from `missing` to `present` for reports generated after this change.

_Update 2026-05-03_: `docs/tasks/model-training/arena-experiment-code-identity-hash.md` adds a Git-based `code_identity` source and top-level `code_hash` when Git identity is available. Dirty worktree state remains explicit.

_Update 2026-05-04_: `docs/tasks/model-training/arena-world-card-metadata.md` adds top-level `world_card` and `experiment_record_metadata.world_card` from existing world/config inputs. Calibration remains `not_available`; no calibration harness or world-pool split is implemented.

_Update 2026-05-04_: `docs/tasks/model-training/arena-reward-identity-completeness-status.md` adds `reward_identity` to `experiment_record_completeness.field_status`, using the already recorded reward identity object behind `reward_hash`.

_Update 2026-05-04_: `docs/tasks/model-training/arena-contract-versions-completeness-status.md` adds `contract_versions` to `experiment_record_completeness.field_status`, using the already recorded observation/action/reward contract-version bundle.

_Update 2026-05-04_: `docs/tasks/model-training/arena-hash-method-completeness-status.md` adds `hash_method` to `experiment_record_completeness.field_status`, using the already recorded canonical hash-method metadata.

_Update 2026-05-04_: the metadata source completeness batch adds `metadata_schema`, `code_identity`, `sim_version_identity`, `random_seed_identity`, `missing_sources`, and `not_applicable_sources` to `experiment_record_completeness.field_status`, using fields already recorded under `experiment_record_metadata`.

## Explicitly Not Implemented

- No sim version source.
- No runtime random seed injection.
- No hidden-world or validation-world hash split.
- No calibration pass/fail score.
- No replay/hybrid data cutoff.
- No training, execution, reward, account, PBT, or checkpoint behavior changes.
- No PostgreSQL data deletion or mutation.

## Acceptance

- A new Arena report contains `reward_hash` and `world_hash`.
- The saved JSON report preserves the same hash values returned by the runner.
- `experiment_record_metadata` exposes the hash method and source identities.
- `experiment_record_completeness` treats generated `reward_hash` and `world_hash` as present.
- `sim_version` and `random_seed` remain explicit missing sources until local ownership is documented.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pure pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct runner assertion passed with `ARENA_EXPERIMENT_RECORD_METADATA_ASSERTIONS_OK`.
- Direct completeness assertion passed with `ARENA_EXPERIMENT_RECORD_HASH_COMPLETENESS_ASSERTIONS_OK`.
- Pytest for `test_runner_orchestrates_arena_clock_and_writes_report` remains blocked by Windows pytest temporary-directory lock/cleanup permissions in this environment.

## Follow-up

- Document a code-hash source before adding `code_hash`.
- Document a sim-version source before adding `sim_version`.
- Add an actual random seed only when the underlying stochastic services can consume it.
- Add hidden/validation world hashes only after the world pool and split rules are documented.
