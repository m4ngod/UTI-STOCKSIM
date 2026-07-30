# Arena Experiment Record Kind Metadata

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires training, calibration, evaluation, and exploit-test records to remain distinguishable. Current Arena reports already contain training episode results and embedded evaluation/exploit sections, but the report did not explicitly label what kind of artifact it was.

This task adds report-kind metadata only. It does not create separate calibration, hidden-evaluation, or exploit-test artifacts.

## Scope

Implemented:

- Add top-level `record_kind` to Arena experiment reports.
- Add `experiment_record_metadata.record_kind`.
- Add `record_kind` to Arena generation summaries.
- Add `aggregate.record_kind` to Arena series aggregates.
- Mark current Arena reports as:
  - `kind=arena_experiment_report`
  - `primary_stage=training`
- List embedded sections:
  - `training_episode`
  - `baseline_suite`
  - `benchmark_comparison`
  - `hidden_evaluation`
  - `exploit_detector`
  - `research_acceptance`
  - `pbt`
- Keep separate artifact statuses explicit:
  - `separate_calibration_record_status=not_available`
  - `separate_hidden_evaluation_record_status=not_available`
  - `separate_exploit_test_record_status=not_available`

## Explicitly Not Implemented

- No separate calibration artifact.
- No separate hidden-evaluation artifact.
- No separate exploit-test artifact.
- No hidden-world runner.
- No calibration metric computation.
- No random seed injection.
- No training, execution, reward, account, PBT, checkpoint, or PostgreSQL behavior changes.

## Acceptance

- New Arena reports can state what kind of experiment record they are.
- Generation summaries expose the record kind without opening full reports.
- Series aggregates count record kinds, primary stages, embedded sections, and missing separate artifact statuses.
- The report does not imply calibration or hidden/exploit artifacts exist separately when they do not.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct assertion passed with `ARENA_RECORD_KIND_METADATA_ASSERTIONS_OK`.

## Progress Update 2026-05-04: Detail Completeness Batch

- `docs/tasks/model-training/arena-record-kind-schema-completeness-status.md` now documents completeness tracking for `record_kind.schema`.
- `docs/tasks/model-training/arena-record-kind-kind-completeness-status.md` now documents completeness tracking for `record_kind.kind`.
- `docs/tasks/model-training/arena-record-primary-stage-completeness-status.md` now documents completeness tracking for `record_kind.primary_stage`.
- `docs/tasks/model-training/arena-record-task-name-completeness-status.md` now documents completeness tracking for `record_kind.task_name`.
- `docs/tasks/model-training/arena-record-embedded-sections-completeness-status.md` now documents completeness tracking for `record_kind.embedded_sections`.
- This remains metadata only and does not create separate calibration, hidden-evaluation, or exploit-test artifacts.

## Follow-up

- Add separate calibration records only after calibration metric ownership and output schema are documented.
- Add separate hidden-evaluation and exploit-test artifacts only after their runners and artifact boundaries are documented.

## Progress Update 2026-05-04: Completeness Status

- `docs/tasks/model-training/arena-record-kind-completeness-status.md` now tracks `record_kind` in `experiment_record_completeness`.
- Separate calibration, hidden-evaluation, and exploit-test artifact statuses are now reflected in completeness field statuses.
- This remains status metadata only; no separate artifact is created.
