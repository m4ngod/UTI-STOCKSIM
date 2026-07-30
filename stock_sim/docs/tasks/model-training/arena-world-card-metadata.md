# Arena World Card Metadata

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package C asks for world-card and calibration metadata before synthetic Arena results are interpreted as transferable. Current reports already include `world_hash` and `world_identity`. This task adds a compact world-card layer that surfaces those existing world/config inputs and keeps calibration gaps explicit.

This is report metadata only. It does not create a world pool, hidden world runner, calibration harness, market-fact metric calculator, or new training behavior.

## Scope

Implemented:

- Add top-level `world_card` to Arena experiment reports.
- Add `experiment_record_metadata.world_card`.
- Add `world_card` to Arena generation summaries.
- Add `aggregate.world_card` to Arena series aggregates.
- Preserve existing world/config inputs:
  - `world_hash`
  - symbols and symbol count
  - retail count and initial cash
  - clock start day, speed, and run flag
  - training-liquidity seed configuration
- Mark world split as:
  - `status=training_only`
  - `reason=world_pool_split_not_implemented`
- Mark calibration as:
  - `status=not_available`
  - `reason=calibration_harness_not_implemented`
- Track missing calibration metrics from the expert-review world-card list:
  - `return_distribution_shape`
  - `volatility_clustering_proxy`
  - `bid_ask_spread`
  - `depth`
  - `volume_turnover`
  - `order_arrival_cancel_fill_behavior`

## Explicitly Not Implemented

- No train/validation/hidden world split.
- No hidden-world runner.
- No calibration pass/fail score.
- No market-fact metric computation.
- No retail family-mix derivation.
- No random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- New Arena reports expose a `world_card` next to `world_hash`.
- Generation summaries can show the world-card status without opening full reports.
- Series aggregates can count world-card observations, unique world hashes, split status, calibration status, and missing calibration metrics.
- Calibration remains explicit as `not_available` until a documented calibration harness exists.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct assertion passed with `ARENA_WORLD_CARD_METADATA_ASSERTIONS_OK`.

## Follow-up

- Add calibration metrics only after the project defines metric ownership and data sources.
- Add train/validation/hidden world split only after seed/config hash split rules are documented.

## Progress Update 2026-05-04: Completeness Status

- `docs/tasks/model-training/arena-world-card-completeness-status.md` now tracks `world_card` and `world_calibration` in `experiment_record_completeness`.
- Reports with `world_card.calibration.status=not_available` keep `world_calibration` explicit as `not_available`.

## Progress Update 2026-05-04: Calibration Score Slot

- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md` now documents the explicit calibration-score slot.
- New world-card metadata includes `calibration.score=None`.
- New world-card metadata includes `calibration.score_status=not_available`.
- Arena generation summaries expose `calibration_score`, `calibration_score_status`, and `calibration_score_reason`.
- Arena series aggregates count `aggregate.world_card.calibration_score_status_counts`.

## Progress Update 2026-05-04: Calibration Score Completeness

- `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md` now documents completeness tracking for the calibration-score slot.
- `experiment_record_completeness.field_status` now tracks `world_calibration_score`.
- This remains metadata only and does not compute calibration scores.

## Progress Update 2026-05-04: World Split Completeness

- `docs/tasks/model-training/arena-world-split-completeness-status.md` now documents completeness tracking for world-card split status.
- `experiment_record_completeness.field_status` now tracks `world_split`.
- Current `world_card.split.status=training_only` remains explicit as `not_available`.
- This remains metadata only and does not implement world splitting.

## Progress Update 2026-05-04: Retail Family Mix Completeness

- `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md` now documents completeness tracking for retail family mix status.
- `experiment_record_completeness.field_status` now tracks `world_retail_family_mix`.
- Current `world_card.retail_profile.family_mix_status=not_available` remains explicit as `not_available`.
- This remains metadata only and does not implement retail family mix calculation.
- Old reports with only `world_hash` do not falsely count as having a complete world card.

## Progress Update 2026-05-04: Liquidity Seed Completeness

- `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md` now documents completeness tracking for training-liquidity seed configuration.
- `experiment_record_completeness.field_status` now tracks `world_liquidity_seed`.
- Explicit `world_card.liquidity_seed.seed_training_liquidity` values count as `present`.
- This remains metadata only and does not change liquidity behavior.

## Progress Update 2026-05-04: World Clock Completeness

- `docs/tasks/model-training/arena-world-clock-completeness-status.md` now documents completeness tracking for world-card clock configuration.
- `experiment_record_completeness.field_status` now tracks `world_clock`.
- Complete `clock_start_day`, `clock_speed`, and `run_clock` metadata counts as `present`.
- This remains metadata only and does not change clock behavior.

## Progress Update 2026-05-04: World Universe Completeness

- `docs/tasks/model-training/arena-world-universe-completeness-status.md` now documents completeness tracking for world-card universe metadata.
- `experiment_record_completeness.field_status` now tracks `world_universe`.
- Non-empty `world_card.universe.symbols` and positive `symbol_count` count as `present`.
- This remains metadata only and does not change symbol selection.

## Progress Update 2026-05-04: World Identity Completeness

- `docs/tasks/model-training/arena-world-identity-completeness-status.md` now documents completeness tracking for the world identity object behind `world_hash` and `world_card`.
- `experiment_record_completeness.field_status` now tracks `world_identity`.
- Existing `experiment_record_metadata.world_identity` objects count as `present`.
- This remains metadata only and does not change world-hash calculation or world generation.
