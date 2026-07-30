# Evidence Runner No-Go Hardening

_Created: 2026-05-07_
_Last updated: 2026-05-07_

## Source

Derived only from:

- `evidence_runner_no_go_hardening_task.md`
- existing project Evidence Runner code, tests, generated artifacts, and docs.

## Purpose

Harden the current healthy `complete / no_go` Task 101 state. The goal is not to turn the six remaining failed evidence
items into green status by lowering gates. The goal is to make live evidence artifacts, aggregate status, parent-gate
eligibility, research acceptance, and Evidence Board rows harder to misread or manually override.

## Current Evidence Interpretation

The current expected Task 101 state remains:

- package status: `complete`
- Go / No-Go: `no_go`
- evidence status counts: `{"pass": 1, "fail": 6}`
- upstream true fail: `calibration`, `hidden_eval`, `exploit_test`, `paired_sensitivity`
- derived fail: `strict_parent_gate`, `research_acceptance_lock`

The single pass is the baseline evidence. The six fails are intentional blockers until the upstream artifacts are
generated from live PostgreSQL/runtime facts and meet their own `pass_gate` criteria.

## Implemented This Round

- Continued hardening now covers Work Package A, Work Package B, Work Package C, Work Package D, and Work Package E at
  an executable service/test boundary.
- `series_evidence_aggregate_v1` now recomputes each evidence status from artifact existence, live runtime source,
  runner version, recomputable hash, and `pass_gate`.
- Manual, injected, injected-only, missing-source, hash-mismatch, and pass-fail-only artifacts cannot become research
  passes in the aggregate.
- Per-evidence aggregate details now include `failure_type`, `blocking_metrics`, `next_action`, `artifact_hash`,
  `runner_version`, `source_run_ids`, `source`, `pass_gate`, and validation reasons.
- `EvidenceArtifactWriter` now emits live-source metadata, `source_run_ids`, `pass_gate`, `failure_type`,
  `blocking_metrics`, and `next_action` for baseline, calibration, hidden evaluation, exploit test, paired sensitivity,
  and parent gate artifacts.
- `StrictParentGateV2` now treats upstream evidence as passed only when it has `source=live_postgresql_runtime`,
  an artifact hash, and `pass_gate=true`; `pass_fail=true` by itself is not enough.
- `ResearchAcceptanceLockV2` now records acceptance level and only opens `level_1_engineering_acceptance`; higher
  claim levels remain locked in this scope.
- `Evidence Board` rows now expose failure details instead of only red/green status.
- Added `engineering_default_target_bands_v0`, P0 calibration metric normalization, and target-band comparison.
- Added `CalibrationRunner`, which produces `calibration_artifact_v1` from live PostgreSQL/runtime fact payloads across
  explicit seeds and source run ids.
- Updated `ExploitTestRunner` so required probe metrics are the six expert-specified categories: `timestamp`,
  `mark_to_market`, `order_boundary`, `fee_accounting`, `fill_rule`, and `clock_boundary`.
- Exploit artifacts now report `probe_metrics`, `severe_flags`, `missing_metrics`, `failure_type`, and `next_action`.
- Updated `PairedSensitivityRunner` with the expert-required scenario mode: `base`, `high_fee`, `high_impact`, and
  `low_liquidity`, with candidate/TWAP/VWAP/AC-lite comparisons.
- Paired sensitivity summaries now expose scenario coverage, baseline coverage, scenario results, degradation curve,
  failure reasons, and next action.
- Updated `HiddenWorldRunner` so hidden evaluation requires a frozen checkpoint, required strong baselines, minimum
  hidden sample size, and hidden worlds not present in checkpoint training hashes.
- Hidden evaluation summaries now expose candidate freeze status, missing baseline names, split contamination worlds,
  paired candidate-vs-baseline metric deltas, `failure_type`, and `next_action`.

## Explicitly Not Done

- Did not convert calibration, hidden evaluation, exploit test, or paired sensitivity from fail to pass.
- Did not run a fresh live Task 101 calibration or exploit package after adding these service boundaries.
- Did not run a fresh live Task 101 paired sensitivity or hidden evaluation package after adding these service
  boundaries.
- Did not read concrete PostgreSQL ORM tables directly for calibration in this round; the runner boundary accepts live
  fact payloads by run id.
