# Long Arena Dry Run Package v1

_Created: 2026-05-05_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 101: Long Arena Dry Run.

## Purpose

Produce a single evidence package for a multi-generation Arena dry run so the project can review whether any candidate
has enough independent evidence to pass the parent gate.

## Package Boundary

Implemented in:

- `app/services/long_arena_dry_run.py`
- `tests/runtime/test_long_arena_dry_run.py`

The v1 runner accepts an Arena series callable. The first implementation used a deterministic headless callable so the
package format could be tested before the local runtime was repaired. The current live run uses the real
`ArenaExperimentRunner.run_generations(...)` callable from `build_app_context()`, backed by PostgreSQL and runtime
`RuntimeModelAgent` execution.

## Package Contents

The package writes `long_arena_dry_run_package_v1` JSON under:

- `output/evidence_artifacts/long_arena_dry_run_package_v1/`

Each package includes:

- run policy: requested generation count, minimum generation count, actual generation count
- Arena series report summary and report hash
- generation report hashes
- `series_evidence_aggregate_v1`
- Evidence Board view
- parent-gate and research-acceptance review
- `status`, `go_no_go`, `failure_reasons`, and canonical `package_hash`

## Headless Package Run

A headless injected-series package run was produced for Task 101:

- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-headless-dry-run-6fb719d531f4c733.json`

This package is a deterministic headless package check. It is not a live PostgreSQL/runtime Arena long run.

## Live PostgreSQL/Runtime Package Run

After repairing the Python runtime dependency path, Task 101 was rerun through the live service/runtime path:

- package: `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-1233652fdd357ead.json`
- status-corrected package: `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-status-fix-dc02f5c7587a9899.json`
- seed/checkpoint adjusted package: `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-live-adjusted-attempt-5d5d363766ebc1d2.json`
- series report: `output/task101_live_long_arena/task101-live-runtime-cc0a9a6a-series-20260507102232.json`
- augmented runtime report: `output/task101_live_long_arena/task101-live-runtime-cc0a9a6a-augmented-runtime-evidence.json`
- series id: `task101-live-runtime-cc0a9a6a`
- candidate id: `T101LIVE_CANDIDATE_cc0a9a6a`
- requested/actual generations: `3 / 3`
- runtime source: `live ArenaExperimentRunner via build_app_context runtime_gateway`
- agent runtime: `RuntimeModelAgent through AgentService/AppContext`
- database dialect: `postgresql`
- database URL driver: `postgresql+pg8000`
- PostgreSQL rows written/read for the package run: 3 `training_episodes`, 21 `model_episode_results`, 38 `model_transitions`

The original package was `incomplete` / `no_go` because the v1 package-completeness check incorrectly treated failed
evidence as incomplete evidence. This was corrected so package `status` only reflects whether the multi-generation run
and required candidate evidence slots are present; pass/fail remains represented by `go_no_go` and
`failure_reasons`. The status-corrected package is now `complete` / `no_go`.

The package remains `no_go`, not because the runtime failed, but because the live evidence shows the candidate does not
pass the required gates:

- checkpoint hash and random seed ledger have now been materialized for the status-adjustment attempt
- baseline evidence now passes after attaching the seed ledger
- calibration evidence fails
- hidden evaluation evidence fails: the live hidden runner attempt produced `median_win_rate=0.0` and
  `strongest_win_rate=0.0`, so the static hold candidate did not beat TWAP/VWAP/AC-lite
- exploit-test evidence fails
- paired fee/impact sensitivity evidence fails
- strict parent gate blocks the candidate
- research acceptance lock remains closed

This is the desired evidence behavior for Task 101: live database/runtime execution now works, while the Evidence Runner
still refuses to promote the candidate without the required independent evidence.

## Explicitly Deferred

- Full GUI screenshot verification.
- PostgreSQL artifact persistence or data deletion.
- Research claim acceptance or parent promotion.

## Verification

- `python -m py_compile app/services/long_arena_dry_run.py tests/runtime/test_long_arena_dry_run.py`
- Direct behavior assertion passed with `LONG_ARENA_DRY_RUN_DIRECT_ASSERTIONS_OK`.
- Headless package output assertion passed with `LONG_ARENA_DRY_RUN_PACKAGE_OUTPUT_OK`.
- `pytest tests/runtime/test_long_arena_dry_run.py tests/runtime/test_arena_experiment_runner.py tests/test_persistence_db_config.py tests/test_persistence_db_health.py`
- Package readback confirmed the original package `status=incomplete`, `go_no_go=no_go`, `actual_generation_count=3`,
  and PostgreSQL row counts.
- Status-corrected package readback confirmed `status=complete`, `go_no_go=no_go`, `actual_generation_count=3`, and
  `status_counts={"fail": 7}`.
- Seed/checkpoint adjusted package readback confirmed `status=complete`, `go_no_go=no_go`, `actual_generation_count=3`,
  `status_counts={"pass": 1, "fail": 6}`, and `baseline_artifact=pass`.
- Live hidden-runner attempt wrote `output/evidence_artifacts/hidden_eval_artifact_v1/hidden-eval-119950edf3a20b87.json`
  with `pass_fail=false`, `hidden_median_win_rate_below_threshold`, and `hidden_strongest_win_rate_below_threshold`.
- Live exploit-runner attempt wrote `output/evidence_artifacts/exploit_test_artifact_v1/exploit-test-6aee4406f101b646.json`
  with `pass_fail=false`; only `no_signal_world` passed while timestamp, mark-to-market, order-boundary,
  fee-accounting, fill-rule, and clock-boundary probe metrics remained `not_available`.
- `pytest tests/runtime/test_long_arena_dry_run.py`
