# Arena Series Experiment Record Completeness

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-audit-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires each training/evaluation artifact to be reproducible enough to audit. Current Arena episode reports already carry some run metadata, but multi-generation summaries need a compact machine-readable view of which reproducibility fields are present and which are still missing.

This task adds a report-only completeness summary. It does not fabricate code hashes, world hashes, reward hashes, random seeds, or data cutoffs. Missing or unavailable fields remain explicit so later work can close them with documented inputs.

## Scope

Implemented:

- Add `experiment_record_completeness` to generation summaries.
- Add `aggregate.experiment_record_completeness` to series aggregates.
- Track field status for:
  - `episode_id`
  - `arena_id`
  - `generation`
  - `model_specs`
  - `reward_profile`
  - `task_name`
  - `symbols`
  - `report_path`
  - `checkpoint_dir`
  - `world_config`
  - `code_hash`
  - `sim_version`
  - `reward_hash`
  - `world_hash`
  - `random_seed`
  - `parent_lineage`
  - `data_cutoff`
- Distinguish field states:
  - `present`
  - `missing`
  - `not_available`
  - `not_applicable`
- Count completeness status, field-status pairs, present fields, missing fields, unavailable fields, and not-applicable fields across a series.

## Explicitly Not Implemented

- No code hash generation.
- No sim version source.
- No reward hash generation.
- No world hash generation.
- No random seed injection.
- No replay/hybrid data-cutoff support.
- No training, execution, reward, account, PBT, or checkpoint behavior changes.
- No PostgreSQL data deletion or mutation.

## Acceptance

- Generation summaries expose field-by-field completeness without hiding missing fields.
- Series aggregates show recurring missing metadata such as `code_hash`, `world_hash`, `reward_hash`, and `random_seed`.
- `data_cutoff` is `not_applicable` when replay/hybrid data is not in use.
- `parent_lineage` is `not_available` when no PBT lineage row exists for the generation.
- Existing baseline-suite, benchmark-comparison, hidden/exploit, audit, research-acceptance, strict-gate, execution, and PBT aggregate fields remain unchanged.

## Verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_episode_audit_summaries`
- Direct assertion passed with `ARENA_SERIES_EXPERIMENT_RECORD_COMPLETENESS_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

## Follow-up

- Add real `code_hash`, `sim_version`, `reward_hash`, `world_hash`, and `random_seed` sources only after their project-local source and ownership are documented.
- Keep replay/hybrid `data_cutoff` as `not_applicable` until replay/hybrid data is added through a documented task.

## Progress Update 2026-05-03

- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md` documents the first safe sources.
- New Arena reports now include deterministic `reward_hash` and `world_hash` values derived from existing local report inputs.
- `code_hash`, `sim_version`, and `random_seed` remain missing until their sources are documented and wired.

## Progress Update 2026-05-03: Code Identity

- `docs/tasks/model-training/arena-experiment-code-identity-hash.md` documents the local Git code identity source.
- New Arena reports now include top-level `code_hash` when Git identity is available.
- Dirty worktree status remains visible in `experiment_record_metadata.code_identity`.
- `sim_version` and `random_seed` remain missing until their sources are documented and wired.

## Progress Update 2026-05-03: Sim Version

- `docs/tasks/model-training/arena-experiment-sim-version-source.md` documents `stock_sim.__version__` as the local sim version source.
- New Arena reports now include top-level `sim_version` when the package version is available.
- `experiment_record_completeness` can now mark `sim_version` as present for new reports.
- `random_seed` remains missing until stochastic services can consume and report it.

## Progress Update 2026-05-03: Random Seed Status

- `docs/tasks/model-training/arena-experiment-random-seed-status.md` documents the current `random_seed` blocker.
- New Arena reports now include `random_seed_identity.status=not_available`.
- `experiment_record_completeness` intentionally continues to count `random_seed` as missing.
- A real seed should only be added after Arena config, retail persona sampling, model training RNG, and market/world RNG consume it.

## Progress Update 2026-05-04: Identity Summary

- `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md` documents the compact identity summary layer.
- Arena generation summaries now include `experiment_record_identity`.
- Arena series aggregates now include `aggregate.experiment_record_identity`.
- The new summary reads existing top-level report fields and `experiment_record_metadata` only.
- `random_seed` remains `not_available` and missing until stochastic services consume a real seed.

## Progress Update 2026-05-04: World Card Completeness