- Did not lower TWAP/VWAP/AC-lite or hidden-evaluation thresholds.
- Did not bypass strict parent gate or open research acceptance when upstream blockers remain.
- Did not delete PostgreSQL historical data.
- Did not claim real-market transfer, alpha validity, or level-2/level-3 research acceptance.
- Reassessed the legacy `full-pass-engineering-attempt` package under current strict rules. Its embedded `go` state is
  not accepted because its artifacts lack the hardened `source` and `pass_gate` fields.

## Validation Rules Added

An evidence artifact can pass aggregate recompute only when all of the following are true:

- artifact exists
- `source` is exactly `live_postgresql_runtime`
- source is not manual, injected, injected-only, or headless injected
- `runner_version` is present
- `artifact_hash` or `lock_hash` exists and can be recomputed from the payload
- `pass_gate` is explicitly `true`

If `status` is `missing` or `not_available`, the aggregate preserves that status. If evidence is present but fails
strict validation or has `pass_gate=false`, the aggregate reports `fail`.

## Evidence Board Failure Detail Contract

Each failed row can now expose:

- `status`
- `failure_type`
- `blocking_metrics`
- `next_action`
- `artifact_hash`
- `runner_version`
- `source_run_ids`
- `source`

## Verification

- `python -m py_compile app/services/series_evidence_aggregate.py app/services/strict_parent_gate.py app/services/research_acceptance_lock.py app/services/evidence_board_service.py app/services/evidence_artifact_writer.py`
- `pytest tests/runtime/test_series_evidence_aggregate.py tests/runtime/test_strict_parent_gate.py tests/runtime/test_research_acceptance_lock.py tests/runtime/test_evidence_board_service.py tests/runtime/test_evidence_artifact_writer.py -q`
- Result: `21 passed`
- `pytest tests/runtime/test_long_arena_dry_run.py tests/runtime/test_hidden_world_runner.py tests/runtime/test_exploit_test_runner.py tests/runtime/test_paired_sensitivity_runner.py tests/runtime/test_evidence_artifact_writer.py tests/runtime/test_series_evidence_aggregate.py tests/runtime/test_strict_parent_gate.py tests/runtime/test_research_acceptance_lock.py tests/runtime/test_evidence_core.py tests/runtime/test_evidence_board_service.py -q`
- Result: `41 passed`
- `pytest tests/runtime/test_calibration_runner.py tests/runtime/test_long_arena_dry_run.py tests/runtime/test_hidden_world_runner.py tests/runtime/test_exploit_test_runner.py tests/runtime/test_paired_sensitivity_runner.py tests/runtime/test_evidence_artifact_writer.py tests/runtime/test_series_evidence_aggregate.py tests/runtime/test_strict_parent_gate.py tests/runtime/test_research_acceptance_lock.py tests/runtime/test_evidence_core.py tests/runtime/test_evidence_board_service.py -q`
- Result: `44 passed`
- `.venv\Scripts\python.exe -m py_compile app\services\paired_sensitivity_runner.py app\services\hidden_world_runner.py app\services\evidence_artifact_writer.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_hidden_world_runner.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `12 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_hidden_world_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `10 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `49 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `6 passed`
- Strict legacy recompute output:
  `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-strict-recomputed-legacy-full-pass-92fe0b788974c59a.json`
- Result: `status=complete`, `go_no_go=no_go`, all seven legacy evidence rows fail strict recompute because they miss
  `source=live_postgresql_runtime` and explicit `pass_gate`.
- Added reusable strict reassessment service:
  `app/services/evidence_package_reassessment.py`
- Service-generated strict recompute output:
  `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-service-recomputed-legacy-full-pass-f3152127052f7b58.json`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `8 passed`
- Evidence-focused regression after the reassessment service:
  `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `52 passed`

## Current No-Go Meaning

The project remains No-Go for research promotion and complex model-route escalation. This is the correct state: runtime
and database execution now work, while research evidence is still insufficient. The next valid progress path is to run
fresh live artifacts through the hardened calibration, exploit, paired sensitivity, and hidden evaluation boundaries.
Legacy all-pass packages are now useful only as comparison inputs; they are not acceptable Go evidence under the current
contract. Strict parent gate and research acceptance lock must stay derived from freshly recomputed upstream results.
