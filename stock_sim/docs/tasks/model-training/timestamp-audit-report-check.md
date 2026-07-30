# Timestamp Audit Report Check

_Created: 2026-05-03_

## Source

This document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/runtime-observation-audit-report.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `persistence/models_training.py`
- `services/training_episode_service.py`
- `app/services/arena_experiment_runner.py`

## Purpose

The expert review requires exploit checks before Arena leaderboard rank can be treated as research acceptance. `timestamp_audit` was previously only a placeholder. This task adds the first report-side timestamp audit using persisted `ModelTransition` metadata.

This is a minimal ordering audit. It does not prove market-data causality and does not inspect every feature timestamp.

## Scope

Implemented:

- Add `timestamp_audit` to Arena episode details.
- Read existing `ModelTransition` rows for the episode.
- Group transitions by `agent_id`.
- Check each agent's persisted transition sequence by transition id.
- Flag:
  - non-integer `step_index`
  - negative `step_index`
  - duplicate `step_index`
  - regressed `step_index`
- Add `timestamp_audit` to `exploit_detector.checks`.
- Set `exploit_detector.status`:
  - `partial` when timestamp audit is available or not available but other exploit checks remain placeholders.
  - `failed` when timestamp audit fails.
- Keep research acceptance incomplete.

Status values:

- `not_available`: no persisted model transitions exist for the episode.
- `pass`: transition step indexes pass the implemented ordering checks.
- `fail`: at least one ordering violation exists.

## Explicitly Not Implemented

- No market-data timestamp causality proof.
- No bar-window or recent-trade time-bound validation.
- No comparison between observation time and execution fill time.
- No hidden split execution.
- No reward, execution, account, or PBT behavior changes.

## Acceptance

- Episodes with no transitions report `timestamp_audit.status=not_available`.
- Episodes with ordered transition step indexes report `timestamp_audit.status=pass`.
- Episodes with duplicate, negative, non-integer, or regressed step indexes report `timestamp_audit.status=fail`.
- `timestamp_audit` is visible under `exploit_detector.checks`.
- Research acceptance remains incomplete.

## Follow-up

- Add semantic timestamp checks for bars and recent trades.
- Add mark-to-market audit as the next report-side exploit detector check.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Update

_Update 2026-05-03_: `docs/tasks/model-training/mark-to-market-audit-report-check.md` promotes `mark_to_market_audit` from a placeholder to a minimal report-side accounting consistency check over episode result rows and transition reward sums.

_Update 2026-05-03_: `docs/tasks/model-training/arena-series-audit-summary.md` carries timestamp audit status and counts into Arena generation summaries and series aggregates. This is report-only and does not add semantic timestamp causality checks.