- `docs/tasks/model-training/arena-world-card-completeness-status.md` documents the world-card completeness extension.
- `experiment_record_completeness.field_status` now tracks `world_card`.
- `experiment_record_completeness.field_status` now tracks `world_calibration`.
- `world_card` is present only when a real world-card object exists, not merely when `world_hash` exists.
- `world_calibration` remains `not_available` while the calibration harness is not implemented.

## Progress Update 2026-05-04: Calibration Score Slot

- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md` documents the explicit calibration-score slot.
- World-card metadata now includes `calibration.score_status=not_available`.
- Arena generation summaries expose calibration-score status and reason.
- Arena series aggregates count `aggregate.world_card.calibration_score_status_counts`.
- This does not compute calibration scores or change completeness status mapping.

## Progress Update 2026-05-04: Calibration Score Completeness

- `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md` documents calibration-score completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_calibration_score`.
- Explicit unavailable score slots are counted as `not_available`.
- Reports lacking the score slot are still counted as `missing`.
- Future real scores can become `present` without changing series aggregate shape.

## Progress Update 2026-05-04: World Split Completeness

- `docs/tasks/model-training/arena-world-split-completeness-status.md` documents world-split completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_split`.
- Current `training_only` world cards are counted as `not_available`.
- Reports lacking split metadata are still counted as `missing`.
- Future validation/hidden split statuses can become `present` without changing series aggregate shape.

## Progress Update 2026-05-04: Retail Family Mix Completeness

- `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md` documents retail-family-mix completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_retail_family_mix`.
- Current explicit unavailable retail-family-mix metadata is counted as `not_available`.
- Reports lacking retail-family-mix metadata are still counted as `missing`.
- Future retail-family-mix evidence can become `present` without changing series aggregate shape.

## Progress Update 2026-05-04: Liquidity Seed Completeness

- `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md` documents training-liquidity seed completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_liquidity_seed`.
- Explicit liquidity-seed configuration is counted as `present`.
- Reports lacking liquidity-seed metadata are still counted as `missing`.

## Progress Update 2026-05-04: World Clock Completeness

- `docs/tasks/model-training/arena-world-clock-completeness-status.md` documents world-clock completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_clock`.
- Complete world-card clock configuration is counted as `present`.
- Reports lacking clock metadata are still counted as `missing`.

## Progress Update 2026-05-04: World Universe Completeness

- `docs/tasks/model-training/arena-world-universe-completeness-status.md` documents world-universe completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_universe`.
- Non-empty world-card universe metadata is counted as `present`.
- Reports lacking world-card universe metadata are still counted as `missing`.

## Progress Update 2026-05-04: World Identity Completeness

- `docs/tasks/model-training/arena-world-identity-completeness-status.md` documents world-identity completeness tracking.
- `experiment_record_completeness.field_status` now tracks `world_identity`.
- Reports with a top-level or metadata `world_identity` object are counted as `present`.
- Reports lacking world-identity metadata are still counted as `missing`.

## Progress Update 2026-05-04: Reward Identity Completeness

- `docs/tasks/model-training/arena-reward-identity-completeness-status.md` documents reward-identity completeness tracking.
- `experiment_record_completeness.field_status` now tracks `reward_identity`.
- Reports with a top-level or metadata `reward_identity` object are counted as `present`.
- Reports lacking reward-identity metadata are still counted as `missing`.

## Progress Update 2026-05-04: Contract Versions Completeness

- `docs/tasks/model-training/arena-contract-versions-completeness-status.md` documents contract-version completeness tracking.
- `experiment_record_completeness.field_status` now tracks `contract_versions`.
- Reports with a top-level or metadata `contract_versions` object are counted as `present`.
- Reports lacking contract-version metadata are still counted as `missing`.

## Progress Update 2026-05-04: Hash Method Completeness

- `docs/tasks/model-training/arena-hash-method-completeness-status.md` documents hash-method completeness tracking.
- `experiment_record_completeness.field_status` now tracks `hash_method`.
- Reports with a top-level or metadata hash-method value are counted as `present`.
- Reports lacking hash-method metadata are still counted as `missing`.

## Progress Update 2026-05-04: Metadata Source Completeness Batch

- `docs/tasks/model-training/arena-metadata-schema-completeness-status.md` documents metadata-schema completeness tracking.
- `docs/tasks/model-training/arena-code-identity-completeness-status.md` documents code-identity completeness tracking.
- `docs/tasks/model-training/arena-sim-version-identity-completeness-status.md` documents sim-version-identity completeness tracking.
- `docs/tasks/model-training/arena-random-seed-identity-completeness-status.md` documents random-seed-identity completeness tracking.
- `docs/tasks/model-training/arena-missing-sources-completeness-status.md` documents missing-sources completeness tracking.
- `docs/tasks/model-training/arena-not-applicable-sources-completeness-status.md` documents not-applicable-sources completeness tracking.
- `experiment_record_completeness.field_status` now tracks `metadata_schema`, `code_identity`, `sim_version_identity`, `random_seed_identity`, `missing_sources`, and `not_applicable_sources`.
- Reports with the corresponding top-level or metadata value are counted as `present`.
- Reports lacking the corresponding metadata remain counted as `missing`.

## Progress Update 2026-05-04: Record Kind Metadata

- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md` documents record-kind labeling.
- Arena generation summaries now include `record_kind`.
- Arena series aggregates now include `aggregate.record_kind`.
- Separate calibration, hidden-evaluation, and exploit-test artifact statuses remain explicit as `not_available`.

