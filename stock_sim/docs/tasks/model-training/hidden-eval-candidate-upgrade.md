# Hidden Evaluation Candidate Upgrade

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- existing hidden-world registry, hidden runner, artifact writer, and runtime tests.

## Purpose

Harden hidden evaluation so it fairly evaluates a frozen candidate against strong baselines on uncontaminated hidden
worlds. A hidden fail is treated as valid research feedback, not as an engineering error to bypass.

## Implemented

- Added required hidden baselines: `twap`, `vwap`, `ac_lite`.
- Added candidate checkpoint freeze validation. A checkpoint must have `frozen=true` or `is_frozen=true`.
- Added hidden split contamination detection against checkpoint training world hashes.
- Added minimum hidden-world sample-size validation.
- Hidden summaries now include:
  - `candidate_frozen`
  - `required_baseline_names`
  - `present_baseline_names`
  - `missing_baseline_names`
  - `split_contamination_worlds`
  - `min_hidden_worlds`
  - `failure_type`
  - `next_action`
- Hidden paired comparisons now record candidate-vs-baseline deltas for `net_return`, `execution_shortfall`,
  `fee_drag`, `turnover`, `max_drawdown`, `inventory_risk`, and `unfilled_ratio`.
- Hidden artifact writing now preserves the summary `failure_type` and `next_action` instead of collapsing all hidden
  failures into a generic baseline failure.

## Explicitly Not Done

- Did not claim the current Task 101 hidden evaluation artifact passes.
- Did not lower the win-rate thresholds against TWAP/VWAP/AC-lite.
- Did not treat hidden underperformance as an engineering failure.
- Did not re-run Task 101 hidden evaluation with a stronger trained candidate.
- Did not open parent eligibility or research acceptance while hidden evaluation remains blocked.
- Did not delete PostgreSQL historical data.

## Verification

- `.venv\Scripts\python.exe -m py_compile app\services\hidden_world_runner.py app\services\evidence_artifact_writer.py tests\runtime\test_hidden_world_runner.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_hidden_world_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `10 passed`
- Full evidence regression:
  `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `49 passed`

## Current No-Go Meaning

Hidden evaluation now explains more failure modes: `underperform_baseline`, `risk_budget_breach`,
`sample_size_too_small`, `split_contamination`, and missing required baseline evidence. The current No-Go remains
correct until a frozen candidate honestly beats the required baselines on uncontaminated hidden worlds with enough
sample size and no risk-budget breach.
