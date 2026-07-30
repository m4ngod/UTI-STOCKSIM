# Calibration Scorecard v0

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/current-work-status/model-training.md`

## Task

Task 87: Calibration Scorecard v0.

## Purpose

Define how market metrics are compared with a target profile before a calibration artifact can be written.

## Target Profile

The profile should include:

- `target_profile_id`
- metric targets with mean and scale or standard deviation.
- metric weights.
- critical distance thresholds.
- required metric list.

## Distance Rule

Use normalized distance:

```python
def normalized_distance(sim_value, target_mean, target_scale, cap=5.0):
    if target_scale <= 0:
        return 0.0 if abs(sim_value - target_mean) < 1e-12 else cap
    return min(abs(sim_value - target_mean) / target_scale, cap)
```

## Pass Rule

Calibration passes only when:

- weighted score is within the documented threshold.
- no critical metric exceeds `critical_max_distance`.
- all required metric coverage is `present`.

Missing or `not_available` required metrics must not become zero-distance passes.

## Output Shape

The scorecard output for Task 88 should include:

- `target_profile_id`
- `score`
- `parts`
- `pass`
- `critical_failures`
- `coverage_failures`
- `failure_reasons`

## Current Status

Implemented in `app/services/evidence_core.py`.

Current code provides:

- `normalized_distance(...)`
- `compute_calibration_scorecard(...)`

Focused tests live in `tests/runtime/test_evidence_core.py`.

Target profile storage, calibration runner execution, GUI behavior, and PostgreSQL behavior remain outside this task.