## Progress Update 2026-05-04: Record Kind Completeness

- `docs/tasks/model-training/arena-record-kind-completeness-status.md` documents record-kind completeness tracking.
- `experiment_record_completeness.field_status` now tracks `record_kind`.
- `experiment_record_completeness.field_status` now tracks separate calibration, hidden-evaluation, and exploit-test artifact status.
- Explicit `not_available` artifact statuses remain visible in completeness aggregates.

## Progress Update 2026-05-04: Record Kind Detail Completeness Batch

- `docs/tasks/model-training/arena-record-kind-schema-completeness-status.md` documents record-kind schema completeness tracking.
- `docs/tasks/model-training/arena-record-kind-kind-completeness-status.md` documents record-kind value completeness tracking.
- `docs/tasks/model-training/arena-record-primary-stage-completeness-status.md` documents record primary-stage completeness tracking.
- `docs/tasks/model-training/arena-record-task-name-completeness-status.md` documents record task-name completeness tracking.
- `docs/tasks/model-training/arena-record-embedded-sections-completeness-status.md` documents embedded-sections completeness tracking.
- `experiment_record_completeness.field_status` now tracks `record_kind_schema`, `record_kind_kind`, `record_primary_stage`, `record_task_name`, and `record_embedded_sections`.
- Reports with the corresponding `record_kind` subfield are counted as `present`.
- Reports lacking the corresponding subfield remain counted as `missing`.

## Progress Update 2026-05-04: Transition Evidence

- `docs/tasks/model-training/arena-transition-evidence-summary.md` documents compact transition evidence summaries.
- Arena generation summaries now include `transition_evidence`.
- Arena series aggregates now include `aggregate.transition_evidence`.
- The summary uses existing audit samples and counts only; raw transition persistence is unchanged.

## Progress Update 2026-05-04: Transition Evidence Completeness

- `docs/tasks/model-training/arena-transition-evidence-completeness-status.md` documents transition-evidence completeness tracking.
- `experiment_record_completeness.field_status` now tracks `transition_evidence`.
- Episodes with transitions mark `transition_evidence` as `present`.
- Episodes without transitions mark `transition_evidence` as `not_available`.

## Progress Update 2026-05-04: Model Lineage Evidence

- `docs/tasks/model-training/arena-model-lineage-evidence-summary.md` documents compact model-lineage evidence summaries.
- Arena generation summaries now include `model_lineage_evidence`.
- Arena series aggregates now include `aggregate.model_lineage_evidence`.
- The summary uses existing model specs, PBT lineage rows, and applied-agent rows only.
- This improves the report answer for model id, parent id, child id, and mutation keys without changing completeness status mapping.

## Progress Update 2026-05-04: Model Lineage Evidence Completeness

- `docs/tasks/model-training/arena-model-lineage-evidence-completeness-status.md` documents model-lineage evidence completeness tracking.
- `experiment_record_completeness.field_status` now tracks `model_lineage_evidence`.
- Generations with PBT lineage rows mark `model_lineage_evidence` as `present`.
- Generations without PBT lineage rows mark `model_lineage_evidence` as `not_available`.
- Series completeness aggregates now count `model_lineage_evidence` field statuses.
