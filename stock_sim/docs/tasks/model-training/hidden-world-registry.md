# Hidden World Registry

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 92: Hidden World Registry.

## Purpose

Create a split registry for visible, validation, hidden, and exploit worlds before Task 93 can evaluate frozen
checkpoints. The registry is an identity and selection boundary only; it does not run hidden evaluation.

## Split Boundary

The registry supports:

- `visible`
- `validation`
- `hidden`
- `exploit`

`train` is accepted as an alias and normalized to `visible`.

## Pass Boundary

The registry passes only when these splits exist:

- `visible`
- `validation`
- `hidden`

`exploit` is registered when present but does not block Task 92 registry creation.

## Current Status

Implemented in `app/services/evidence_core.py`:

- `build_world_split_registry(...)`
- `world_split_registry_hash(...)`
- `hidden_world_specs(...)`
- `WORLD_REGISTRY_SPLITS`

Focused tests live in `tests/runtime/test_evidence_core.py`.

## Explicitly Deferred

- Hidden-World Runner v0.
- Frozen checkpoint loading or evaluation.
- Baseline comparison on hidden worlds.
- No-learning enforcement during policy evaluation.
- `hidden_eval_artifact_v1` persistence.
- GUI behavior.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/evidence_core.py tests/runtime/test_evidence_core.py`
- Direct behavior assertion passed with `HIDDEN_WORLD_REGISTRY_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
