# Arena World Card Completeness Status

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Task 52 added `world_card` metadata from existing Arena world/config inputs. Work Package C also requires calibration status to be visible before rankings are interpreted. This task makes `experiment_record_completeness` track whether a real world card exists and whether world calibration is available.

This is a report completeness change only. It does not implement calibration metrics or a world-pool split.

## Scope

Implemented:

- Add `world_card` to `experiment_record_completeness.field_status`.
- Add `world_calibration` to `experiment_record_completeness.field_status`.
- Treat `world_card` as `present` only when a real `world_card` object exists in the report or `experiment_record_metadata`.
- Treat `world_calibration` as:
  - `present` when calibration is reported as `pass`, `available`, or `complete`
  - `not_available` when calibration is explicitly `not_available`
  - `missing` when no calibration status is present
- Carry the new statuses into `aggregate.experiment_record_completeness.field_status_counts`, present/missing counts, and not-available counts.

## Explicitly Not Implemented

- No calibration pass/fail computation.
- No market-fact metric computation.
- No train/validation/hidden world split.
- No hidden-world runner.
- No random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- Reports with `world_card` can mark `world_card` as present in completeness.
- Reports with `world_card.calibration.status=not_available` mark `world_calibration` as `not_available`, not silently complete.
- Old reports with only `world_hash` do not falsely count as having a complete world card.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_WORLD_CARD_COMPLETENESS_ASSERTIONS_OK`.

## Follow-up

- Add real calibration statuses only after metric ownership, data sources, and pass/fail thresholds are documented.

## Progress Update 2026-05-04: Calibration Score Slot

- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md` documents the calibration-score slot.
- `world_card.calibration.score_status` remains `not_available` until a calibration harness exists.
- This does not change `experiment_record_completeness.field_status.world_calibration`.

## Progress Update 2026-05-04: Calibration Score Completeness

- `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md` documents calibration-score completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_calibration_score`.
- Explicit `calibration_score_status=not_available` remains visible as `not_available`.

## Progress Update 2026-05-04: World Split Completeness

- `docs/tasks/model-training/arena-world-split-completeness-status.md` documents world-split completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_split`.
- Current `training_only` split status remains visible as `not_available`.

## Progress Update 2026-05-04: Retail Family Mix Completeness

- `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md` documents retail-family-mix completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_retail_family_mix`.
- Current `retail_family_mix_status=not_available` remains visible as `not_available`.

## Progress Update 2026-05-04: Liquidity Seed Completeness

- `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md` documents liquidity-seed completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_liquidity_seed`.
- Explicit liquidity-seed configuration remains visible as `present`.

## Progress Update 2026-05-04: World Clock Completeness

- `docs/tasks/model-training/arena-world-clock-completeness-status.md` documents world-clock completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_clock`.
- Complete world-card clock configuration remains visible as `present`.

## Progress Update 2026-05-04: World Universe Completeness

- `docs/tasks/model-training/arena-world-universe-completeness-status.md` documents world-universe completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_universe`.
- Non-empty world-card universe metadata remains visible as `present`.
- Add hidden/validation world status only after documented world-pool split rules exist.
