# Evidence Contract Tests v1

_Created: 2026-05-05_

## Source

Derived only from:

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`

## Task

Task 100: Evidence Contract Tests.

## Purpose

Add a cross-runner contract test layer for the Evidence Runner phase so schema, hash identity, seed identity,
reproducibility, no-learning discipline, and bad-policy rejection are checked together.

## Test Boundary

Implemented in:

- `tests/runtime/test_evidence_contracts.py`

The contract tests are runtime-level tests. They do not construct the GUI, run a long Arena series, or touch
PostgreSQL data.

## Covered Contracts

The v1 contract test file covers:

- `world_spec_v1` canonical hash excludes `world_spec_hash` and changes on meaningful world changes.
- `random_seed_ledger_v1` derives deterministic label seeds and hashes excluding `random_seed_ledger_hash`.
- separate evidence artifacts include the common schema fields required by the expert-review artifact contract.
- artifact hash is reproducible for identical payloads and excludes the `artifact_hash` self field.
- Hidden-World, Paired Fee/Impact, and Exploit runners call evaluators with `allow_learning=False`.
- a constructed bad policy signal is rejected by `exploit_test_artifact_v1`.
- `parent_gate_artifact_v2` rejects a candidate when exploit evidence fails, even when other evidence passes.

## Explicitly Deferred

- Repairing the local pytest installation.
- Long Arena dry run execution.
- PostgreSQL artifact persistence or data deletion.
- GUI screenshot verification.

## Verification

- `python -m py_compile tests/runtime/test_evidence_contracts.py app/services/evidence_artifact_writer.py app/services/evidence_core.py app/services/hidden_world_runner.py app/services/paired_sensitivity_runner.py app/services/exploit_test_runner.py app/services/strict_parent_gate.py`
- Direct behavior assertion passed with `EVIDENCE_CONTRACT_TESTS_DIRECT_ASSERTIONS_OK`.

Targeted pytest could not run because the available runtime Python does not have `pytest` installed.
