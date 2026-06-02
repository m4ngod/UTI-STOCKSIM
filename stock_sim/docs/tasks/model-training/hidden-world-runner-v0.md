# Hidden-World Runner v0

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 93: Hidden-World Runner v0.

## Purpose

Evaluate a frozen checkpoint against hidden-world specs and baseline policies without training, PBT, reward tuning,
hyperparameter updates, or policy mutation.

## Runner Boundary

Implemented in `app/services/hidden_world_runner.py`:

- `HiddenWorldRunner.run_hidden_eval(...)`
- Hidden specs are selected from `hidden_world_registry_v1`.
- The runner evaluates only specs whose split is `hidden`.
- The injected evaluator is called with `allow_learning=False` for the frozen policy and all baselines.
- Baseline comparisons are computed per hidden world.
- The result is persisted through `EvidenceArtifactWriter.write_hidden_eval_artifact(...)`.

## Pass Boundary

`hidden_eval_artifact_v1` can pass only when:

- common Evidence Runner identity fields are present,
- `checkpoint_hash` is present,
- hidden-world results exist,
- model win rate against baseline median is at least `0.60` by default,
- model win rate against the strongest baseline is at least `0.40` by default,
- no configured risk limit is breached,
- no `no_signal` hidden world produces positive model score beyond the configured tolerance,
- baselines are present for each hidden world.

## Artifact Output

The artifact uses:

- `artifact_kind=hidden_eval_artifact_v1`
- `runner_name=hidden_world_runner`
- `runner_version=v0`
- `checkpoint_hash`
- hidden registry hash as `world_hash`
- per-world model and baseline metrics
- per-world comparison fields
- summary metrics and failure reasons
- canonical `artifact_hash`

## Explicitly Deferred

- Real checkpoint file loading.
- Real world construction from a world spec.
- Runtime Arena integration.
- Paired fee/impact sensitivity runner.
- Exploit-test runner.
- Strict parent gate v2.
- GUI behavior.
- PostgreSQL artifact persistence or data deletion.

## Verification

- `python -m py_compile app/services/hidden_world_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_hidden_world_runner.py`
- Direct behavior assertion passed with `HIDDEN_WORLD_RUNNER_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the project `.venv` points to a missing `Python311` executable and the available
system/runtime Python installations do not have `pytest` installed.
