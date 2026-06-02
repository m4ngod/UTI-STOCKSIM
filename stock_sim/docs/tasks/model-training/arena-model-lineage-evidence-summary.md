# Arena Model Lineage Evidence Summary

_Created: 2026-05-04_

## Source

This document is derived only from:

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`
- `docs/tasks/model-training/arena-transition-evidence-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

## Purpose

Work Package E requires generated reports to answer what model and what parent lineage produced a result, including mutation evidence. Existing Arena reports already carry `config.model_specs`, `pbt.lineage`, and `pbt.applied_agents`. This task exposes those existing fields in a compact generation summary and series aggregate.

This is a report-summary change only. It does not create new lineage, mutate models, change PBT parent selection, or add a new model registry path.

## Scope

Implemented:

- Add `model_lineage_evidence` to Arena generation summaries.
- Add `aggregate.model_lineage_evidence` to Arena series aggregates.
- Read existing evidence from:
  - `config.model_specs`
  - `pbt.lineage`
  - `pbt.applied_agents`
- Generation summaries now expose:
  - status: `has_lineage` or `no_lineage`
  - model count and agent count
  - model ids and agent ids
  - lineage count and applied-agent count
  - applied model ids
  - parent model ids
  - child model ids
  - mutation keys
  - bounded lineage samples
- Series aggregates now count:
  - observed reports
  - total lineage rows
  - total applied-agent rows
  - lineage status counts
  - model id counts
  - agent id counts
  - parent model id counts
  - child model id counts
  - applied model id counts
  - mutation key counts

## Explicitly Not Implemented

- No new PBT lineage creation.
- No new mutation logic.
- No model registry or checkpoint loading changes.
- No training, execution, reward, account, checkpoint, or PostgreSQL behavior changes.
- No automatic checkpoint promotion.

## Acceptance

- Generation summaries can answer which model ids participated and whether parent/child lineage exists.
- Series aggregates can count parent ids, child ids, and mutation keys without opening every full report.
- Reports remain a compact summary of existing evidence; no raw model artifacts or new lineage rows are generated.

## Verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
- Direct assertion passed with `ARENA_MODEL_LINEAGE_EVIDENCE_ASSERTIONS_OK`.

## Follow-up

- Keep this as report-only evidence until the project documents a separate model-lineage artifact schema or additional mutation acceptance criteria.

## Progress Update 2026-05-04: Completeness Status

- `docs/tasks/model-training/arena-model-lineage-evidence-completeness-status.md` now tracks `model_lineage_evidence` in `experiment_record_completeness`.
- Generations with compact lineage evidence mark the field as `present`.
- Generations without PBT lineage rows keep the field explicit as `not_available`.
