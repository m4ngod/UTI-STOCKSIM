# Paired Fee/Impact Sensitivity Runner v0

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 94: Paired Fee/Impact Runner v0.

## Purpose

Identify whether a frozen checkpoint only works because of low fees, optimistic impact, optimistic fill latency, or
similar execution-rule assumptions. The runner does not require the model to remain profitable under every stressed
world; it requires a paired degradation curve that is explicit and non-crashing.

## Runner Boundary

Implemented in `app/services/paired_sensitivity_runner.py`:

- `PairedSensitivityRunner.run_paired_sensitivity(...)`
- `apply_perturbation(...)`
- `metric_delta(...)`

The runner:

- evaluates the base world once,
- applies configured perturbations to the same base world spec,
- evaluates each stressed world with the same frozen policy,
- calls the supplied evaluator with `allow_learning=False`,
- records base metrics, stressed metrics, and numeric deltas,
- persists a separate `paired_sensitivity_artifact_v1`.

## Supported Perturbation Kinds

The v0 runner supports the required Week 3 categories:

- `fee`
- `impact`
- `latency`

It also has explicit paths for the markdown's additional recommended perturbation groups:

- `queue`
- `spread`
- `liquidity`
- `partial_fill`
- custom path operations through `path`, `op`, and `value`.

## Pass Boundary

`paired_sensitivity_artifact_v1` can pass only when:

- common Evidence Runner identity fields are present,
- `checkpoint_hash` is present,
- paired results exist,
- required perturbation kinds are present,
- base and stressed evaluations do not error,
- each paired result has a finite base and stressed score.

Severe score degradation can be reported as a warning when the caller supplies `severe_degradation_ratio`; it is not a
default failure because the markdown says high-fee worlds do not have to remain profitable.

## Artifact Output

The artifact uses:

- `artifact_kind=paired_sensitivity_artifact_v1`
- `runner_name=paired_sensitivity_runner`
- `runner_version=v0`
- `checkpoint_hash`
- base world id/hash
- per-perturbation base/stressed metrics
- per-perturbation delta and degradation values
- summary degradation curve
- pass/fail and failure reasons
- canonical `artifact_hash`

## Explicitly Deferred

- Real checkpoint file loading.
- Real world construction from a world spec.
- Runtime Arena integration.
- Multi-seed sensitivity aggregation.
- Exploit-test runner.
- Strict parent gate v2.
- GUI behavior.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/paired_sensitivity_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_paired_sensitivity_runner.py`
- Direct behavior assertion passed with `PAIRED_SENSITIVITY_RUNNER_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
