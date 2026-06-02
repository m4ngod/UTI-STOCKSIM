# Model Training Status

## Module

Multi-agent adversarial model training foundation

## Current state

in-progress

## Task 2026-05-07-evidence-package-reassessment-runner

### status

done

### goal

Continue the no-go hardening task by making strict reassessment of saved evidence packages repeatable instead of relying
on a one-off script.

### files involved

- `evidence_runner_no_go_hardening_task.md`
- `evidence_runner_no_go_hardening_task_做得怎样.docx`
- `docs/tasks/model-training/evidence-package-reassessment-runner.md`
- `docs/tasks/model-training/legacy-full-pass-package-strict-reassessment.md`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- `docs/current-work-status/model-training.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `app/services/evidence_package_reassessment.py`
- `tests/runtime/test_evidence_package_reassessment.py`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-service-recomputed-legacy-full-pass-f3152127052f7b58.json`

### change summary

- Added `EvidencePackageReassessmentRunner`, which reads a saved long Arena package, resolves embedded evidence hashes
  back to artifact JSON files, rebuilds candidate evidence, and reruns current strict aggregate/package logic.
- Added tests for both stale legacy all-pass artifacts and strict live artifacts.
- Reassessed the real legacy full-pass package through the new service.
- Service-generated strict recompute result is `status=complete`, `go_no_go=no_go`, with all seven evidence rows failing
  because the old artifacts lack current strict fields.

### verification

- `.venv\Scripts\python.exe -m pytest tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `8 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_evidence_package_reassessment.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `52 passed`

### impact / risk

- Positive: package reassessment is now reusable and test-covered.
- Residual No-Go remains intentional: this reassessment rejects stale evidence; it does not generate fresh pass evidence.

### next actions

- Use the reassessment runner on any old package before treating it as current evidence.
- Generate fresh live PostgreSQL/runtime artifacts with the hardened contract at creation time.

## Task 2026-05-07-legacy-full-pass-strict-reassessment

### status

done

### goal

Compare the current response document and expert task against the latest generated artifacts, then reassess the legacy
`full-pass-engineering-attempt` package under the current hardened evidence rules.

### files involved

- `evidence_runner_no_go_hardening_task.md`
- `evidence_runner_no_go_hardening_task_做得怎样.docx`
- `docs/tasks/model-training/legacy-full-pass-package-strict-reassessment.md`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- `docs/current-work-status/model-training.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `tests/runtime/test_series_evidence_aggregate.py`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-strict-recomputed-legacy-full-pass-92fe0b788974c59a.json`

### change summary

- Found that the response document had recorded Work Package A-E hardening, but its latest appended section was encoded
  incorrectly in the DOCX and needed repair.
- Read back the latest legacy `full-pass-engineering-attempt` package, which claimed `status=complete` and
  `go_no_go=go`.
- Recomputed the same candidate evidence through the current strict aggregate and produced a strict reassessment
  package.
- The strict reassessment package is `complete / no_go`; all seven evidence rows fail because the legacy artifacts miss
  current required fields such as `source=live_postgresql_runtime` and explicit `pass_gate`.
- Added a regression test proving pass-looking legacy artifacts without strict fields are rejected.

### verification

- `.venv\Scripts\python.exe -m pytest tests\runtime\test_series_evidence_aggregate.py -q`
- Result: `6 passed`

### impact / risk

- Positive: an old all-pass package can no longer be mistaken for a valid hardened Go package.
- Residual No-Go is intentional: fresh live PostgreSQL/runtime artifacts still need to be regenerated with the hardened
  fields before parent eligibility or research acceptance can open.

### next actions

- Re-run Task 101 live evidence generation through current calibration, exploit, paired sensitivity, and hidden
  evaluation code so the artifacts include the hardened contract fields at creation time.
- Keep the legacy full-pass package only as a comparison input, not as acceptance evidence.

## Task 2026-05-07-evidence-runner-paired-hidden-hardening

### status

done

### goal

Compare `evidence_runner_no_go_hardening_task.md` with the current response document and continue unfinished Work
Package D/E work without turning No-Go evidence green by manual override.

### files involved

- `evidence_runner_no_go_hardening_task.md`
- `evidence_runner_no_go_hardening_task_做得怎样.docx`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- `docs/tasks/model-training/paired-sensitivity-runner-hardening.md`
- `docs/tasks/model-training/hidden-eval-candidate-upgrade.md`
- `docs/current-work-status/model-training.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `app/services/paired_sensitivity_runner.py`
- `app/services/hidden_world_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_paired_sensitivity_runner.py`
- `tests/runtime/test_hidden_world_runner.py`

### change summary

- Confirmed the response document had covered calibration/exploit hardening but not the new paired sensitivity and hidden
  evaluation work.
- Hardened paired sensitivity with required `base`, `high_fee`, `high_impact`, and `low_liquidity` scenarios plus
  required TWAP/VWAP/AC-lite paired baselines.
- Hardened hidden evaluation with frozen checkpoint validation, hidden split contamination checks, required baseline
  coverage, minimum hidden sample size, and paired candidate-vs-baseline metric deltas.
- Hidden artifacts now keep the summary `failure_type` and `next_action`, including split contamination, sample size,
  risk-budget breach, missing baseline, and underperform-baseline outcomes.

### verification

- `.venv\Scripts\python.exe -m py_compile app\services\paired_sensitivity_runner.py app\services\hidden_world_runner.py app\services\evidence_artifact_writer.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_hidden_world_runner.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `12 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_hidden_world_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `10 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `49 passed`

### impact / risk

- Positive: Work Package D/E now have stronger executable evidence boundaries and clearer failure reasons.
- Residual No-Go is intentional: this did not rerun Task 101 live artifacts and did not make hidden or paired evidence
  pass without real evidence.

### next actions

- Re-run live Task 101 artifact generation through the hardened calibration, exploit, paired sensitivity, and hidden
  evaluation boundaries.
- Keep strict parent gate and research acceptance lock derived only from upstream live evidence.

## Task 2026-05-07-evidence-runner-calibration-exploit-hardening

### status

done

### goal

Continue the No-Go hardening task by completing the first executable boundaries for Work Package A/B calibration and
Work Package C exploit probe metrics.

### files involved

- `evidence_runner_no_go_hardening_task.md`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- `docs/tasks/model-training/calibration-target-bands-v0.md`
- `docs/tasks/model-training/live-calibration-artifact-hardening.md`
- `docs/tasks/model-training/exploit-probe-metrics-completion.md`
- `docs/current-work-status/model-training.md`
- `app/services/evidence_core.py`
- `app/services/calibration_runner.py`
- `app/services/exploit_test_runner.py`
- `tests/runtime/test_evidence_core.py`
- `tests/runtime/test_calibration_runner.py`
- `tests/runtime/test_exploit_test_runner.py`
- `evidence_runner_no_go_hardening_task_做得怎样.docx`

### change summary

- Added P0 calibration metric names and broad `engineering_default_v0` target bands.
- Added calibration observed-metric normalization and target-band comparison.
- Extended `MarketMetricsExtractor` to derive `fill_rate`, `cancel_rate`, `retail_family_mix`, and
  `order_lifespan_mean` when runtime fact payloads contain enough fields.
- Added `CalibrationRunner`, which runs each world/seed through `backend="postgresql_runtime"`, fetches runtime facts by
  run id, aggregates per-seed metrics, compares target bands, and writes `calibration_artifact_v1`.
- Calibration artifacts now keep `engineering_pass` separate from `research_pass`; engineering defaults never create a
  research pass.
- Updated `ExploitTestRunner` to expose the six expert-required probe categories: `timestamp`, `mark_to_market`,
  `order_boundary`, `fee_accounting`, `fill_rule`, and `clock_boundary`.
- Exploit artifacts now include `probe_metrics`, `severe_flags`, `missing_metrics`, `failure_type`, and `next_action`.

### verification

- `.venv\Scripts\python.exe -m py_compile app\services\calibration_runner.py app\services\evidence_core.py app\services\exploit_test_runner.py app\services\evidence_artifact_writer.py tests\runtime\test_calibration_runner.py tests\runtime\test_evidence_core.py tests\runtime\test_exploit_test_runner.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_evidence_core.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `18 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_calibration_runner.py tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `44 passed`

### impact / risk

- Positive: calibration can now fail for concrete missing P0 metrics instead of staying a document-only blocker.
- Positive: exploit evidence now reports the six required probe categories and blocks on missing probe metrics.
- Residual No-Go is intentional: this did not rerun Task 101 with fresh live calibration/exploit artifacts and did not
  convert existing failed artifacts to pass.

### next actions

- Replace the calibration test fact callback with a direct PostgreSQL/runtime fact reader.
- Re-run live Task 101 calibration and exploit artifact generation from real database rows.
- Continue Work Package D by hardening paired sensitivity to base/high_fee/high_impact/low_liquidity plus TWAP/VWAP/AC-lite comparisons.

## Task 2026-05-07-evidence-runner-no-go-hardening

### status

done

### goal

Start the expert-requested Evidence Runner No-Go hardening work so the healthy `complete / no_go` package cannot be
misread as a research pass or manually turned green through status fields.

### files involved

- `evidence_runner_no_go_hardening_task.md`
- `docs/tasks/model-training/evidence-runner-no-go-hardening.md`
- `docs/current-work-status/model-training.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `app/services/series_evidence_aggregate.py`
- `app/services/evidence_artifact_writer.py`
- `app/services/strict_parent_gate.py`
- `app/services/research_acceptance_lock.py`
- `app/services/evidence_board_service.py`
- `tests/runtime/test_series_evidence_aggregate.py`
- `tests/runtime/test_strict_parent_gate.py`
- `tests/runtime/test_research_acceptance_lock.py`
- `tests/runtime/test_evidence_board_service.py`
- `tests/runtime/test_evidence_artifact_writer.py`
- `tests/runtime/test_long_arena_dry_run.py`
- `evidence_runner_no_go_hardening_task_做得怎样.docx`

### change summary

- Added the task document at `docs/tasks/model-training/evidence-runner-no-go-hardening.md`.
- Hardened `SeriesEvidenceAggregate` so evidence status is recomputed from artifact existence, live runtime source,
  runner version, recomputable hash, and explicit `pass_gate`.
- Manual, injected, injected-only, missing-source, hash-mismatch, and pass-fail-only artifacts now fail strict aggregate
  recompute.
- Added per-evidence diagnostics: `failure_type`, `blocking_metrics`, `next_action`, `artifact_hash`,
  `runner_version`, `source_run_ids`, `source`, `pass_gate`, and validation reasons.
- Updated artifact writer output fields so newly written evidence carries live-source metadata and `pass_gate`.
- Updated `StrictParentGateV2` so upstream evidence must be live, hashed, and `pass_gate=true`; `pass_fail=true` alone
  no longer qualifies.
- Updated `ResearchAcceptanceLockV2` to record acceptance level and only allow `level_1_engineering_acceptance` in this
  scope.
- Updated Evidence Board rows to display failure details instead of only status.

### verification

- `.venv\Scripts\python.exe -m py_compile app\services\series_evidence_aggregate.py app\services\strict_parent_gate.py app\services\research_acceptance_lock.py app\services\evidence_board_service.py app\services\evidence_artifact_writer.py`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_board_service.py tests\runtime\test_evidence_artifact_writer.py -q`
- Result: `21 passed`
- `.venv\Scripts\python.exe -m pytest tests\runtime\test_long_arena_dry_run.py tests\runtime\test_hidden_world_runner.py tests\runtime\test_exploit_test_runner.py tests\runtime\test_paired_sensitivity_runner.py tests\runtime\test_evidence_artifact_writer.py tests\runtime\test_series_evidence_aggregate.py tests\runtime\test_strict_parent_gate.py tests\runtime\test_research_acceptance_lock.py tests\runtime\test_evidence_core.py tests\runtime\test_evidence_board_service.py -q`
- Result: `41 passed`

### impact / risk

- Positive: the current Task 101 No-Go state is harder and more honest; old `pass_fail=true` or manual status fields no
  longer bypass strict aggregate recompute.
- Positive: downstream parent gate and research lock remain derived from upstream evidence instead of leaderboard or
  manual overrides.
- Residual No-Go is intentional: calibration, hidden evaluation, exploit test, and paired sensitivity still need real
  upstream evidence improvement.

### next actions

- Implement live calibration target-band extraction and missing-metric reporting before attempting calibration pass.
- Complete exploit probe metrics before attempting exploit pass.
- Run base/high_fee/high_impact/low_liquidity paired sensitivity worlds before attempting paired-sensitivity pass.
- Keep strict parent gate and research acceptance lock derived only; do not manually open them while upstream blockers remain.

## Task 2026-05-07-model-training-101-fail-to-success-attempt

### status

partial

### goal

Try to turn Task 101 live package evidence failures into success without falsifying evidence.

### files involved

- `UTI-STOCKSIM_绗簩杞笓瀹惰瘎瀹′笌Evidence_Runner钀藉湴璁捐.md`
- `docs/tasks/model-training/long-arena-dry-run-package-v1.md`
- `docs/current-work-status/model-training.md`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `UTI-STOCKSIM_绗簩杞笓瀹惰瘎瀹′笌Evidence_Runner钀藉湴璁捐_鍋氬緱鎬庢牱.docx`
- `output/evidence_artifacts/random_seed_ledger_v1/task101-live-runtime-cc0a9a6a-random-seed-ledger-6fc99ac54e04bffe.json`
- `output/model_checkpoints/task101_static_candidate_v2/task101-live-runtime-cc0a9a6a-static-candidate-checkpoint.json`
- `output/evidence_artifacts/hidden_eval_artifact_v1/hidden-eval-119950edf3a20b87.json`
- `output/evidence_artifacts/exploit_test_artifact_v1/exploit-test-6aee4406f101b646.json`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-live-adjusted-attempt-5d5d363766ebc1d2.json`

### change summary

- Rechecked the seven failed evidence slots and separated metadata failures from actual evaluation failures.
- Added a real `random_seed_ledger_v1` artifact for the Task 101 adjustment attempt.
- Materialized the static external candidate checkpoint through the project model-registry checkpoint path.
- Re-emitted the baseline artifact with the seed ledger; `baseline_artifact` now passes.
- Tried live hidden evaluation through `HiddenWorldRunner` and live `ArenaExperimentRunner` episode runs.
- Tried live exploit evaluation through `ExploitTestRunner` and live `ArenaExperimentRunner` episode runs.
- Repacked Task 101 as `complete / no_go` with `status_counts={"pass": 1, "fail": 6}`.

### verification

- Adjusted package readback confirmed `baseline_artifact=pass`, `calibration_artifact=fail`,
  `hidden_eval_artifact=fail`, `exploit_test_artifact=fail`, `paired_sensitivity_artifact=fail`,
  `parent_gate_artifact=fail`, and `research_acceptance_lock=fail`.
- Hidden evaluation readback confirmed `median_win_rate=0.0` and `strongest_win_rate=0.0`.
- Exploit evaluation readback confirmed only `no_signal_world` passed; six required probe categories remained
  `not_available`.

### impact / risk

- Positive: the old seven-fail state has been reduced to one pass and six fails with real evidence changes.
- Residual No-Go is intentional: making the remaining evidence pass would require real calibration metrics, hidden
  outperformance, complete exploit probe metrics, and wired fee/impact/latency paired worlds.

### next actions

- Implement live calibration metric extraction before attempting `calibration_artifact=pass`.
- Wire exploit probe metrics and fee/impact/latency variant worlds before attempting `exploit_test_artifact=pass` or
  `paired_sensitivity_artifact=pass`.

## Task 2026-05-07-model-training-101-package-status

### status

done

### goal

Separate Task 101 evidence-package completeness from the Go / No-Go decision.

### files involved

- `UTI-STOCKSIM_绗簩杞笓瀹惰瘎瀹′笌Evidence_Runner钀藉湴璁捐.md`
- `docs/tasks/model-training/long-arena-dry-run-package-v1.md`
- `docs/current-work-status/model-training.md`
- `app/services/long_arena_dry_run.py`
- `tests/runtime/test_long_arena_dry_run.py`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-status-fix-dc02f5c7587a9899.json`
- `UTI-STOCKSIM_绗簩杞笓瀹惰瘎瀹′笌Evidence_Runner钀藉湴璁捐_鍋氬緱鎬庢牱.docx`

### change summary

- Corrected `LongArenaDryRunRunner` so failed evidence no longer makes the package `status` incomplete by itself.
- The package is now considered complete when the multi-generation run exists, at least one candidate exists, and there
  are no missing or not_available evidence slots.
- Failed evidence still blocks `go_no_go` and remains visible in `failure_reasons`.
- Added a regression test covering `complete / no_go` when all evidence slots are present but some required evidence fails.
- Repacked the Task 101 live PostgreSQL/runtime evidence into a status-corrected package:
  `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-status-fix-dc02f5c7587a9899.json`.

### verification

- `pytest tests/runtime/test_long_arena_dry_run.py`
- Package readback confirmed `status=complete`, `go_no_go=no_go`, `actual_generation_count=3`, and
  `status_counts={"fail": 7}`.

### impact / risk

- Positive: Task 101 now reports package completeness separately from evidence acceptance.
- Residual No-Go is intentional: the live candidate still fails baseline, calibration, hidden evaluation, exploit test,
  paired sensitivity, parent gate, and research acceptance lock evidence.

### next actions

- Continue only by generating the missing/failed independent evidence with real runners; do not convert the current
  `no_go` to `go` by rewriting artifact outcomes.

## Task 2026-05-05-model-route-gate-v1

### status

done

### goal

Convert the expert-review section 16 model-route guidance into a machine-readable gate.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/model-route-gate-v1.md`
- `docs/tasks/model-training/evidence-runner-go-no-go-review.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/model_route_gate.py`
- `tests/runtime/test_model_route_gate.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/model-route-gate-v1.md`.
- Added `app/services/model_route_gate.py`.
- Added `tests/runtime/test_model_route_gate.py`.
- The gate allows current P0/P1 routes such as `ppo_lstm_v1` and rule baselines when Evidence Runner is No-Go.
- The gate blocks advanced route tokens such as `transformer`, `gtrxl`, `marl`, `historical_replay`, `hybrid_env`,
  and `alpha_claim` while Evidence Runner is No-Go.
- The gate writes `model_route_gate_v1` JSON records with allowed/blocked route status and `route_gate_hash`.
- Did not wire the gate into `ModelRegistryService`, register advanced models, make research claims, or delete
  PostgreSQL data.

### verification

- `python -m py_compile app/services/model_route_gate.py tests/runtime/test_model_route_gate.py`
- Direct behavior assertion passed with `MODEL_ROUTE_GATE_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because the available runtime Python does not have `pytest` installed.

### impact / risk

- Positive: the No-Go decision now has a testable engineering boundary for model-route escalation.
- Risk: advanced route blocking is not enforced at model registration/runtime until a future wiring step.

### next actions

- Wire `ModelRouteGate` into model registration or Arena configuration only after the live Task 101 dependency blocker is repaired.

## Task 2026-05-05-model-training-go-no-go-review

### status

done

### goal

Apply the expert-review section 15 Go / No-Go criteria after Task 82-101 work.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-go-no-go-review.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/evidence-runner-go-no-go-review.md`.
- Reviewed section 15 Go criteria against the completed/partial Evidence Runner phase work.
- Recorded a No-Go decision for more complex model work because the live long Arena series remains blocked.
- Allowed next work is limited to dependency repair and re-running Task 101 through the live database-backed Arena path.
- Explicitly deferred Transformer, complex MARL, new alpha-claim routes, and research claims based on the headless package alone.
- Did not delete PostgreSQL data.

### verification

- Documentation readback confirmed `No-Go for more complex model work`.

### impact / risk

- Positive: the project now has a clear phase gate and will not treat the headless package as live evidence.
- Risk: progress toward advanced models remains blocked until the runtime environment supports live Arena execution.

### next actions

- Repair the local Python/runtime dependency environment before reattempting Task 101 live long run.

## Task 2026-05-05-model-training-101

### status

partial

### goal

Create a Long Arena Dry Run evidence package boundary for multi-generation series review and gate outcome inspection.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/long-arena-dry-run-package-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/long_arena_dry_run.py`
- `tests/runtime/test_long_arena_dry_run.py`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-headless-dry-run-6fb719d531f4c733.json`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/long-arena-dry-run-package-v1.md`.
- Added `app/services/long_arena_dry_run.py`.
- Added `tests/runtime/test_long_arena_dry_run.py`.
- Task 101 now has a package runner that calls an injected Arena series callable, requires a multi-generation series
  shape, aggregates candidate evidence, builds an Evidence Board view, reviews parent/research eligibility, and writes
  `long_arena_dry_run_package_v1` JSON with `package_hash`.
- Produced a deterministic headless package at
  `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-headless-dry-run-6fb719d531f4c733.json`.
- Attempted the existing live `ArenaExperimentRunner` path, but the available runtime cannot import it because
  `sqlalchemy` is not installed.
- Rechecked the local project `.venv` and sibling `Quent\.venv`; both launchers point to a missing Python311
  executable, so they cannot be used to run the live Arena path.
- Did not run a live PostgreSQL/runtime long Arena series, repair dependencies, verify GUI screenshots, or delete
  PostgreSQL data.

### verification

- `python -m py_compile app/services/long_arena_dry_run.py tests/runtime/test_long_arena_dry_run.py`
- Direct behavior assertion passed with `LONG_ARENA_DRY_RUN_DIRECT_ASSERTIONS_OK`.
- Headless package output assertion passed with `LONG_ARENA_DRY_RUN_PACKAGE_OUTPUT_OK`.

### verification note

- Targeted pytest could not run because the available runtime Python does not have `pytest` installed.
- Live Arena import/run is blocked by missing `sqlalchemy` in the available runtime.
- Project `.venv` and `Quent\.venv` are also unusable in this workspace because both Python launchers point to a
  missing Python311 executable.

### impact / risk

- Positive: Task 101 now has a hashable evidence-package artifact that joins multi-generation series metadata,
  evidence aggregate, Evidence Board, and gate review.
- Risk: the actual live long Arena run remains blocked until the runtime dependency environment is repaired.

### next actions

- Repair runtime dependencies (`sqlalchemy`, pytest, and project venv) before attempting the live PostgreSQL-backed long Arena series.

## Task 2026-05-05-model-training-100

### status

done

### goal

Add Evidence Contract Tests for schema/hash/seed/reproducibility and runner no-learning discipline.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-contract-tests-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `tests/runtime/test_evidence_contracts.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/evidence-contract-tests-v1.md`.
- Added `tests/runtime/test_evidence_contracts.py`.
- The contract tests cover WorldSpec canonical hash stability, RandomSeedLedger seed/hash reproducibility, common
  separate-artifact schema fields, artifact self-hash exclusion, and deterministic artifact hash output.
- Hidden-World, Paired Fee/Impact, and Exploit runners are checked together for `allow_learning=False`.
- A constructed bad-policy signal is rejected by `exploit_test_artifact_v1`.
- `parent_gate_artifact_v2` rejects the candidate when exploit evidence fails, even if other required evidence passes.
- Did not repair pytest, run a long Arena dry run, touch GUI screenshots, or delete PostgreSQL data.

### verification

- `python -m py_compile tests/runtime/test_evidence_contracts.py app/services/evidence_artifact_writer.py app/services/evidence_core.py app/services/hidden_world_runner.py app/services/paired_sensitivity_runner.py app/services/exploit_test_runner.py app/services/strict_parent_gate.py`
- Direct behavior assertion passed with `EVIDENCE_CONTRACT_TESTS_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because the available runtime Python does not have `pytest` installed.

### impact / risk

- Positive: Task 100 now provides a single contract layer that protects evidence schema, identity, no-learning, and bad-policy rejection boundaries.
- Risk: this is still a direct/runtime test boundary until the project pytest environment is repaired.

### next actions

- Continue Task 101 by running a long Arena dry run and producing a complete evidence package, if the required runtime dependencies are available.

## Task 2026-05-05-model-training-99

### status

done

### goal

Implement the first GUI Evidence Board boundary so Arena can display evidence status instead of only return ranking.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/gui-evidence-board-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/evidence_board_service.py`
- `app/panels/arena/panel.py`
- `app/ui/adapters/arena_adapter.py`
- `tests/runtime/test_evidence_board_service.py`
- `tests/frontend/unit/test_arena_panel.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/gui-evidence-board-v1.md`.
- Added `app/services/evidence_board_service.py`.
- Arena experiment view now exposes `evidence_board`.
- Arena adapter now renders a headless/desktop evidence table alongside arena and leaderboard tables.
- Evidence Board rows show baseline, calibration, hidden, exploit, fee/impact sensitivity, parent eligibility, and
  research-claim eligibility.
- Evidence Board preserves `pass`, `fail`, `missing`, and `not_available` states from `series_evidence_aggregate_v1`.
- `not_available` evidence produces debt metadata with owner, required input, blocking reason, planned task id, and
  replacement artifact kind.
- Did not implement full visual redesign, color-coded styling, row click-through to artifacts, long Arena dry run, or
  PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/evidence_board_service.py app/panels/arena/panel.py app/ui/adapters/arena_adapter.py tests/runtime/test_evidence_board_service.py tests/frontend/unit/test_arena_panel.py`
- Direct behavior assertion passed with `GUI_EVIDENCE_BOARD_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 99 now has a visible Arena panel data path for evidence status, not only leaderboard rows.
- Risk: the visual treatment remains the existing simple table layout until a dedicated GUI polish task.

### next actions

- Continue Task 100 by adding Evidence Contract Tests for schema/hash/seed/reproducibility/no-learning.

## Task 2026-05-05-model-training-98

### status

done

### goal

Implement Series Evidence Aggregate so a series-level evidence package can show pass/fail/missing/not_available
status clearly before GUI board and long dry-run work.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/series-evidence-aggregate-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/series_evidence_aggregate.py`
- `tests/runtime/test_series_evidence_aggregate.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/series-evidence-aggregate-v1.md`.
- Added `app/services/series_evidence_aggregate.py`.
- Added `tests/runtime/test_series_evidence_aggregate.py`.
- Series aggregate tracks candidate evidence for baseline, calibration, hidden eval, exploit test, paired sensitivity,
  parent gate, and research acceptance lock.
- Each evidence slot is classified as `pass`, `fail`, `missing`, or `not_available`.
- The aggregate records per-candidate evidence statuses, evidence hashes, parent eligibility, research acceptance,
  series status counts, evidence-kind status counts, `go_no_go`, and failure reasons.
- The aggregate writes `series_evidence_aggregate_v1` JSON records with canonical `aggregate_hash`.
- Did not run a long Arena series, wire the aggregate into existing Arena report generation, implement GUI Evidence
  Board, add Evidence Contract Tests, or delete PostgreSQL data.

### verification

- `python -m py_compile app/services/series_evidence_aggregate.py tests/runtime/test_series_evidence_aggregate.py`
- Direct behavior assertion passed with `SERIES_EVIDENCE_AGGREGATE_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 98 now has an executable series-level evidence package aggregate.
- Risk: it is not wired into live Arena report generation yet; Task 101 still needs an actual long dry run.

### next actions

- Continue Task 99 by implementing GUI Evidence Board display data boundaries.

## Task 2026-05-05-model-training-97

### status

done

### goal

Implement Research Acceptance Lock v2 so research claims are blocked unless required evidence passes through
`parent_gate_artifact_v2` and evidence hashes are present.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/research-acceptance-lock-v2.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/research_acceptance_lock.py`
- `tests/runtime/test_research_acceptance_lock.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/research-acceptance-lock-v2.md`.
- Added `app/services/research_acceptance_lock.py`.
- Added `tests/runtime/test_research_acceptance_lock.py`.
- Research Acceptance Lock v2 consumes `parent_gate_artifact_v2`.
- The lock opens only when parent gate `pass_fail=True`, `eligible_for_research_claim=True`, required evidence has no
  failures, required evidence hashes are present, and claim/candidate fields are present.
- The lock writes `research_acceptance_lock_v2` JSON records with `status`, `is_research_accepted`, failure reasons,
  required evidence, required evidence hashes, and canonical `lock_hash`.
- Did not mutate existing Arena research acceptance sections, write research conclusions into reports, implement
  Series Evidence Aggregate, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/research_acceptance_lock.py tests/runtime/test_research_acceptance_lock.py`
- Direct behavior assertion passed with `RESEARCH_ACCEPTANCE_LOCK_V2_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 97 now has an executable lock that prevents research acceptance without required evidence.
- Risk: it is not wired into live Arena report writing yet; this preserves current report behavior until an explicit integration task.

### next actions

- Continue Task 98 by implementing Series Evidence Aggregate for pass/fail/missing/not_available evidence status.

## Task 2026-05-05-model-training-96

### status

done

### goal

Implement Strict Parent Gate v2 so required independent evidence artifacts decide PBT parent eligibility, checkpoint
promotion eligibility, and research-claim eligibility separately.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/strict-parent-gate-v2.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/strict_parent_gate.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_strict_parent_gate.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/strict-parent-gate-v2.md`.
- Added `app/services/strict_parent_gate.py`.
- Added `tests/runtime/test_strict_parent_gate.py`.
- Added `EvidenceArtifactWriter.write_parent_gate_artifact(...)`.
- Gate v2 requires experiment record completeness, checkpoint hash, lineage evidence, baseline artifact,
  calibration artifact, hidden-eval artifact, exploit-test artifact, and paired-sensitivity artifact.
- Gate v2 writes a separate `parent_gate_artifact_v2`.
- Eligibility is split into `eligible_for_pbt_parent`, `eligible_for_checkpoint_promotion`, and
  `eligible_for_research_claim`.
- PBT parent eligibility requires all required evidence to pass.
- Checkpoint promotion additionally requires `hidden_rank_ok`.
- Research claim eligibility additionally requires `statistical_confidence_ok`.
- Did not mutate existing PBT parent selection, automatic checkpoint promotion, research acceptance lock v2,
  series aggregate, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/strict_parent_gate.py app/services/evidence_artifact_writer.py tests/runtime/test_strict_parent_gate.py`
- Direct behavior assertion passed with `STRICT_PARENT_GATE_V2_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 96 now has an executable evidence-gated parent artifact boundary.
- Risk: it is not wired into live PBT selection yet; this preserves runtime behavior until an explicit integration task.

### next actions

- Continue Task 97 by implementing Research Acceptance Lock v2 over required evidence.

## Task 2026-05-05-model-training-95

### status

done

### goal

Implement Exploit Test Runner v0 so a frozen checkpoint can be evaluated against required exploit probes and emit a
separate exploit evidence artifact.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/exploit-test-runner-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/exploit_test_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_exploit_test_runner.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/exploit-test-runner-v0.md`.
- Added `app/services/exploit_test_runner.py`.
- Added `tests/runtime/test_exploit_test_runner.py`.
- Added `EvidenceArtifactWriter.write_exploit_test_artifact(...)`.
- Exploit runner evaluates exploit world specs with a frozen policy and `allow_learning=False`.
- V0 implements required probes for `no_signal_world`, `timestamp_leakage`, `mark_to_market_leakage`,
  `order_boundary`, `fee_accounting`, `fill_rule_exploit`, and `clock_boundary`.
- The artifact summary includes required probe names, probe status counts, pass/fail, and failure reasons.
- Passing requires exploit details, no evaluator errors, all required probes present, no failed probes, and no
  `not_available` probe evidence.
- Did not implement real checkpoint file loading, real world construction, Arena integration, statistical multi-seed
  significance tests, strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/exploit_test_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_exploit_test_runner.py`
- Direct behavior assertion passed with `EXPLOIT_TEST_RUNNER_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 95 now has an executable exploit-test artifact boundary instead of only report placeholders.
- Risk: probe metrics still depend on injected runtime/audit result fields until Arena/runtime integration supplies them end to end.

### next actions

- Continue Task 96 by implementing Strict Parent Gate v2 over the separate evidence artifacts.

## Task 2026-05-05-model-training-94

### status

done

### goal

Implement Paired Fee/Impact Sensitivity Runner v0 so a frozen checkpoint can be evaluated on base/stressed world pairs
and emit a separate degradation-curve artifact.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/paired-fee-impact-runner-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/paired_sensitivity_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_paired_sensitivity_runner.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/paired-fee-impact-runner-v0.md`.
- Added `app/services/paired_sensitivity_runner.py`.
- Added `tests/runtime/test_paired_sensitivity_runner.py`.
- Added `EvidenceArtifactWriter.write_paired_sensitivity_artifact(...)`.
- Paired runner evaluates the base world once and each stressed world with the same frozen policy.
- The injected evaluator is called with `allow_learning=False`.
- V0 supports required `fee`, `impact`, and `latency` perturbation kinds.
- V0 also includes explicit paths for `queue`, `spread`, `liquidity`, `partial_fill`, and custom path operations.
- The artifact summary includes present/missing perturbation kinds, degradation curve, warnings, pass/fail, and failure reasons.
- Passing requires paired results, required perturbation kinds, no evaluator errors, and finite base/stressed score pairs.
- Did not implement real checkpoint file loading, real world construction, Arena integration, multi-seed aggregation,
  exploit-test runner, strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/paired_sensitivity_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_paired_sensitivity_runner.py`
- Direct behavior assertion passed with `PAIRED_SENSITIVITY_RUNNER_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 94 now has an executable paired-sensitivity artifact boundary instead of only `not_available` report slots.
- Risk: the runner still depends on injected world construction/evaluation and does not yet run multi-seed sensitivity in Arena.

### next actions

- Continue Task 95 by implementing Exploit Test Runner v0.

## Task 2026-05-05-model-training-93

### status

done

### goal

Implement Hidden-World Runner v0 so a frozen checkpoint can be evaluated on hidden world specs without training,
PBT, reward tuning, or policy updates.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/hidden-world-runner-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/hidden_world_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_hidden_world_runner.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/hidden-world-runner-v0.md`.
- Added focused runtime tests in `tests/runtime/test_hidden_world_runner.py`.
- Tightened `HiddenWorldRunner.run_hidden_eval(...)` around the Task 93 boundary.
- Hidden evaluation now selects only `hidden` split worlds from `hidden_world_registry_v1`.
- The injected evaluator is called with `allow_learning=False` for both the frozen policy and baselines.
- The runner writes a separate `hidden_eval_artifact_v1`.
- Summary metrics include hidden-world count, median-baseline win rate, strongest-baseline win rate, no-signal
  failures, configured risk limits, and risk-limit failures.
- Passing requires hidden results, baselines, threshold win rates, no no-signal positive alpha, and no configured
  risk-limit breach.
- Did not implement real checkpoint file loading, real world construction, Arena integration, paired sensitivity,
  exploit-test runner, strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/hidden_world_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_hidden_world_runner.py`
- Direct behavior assertion passed with `HIDDEN_WORLD_RUNNER_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 93 now has an executable frozen hidden-evaluation boundary and a separate evidence artifact.
- Risk: checkpoint loading and world construction remain injected boundaries, so end-to-end Arena wiring is still future work.

### next actions

- Continue Task 94 by implementing Paired Fee/Impact Runner v0.

## Task 2026-05-05-model-training-92

### status

done

### goal

Create the hidden-world split registry boundary for visible, validation, hidden, and exploit world specs before
Hidden-World Runner v0 evaluates frozen checkpoints.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/hidden-world-registry.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `app/services/evidence_core.py`
- `tests/runtime/test_evidence_core.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/hidden-world-registry.md`.
- Added `WORLD_REGISTRY_SPLITS`.
- Added `build_world_split_registry(...)`.
- Added `world_split_registry_hash(...)`.
- Added `hidden_world_specs(...)`.
- Registry supports `visible`, `validation`, `hidden`, and `exploit`.
- `train` is normalized to `visible`.
- Registry `pass_fail` requires `visible`, `validation`, and `hidden` splits.
- Registry hash excludes `registry_hash` itself.
- Did not implement Hidden-World Runner v0, frozen checkpoint loading/evaluation, no-learning enforcement,
  hidden_eval_artifact_v1 persistence, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/evidence_core.py tests/runtime/test_evidence_core.py`
- Direct behavior assertion passed with `HIDDEN_WORLD_REGISTRY_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: Task 93 now has a registry shape for selecting hidden worlds without reusing visible/training worlds.
- Risk: this is registry identity work only; hidden evaluation still remains unimplemented until Task 93.

### next actions

- Continue Task 93 by implementing Hidden-World Runner v0 with frozen-policy/no-learning boundaries.

## Task 2026-05-05-model-training-91

### status

done

### goal

Add AC-lite as a simplified Almgren-Chriss style baseline that runs through the same model registry, `act.v1`, Arena,
and baseline artifact path as other baselines.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/ac-lite-baseline.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_model_registry_external.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `tests/runtime/test_evidence_artifact_writer.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/ac-lite-baseline.md`.
- Extended `ScheduledExecutionBaselineModel` with AC-lite risk/cost schedule progress.
- Added built-in `ac_lite_execution_v1`.
- AC-lite emits `act.v1` `target_weight` actions with `rebalance_mode=ac_lite`.
- AC-lite schedule metadata includes `sigma`, `eta`, `risk_aversion`, `horizon_steps`, `step_index`, `progress`, and
  target gross budget.
- Added AC-lite to default `ArenaExperimentConfig.model_specs` as a `collect_only` baseline.
- Added AC-lite to default `pbt_excluded_model_ids`.
- Added `_baseline_kind(...)` mapping for `ac_lite`.
- Added AC-lite to `baseline_artifact_v1` default required baseline kinds.
- Did not implement order-level AC slicing, calibrated impact/risk inputs, arrival-price capture, implementation
  shortfall reward wiring, strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/model_registry_service.py app/services/arena_experiment_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_model_registry_external.py tests/runtime/test_arena_experiment_runner.py tests/runtime/test_evidence_artifact_writer.py`
- Direct behavior assertion passed with `AC_LITE_BASELINE_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: HOLD/random/target-weight/TWAP/VWAP/AC-lite can now be treated as runnable baseline kinds by the baseline artifact writer.
- Risk: AC-lite is still a scheduled target-weight baseline, not a full order-level Almgren-Chriss executor.

### next actions

- Continue Task 92 by defining and implementing the hidden-world registry split boundary.

## Task 2026-05-05-model-training-90

### status

done

### goal

Move TWAP/VWAP from pure `not_available` report slots to runnable built-in baseline policies that still use the
existing `act.v1` and Arena/runtime path.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/twap-vwap-report-slots.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/current-work-status/model-training.md`
- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_model_registry_external.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `tests/runtime/test_evidence_artifact_writer.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `ScheduledExecutionBaselineModel`.
- Added built-in `twap_execution_v1`.
- Added built-in `vwap_execution_v1`.
- Both policies emit `act.v1` `target_weight` actions with `rebalance_mode=twap` or `rebalance_mode=vwap`.
- Both include `payload.schedule` metadata with schedule type, step index, horizon, progress, and target gross budget.
- Added both baselines to default `ArenaExperimentConfig.model_specs` as `collect_only`.
- Added both baselines to default `pbt_excluded_model_ids`.
- Added `_baseline_kind(...)` mappings for `twap` and `vwap`.
- Updated `baseline_artifact_v1` default required baselines to include `twap` and `vwap`.
- Did not implement true order-level TWAP/VWAP slicing, arrival-price capture, implementation shortfall reward wiring,
  strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/model_registry_service.py app/services/arena_experiment_runner.py app/services/evidence_artifact_writer.py tests/runtime/test_model_registry_external.py tests/runtime/test_arena_experiment_runner.py tests/runtime/test_evidence_artifact_writer.py`
- Direct behavior assertion passed with `TWAP_VWAP_MODEL_AND_ARTIFACT_DIRECT_ASSERTIONS_OK`.

### verification note

- Targeted pytest could not run because `.venv` points to a missing `Python311` executable and the available system/runtime Python installations do not have `pytest` installed.

### impact / risk

- Positive: TWAP/VWAP are now runnable through the same model registry and action contract as existing baselines.
- Positive: default Arena series can include TWAP/VWAP baseline rows instead of only reporting unavailable slots.
- Risk: these are scheduled target-weight baselines, not yet order-level slicing baselines with arrival-price and shortfall accounting.

### next actions

- Continue Task 91 by implementing AC-lite baseline or, if blocked, document the exact missing impact/risk inputs.

## Task 2026-05-05-model-training-82-87-completion-audit

### status

done

### goal

Re-check Task 82 through Task 87 against `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md` and complete
any task that was only documented rather than implemented.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/tasks/model-training/calibration-scorecard-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/evidence_core.py`
- `tests/runtime/test_evidence_core.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Re-checked Task 82-87 and found Task 84-87 were previously docs-only, so they were not truly complete against the
  Evidence Runner implementation intent.
- Added `app/services/evidence_core.py`.
- Added `tests/runtime/test_evidence_core.py`.
- Implemented Task 84 with `build_world_spec_v1(...)`, `build_world_spec_from_arena_identity(...)`, and
  `world_spec_hash(...)`.
- Implemented Task 85 with `derive_seed(...)`, `build_random_seed_ledger(...)`, and `random_seed_ledger_hash(...)`.
- Implemented Task 86 with `MarketMetricsExtractor.extract(...)`, including metric values and coverage statuses.
- Implemented Task 87 with `normalized_distance(...)` and `compute_calibration_scorecard(...)`.
- Updated Task 84-87 task docs from `Documented only` to implemented status.
- Task 82 and Task 83 remain docs/contract tasks and did not require additional code in this pass.
- Did not implement hidden-world registry, full calibration runner, target profile storage, PostgreSQL artifact
  persistence, GUI behavior, strict parent gate v2, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/evidence_core.py app/services/evidence_artifact_writer.py tests/runtime/test_evidence_core.py tests/runtime/test_evidence_artifact_writer.py`
- `.venv\Scripts\python.exe -m pytest tests/runtime/test_evidence_core.py tests/runtime/test_evidence_artifact_writer.py -q`

### impact / risk

- Positive: Task 84-87 now have runnable implementation and tests instead of only task documents.
- Positive: Calibration scorecard now explicitly blocks missing required metrics rather than treating them as zero-distance passes.
- Risk: the implemented modules are core utilities; they are not yet wired into an end-to-end calibration runner or Arena aggregate.

### next actions

- Wire these utilities into Task 88 calibration artifact production once a calibration runner invocation boundary is added.

## Task 2026-05-05-model-training-89

### status

done

### goal

Produce a separate `baseline_artifact_v1` from the existing Arena baseline suite while preserving the current
runtime/contract execution boundary for baselines.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/unified-baseline-runner.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `docs/code-index.md`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_evidence_artifact_writer.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/unified-baseline-runner.md`.
- Added `EvidenceArtifactWriter.write_baseline_artifact(...)`.
- The writer creates a separate `baseline_artifact_v1` JSON artifact from existing Arena `baseline_suite`,
  baseline result rows, and `benchmark_comparison`.
- The Task 89 pass boundary requires current project-owned baseline kinds:
  - `no_trade_cash`
  - `random_constrained`
  - `target_weight_naive_rebalance`
- Missing identity fields, missing baseline suite, missing baseline results, missing benchmark comparison, or missing
  required baseline kinds block `pass_fail=True` while still persisting the failed artifact.
- Did not implement TWAP, VWAP, AC-lite, a new baseline execution scheduler, PostgreSQL artifact persistence, GUI
  behavior, strict parent gate v2, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/evidence_artifact_writer.py tests/runtime/test_evidence_artifact_writer.py`
- `.venv\Scripts\python.exe -m pytest tests/runtime/test_evidence_artifact_writer.py -q`

### impact / risk

- Positive: Baseline evidence now has a separate artifact writer instead of only embedded report sections.
- Positive: The implementation does not create a shortcut baseline path outside Arena/runtime contracts.
- Risk: TWAP, VWAP, and AC-lite remain unavailable until Task 90 and Task 91.

### next actions

- Continue Task 90 by implementing or documenting TWAP/VWAP baseline execution boundaries before they can be marked
  present in baseline artifacts.

## Task 2026-05-05-model-training-88

### status

done

### goal

Implement the first separate Evidence Runner artifact writer for `calibration_artifact_v1` without claiming a calibration runner, metric extractor, scorecard implementation, or database persistence.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/tasks/model-training/calibration-scorecard-v0.md`
- `docs/tasks/model-training/calibration-artifact-writer.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `app/services/evidence_artifact_writer.py`
- `tests/runtime/test_evidence_artifact_writer.py`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Restored the missing docs files for Task 82 through Task 87 from the existing project status ledger and the second expert review.
- Added `docs/tasks/model-training/calibration-artifact-writer.md`.
- Added `EvidenceArtifactWriter.write_calibration_artifact(...)`.
- The writer creates a separate `calibration_artifact_v1` JSON artifact under an artifact root.
- The artifact includes common Evidence Runner fields, metrics, scorecard, dependency list, pass/fail, failure reasons, and `artifact_hash`.
- `artifact_hash` is computed with `artifact_hash` itself excluded.
- Missing `code_identity_hash`, `sim_version_identity`, `world_hash`, `random_seed_ledger_hash`, `contract_versions`, or `scorecard` blocks `pass_fail=True` while still persisting the failed artifact.
- Did not implement calibration runner execution, market metrics extraction, scorecard computation, target profile storage, PostgreSQL persistence, GUI behavior, strict parent gate v2, or PostgreSQL data deletion.

### verification

- `python -m py_compile app/services/evidence_artifact_writer.py tests/runtime/test_evidence_artifact_writer.py`
- `.venv\Scripts\python.exe -m pytest tests/runtime/test_evidence_artifact_writer.py -q`

### impact / risk

- Positive: Task 88 now has a real separate JSON artifact writer instead of only embedded Arena report metadata.
- Positive: missing seed-ledger or identity inputs cannot silently produce a passing calibration artifact.
- Risk: calibration evidence still remains incomplete until Task 86/87 code and a real calibration runner produce metrics and scorecards.

### next actions

- Continue Task 89 by implementing or documenting the Unified Baseline Runner boundary so baseline artifacts can be produced through the same runtime/contract path.

## Task 2026-05-05-model-training-87

### status

done

### goal

Define Calibration Scorecard v0 target profile, normalized distance, critical failure, and pass/fail boundaries before calibration scoring or artifact writing code.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/tasks/model-training/calibration-scorecard-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/calibration-scorecard-v0.md`.
- Documented target profile schema and ownership boundaries.
- Documented metric eligibility using Task 86 `metric_coverage`.
- Documented normalized distance semantics from the second expert review.
- Documented score parts, weighted total score, critical failure keys, and pass/fail boundary.
- Documented the scorecard output shape that Task 88 `calibration_artifact_v1` writer should consume.
- Kept current `world_card.calibration.status=not_available`, `score=None`, and `score_status=not_available` boundaries honest.
- Did not implement scorecard code, target profile storage, calibration score computation, artifact writing, runner behavior, or PostgreSQL data deletion.

### verification

- Direct document assertion passed with `CALIBRATION_SCORECARD_V0_DOC_ASSERTIONS_OK`.
- DOCX response document was updated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: Task 88 now has a documented scorecard object and pass/fail boundary to consume.
- Positive: missing and not-available metrics cannot silently become zero-distance passes.
- Risk: no target profile or calibration score implementation exists yet, so calibration evidence remains `not_available`.

### next actions

- Implement Task 88 by documenting Calibration Artifact Writer boundaries for `calibration_artifact_v1`.

## Task 2026-05-05-model-training-86

### status

done

### goal

Define Market Metrics Extractor v0 inputs, supported metric groups, coverage statuses, and unavailable metric boundaries before calibration scoring or artifact writing.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/market-metrics-extractor-v0.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/market-metrics-extractor-v0.md`.
- Documented normalized extractor inputs for orders, trades, snapshots, bars, accounts, account-equity snapshots, and optional holding samples.
- Mapped existing persisted runtime tables and `RetailCalibrationReportCollector` samples to supported metric groups.
- Documented price stylized facts, microstructure, liquidity, behavior, and rule-consistency metric boundaries.
- Documented `metric_coverage` fields and stable missing/not-available reason keys.
- Kept unsupported metrics such as cancel rate, fill probability by price offset, trade-through anomaly, retail family contribution, T+1 rejection rate, short-sell rejection rate, fee consistency, and frozen release consistency explicit as `not_available` unless their source semantics are later wired.
- Did not implement extractor code, calibration scoring, calibration artifact writing, WorldSpec code, RandomSeedLedger code, runner behavior, GUI behavior, or PostgreSQL data deletion.

### verification

- Direct document assertion passed with `MARKET_METRICS_EXTRACTOR_V0_DOC_ASSERTIONS_OK`.
- DOCX response document was updated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: Task 87 and Task 88 now have a documented metrics input and coverage boundary before scoring/artifact code is added.
- Positive: existing retail calibration metrics are reused as a documented source instead of duplicating or inventing new semantics.
- Risk: no formal extractor code exists yet, and calibration evidence still remains `not_available`.

### next actions

- Implement Task 87 by documenting Calibration Scorecard v0 target profile ownership, normalized distance, critical failures, and pass/fail rules before code work.

## Task 2026-05-05-model-training-85

### status

done

### goal

Define RandomSeedLedger v1 and split Task 85 into implementation-ready steps without fabricating a seed or changing current stochastic behavior.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/random-seed-ledger-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/random-seed-ledger-v1.md`.
- Documented the proposed `random_seed_ledger_v1` schema.
- Documented the `sha256_label_derivation_v1` seed derivation contract from the second expert review.
- Documented required seed labels for retail population, liquidity noise, model initialization, episode sampling, hidden-world selection, world generation, calibration, baselines, paired perturbations, exploit worlds, and PBT mutation.
- Documented artifact blocking rules for calibration, baseline, hidden evaluation, exploit test, paired sensitivity, and parent gate artifacts.
- Documented ledger hash rules, status rules, and required implementation tests.
- Kept current `random_seed_identity.status=not_available`, `random_seed=None`, and `missing_sources=random_seed` boundaries honest.
- Did not implement seed injection, seed ledger code, artifact pass/fail enforcement, stochastic behavior changes, or PostgreSQL data deletion.

### verification

- Direct document assertion passed with `RANDOM_SEED_LEDGER_V1_DOC_ASSERTIONS_OK`.
- DOCX response document was updated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: Evidence Runner artifacts now have a documented seed-ledger dependency before runner work begins.
- Positive: the project still avoids misleading report-only seeds.
- Risk: no actual seed-controlled reproducibility exists until owning services consume the ledger.

### next actions

- Implement Task 86 by documenting the Market Metrics Extractor v0 inputs, supported metrics, missing metric boundaries, and artifact dependencies before code changes.

## Task 2026-05-05-model-training-84

### status

done

### goal

Define the WorldSpec canonical hash contract and split Task 84 into smaller implementation-ready steps without changing current world generation or hash behavior.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/worldspec-canonical-hash.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/worldspec-canonical-hash.md`.
- Documented the proposed `world_spec_v1` shape from the second expert review.
- Mapped existing Arena `world_identity` and `world_card` metadata to supported WorldSpec fields.
- Marked unsupported world fields as `not_available` instead of fabricating market rules, fee models, impact models, fill models, retail family weights, calibration targets, scenario families, or hidden splits.
- Documented canonical JSON rules and `world_spec_hash` payload boundaries.
- Documented required tests for hash stability, input sensitivity, explicit `not_available`, and self-hash exclusion.
- Did not implement `world_spec_v1`, `world_spec_hash`, hidden-world registry, split generation, RandomSeedLedger, calibration, artifact persistence, runner behavior, or PostgreSQL data deletion.

### verification

- Direct document assertion passed with `WORLDSPEC_CANONICAL_HASH_DOC_ASSERTIONS_OK`.
- DOCX response document was updated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: Task 84 now has implementation-ready boundaries before code changes.
- Positive: unsupported world semantics remain explicit and are not silently treated as available.
- Risk: existing `world_hash` is still the current Arena config identity hash; no formal `world_spec_hash` exists yet.

### next actions

- Implement Task 85 by documenting RandomSeedLedger v1 before any hidden, paired, or exploit runner claims seed-controlled reproducibility.

## Task 2026-05-04-model-training-83

### status

done

### goal

Define Separate Artifact Schemas v1 for Evidence Runner outputs before implementing artifact writers or runner behavior.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/separate-artifact-schemas-v1.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/separate-artifact-schemas-v1.md`.
- Documented common fields for Evidence Runner artifacts, including artifact identity, runner identity, code/sim/world/reward/contract/seed ledger identity, metrics, pass/fail, failure reasons, dependencies, and artifact hash.
- Documented six artifact kinds:
  - `calibration_artifact_v1`
  - `baseline_artifact_v1`
  - `hidden_eval_artifact_v1`
  - `exploit_test_artifact_v1`
  - `paired_sensitivity_artifact_v1`
  - `parent_gate_artifact_v2`
- Documented pass/fail boundaries and stable failure reason keys for each artifact kind.
- Documented that parent eligibility, checkpoint promotion, and research claim eligibility must remain separate.
- Did not implement artifact persistence, artifact writers, runners, strict parent gate v2 behavior, GUI behavior, or PostgreSQL data deletion.

### verification

- Direct document assertion passed with `SEPARATE_ARTIFACT_SCHEMAS_V1_ASSERTIONS_OK`.
- DOCX response document was updated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: Evidence Runner implementation now has documented output contracts before code is added.
- Positive: embedded report sections remain clearly separate from independent evidence artifacts.
- Risk: this is still schema documentation only; no artifact is produced yet.

### next actions

- Implement Task 84 by defining WorldSpec canonical hash using only project-owned world/config inputs.
- Implement Task 85 by defining RandomSeedLedger v1 before artifacts depend on seed identity.

## Task 2026-05-04-model-training-82

### status

done

### goal

Switch model-training work from Metadata Completeness Phase to Evidence Runner Phase by documenting the Task 82 phase charter and freezing completeness-only expansion as the default next step.

### files involved

- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md`
- `docs/tasks/model-training/evidence-runner-phase-charter.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/current-work-status/model-training.md`
- `UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计_做得怎样.docx`

### change summary

- Added `docs/tasks/model-training/evidence-runner-phase-charter.md`.
- Recorded that Task 82 freezes further horizontal `experiment_record_completeness.field_status` expansion unless it fixes a documented bug or blocks an Evidence Runner artifact.
- Recorded the Evidence Runner priority order from Task 83 through Task 101.
- Recorded the minimum separate artifact kinds that Task 83 must define before runner implementation.
- Kept calibration, hidden evaluation, exploit tests, paired sensitivity, and parent-gate evidence as `not_available` until independent artifacts/runners exist.
- Did not change training, execution, reward, account, PBT parent selection, checkpoint promotion, GUI behavior, or PostgreSQL data.

### verification

- Direct document assertion passed with `EVIDENCE_RUNNER_PHASE_CHARTER_ASSERTIONS_OK`.
- DOCX response document was generated and checked with `python-docx` structural assertions.

### impact / risk

- Positive: the project now has an explicit phase boundary matching the second expert review.
- Positive: future work has a documented guardrail against continuing to add only completeness metadata.
- Risk: this is a docs-first charter only; no separate Evidence Runner artifact has been implemented yet.

### next actions

- Implement Task 83 by documenting Separate Artifact Schemas v1 for calibration, baseline, hidden evaluation, exploit test, paired sensitivity, and parent gate artifacts.

## Task 2026-05-04-model-training-77-81

### status

done

### goal

Make five existing record-kind detail fields visible in experiment record completeness without changing record-kind semantics or artifact generation.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庚惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`
- `docs/tasks/model-training/arena-record-kind-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-record-kind-schema-completeness-status.md`
- `docs/tasks/model-training/arena-record-kind-kind-completeness-status.md`
- `docs/tasks/model-training/arena-record-primary-stage-completeness-status.md`
- `docs/tasks/model-training/arena-record-task-name-completeness-status.md`
- `docs/tasks/model-training/arena-record-embedded-sections-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added five task documents for Task 77 through Task 81.
- Added `record_kind_schema` to `experiment_record_completeness.field_status`.
- Added `record_kind_kind` to `experiment_record_completeness.field_status`.
- Added `record_primary_stage` to `experiment_record_completeness.field_status`.
- Added `record_task_name` to `experiment_record_completeness.field_status`.
- Added `record_embedded_sections` to `experiment_record_completeness.field_status`.
- Series completeness aggregates now count all five field statuses.
- Did not change record-kind values, embedded-section taxonomy, separate artifact boundaries, hidden-world runner behavior, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
- Direct record-kind detail completeness batch assertion passed with `ARENA_RECORD_KIND_DETAIL_COMPLETENESS_BATCH_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes detailed record-kind metadata from only having a record-kind object.
- Positive: future artifact-boundary validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no separate artifact generation is added.

### next actions

- Add deeper artifact-boundary validation only after separate artifact schemas and runners are documented.

## Task 2026-05-04-model-training-71-76

### status

done

### goal

Make six existing experiment-record metadata source fields visible in experiment record completeness without changing metadata generation, hash calculation, random-seed behavior, or report identity semantics.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-metadata-schema-completeness-status.md`
- `docs/tasks/model-training/arena-code-identity-completeness-status.md`
- `docs/tasks/model-training/arena-sim-version-identity-completeness-status.md`
- `docs/tasks/model-training/arena-random-seed-identity-completeness-status.md`
- `docs/tasks/model-training/arena-missing-sources-completeness-status.md`
- `docs/tasks/model-training/arena-not-applicable-sources-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added six task documents for Task 71 through Task 76.
- Added `metadata_schema` to `experiment_record_completeness.field_status`.
- Added `code_identity` to `experiment_record_completeness.field_status`.
- Added `sim_version_identity` to `experiment_record_completeness.field_status`.
- Added `random_seed_identity` to `experiment_record_completeness.field_status`.
- Added `missing_sources` to `experiment_record_completeness.field_status`.
- Added `not_applicable_sources` to `experiment_record_completeness.field_status`.
- Series completeness aggregates now count all six field statuses.
- Did not change metadata schema values, Git identity collection, sim-version source, random-seed behavior, hash calculation, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct metadata-source completeness batch assertion passed with `ARENA_METADATA_SOURCE_COMPLETENESS_BATCH_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit metadata source ledgers from missing source metadata.
- Positive: future metadata validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no source semantic validation is added.

### next actions

- Add deeper metadata-source validation only after validation ownership and allowed schema evolution are documented.

## Task 2026-05-04-model-training-70

### status

done

### goal

Make hash-method metadata visible in experiment record completeness without changing hash calculation or report identity values.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-hash-method-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-hash-method-completeness-status.md`.
- Added `hash_method` to `experiment_record_completeness.field_status`.
- `hash_method` is `present` when a top-level or metadata hash-method value exists.
- `hash_method` is `missing` when no hash-method value exists.
- Series completeness aggregates now count `hash_method` field statuses.
- Did not change hash-method values, reward/world/code hash calculation, reward behavior, reward benchmark, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct hash-method completeness assertion passed with `ARENA_HASH_METHOD_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit hash-method metadata from only having derived hash values.
- Positive: future hash-method validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no hash-method semantic validation is added.

### next actions

- Add deeper hash-method validation only after validation ownership and allowed schema evolution are documented.

## Task 2026-05-04-model-training-69

### status

done

### goal

Make observation/action/reward contract-version metadata visible in experiment record completeness without changing any contract versions or contract behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-contract-versions-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `rl/contracts.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-contract-versions-completeness-status.md`.
- Added `contract_versions` to `experiment_record_completeness.field_status`.
- `contract_versions` is `present` when a top-level or metadata contract-version object exists.
- `contract_versions` is `missing` when no contract-version object exists.
- Series completeness aggregates now count `contract_versions` field statuses.
- Did not change observation/action/reward contract constants, contract schemas, reward behavior, reward benchmark, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct contract-version completeness assertion passed with `ARENA_CONTRACT_VERSIONS_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit contract-version metadata from only having reward/world hashes.
- Positive: future contract-version validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no contract semantic validation is added.

### next actions

- Add deeper contract-version validation only after validation ownership and allowed schema evolution are documented.

## Task 2026-05-04-model-training-68

### status

done

### goal

Make reward identity metadata visible in experiment record completeness without changing reward-hash calculation or reward behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-reward-identity-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-reward-identity-completeness-status.md`.
- Added `reward_identity` to `experiment_record_completeness.field_status`.
- `reward_identity` is `present` when a top-level or metadata reward-identity object exists.
- `reward_identity` is `missing` when no reward-identity object exists.
- Series completeness aggregates now count `reward_identity` field statuses.
- Did not change reward-hash calculation, reward identity schema, reward behavior, reward benchmark, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct reward-identity completeness assertion passed with `ARENA_REWARD_IDENTITY_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit reward identity metadata from only having a derived reward hash.
- Positive: future reward-identity validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no reward semantic validation is added.

### next actions

- Add deeper reward-identity validation only after validation ownership and allowed schema evolution are documented.

## Task 2026-05-04-model-training-67

### status

done

### goal

Make world identity metadata visible in experiment record completeness without changing world-hash calculation or world generation.

### files involved

- `UTI-STOCKSIM_娑撴挸顔嶇拠鍕吀娑撳氦鎯ら崷鎷岊啎鐠?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-identity-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-identity-completeness-status.md`.
- Added `world_identity` to `experiment_record_completeness.field_status`.
- `world_identity` is `present` when a top-level or metadata world-identity object exists.
- `world_identity` is `missing` when no world-identity object exists.
- Series completeness aggregates now count `world_identity` field statuses.
- Did not change world-hash calculation, world-identity schema, world generation, world split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct world-identity completeness assertion passed with `ARENA_WORLD_IDENTITY_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit world identity metadata from only having derived hashes or world-card summaries.
- Positive: future world-identity validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no world identity semantic validation is added.

### next actions

- Add deeper world-identity validation only after validation ownership and allowed schema evolution are documented.

## Task 2026-05-04-model-training-66

### status

done

### goal

Make world-card universe metadata visible in experiment record completeness without changing symbol selection.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-universe-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-universe-completeness-status.md`.
- Added `world_universe` to `experiment_record_completeness.field_status`.
- `world_universe` is `present` when world-card symbols are non-empty and `symbol_count` is greater than zero.
- `world_universe` is `missing` when world-card universe metadata is empty or absent.
- Series completeness aggregates now count `world_universe` field statuses.
- Did not change symbol selection, universe expansion/filtering, world split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct world-universe completeness assertion passed with `ARENA_WORLD_UNIVERSE_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit world-card universe metadata from missing metadata.
- Positive: future world-universe validation can become more detailed without changing aggregate shape.
- Risk: this remains status metadata only; no symbol-pool validation is added.

### next actions

- Add universe validation or hidden-world universe split only after symbol-pool ownership and world-card artifact boundaries are documented.

## Task 2026-05-04-model-training-65

### status

done

### goal

Make world-card clock configuration visible in experiment record completeness without changing clock behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-clock-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-clock-completeness-status.md`.
- Added `world_clock` to `experiment_record_completeness.field_status`.
- `world_clock` is `present` when `clock_start_day`, `clock_speed`, and `run_clock` are present in the world card.
- `world_clock` is `missing` when any required clock field is absent.
- Series completeness aggregates now count `world_clock` field statuses.
- Did not change simulation clock behavior, time-step semantics, world split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct world-clock completeness assertion passed with `ARENA_WORLD_CLOCK_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit clock configuration from missing metadata.
- Positive: both enabled and disabled runtime-clock settings are treated as auditable when explicitly present.
- Risk: this remains status metadata only; no clock or time-regime evaluation is added.

### next actions

- Add additional clock or time-regime evidence only after metric ownership and world-card artifact boundaries are documented.

## Task 2026-05-04-model-training-64

### status

done

### goal

Make world-card training-liquidity seed configuration visible in experiment record completeness without changing liquidity behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md`.
- Added `world_liquidity_seed` to `experiment_record_completeness.field_status`.
- `world_liquidity_seed` is `present` when `seed_training_liquidity` is explicitly present in the world card.
- `world_liquidity_seed` is `missing` when no liquidity-seed metadata exists.
- Series completeness aggregates now count `world_liquidity_seed` field statuses.
- Did not add new liquidity seed behavior, liquidity model changes, matching-engine changes, world split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct liquidity-seed completeness assertion passed with `ARENA_WORLD_LIQUIDITY_SEED_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes explicit liquidity-seed configuration from missing metadata.
- Positive: both enabled and disabled liquidity-seed settings are treated as auditable when explicitly present.
- Risk: this remains status metadata only; no liquidity or market-depth evidence is added.

### next actions

- Add detailed liquidity or market-depth evidence only after metric ownership, data sources, and world-card artifact boundaries are documented.

## Task 2026-05-04-model-training-63

### status

done

### goal

Make world-card retail family mix status visible in experiment record completeness without implementing retail mix reporting.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md`.
- Added `world_retail_family_mix` to `experiment_record_completeness.field_status`.
- `world_retail_family_mix` is `present` when retail family mix evidence is available/pass/complete/present.
- `world_retail_family_mix` is `not_available` when `retail_family_mix_status=not_available`.
- `world_retail_family_mix` is `missing` when no retail family mix status exists.
- Series completeness aggregates now count `world_retail_family_mix` field statuses.
- Did not add retail family mix calculation, retail calibration harnesses, persona distribution reports, world split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct retail-family-mix completeness assertion passed with `ARENA_WORLD_RETAIL_FAMILY_MIX_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes unavailable retail-family-mix metadata from missing metadata.
- Positive: future world cards with real retail mix evidence can become `present` without changing aggregate shape.
- Risk: this remains status metadata only; no retail-family-mix calculation exists yet.

### next actions

- Add real retail family mix evidence only after metric ownership, data sources, and world-card artifact boundaries are documented.

## Task 2026-05-04-model-training-62

### status

done

### goal

Make world-card split status visible in experiment record completeness without implementing world splitting.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-split-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-split-completeness-status.md`.
- Added `world_split` to `experiment_record_completeness.field_status`.
- `world_split` is `present` when a validation/hidden/complete split status exists.
- `world_split` is `not_available` when `split_status=training_only` or `not_available`.
- `world_split` is `missing` when no world-card split status exists.
- Series completeness aggregates now count `world_split` field statuses.
- Did not add train/validation/hidden world split, seed/config hash split rules, hidden-world runner, calibration score computation, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct world-split completeness assertion passed with `ARENA_WORLD_SPLIT_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes training-only world cards from missing split metadata.
- Positive: future validation/hidden split reports can become `present` without changing aggregate shape.
- Risk: this remains status metadata only; no world split exists yet.

### next actions

- Add real train/validation/hidden split only after seed/config hash split rules and artifact boundaries are documented.

## Task 2026-05-04-model-training-61

### status

done

### goal

Make the explicit world-card calibration-score slot visible in experiment record completeness without computing calibration scores.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md`
- `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md`.
- Added `world_calibration_score` to `experiment_record_completeness.field_status`.
- `world_calibration_score` is `present` when a real score or available/pass/complete score status exists.
- `world_calibration_score` is `not_available` when `calibration_score_status=not_available`.
- `world_calibration_score` is `missing` when no calibration-score slot/status exists.
- Series completeness aggregates now count `world_calibration_score` field statuses.
- Did not add calibration score computation, calibration pass/fail thresholds, calibration harnesses, world-pool split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct world-calibration-score completeness assertion passed with `ARENA_WORLD_CALIBRATION_SCORE_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes missing calibration-score slots from explicit `not_available` score slots.
- Positive: future reports with real scores can become `present` without changing aggregate shape.
- Risk: this remains status metadata only; no calibration score or pass/fail claim exists.

### next actions

- Add real calibration scores only after metric ownership, data sources, pass/fail thresholds, and artifact boundaries are documented.

## Task 2026-05-04-model-training-60

### status

done

### goal

Add an explicit calibration-score slot to Arena world-card metadata without computing calibration scores.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-world-card-calibration-score-slot.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-card-calibration-score-slot.md`.
- Added `world_card.calibration.score=None`.
- Added `world_card.calibration.score_status=not_available`.
- Added `world_card.calibration.score_reason=calibration_harness_not_implemented`.
- Arena generation `world_card` summaries now expose `calibration_score`, `calibration_score_status`, and `calibration_score_reason`.
- Arena series `aggregate.world_card` now counts `calibration_score_status_counts`.
- Did not add calibration score computation, calibration pass/fail thresholds, calibration harnesses, world-pool split, hidden-world runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct calibration-score slot assertion passed with `ARENA_WORLD_CARD_CALIBRATION_SCORE_SLOT_ASSERTIONS_OK`.
- `tests/runtime/test_arena_experiment_runner.py::test_runner_orchestrates_arena_clock_and_writes_report` remains blocked in this environment by Windows pytest temporary-directory lock permissions, not by the calibration-score assertions.

### impact / risk

- Positive: world-card metadata now explicitly says calibration score is unavailable.
- Positive: series reports can count calibration-score availability without opening every full report.
- Risk: this remains a report slot only; no calibration score or pass/fail claim exists.

### next actions

- Add real calibration scores only after metric ownership, data sources, pass/fail thresholds, and artifact boundaries are documented.

## Task 2026-05-04-model-training-59

### status

done

### goal

Make compact model-lineage evidence visible in experiment record completeness without changing PBT behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-model-lineage-evidence-summary.md`
- `docs/tasks/model-training/arena-model-lineage-evidence-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-model-lineage-evidence-completeness-status.md`.
- Added `model_lineage_evidence` to `experiment_record_completeness.field_status`.
- `model_lineage_evidence` is `present` when compact lineage evidence has a PBT lineage row.
- `model_lineage_evidence` is `not_available` when a generation has no PBT lineage row.
- Series completeness aggregates now count `model_lineage_evidence` field statuses.
- Did not add new PBT lineage creation, mutation logic, separate model-lineage artifacts, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_model_lineage_evidence`
- Direct model-lineage evidence completeness assertion passed with `ARENA_MODEL_LINEAGE_EVIDENCE_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now tracks whether compact model-lineage evidence exists.
- Positive: no-lineage generations are explicit as `not_available` rather than confused with missing metadata.
- Risk: this remains status metadata only; no separate model-lineage artifact exists yet.

### next actions

- Keep model-lineage artifact expansion deferred until the project documents a separate artifact schema or additional mutation acceptance criteria.

## Task 2026-05-04-model-training-58

### status

done

### goal

Expose compact model, parent-lineage, and mutation-key evidence in Arena generation and series reports without changing PBT behavior.

### files involved

- `UTI-STOCKSIM_涓撳璇勫涓庤惤鍦拌璁?docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-transition-evidence-summary.md`
- `docs/tasks/model-training/arena-model-lineage-evidence-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-model-lineage-evidence-summary.md`.
- Added `model_lineage_evidence` to Arena generation summaries.
- Added `aggregate.model_lineage_evidence` to Arena series aggregates.
- The summary reads existing `config.model_specs`, `pbt.lineage`, and `pbt.applied_agents` only.
- Generation summaries now expose model ids, agent ids, parent model ids, child model ids, applied model ids, mutation keys, lineage counts, and bounded lineage samples.
- Series aggregates now count model ids, agent ids, parent/child model ids, applied model ids, mutation keys, and lineage statuses.
- Did not add new PBT lineage creation, mutation logic, checkpoint loading, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_model_lineage_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
- Direct model-lineage evidence assertion passed with `ARENA_MODEL_LINEAGE_EVIDENCE_ASSERTIONS_OK`.

### impact / risk

- Positive: reports now answer the model/parent-lineage/mutation-key portion of Work Package E more directly.
- Positive: no-lineage generations remain explicit as `no_lineage`.
- Risk: this remains summary-only; it does not create separate model-lineage artifacts or validate mutation quality.

### next actions

- Keep model-lineage artifact expansion deferred until the project documents a separate artifact schema or additional mutation acceptance criteria.

## Task 2026-05-04-model-training-57

### status

done

### goal

Make compact transition evidence visible in experiment record completeness without changing transition storage.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-transition-evidence-summary.md`
- `docs/tasks/model-training/arena-transition-evidence-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-transition-evidence-completeness-status.md`.
- Added `transition_evidence` to `experiment_record_completeness.field_status`.
- `transition_evidence` is `present` when compact transition evidence has a summary.
- `transition_evidence` is `not_available` when an episode has no transitions.
- Series completeness aggregates now count `transition_evidence` field statuses.
- Did not add new transition persistence, larger raw samples, replay artifacts, failure reproduction runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
- Direct transition-evidence completeness assertion passed with `ARENA_TRANSITION_EVIDENCE_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now tracks whether compact transition evidence exists.
- Positive: no-transition episodes are explicit as `not_available` rather than being confused with missing metadata.
- Risk: this remains status metadata only; no replay/failure reproduction artifact exists yet.

### next actions

- Add replay or failure reproduction artifacts only after their schema, retention policy, and data source boundaries are documented.

## Task 2026-05-04-model-training-56

### status

done

### goal

Expose compact transition evidence summaries for Arena generation and series reports without changing transition storage.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-transition-evidence-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-transition-evidence-summary.md`.
- Added `transition_evidence` to Arena generation summaries.
- Added `aggregate.transition_evidence` to Arena series aggregates.
- The summary reads existing transition count and audit sections only.
- It reports the compact policy `compact_summary_with_bounded_audit_samples` with `sample_limit_per_audit=5`.
- It counts audit sample counts, audit violation counts, evidence statuses, and per-audit statuses across a series.
- Did not add new transition persistence, larger raw samples, replay artifacts, failure reproduction runner, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_transition_evidence`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
- Direct transition-evidence assertion passed with `ARENA_TRANSITION_EVIDENCE_SUMMARY_ASSERTIONS_OK`.

### impact / risk

- Positive: multi-generation reports now show whether compact transition evidence exists.
- Positive: aggregate reports can count audit samples and violations without expanding raw transition storage.
- Risk: this remains summary-only; no replay/failure reproduction artifact exists yet.

### next actions

- Add replay or failure reproduction artifacts only after their schema, retention policy, and data source boundaries are documented.

## Task 2026-05-04-model-training-55

### status

done

### goal

Make Arena record-kind and separate artifact boundary statuses visible in experiment record completeness.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`
- `docs/tasks/model-training/arena-record-kind-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-record-kind-completeness-status.md`.
- Added `record_kind` to `experiment_record_completeness.field_status`.
- Added `separate_calibration_record` to `experiment_record_completeness.field_status`.
- Added `separate_hidden_evaluation_record` to `experiment_record_completeness.field_status`.
- Added `separate_exploit_test_record` to `experiment_record_completeness.field_status`.
- `record_kind` is present only when a real record-kind object exists in the report or metadata.
- Separate artifact statuses remain `not_available` when record-kind metadata explicitly says the separate artifact is not available.
- Series completeness aggregates now count record-kind and separate artifact field statuses.
- Did not add separate calibration artifacts, hidden-world runner, exploit-test artifact, calibration metrics, random seed injection, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
- Direct record-kind completeness assertion passed with `ARENA_RECORD_KIND_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now tracks whether report artifact boundaries are labeled.
- Positive: separate calibration, hidden-evaluation, and exploit-test artifacts remain explicitly unavailable instead of implied.
- Risk: this is status metadata only; no separate artifact exists yet.

### next actions

- Add separate calibration, hidden-evaluation, and exploit-test artifacts only after their schemas, runners, and artifact boundaries are documented.

## Task 2026-05-04-model-training-54

### status

done

### goal

Label Arena experiment reports with record-kind metadata so training, calibration, evaluation, and exploit-test artifacts remain distinguishable.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`.
- Added top-level `record_kind` to Arena experiment reports.
- Added `experiment_record_metadata.record_kind`.
- Added `record_kind` to Arena generation summaries.
- Added `aggregate.record_kind` to Arena series aggregates.
- Current Arena reports are marked `kind=arena_experiment_report` and `primary_stage=training`.
- Embedded sections are listed explicitly, including training episode, baseline suite, benchmark comparison, hidden evaluation, exploit detector, research acceptance, and PBT.
- Separate calibration, hidden-evaluation, and exploit-test artifact statuses remain `not_available`.
- Did not add separate calibration artifacts, hidden-world runner, exploit-test artifact, calibration metrics, random seed injection, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_record_kind`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct record-kind assertion passed with `ARENA_RECORD_KIND_METADATA_ASSERTIONS_OK`.

### impact / risk

- Positive: reports now identify themselves as training-stage Arena experiment records.
- Positive: missing separate calibration/hidden/exploit artifacts are explicit instead of implied.
- Risk: this is record labeling only; it does not create the separate artifacts.

### next actions

- Add separate calibration records only after calibration metric ownership and output schema are documented.
- Add hidden-evaluation and exploit-test artifacts only after their runners and artifact boundaries are documented.

## Task 2026-05-04-model-training-53

### status

done

### goal

Make Arena world-card and calibration status visible in experiment record completeness without implementing calibration logic.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `docs/tasks/model-training/arena-world-card-completeness-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-card-completeness-status.md`.
- Added `world_card` to `experiment_record_completeness.field_status`.
- Added `world_calibration` to `experiment_record_completeness.field_status`.
- `world_card` is `present` only when a real world-card object exists in the report or metadata.
- `world_calibration` is `not_available` when `world_card.calibration.status=not_available`.
- Series completeness aggregates now count `world_card` and `world_calibration` field statuses.
- Did not add calibration metrics, world-pool split, hidden-world runner, random seed injection, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
- Direct world-card completeness assertion passed with `ARENA_WORLD_CARD_COMPLETENESS_ASSERTIONS_OK`.

### impact / risk

- Positive: completeness now distinguishes `world_hash` from a real `world_card`.
- Positive: missing calibration remains visible as `not_available` instead of being hidden.
- Risk: calibration remains report status only; no calibration score or pass/fail claim exists yet.

### next actions

- Add real calibration metrics only after metric ownership, data sources, and thresholds are documented.
- Add hidden/validation world status only after documented world-pool split rules exist.

## Task 2026-05-04-model-training-52

### status

done

### goal

Add Arena world-card metadata and summary fields from existing world/config inputs without implementing calibration logic.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`
- `docs/tasks/model-training/arena-world-card-metadata.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-world-card-metadata.md`.
- Added top-level `world_card` to Arena experiment reports.
- Added `experiment_record_metadata.world_card`.
- Added `world_card` to Arena generation summaries.
- Added `aggregate.world_card` to Arena series aggregates.
- The world card exposes existing symbols, retail profile, clock settings, training-liquidity seed settings, and `world_hash`.
- World split is explicitly `training_only` because world-pool split rules are not implemented.
- Calibration is explicitly `not_available` because the calibration harness is not implemented.
- Did not add calibration metrics, hidden-world runner, world-pool split, random seed injection, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_world_card`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
- Direct world-card assertion passed with `ARENA_WORLD_CARD_METADATA_ASSERTIONS_OK`.

### impact / risk

- Positive: reports can now show which Arena world/config identity was used in a human-readable world-card shape.
- Positive: missing calibration metrics are explicit rather than implied.
- Risk: this is still report metadata only; no calibration pass/fail or hidden-world transfer claim exists.

### next actions

- Add calibration metrics only after metric ownership and data sources are documented.
- Add train/validation/hidden world split only after seed/config hash split rules are documented.

## Task 2026-05-04-model-training-51

### status

done

### goal

Expose Arena experiment record identity in generation and series summaries without creating new identity values.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`.
- Added `experiment_record_identity` to Arena generation summaries.
- Added `aggregate.experiment_record_identity` to Arena series aggregates.
- The identity summary reads existing top-level report fields and `experiment_record_metadata`.
- It exposes existing code hash, sim version, reward hash, world hash, random-seed status, dirty-code status, missing sources, and not-applicable sources.
- It does not generate a fake random seed or add new hash/version sources.
- Did not change training, reward, world, PBT, checkpoint, replay/hybrid, or PostgreSQL data behavior.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_identity`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct identity-summary assertion passed with `ARENA_SERIES_EXPERIMENT_RECORD_IDENTITY_ASSERTIONS_OK`.

### impact / risk

- Positive: multi-generation reports can show the identity state for each generation without opening every full report.
- Positive: series aggregates can count repeated source gaps such as `random_seed`.
- Risk: identity quality is still bounded by upstream metadata; `random_seed` remains `not_available` until RNG ownership is wired.

### next actions

- Add a real random seed only after Arena config, retail persona sampling, model training RNG, and market/world RNG consume it.
- Keep replay/hybrid `data_cutoff` not applicable until replay/hybrid data is added through a documented task.

## Task 2026-05-03-model-training-50

### status

done

### goal

Make the Arena experiment random-seed gap explicit without fabricating a seed value.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-sim-version-source.md`
- `docs/tasks/model-training/arena-experiment-random-seed-status.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-experiment-random-seed-status.md`.
- Added `random_seed_identity` to `experiment_record_metadata`.
- Added top-level `random_seed=None` to Arena experiment reports.
- `random_seed_identity.status=not_available`.
- `random_seed_identity.reason=random_seed_not_wired_to_stochastic_services`.
- The report records prerequisites before a real seed can become present:
  - `arena_config_random_seed`
  - `retail_persona_rng_seed`
  - `model_training_rng_seed`
  - `market_world_rng_seed`
- `missing_sources` continues to include `random_seed`.
- `experiment_record_completeness` continues to count `random_seed` as missing.
- Did not add a fake seed value, Arena config seed field, RNG wiring, hidden-world seed, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct random-seed status assertion passed with `ARENA_EXPERIMENT_RANDOM_SEED_STATUS_ASSERTIONS_OK`.

### impact / risk

- Positive: new Arena reports explain why Work Package E `random_seed` remains missing.
- Positive: the report does not overclaim reproducibility by writing a seed that does not control stochastic services.
- Risk: `random_seed` remains incomplete until RNG ownership is actually wired through Arena, retail persona, model training, and world generation paths.

### next actions

- Add a real `ArenaExperimentConfig.random_seed` only when underlying stochastic services consume it.
- Route the seed through retail persona sampling, model training RNG, and market/world RNG before marking `random_seed` present.

## Task 2026-05-03-model-training-49

### status

done

### goal

Add an Arena experiment `sim_version` source using the existing `stock_sim.__version__` package value.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-code-identity-hash.md`
- `docs/tasks/model-training/arena-experiment-sim-version-source.md`
- `stock_sim/__init__.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-experiment-sim-version-source.md`.
- Added `sim_version_identity` to `experiment_record_metadata`.
- Added top-level `sim_version` to Arena experiment reports when `stock_sim.__version__` is available.
- `sim_version_identity` records `source=stock_sim.__version__`.
- `missing_sources` no longer includes `sim_version` when the version is available.
- `experiment_record_completeness` can now mark `sim_version` as present for new reports.
- Did not add a new versioning policy, dependency/environment version hash, runtime random seed injection, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct sim-version/completeness assertion passed with `ARENA_EXPERIMENT_SIM_VERSION_ASSERTIONS_OK`.

### impact / risk

- Positive: new Arena reports can now answer "what sim version" using an existing local source.
- Positive: Work Package E missing metadata is narrowed further without inventing new runtime behavior.
- Risk: `stock_sim.__version__` is currently `0.0.1`; this task wires the source but does not define a release/versioning policy.
- Risk: `random_seed` remains missing until stochastic services can consume and report it.

### next actions

- Add `random_seed` only after underlying stochastic services can consume and report it.
- Define broader dependency/environment identity only if a project-local task requires it.

## Task 2026-05-03-model-training-48

### status

done

### goal

Add a Git-based Arena experiment `code_hash` source while keeping dirty worktree state explicit.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `docs/tasks/model-training/arena-experiment-code-identity-hash.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-experiment-code-identity-hash.md`.
- Added Git-based `code_identity` to `experiment_record_metadata`.
- Added top-level `code_hash` to Arena experiment reports when Git identity is available.
- The code identity records Git HEAD, branch, dirty flag, porcelain status entry count, and status hash.
- `missing_sources` no longer includes `code_hash` when Git identity is available.
- If Git identity cannot be read, `code_hash` remains missing instead of being fabricated.
- Dirty worktree state remains explicit and is not treated as a clean release artifact.
- Did not add sim version, runtime random seed injection, full source archive hash, dependency/environment hash, training behavior, PBT behavior, checkpoint behavior, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_experiment_record_metadata_includes_git_code_identity_when_available`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct code identity/completeness assertion passed with `ARENA_EXPERIMENT_CODE_IDENTITY_ASSERTIONS_OK`.

### impact / risk

- Positive: new Arena reports can now answer "what code identity" produced the result when Git is available.
- Positive: dirty worktree state is visible in report metadata, avoiding a false clean-release claim.
- Risk: this is a Git identity hash, not a full source archive hash or dependency/environment hash.
- Risk: `sim_version` and `random_seed` remain missing until their local sources and ownership are documented.

### next actions

- Document a local ownership rule for `sim_version`.
- Add `random_seed` only after underlying stochastic services can consume and report it.
- Keep full source archive and environment hashes deferred until a project-local document asks for that broader scope.

## Task 2026-05-03-model-training-47

### status

done

### goal

Add deterministic Arena report metadata hashes for reward identity and world/config identity using existing local report inputs only.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`
- `rl/contracts.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`.
- Added top-level `reward_hash` to Arena experiment reports.
- Added top-level `world_hash` to Arena experiment reports.
- Added `experiment_record_metadata` with hash method, reward identity, world identity, contract versions, missing sources, and not-applicable sources.
- `reward_hash` is derived from canonical JSON over reward profile, task name, and `rew.v1`.
- `world_hash` is derived from canonical JSON over current Arena world/config inputs such as symbols, retail count/cash, clock settings, and training-liquidity settings.
- `experiment_record_completeness` now treats top-level `world_hash` as a valid source, so generated reward/world hashes become present in new reports.
- Did not add code hash, sim version, random seed injection, hidden-world split, calibration pass/fail, replay data cutoff, PBT behavior changes, checkpoint promotion, or PostgreSQL data deletion.

### verification

- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Targeted pure pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
- Direct runner assertion passed with `ARENA_EXPERIMENT_RECORD_METADATA_ASSERTIONS_OK`.
- Direct completeness assertion passed with `ARENA_EXPERIMENT_RECORD_HASH_COMPLETENESS_ASSERTIONS_OK`.
- `tests/runtime/test_arena_experiment_runner.py::test_runner_orchestrates_arena_clock_and_writes_report` remains blocked by Windows pytest temporary-directory lock/cleanup permission errors in this environment.

### impact / risk

- Positive: newly generated Arena reports can now answer "what reward profile/task" and "what Arena world/config identity" produced the result.
- Positive: the hash source identities are saved beside the hashes, keeping the report auditable.
- Risk: the `world_hash` is a config identity hash, not a calibrated hidden-world or validation-world proof.
- Risk: `code_hash`, `sim_version`, and `random_seed` remain missing until their local sources and ownership are documented.

### next actions

- Document a code-hash source before adding `code_hash`.
- Document a sim-version source before adding `sim_version`.
- Add a real random seed only when the underlying stochastic services can consume it.
- Keep hidden/validation world hashes deferred until world-pool split rules are documented.

## Task 2026-05-03-model-training-46

### status

done

### goal

Expose Arena experiment record completeness in generation summaries and series aggregates without fabricating reproducibility metadata.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-series-audit-summary.md`
- `docs/tasks/model-training/arena-series-experiment-record-completeness.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-experiment-record-completeness.md`.
- Added `experiment_record_completeness` to Arena generation summaries.
- Added `aggregate.experiment_record_completeness` to Arena series aggregates.
- Generation summaries now distinguish `present`, `missing`, `not_available`, and `not_applicable` field states.
- Series aggregates now count completeness status, field-status pairs, present fields, missing fields, unavailable fields, and not-applicable fields.
- Missing reproducibility fields such as `code_hash`, `sim_version`, `reward_hash`, `world_hash`, and `random_seed` are reported as missing rather than inferred.
- `data_cutoff` is reported as `not_applicable` until replay/hybrid data is documented.
- `parent_lineage` is reported as `not_available` when no PBT lineage row exists.
- Did not add new metadata sources, training behavior, execution behavior, reward behavior, PBT behavior, checkpoint promotion, or PostgreSQL data deletion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_experiment_record_completeness`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_episode_audit_summaries`
- Direct experiment-record completeness assertion passed with `ARENA_SERIES_EXPERIMENT_RECORD_COMPLETENESS_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose reproducibility gaps directly instead of leaving readers to inspect raw episode/config payloads.
- Positive: the output stays honest about missing code/world/reward/seed metadata and does not overclaim reproducibility.
- Risk: this is report-only; actual hash/seed/version sources still need documented ownership before they can become present.

### next actions

- Define documented sources for code hash, sim version, reward hash/profile hash, world hash/config hash, and random seed.
- Keep replay/hybrid `data_cutoff` deferred until replay/hybrid data is implemented through a documented task.

## Task 2026-05-03-model-training-45

### status

done

### goal

Expose episode-level audit and sensitivity sections directly in Arena generation summaries and series aggregates without adding new audit logic.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/runtime-observation-audit-report.md`
- `docs/tasks/model-training/timestamp-audit-report-check.md`
- `docs/tasks/model-training/arena-series-audit-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-audit-summary.md`.
- Added `audit_summary` to Arena generation summaries.
- Added `aggregate.audit_summary` to Arena series aggregates.
- Generation summaries now carry audit status, reason, scope, transition/result counts, violation count, and required-input count for:
  - `runtime_observation_audit`
  - `fee_sensitivity`
  - `impact_sensitivity`
  - `timestamp_audit`
  - `mark_to_market_audit`
  - `order_anomaly_audit`
- Series aggregates now count audit observations, transition/result totals, violations, required inputs, status counts by audit, and reason counts by audit.
- Did not add new audit checks, hidden-world runners, paired-world runners, reward benchmark rewiring, PBT behavior changes, strict gate decision changes, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_episode_audit_summaries`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_hidden_and_exploit_diagnostics`
- Direct audit summary assertion passed with `ARENA_SERIES_AUDIT_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose audit availability and failure counts directly instead of requiring readers to inspect each episode audit section.
- Positive: fee/impact `not_available` states remain explicit and countable across a series.
- Risk: this is report-only; deeper semantic audits and paired-world sensitivity checks remain unavailable until documented inputs and runners exist.

### next actions

- Use `aggregate.audit_summary.status_counts_by_audit` in future report readers.
- Continue implementing only documented audit, hidden, and exploit prerequisites.

## Task 2026-05-03-model-training-44

### status

done

### goal

Expose hidden-evaluation and exploit-detector status directly in Arena generation summaries and series aggregates without implementing hidden worlds or new exploit checks.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/hidden-evaluation-report-slots.md`
- `docs/tasks/model-training/arena-series-hidden-exploit-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-hidden-exploit-summary.md`.
- Added `hidden_evaluation` to Arena generation summaries.
- Added `exploit_detector` to Arena generation summaries.
- Added `aggregate.hidden_evaluation` to Arena series aggregates.
- Added `aggregate.exploit_detector` to Arena series aggregates.
- Generation summaries now carry hidden/exploit status, reason, implemented checks, placeholder checks, check counts, check status counts, check reason counts, and required input counts.
- Series aggregates now count hidden/exploit observations, statuses, check statuses, check reasons, implemented checks, and placeholder checks.
- Did not implement hidden worlds, paired worlds, no-signal worlds, new exploit audits, PBT behavior changes, strict gate decision changes, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_hidden_and_exploit_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_benchmark_comparison_diagnostics`
- Direct hidden/exploit summary assertion passed with `ARENA_SERIES_HIDDEN_EXPLOIT_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose hidden-evaluation and exploit-detector blockers directly, rather than requiring readers to infer them through research acceptance.
- Positive: unavailable hidden/exploit inputs remain explicit and machine-readable.
- Risk: this is report-only; hidden-world and paired-world checks remain unavailable until documented inputs and runners exist.

### next actions

- Use `aggregate.hidden_evaluation.status_counts` and `aggregate.exploit_detector.status_counts` in future report readers.
- Continue implementing only documented hidden/exploit prerequisites.

## Task 2026-05-03-model-training-43

### status

done

### goal

Expose benchmark comparison availability and candidate-baseline comparison counts in Arena generation summaries and series aggregates without changing runtime or PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-series-benchmark-comparison-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-benchmark-comparison-summary.md`.
- Added `benchmark_comparison` to Arena generation summaries.
- Added `aggregate.benchmark_comparison` to Arena series aggregates.
- Generation summaries now carry benchmark comparison status, baseline kinds, candidate count, candidate ids, and candidate-baseline pair count.
- Series aggregates now count benchmark comparison observations, statuses, baseline kinds, candidate counts, and candidate-baseline pair counts.
- Did not add new baseline policies, TWAP/VWAP schedules, reward benchmark rewiring, baseline-relative PBT gate, strict gate decision changes, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_benchmark_comparison_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_baseline_suite_diagnostics`
- Direct benchmark comparison summary assertion passed with `ARENA_SERIES_BENCHMARK_COMPARISON_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose benchmark comparison availability directly.
- Positive: missing-baseline benchmark comparison states can now be counted across a series.
- Risk: this is report-only; reward benchmark rewiring and baseline-relative parent gates remain deferred.

### next actions

- Use `aggregate.benchmark_comparison.status_counts` in future report readers.
- Continue implementing only documented baseline, hidden, and exploit prerequisites.

## Task 2026-05-03-model-training-42

### status

done

### goal

Expose baseline-suite status and missing baseline diagnostics in Arena generation summaries and series aggregates without changing runtime or PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/arena-series-baseline-suite-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-baseline-suite-summary.md`.
- Added `baseline_suite` to Arena generation summaries.
- Added `aggregate.baseline_suite` to Arena series aggregates.
- Generation summaries now carry baseline-suite task name, status, present kinds, missing required kinds, required rows, and optional rows.
- Series aggregates now count baseline-suite observations, complete/incomplete status, present baseline kinds, missing required kinds, required kind/status pairs, and optional kind/status pairs.
- Did not add new baseline policies, TWAP/VWAP schedules, reward benchmark rewiring, PBT behavior changes, strict gate decision changes, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_baseline_suite_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_research_acceptance_diagnostics`
- Direct baseline-suite summary assertion passed with `ARENA_SERIES_BASELINE_SUITE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose baseline-suite completeness directly, rather than requiring readers to infer it from research acceptance.
- Positive: recurring missing baseline kinds can now be counted across a series.
- Risk: this is report-only; TWAP/VWAP schedule execution and deeper execution baselines remain unavailable until documented inputs and runners exist.

### next actions

- Use `aggregate.baseline_suite.missing_required_counts` in future report readers.
- Continue implementing only documented baseline, hidden, and exploit prerequisites.

## Task 2026-05-03-model-training-41

### status

done

### goal

Expose research acceptance status and lock diagnostics in Arena generation summaries and series aggregates without changing PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/arena-series-research-acceptance-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-research-acceptance-summary.md`.
- Added `research_acceptance` to Arena generation summaries.
- Added `aggregate.research_acceptance` to Arena series aggregates.
- Generation summaries now carry research acceptance status, reasons, required sections, strict parent allowance, and acceptance-lock fields.
- Series aggregates now count observed, accepted, rejected, and strict-parent-allowed research acceptance reports.
- Series aggregates now count research acceptance statuses, acceptance-lock statuses, lock blocking sections, and required-section status pairs.
- Did not change default PBT parent selection, strict gate decisions, reward behavior, execution behavior, account behavior, runtime behavior, hidden evaluation, exploit checks, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_research_acceptance_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_strict_parent_gate_diagnostics`
- Direct research acceptance summary assertion passed with `ARENA_SERIES_RESEARCH_ACCEPTANCE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now expose research acceptance state directly, rather than requiring readers to infer it from strict gate diagnostics.
- Positive: the new summary and aggregate fields reuse existing report metadata and do not affect training behavior.
- Risk: research acceptance remains incomplete because hidden-world and paired-world checks remain unavailable until documented inputs and runners exist.

### next actions

- Use `aggregate.research_acceptance.lock_blocking_section_counts` in future report readers.
- Continue implementing only documented hidden/exploit prerequisites.

## Task 2026-05-03-model-training-40

### status

done

### goal

Aggregate strict PBT parent gate diagnostics across Arena multi-generation series reports without changing PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/arena-series-strict-gate-summary.md`
- `docs/tasks/model-training/arena-series-strict-gate-aggregate.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-strict-gate-aggregate.md`.
- Added `aggregate.strict_parent_gate` to Arena series reports.
- Added strict gate observed, enabled, passed, blocked, and disabled counters.
- Added aggregate `blocking_reason_counts`.
- Added aggregate `lock_blocking_section_counts`.
- Preserved existing aggregate totals for transitions, execution health, checkpoints, lineage, applied agents, winners, losers, and final models.
- Did not change default PBT parent selection, strict gate decisions, reward behavior, execution behavior, account behavior, runtime behavior, hidden evaluation, exploit checks, or checkpoint promotion.

### verification

- Targeted pytest passed:
  - `tests/runtime/test_arena_experiment_runner.py::test_series_aggregate_counts_strict_parent_gate_diagnostics`
  - `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`
- Direct series aggregate assertion passed with `ARENA_SERIES_STRICT_GATE_AGGREGATE_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports now show recurring strict-gate blockers without requiring readers to inspect every generation.
- Positive: the new aggregate fields reuse existing diagnostics and do not affect training behavior.
- Risk: aggregate diagnostics are explanatory only; hidden-world and paired-world checks remain unavailable until documented inputs and runners exist.

### next actions

- Use `aggregate.strict_parent_gate.blocking_reason_counts` in future report readers.
- Continue implementing only documented hidden/exploit prerequisites.

## Task 2026-05-03-model-training-39

### status

done

### goal

Expose strict PBT parent gate diagnostics in Arena multi-generation summaries without changing PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/strict-parent-gate-diagnostics.md`
- `docs/tasks/model-training/arena-series-strict-gate-summary.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/arena-series-strict-gate-summary.md`.
- Added `pbt.strict_parent_gate` to Arena generation summaries.
- The summary now carries strict gate `enabled`, `passes`, `reason`, and `blocking_reasons`.
- The summary now carries acceptance lock status, blocking sections, and reason.
- Existing generation summary PBT fields and counts remain unchanged.
- Did not change default PBT parent selection, strict gate decisions, reward behavior, execution behavior, account behavior, runtime behavior, hidden evaluation, exploit checks, or checkpoint promotion.

### verification

- Targeted pytest passed: `tests/runtime/test_arena_experiment_runner.py::test_generation_summary_includes_strict_parent_gate_diagnostics`.
- Direct generation summary assertion passed with `ARENA_SERIES_STRICT_GATE_SUMMARY_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.

### impact / risk

- Positive: multi-generation reports can now show why strict parent eligibility was blocked without requiring readers to open each full episode report.
- Positive: the new summary fields reuse existing gate diagnostics and do not affect training behavior.
- Risk: diagnostics are still explanatory only; hidden-world and paired-world checks remain unavailable until documented inputs and runners exist.

### next actions

- Keep using summary-level `pbt.strict_parent_gate.blocking_reasons` in future report readers.
- Continue implementing only documented hidden/exploit prerequisites.

## Task 2026-05-03-model-training-38

### status

done

### goal

Add strict PBT parent gate diagnostics so blocked strict eligibility reports explain the exact machine-readable reasons.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`
- `docs/tasks/model-training/strict-parent-gate-diagnostics.md`
- `app/services/model_population_service.py`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `docs/tasks/model-training/strict-parent-gate-diagnostics.md`.
- Added `strict_parent_gate.blocking_reasons`.
- Added `strict_parent_gate.reason`.
- Preserved `strict_parent_gate.passes` behavior.
- Preserved default `strict_parent_eligibility=false` behavior.
- Did not change default PBT parent selection, reward behavior, execution behavior, account behavior, runtime behavior, hidden evaluation, exploit checks, or checkpoint promotion.

### verification

- Direct strict parent gate diagnostic assertion passed with `STRICT_PARENT_GATE_DIAGNOSTIC_ASSERTIONS_OK`.
- `app/services/model_population_service.py` and `tests/runtime/test_pbt_lineage.py` passed `py_compile`.
- Targeted pytest for the two strict-gate tests is blocked because bundled Python 3.12 cannot load NumPy C extensions from the project `.venv`.

### impact / risk

- Positive: strict gate reports now state why eligibility is blocked without requiring callers to infer across acceptance, lock, and required-section fields.
- Positive: default PBT behavior still does not change.
- Risk: diagnostics are report-side only; hidden-world and paired-world checks remain unavailable until their inputs and runners are documented.

### next actions

- Use `blocking_reasons` in future reporting surfaces.
- Keep strict parent eligibility opt-in and blocked until hidden evaluation and exploit detector outputs can become complete.

## Task 2026-05-03-model-training-37

### status

done

### goal

Connect the Arena `research_acceptance.acceptance_lock` report field to the existing strict PBT parent eligibility opt-in gate.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`
- `app/services/model_population_service.py`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `docs/tasks/model-training/strict-parent-acceptance-lock-gate.md`.
- Strict parent eligibility now reads `research_acceptance.acceptance_lock`.
- Strict parent eligibility requires `acceptance_lock.status=open`.
- Strict parent eligibility rejects non-empty `acceptance_lock.blocking_sections`.
- Strict parent eligibility requires `research_acceptance.strict_parent_eligibility_allowed=true`.
- Strict parent gate output now exposes lock status, blocking sections, reason, and strict eligibility allowance.
- Default `strict_parent_eligibility=false` behavior remains unchanged.
- Did not change default PBT parent selection, reward behavior, execution behavior, account behavior, runtime behavior, hidden evaluation, exploit checks, or checkpoint promotion.

### verification

- Direct strict parent acceptance-lock assertion passed with `STRICT_PARENT_ACCEPTANCE_LOCK_ASSERTIONS_OK`.
- `app/services/model_population_service.py` and `tests/runtime/test_pbt_lineage.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: strict PBT parent eligibility can no longer pass by only marking required sections as `complete` while the acceptance lock remains locked.
- Positive: strict gate output now tells callers exactly which lock fields are blocking parent eligibility.
- Risk: the lock remains conservative because hidden-world and paired-world checks are still unavailable by project-document design.

### next actions

- Keep Arena reports setting `strict_parent_eligibility_allowed=false` until hidden evaluation and exploit detector are complete.
- Continue implementing only documented hidden/exploit prerequisites.

## Task 2026-05-03-model-training-36

### status

done

### goal

Add a machine-readable research acceptance lock so incomplete report sections cannot be mistaken for research acceptance or strict PBT parent eligibility.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/research-acceptance-lock-report.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `research_acceptance.acceptance_lock` to Arena report metadata.
- The lock records required sections:
  - `baseline_suite`
  - `hidden_evaluation`
  - `exploit_detector`
- The lock records `blocking_sections` for any required section that is not `complete`.
- The lock reports `status=locked` while blocking sections exist.
- Added `research_acceptance.strict_parent_eligibility_allowed=false`.
- Preserved `research_acceptance.status=incomplete`.
- Preserved `research_acceptance.is_research_accepted=false`.
- Preserved strict parent eligibility as opt-in only.
- Did not change default PBT parent selection, reward behavior, execution behavior, account behavior, runtime behavior, or checkpoint promotion.

### verification

- Direct research acceptance lock assertion passed with `RESEARCH_ACCEPTANCE_LOCK_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: Arena reports now expose a clear lock between incomplete hidden/exploit evidence and strict parent eligibility.
- Positive: downstream code can read `acceptance_lock.blocking_sections` instead of inferring from free-text reasons.
- Risk: the lock is still a report-side guard; hidden-world and paired-world checks remain unavailable until their inputs and runners are documented.

### next actions

- Keep strict parent eligibility opt-in until `baseline_suite`, `hidden_evaluation`, and `exploit_detector` are all `complete`.
- Implement hidden-world or paired-world checks only after the required inputs are defined in project documents.

## Task 2026-05-03-model-training-35

### status

done

### goal

Replace pure hidden evaluation placeholders with explicit `not_available` report slots and required inputs, without inventing a hidden-world runner.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `docs/tasks/model-training/hidden-evaluation-report-slots.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/hidden-evaluation-report-slots.md`.
- Changed `hidden_evaluation.status` from `not_implemented` to `not_available`.
- Added `hidden_evaluation.reason=hidden_world_runner_not_implemented`.
- Preserved hidden split required inputs:
  - unseen seed
  - unseen retail mix
  - altered fees
  - altered liquidity depth
  - altered tick/spread regime
- Changed `frozen_policy_hidden_seed` to explicit `not_available`.
- Changed `cross_world_transfer` to explicit `not_available`.
- Added required inputs for `frozen_policy_hidden_seed`.
- Added required inputs for `cross_world_transfer`.
- Research acceptance remains incomplete.
- Strict parent eligibility opt-in behavior remains unchanged.
- Reward behavior, execution behavior, account behavior, runtime behavior, and PBT behavior remain unchanged.

### verification

- Direct hidden evaluation slot assertion passed with `HIDDEN_EVALUATION_NOT_AVAILABLE_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: hidden evaluation now states exactly why it is unavailable and what inputs are required.
- Positive: strict parent eligibility still cannot pass because hidden evaluation is not complete.
- Risk: no hidden-world runner, hidden seed execution, or paired transfer evaluation exists yet.

### next actions

- Implement hidden-world runner only after project documents define world-pool and hidden seed inputs.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-34

### status

done

### goal

Replace pure `fee_sensitivity` and `impact_sensitivity` placeholders with explicit `not_available` report slots and required inputs, without inventing altered fee or impact worlds.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/order-anomaly-audit-report-check.md`
- `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/fee-impact-sensitivity-report-slots.md`.
- Added `fee_sensitivity` report slot to Arena episode details and `exploit_detector.checks`.
- Added `impact_sensitivity` report slot to Arena episode details and `exploit_detector.checks`.
- Both slots report `status=not_available`.
- `fee_sensitivity.reason=fee_variant_worlds_not_implemented`.
- `impact_sensitivity.reason=liquidity_depth_variant_worlds_not_implemented`.
- Added required inputs for future fee sensitivity:
  - base and altered fee model
  - same policy result
  - same seed/world hash
  - base and altered net reward after fees
  - base and altered fill/turnover metrics
- Added required inputs for future impact sensitivity:
  - base and altered liquidity depth or impact model
  - same policy result
  - same seed/world hash
  - base and altered slippage/fill-price metrics
  - base and altered fill/turnover metrics
- Research acceptance remains incomplete.
- Reward behavior, execution behavior, account behavior, runtime behavior, and PBT behavior remain unchanged.

### verification

- Direct fee/impact sensitivity slot assertion passed with `FEE_IMPACT_SENSITIVITY_SLOT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: fee and impact sensitivity are no longer invisible placeholders; reports now state exactly why they are unavailable and what inputs are required.
- Positive: future paired-world implementation has a stable report contract.
- Risk: no altered fee world, altered liquidity world, or impact replay exists yet.

### next actions

- Implement paired-world fee sensitivity only after the project has a documented altered-fee world runner.
- Implement paired-world impact sensitivity only after the project has documented liquidity-depth or impact-model variant inputs.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-33

### status

done

### goal

Promote `order_anomaly_audit` from placeholder to a minimal report-side execution-health consistency check using persisted transition execution payloads and episode result metrics.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/mark-to-market-audit-report-check.md`
- `docs/tasks/model-training/order-anomaly-audit-report-check.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/order-anomaly-audit-report-check.md`.
- Added `order_anomaly_audit` to Arena episode details.
- The audit reads persisted `ModelTransition.execution_json` rows.
- The audit recomputes minimal execution-health metrics:
  - submitted order count
  - filled order count
  - open order count
  - rejected order count
  - trade count
  - submitted notional
  - filled notional
  - open order notional
- The audit flags malformed or impossible execution payloads:
  - execution is not an object
  - `orders` is not a list
  - `trades` is not a list
  - order is not an object
  - negative order qty or price
  - negative filled qty
  - negative trade qty or price
  - filled/open/rejected counts exceed submitted order count
- The audit compares recomputed metrics with episode result `execution_health` when result rows exist for the agent.
- `order_anomaly_audit` is now included in `exploit_detector.checks`.
- `exploit_detector.status` becomes `failed` when this audit fails.
- Research acceptance remains incomplete.
- Order execution, matching, account state, reward behavior, runtime behavior, and PBT behavior remain unchanged.

### verification

- Direct order anomaly audit assertion passed with `ORDER_ANOMALY_AUDIT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: `order_anomaly_audit` is now a visible report-side check instead of a placeholder.
- Positive: exploit detector reports can fail when persisted execution payloads or execution-health aggregates are internally inconsistent.
- Risk: this is not a matching-engine replay or churn-threshold detector; deeper lifecycle and rate checks remain pending.

### next actions

- Add fee and impact sensitivity report checks next.
- Add churn-rate thresholds only after project documents define safe limits.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-32

### status

done

### goal

Promote `mark_to_market_audit` from placeholder to a minimal report-side accounting consistency check using existing episode result and transition reward data.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/timestamp-audit-report-check.md`
- `docs/tasks/model-training/mark-to-market-audit-report-check.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/mark-to-market-audit-report-check.md`.
- Added `mark_to_market_audit` to Arena episode details.
- The audit reads existing episode result rows.
- The audit optionally reads persisted transition `reward_json` rows.
- The audit checks:
  - `equity_start` exists and is positive.
  - `equity_end` exists.
  - `reward_total` exists.
  - `fee_total` exists and is non-negative.
  - `max_drawdown` is non-negative.
  - `equity_return` matches `(equity_end - equity_start) / equity_start`.
  - `score` matches `equity_return + reward_total - max_drawdown`.
  - `reward_total` matches summed transition `step_reward` when transition rewards exist for the agent.
- `mark_to_market_audit` is now included in `exploit_detector.checks`.
- `exploit_detector.status` becomes `failed` when this audit fails.
- Research acceptance remains incomplete.
- Reward behavior, execution behavior, account behavior, runtime valuation, and PBT behavior remain unchanged.

### verification

- Direct mark-to-market audit assertion passed with `MARK_TO_MARKET_AUDIT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: `mark_to_market_audit` is now a visible report-side check instead of a placeholder.
- Positive: exploit detector reports can fail when episode result accounting is internally inconsistent.
- Risk: this is not a full independent valuation replay; account ledger reconstruction and raw-position mark-to-market remain pending.

### next actions

- Add order anomaly audit as the next report-side exploit detector check.
- Add deeper account ledger reconstruction only if project documents define the required ledger inputs.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-31

### status

done

### goal

Promote `timestamp_audit` from placeholder to a minimal report-side exploit detector check using persisted `ModelTransition.step_index` ordering.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/runtime-observation-audit-report.md`
- `docs/tasks/model-training/timestamp-audit-report-check.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/timestamp-audit-report-check.md`.
- Added `timestamp_audit` to Arena episode details.
- The audit reads existing persisted `ModelTransition` rows.
- The audit groups transitions by `agent_id` and checks persisted transition order by transition id.
- The audit flags:
  - non-integer `step_index`
  - negative `step_index`
  - duplicate `step_index`
  - regressed `step_index`
- `timestamp_audit` is now included in `exploit_detector.checks`.
- `exploit_detector.status` remains non-complete:
  - `partial` when timestamp audit is available or not available while other exploit checks remain placeholders.
  - `failed` when timestamp audit fails.
- Research acceptance remains incomplete.
- Reward behavior, execution behavior, account behavior, runtime observation generation, and PBT behavior remain unchanged.

### verification

- Direct timestamp audit assertion passed with `TIMESTAMP_AUDIT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` and `tests/runtime/test_arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: `timestamp_audit` is now a visible report-side check instead of a placeholder.
- Positive: exploit detector reports can fail when persisted transition ordering is obviously invalid.
- Risk: this is not a full market-data timestamp causality proof; bar-window and recent-trade semantic checks remain pending.

### next actions

- Add semantic timestamp checks for bars and recent trades.
- Add mark-to-market audit as the next report-side exploit detector check.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-30

### status

done

### goal

Add a report-side runtime observation audit over persisted `ModelTransition.observation_json` rows so no-signal reports can use actual persisted `obs.v1` transition data when available.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/no-signal-payload-observation-audit.md`
- `docs/tasks/model-training/runtime-observation-audit-report.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/runtime-observation-audit-report.md`.
- Added `runtime_observation_audit` to Arena episode details.
- The audit reads existing persisted `ModelTransition.observation_json` rows.
- The audit checks:
  - observation is an object
  - `contract_version == obs.v1`
  - required top-level sections exist: `market`, `account`, `context`, `features`
  - required sections are objects
  - no unexpected top-level keys outside the `obs.v1` structure
  - no field paths matching Alpha-to-Execution disallowed input classes
- Derived `alpha_to_execution.no_signal.v1` payloads now use runtime observation audit status as `observation_audit_status` when available.
- `no_signal_world` reports can include the linked `runtime_observation_audit`.
- Normal `alpha_to_execution.v1` reports, reward behavior, execution behavior, account behavior, PBT behavior, and research acceptance remain unchanged.

### verification

- Direct runtime observation audit assertion passed with `RUNTIME_OBSERVATION_AUDIT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the project now audits actual persisted runtime observations when transition rows exist, instead of relying only on derived payload fields.
- Positive: no-signal report checks can consume this audit without changing training or execution behavior.
- Risk: this remains a structural/path audit; deeper timestamp causality and semantic future-data checks remain pending.

### next actions

- Add deeper semantic checks for time-valid bars and recent trade windows.
- Add timestamp audit as a separate exploit detector check.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-29

### status

done

### goal

Add a minimal no-signal payload observation audit so derived `alpha_to_execution.no_signal.v1` reports no longer need manual `no_signal_observation_audit_status` for the alpha contract shape.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/no-signal-episode-payload-derivation.md`
- `docs/tasks/model-training/no-signal-payload-observation-audit.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/no-signal-payload-observation-audit.md`.
- Added a payload-level no-signal observation audit in `ArenaExperimentRunner` reports.
- The audit checks only no-signal alpha contract fields:
  - `alpha_signal_source == no_signal`
  - `direction == 0.0`
  - `confidence == 0.0`
  - `target_weight_hint == null`
- `no_signal_world` now includes an `observation_audit` object with status, reason, scope, missing fields, and violations.
- If `observation_audit_status` is absent, it is derived from the payload audit.
- Derived `alpha_to_execution.no_signal.v1` payloads can now pass the no-signal check without manually setting `no_signal_observation_audit_status`.
- Manual `observation_audit_status` is still accepted when supplied.
- Normal `alpha_to_execution.v1` reports, reward behavior, execution behavior, account behavior, PBT behavior, and research acceptance remain unchanged.

### verification

- Direct payload-audit assertion passed with `NO_SIGNAL_PAYLOAD_AUDIT_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the no-signal derived report path now has a traceable audit object instead of relying only on manual status.
- Positive: the audit scope is explicit and narrow, reducing the chance it is mistaken for full hidden/exploit evaluation.
- Risk: this is not yet a full runtime observation audit across real `obs.v1` decision payloads.

### next actions

- Add a real runtime observation audit that checks actual `obs.v1` payloads against allowed/disallowed fields.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-28

### status

done

### goal

Add a minimal report-side derivation harness so `alpha_to_execution.no_signal.v1` episode results can produce a `no_signal_check` payload without changing Arena runtime behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/no-signal-world-report-check.md`
- `docs/tasks/model-training/no-signal-episode-payload-derivation.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/no-signal-episode-payload-derivation.md`.
- Added `ArenaExperimentConfig.no_signal_tolerance`.
- Added `ArenaExperimentConfig.no_signal_fee_model`.
- Added `ArenaExperimentConfig.no_signal_observation_audit_status`.
- Added report-side payload derivation for `alpha_to_execution.no_signal.v1` when manual `no_signal_check` is absent and episode results contain a candidate row.
- Derived payload includes:
  - fixed no-signal alpha contract fields
  - configured tolerance
  - configured fee model or current reward profile
  - episode/config id as `world_seed_or_hash`
  - candidate `reward_total - fee_total`
  - candidate score excess versus `no_trade_cash` when available
  - optional observation audit status
  - source and candidate identity for traceability
- Manual `no_signal_check` still takes precedence.
- Normal `alpha_to_execution.v1` reports still keep the previous placeholder unless explicit input is supplied.
- Research acceptance remains incomplete.

### verification

- Direct no-signal derivation assertion passed with `NO_SIGNAL_DERIVED_PAYLOAD_ASSERTIONS_OK`.
- `app/services/arena_experiment_runner.py` passed `py_compile`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the no-signal report check no longer has to be supplied entirely by hand for explicitly marked no-signal episodes.
- Positive: reports now preserve which candidate row produced the derived no-signal payload.
- Risk: this is still a report derivation harness, not a full controlled no-signal world generator or observation audit.

### next actions

- Add a real observation audit result instead of manually setting `no_signal_observation_audit_status`.
- Add controlled no-signal run setup that guarantees observations are no-signal at decision time.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-27

### status

done

### goal

Implement the first minimal `no_signal_world` exploit detector report check while keeping normal Arena behavior, reward behavior, and PBT behavior unchanged.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `docs/tasks/model-training/no-signal-world-report-check.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/no-signal-world-report-check.md`.
- Added `ArenaExperimentConfig.no_signal_check`, defaulting to `None`.
- Preserved default `exploit_detector.no_signal_world` placeholder output when no explicit check input is supplied.
- Added explicit-input report execution for `no_signal_world`:
  - `pass` when no-signal contract inputs and metrics remain within tolerance.
  - `fail` when alpha contract fields, audit status, or no-signal metrics violate the rule.
  - `warn` when inputs are incomplete but no supplied value fails the rule.
- Kept `exploit_detector.status` non-complete:
  - `partial` when only no-signal check runs successfully.
  - `failed` when no-signal check fails.
- Kept `research_acceptance.is_research_accepted=false`.
- Did not implement no-signal world generation, reward changes, hidden evaluation, or strict PBT default enforcement.

### verification

- Direct no-signal report-check assertion passed with `NO_SIGNAL_WORLD_REPORT_CHECK_ASSERTIONS_OK`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the first exploit-detector check now has real machine-readable pass/fail/warn output when explicit inputs are available.
- Positive: default Arena reports stay compatible with the earlier placeholder contract.
- Risk: the check still depends on a supplied payload; it is not yet produced by an actual controlled no-signal world run.

### next actions

- Add a minimal no-signal run harness that can produce the `no_signal_check` payload from controlled execution.
- Keep strict parent eligibility opt-in until hidden evaluation and exploit detector sections can both become complete.

## Task 2026-05-03-model-training-26

### status

done

### goal

Document the controlled no-signal scenario required before implementing the first real `no_signal_world` exploit check.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/controlled-no-signal-scenario.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/controlled-no-signal-scenario.md`.
- Defined scenario id `alpha_to_execution.no_signal.v1`.
- Documented the required `alpha_signal` shape:
  - `source=no_signal`
  - `direction=0.0`
  - `confidence=0.0`
  - `target_weight_hint=null`
- Documented disallowed future, GUI, hidden-label, post-decision, and persistence-only fields.
- Added required input fields to the `exploit_detector.no_signal_world` placeholder:
  - alpha signal source
  - direction
  - confidence
  - target weight hint
  - no-signal tolerance
  - fee model
  - world seed/hash
  - observation audit status
- Left no-signal world execution, reward-leak statistics, runtime behavior, reward behavior, and PBT behavior unchanged.

### verification

- Direct no-signal placeholder assertion passed with `NO_SIGNAL_SCENARIO_ASSERTIONS_OK`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the first real exploit check now has a documented input contract.
- Positive: future implementation can distinguish a no-signal scenario from arbitrary zero-return assumptions.
- Risk: no real no-signal world has run yet; this remains a docs/report-contract step.

### next actions

- Implement `no_signal_world` as the first real exploit detector check once a minimal no-signal run harness is available.
- Keep strict parent eligibility opt-in until the check produces real pass/fail output.

## Task 2026-05-03-model-training-25

### status

done

### goal

Add strict PBT parent eligibility as an opt-in gate that reads research-acceptance sections without changing default PBT behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`
- `app/services/model_population_service.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `docs/tasks/model-training/strict-parent-eligibility-opt-in.md`.
- Added `PopulationEvolutionConfig.strict_parent_eligibility`, defaulting to `False`.
- Added `PopulationEvolutionConfig.research_acceptance` so strict mode can read `research_acceptance.required_sections`.
- Strict mode requires:
  - `research_acceptance.is_research_accepted=True`
  - `baseline_suite=complete`
  - `hidden_evaluation=complete`
  - `exploit_detector=complete`
- Current placeholder reports therefore reject all parents only when strict mode is explicitly enabled.
- Default PBT parent eligibility remains unchanged.
- `ArenaExperimentConfig.pbt_strict_parent_eligibility` defaults to `False` and passes the episode research-acceptance section into the population service only for gate evaluation.

### verification

- Direct strict-gate assertion passed with `STRICT_PARENT_GATE_ASSERTIONS_OK`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: the project now has the strict parent-gate structure requested by the expert review without prematurely changing default behavior.
- Positive: once real hidden/exploit checks exist, the strict gate already has a place to consume them.
- Risk: strict mode is intentionally unusable for acceptance while hidden/exploit sections are placeholders.

### next actions

- Document controlled `no_signal` scenario support before implementing the first real exploit check.
- Then implement `no_signal_world` as the first exploit detector check.

## Task 2026-05-03-model-training-24

### status

done

### goal

Add hidden evaluation and exploit detector placeholder structures to Arena reports so research acceptance can reference machine-readable sections before real checks exist.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/hidden-evaluation-exploit-placeholders.md`.
- Added `hidden_evaluation` report section with `status=not_implemented`, required hidden-input fields, and placeholder checks for frozen-policy hidden seed and cross-world transfer.
- Added `exploit_detector` report section with placeholder checks for no-signal world, fee sensitivity, impact sensitivity, timestamp audit, mark-to-market audit, and order anomaly audit.
- Updated `research_acceptance.required_sections` so it records baseline, hidden evaluation, and exploit detector status.
- Left runtime behavior, reward behavior, hidden-world execution, exploit execution, and PBT parent selection unchanged.

### verification

- Direct report-structure assertion passed with `HIDDEN_EXPLOIT_PLACEHOLDER_ASSERTIONS_OK`.
- Full pytest remains blocked by the same sandbox interpreter/temp-directory issue recorded in Task 23.

### impact / risk

- Positive: Arena reports now have the shape needed for future hidden evaluation and exploit checks.
- Positive: `research_acceptance` reasons are no longer only free-form strings; they reference required sections.
- Risk: the checks are placeholders only; no hidden worlds, no-signal runs, audit logic, or strict parent gating has executed yet.

### next actions

- Add strict PBT parent eligibility as an opt-in/disabled mode that reads these report sections without changing default behavior.
- Then implement the first real exploit check, likely `no_signal_world`, once controlled alpha/no-signal scenario support is documented.

## Task 2026-05-03-model-training-23

### status

done

### goal

Add TWAP/VWAP optional report slots as explicit `not_available` entries before implementing execution schedules or reward benchmark wiring.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/twap-vwap-report-slots.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/twap-vwap-report-slots.md`.
- Extended Arena `baseline_suite.optional` entries for `twap` and `vwap`.
- Each optional slot now reports:
  - `status=not_available`
  - `reason=schedule_execution_not_implemented`
  - required inputs: arrival price, target quantity/notional, horizon, realized fill price, benchmark fill price
- Left TWAP/VWAP schedule execution, reward benchmark wiring, runtime behavior, and PBT behavior unchanged.

### verification

- Direct report-structure assertion passed with `REPORT_SLOT_ASSERTIONS_OK`.
- Full `pytest tests/runtime/test_arena_experiment_runner.py` could not complete in this sandbox because:
  - project `.venv` launcher points at unavailable `C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe`
  - fallback pytest using bundled Python plus venv site-packages hit temporary-directory permission errors
- The change is limited to report slot construction and a matching test assertion.

### impact / risk

- Positive: reports no longer merely omit TWAP/VWAP; they explicitly say the slots are not available and what inputs are needed.
- Positive: future schedule execution can be implemented against a documented report contract.
- Risk: TWAP/VWAP execution itself, hidden evaluation, exploit detector, benchmark-return reward wiring, and strict PBT parent eligibility remain pending.

### next actions

- Add hidden evaluation and exploit detector placeholder structures.
- Then tighten strict PBT parent eligibility only after those outputs exist.

## Task 2026-05-03-model-training-22

### status

done

### goal

Implement the required deterministic target-weight naive rebalance baseline using the existing `act.v1 target_weight` runtime path.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `docs/tasks/model-training/target-weight-naive-rebalance-baseline.md`
- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_model_registry_external.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/target-weight-naive-rebalance-baseline.md`.
- Added `TargetWeightNaiveRebalanceModel` as `target_weight_naive_rebalance_v1`.
- The baseline emits deterministic long-only equal weights over `obs.v1.context.symbol_universe`.
- The action remains `act.v1 target_weight` and therefore still goes through `ActionParser`, `ModelBridge`, order service, account/risk/matching truth, and existing runtime semantics.
- Added the baseline to default `ArenaExperimentConfig.model_specs`.
- Added the baseline to default PBT exclusions.
- Updated Arena report expectations so the required baseline suite can become complete when no-trade, random-constrained, and target-weight naive rebalance rows are present.

### verification

- `.venv\\Scripts\\python.exe -m pytest tests/runtime/test_arena_experiment_runner.py tests/runtime/test_model_registry_external.py -q`
- Result: `20 passed`.

### impact / risk

- Positive: Alpha-to-Execution reports now have the three required initial baseline kinds available by default.
- Positive: PPO/LSTM candidate results can be compared against a deterministic target-weight executor, not only hold/random rows.
- Positive: baseline agents remain excluded from default PBT parent selection.
- Risk: TWAP/VWAP report slots, hidden evaluation, exploit detector, benchmark-return reward wiring, and strict PBT parent eligibility remain pending.

### next actions

- Add TWAP/VWAP report slots as `not_available` with required input fields documented.
- Add hidden evaluation and exploit detector placeholder structures.
- Tighten strict PBT parent eligibility only after those outputs exist.

## Task 2026-05-03-model-training-21

### status

done

### goal

Add the Arena report structure requested after the baseline inventory so existing baseline rows are visible before changing `ppo_lstm_v1` behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `docs/tasks/model-training/arena-report-research-acceptance-plan.md`
- `app/services/arena_experiment_runner.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `docs/code-index.md`

### change summary

- Added `docs/tasks/model-training/arena-report-research-acceptance-plan.md`.
- Added report labels for existing baselines:
  - `hold_model_v1` -> `baseline_kind=no_trade_cash`
  - `random_weight_v1` -> `baseline_kind=random_constrained`
- Added `result_role` and `baseline_kind` to Arena episode result rows.
- Added `baseline_suite`, `benchmark_comparison`, and `research_acceptance` sections to Arena episode reports.
- Kept `research_acceptance.status=incomplete` until missing required baselines, hidden evaluation, and exploit detector work is implemented.
- Left model actions, reward calculation, runtime matching, and PBT behavior unchanged.

### verification

- `.venv\\Scripts\\python.exe -m pytest tests/runtime/test_arena_experiment_runner.py -q`
- Result: `9 passed`.

### impact / risk

- Positive: Arena reports now separate baseline rows from trainable candidate rows.
- Positive: PPO/LSTM results can be read relative to existing no-trade and random-constrained baselines.
- Positive: the report now explicitly says research acceptance is incomplete instead of implying leaderboard rank is enough.
- Risk: `target_weight_naive_rebalance`, TWAP/VWAP, hidden evaluation, exploit detector, and strict parent eligibility remain pending.

### next actions

- Add the deterministic `target_weight_naive_rebalance_v1` baseline through the existing `act.v1 target_weight` runtime path.
- Add TWAP/VWAP report slots as `not_available` until schedule logic exists.
- Add hidden evaluation and exploit detector placeholders, then tighten strict PBT parent eligibility.

## Task 2026-05-03-model-training-20

### status

done

### goal

Inventory existing baseline support before changing `ppo_lstm_v1` or adding Alpha-to-Execution runtime behavior.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`
- `app/services/model_registry_service.py`
- `app/services/arena_experiment_runner.py`
- `rl/reward_builder.py`
- `tests/runtime/test_arena_experiment_runner.py`

### change summary

- Added `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`.
- Recorded existing baseline-like assets:
  - `hold_model_v1`
  - `random_weight_v1`
  - default PPO/LSTM candidate population
  - default PBT exclusion for hold/random baselines
  - execution-health metrics in Arena reports
  - `RewardBuilder` benchmark hook
- Recorded missing or partial pieces:
  - explicit no-trade/cash report row
  - explicit random constrained report row
  - target-weight naive rebalance baseline
  - TWAP/VWAP baseline report slots
  - baseline comparison section in Arena reports
  - baseline-relative strict parent gate
- Defined a safe implementation order that starts with labels/report semantics before adding new baseline logic.

### verification

- Document-only update.
- Baseline inventory was checked against existing project files with text search and targeted reads.

### impact / risk

- Positive: baseline work now has a concrete inventory and order of operations.
- Positive: the project can avoid changing PPO/LSTM before it knows what baseline comparison must report.
- Risk: no report code was changed yet; baseline comparison remains pending.

### next actions

- Document the Arena report structure for `baseline_suite`, `benchmark_comparison`, and `research_acceptance`.
- Then add report labels for existing `hold_model_v1` and `random_weight_v1`.

## Task 2026-05-03-model-training-19

### status

done

### goal

Create the first concrete Alpha-to-Execution task card requested by the expert-review P0 breakdown.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`
- `docs/tasks/model-training/alpha-to-execution-task-card.md`
- `docs/contracts/runtime/model-observation-contract.md`
- `docs/contracts/runtime/model-action-contract.md`
- `docs/contracts/runtime/model-reward-contract.md`

### change summary

- Added `docs/tasks/model-training/alpha-to-execution-task-card.md`.
- Defined the task as `alpha_to_execution.v1`.
- Mapped the task to existing `obs.v1`, `act.v1`, and `rew.v1` instead of adding a new model family.
- Documented controlled alpha input rules, allowed/disallowed observation fields, target-weight and order-intent action paths, execution-aware reward requirements, required baselines, failure conditions, and acceptance criteria.
- Added a first implementation checklist that starts with baseline inventory, no-signal checks, report placeholders, and stricter PBT parent eligibility.

### verification

- Document-only update.
- The task card uses only existing project documents and contracts as source material.

### impact / risk

- Positive: the expert review's recommendation to split alpha from execution now has a concrete project task card.
- Positive: future code work has a narrower acceptance target and can avoid claiming synthetic Arena alpha.
- Risk: no runtime/report code was changed yet; baseline report slots, no-signal scenario support, hidden evaluation, and stricter PBT eligibility remain pending.

### next actions

- Inventory current baseline support against the required Alpha-to-Execution baselines.
- Add report fields for benchmark comparison before changing `ppo_lstm_v1`.
- Add hidden evaluation and exploit detector placeholders to Arena experiment reports.

## Task 2026-05-03-model-training-18

### status

done

### goal

Turn the expert review document `UTI-STOCKSIM_专家评审与落地设计.docx` into a concrete next-step task breakdown without adding a new model family or undocumented platform scope.

### files involved

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `README.md`
- `docs/design/model-training-design.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/tasks/model-training/expert-review-p0-task-breakdown.md`

### change summary

- Added a new task breakdown under `docs/tasks/model-training/` following the docs organization rules.
- Split the expert review's near-term P0/P1 recommendations into smaller work packages:
  - Alpha-to-Execution task boundary
  - baseline suite
  - calibration harness and world pool
  - hidden evaluation and exploit detector
  - experiment record completeness
- Kept the document aligned with the existing completed Arena/PPO/PBT/multi-generation work and the review's warning not to treat synthetic Arena profit as real-market alpha.

### verification

- Document-only update.
- The new task document was derived from project-local documents and the expert review docx.

### impact / risk

- Positive: the next model-training work is now framed around falsifiability, calibration, baselines, and anti-exploit evaluation instead of adding model complexity.
- Positive: the task document gives a safe implementation order for future code work.
- Risk: no code was changed in this task; implementation of Alpha-to-Execution, calibration reports, baselines, and hidden evaluation remains pending.

### next actions

- Create the Alpha-to-Execution task card and map it to current `obs.v1`, `act.v1`, and `rew.v1`.
- Inventory existing baseline support before adding new baseline code.
- Add world/calibration metadata and hidden evaluation fields to Arena experiment reports.

## Task 2026-04-26-model-training-01

### status

done

### goal

Start implementing the first work packages from `docs/design/model-training-design.md` and `docs/plan/multi-agent-training-roadmap.md`: make Model a visible first-class agent type and land the first contract-level closed-loop pieces.

### files involved

- `app/core_dto/agent.py`
- `app/services/agent_service.py`
- `app/services/model_registry_service.py`
- `app/services/runtime_model_agent.py`
- `app/controllers/agent_controller.py`
- `app/panels/agents/panel.py`
- `app/ui/adapters/agents_adapter.py`
- `rl/contracts.py`
- `rl/action_parser.py`
- `rl/observation_builder.py`
- `rl/model_bridge.py`
- `rl/reward_builder.py`
- `docs/contracts/runtime/model-reward-contract.md`
- `tests/frontend/unit/test_agents_model_view.py`
- `tests/runtime/test_model_action_target_weight.py`
- `tests/runtime/test_reward_builder.py`

### change summary

- Added model-oriented fields to `AgentMetaDTO`: `model_id`, `mode`, `episode_id`, `last_reward`, `equity`, `pnl`, and `last_action`.
- Added `AgentService.create_model_agent(...)` and controller support so the platform can create Model agents as first-class metadata objects.
- Added a small `ModelRegistryService` with `HoldModel` and `RandomWeightModel` placeholders.
- Added `RuntimeModelAgent`, a minimal service-layer lifecycle wrapper for observation -> action -> execution -> reward.
- Updated the Agent panel view to expose `All / Retail / Model` filtering and model-compatible columns.
- Extended `obs.v1` builder with a multi-symbol `build_many(...)` path while preserving the old single-symbol shape.
- Extended `act.v1` parsing to support `target_weight` and `target_position`.
- Implemented first target-weight translation in `ModelBridge`, converting model portfolio intent into runtime orders.
- Added `rew.v1` through `RewardBuilder`.

### verification

- `tests/frontend/unit/test_agents_model_view.py`
- `tests/runtime/test_model_action_target_weight.py`
- `tests/runtime/test_reward_builder.py`
- `tests/test_model_bridge.py`
- `tests/frontend/unit/test_agents_panel.py`
- `tests/frontend/unit/test_agents_adapter_control.py`
- `tests/frontend/unit/test_agent_service_runtime_gateway.py`
- `tests/frontend/unit/test_agent_service_runtime_authority.py`
- `tests/frontend/unit/test_agent_controller_batch.py`
- `tests/frontend/unit/test_agent_creation_controller_batch.py`
- `tests/frontend/unit/test_controllers_agents.py`
- `tests/frontend/integration/test_agents_flow.py`

### impact / risk

- Positive: the desktop platform can now represent model agents distinctly from retail agents.
- Positive: the first contract loop can parse `target_weight`, translate it into orders, and calculate a structured reward.
- Positive: the Agent panel has the first training-console affordance without requiring a full Arena panel yet.
- Risk: `RuntimeModelAgent` is still an MVP and does not yet persist transitions, episode reports, checkpoints, or lineage.
- Risk: target-weight execution currently uses a simple one-shot rebalance order plan; later versions should support slicing, slippage constraints, and richer risk feedback.

### next actions

- Persist `training_episodes` and `model_episode_results`.
- Record per-step transitions for model agents.
- Surface model reward/action metrics back into the Agent panel after each runtime step.
- Add Arena service orchestration for two or more model agents plus retail background agents.

## Task 2026-04-26-model-training-02

### status

done

### goal

Start Phase 3 by making model episodes produce persistent transition and result records, and surface live model metrics back into the Agent panel.

### files involved

- `persistence/models_training.py`
- `persistence/models_init.py`
- `services/training_episode_service.py`
- `app/services/runtime_model_agent.py`
- `app/services/agent_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `tests/runtime/test_training_episode_report.py`
- `tests/frontend/unit/test_agents_model_view.py`

### change summary

- Added persistence models for `training_episodes`, `model_episode_results`, and `model_transitions`.
- Added `TrainingEpisodeService` to create episodes, record model transitions, upsert model results, rank episode results, and return episode summaries.
- Added a lightweight `EpisodeAgentAccumulator` for reward total, equity return, drawdown, turnover, fee, and trade-count aggregation.
- Extended `RuntimeModelAgent` so each `step_once()` can persist a transition and update a per-agent episode result when `episode_id` is present.
- Added model metrics callback wiring from `RuntimeModelAgent` to `AgentService`.
- Agent metadata now receives live `last_reward`, `last_action`, `equity`, and `pnl` updates after model steps.
- Added an implementation progress ledger to `docs/plan/multi-agent-training-roadmap.md` so completed work is clearly marked and not repeated.

### verification

- `tests/runtime/test_training_episode_report.py`
- `tests/frontend/unit/test_agents_model_view.py`

### impact / risk

- Positive: model-agent runs now produce persistent episode artifacts instead of only transient in-memory step output.
- Positive: the Agent panel can observe model behavior through current metrics without taking ownership of training logic.
- Positive: later Arena and PBT services can build on durable episode/result rows.
- Risk: episode result aggregation is still MVP-level and does not yet include benchmark-relative scoring, checkpoint lineage, or complete slippage/risk diagnostics.

### next actions

- Add `TrainingArenaService` to orchestrate multiple model agents plus retail background agents under one episode.
- Add checkpoint and lineage tables/services before implementing PBT inheritance.
- Promote episode summaries into a future Arena panel instead of overloading the Agent panel.

## Task 2026-04-26-model-training-03

### status

done

### goal

Start Phase 4 by adding a service-layer Arena MVP that can create, start, stop, and evaluate multi-model episodes without placing training orchestration in the UI.

### files involved

- `app/services/training_arena_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_training_arena_service.py`

### change summary

- Added `TrainingArenaService` with in-process Arena state and the standard Arena states from the roadmap.
- Added `TrainingArenaConfig`, `ArenaModelSpec`, and `TrainingArenaState`.
- `create_arena(...)` registers a model/retail training container.
- `start_arena(...)` creates a training episode, creates or binds model agents, optionally creates retail background agents, and starts all participants.
- `stop_arena(...)` stops all model and retail participants known to the Arena.
- `evaluate_arena(...)` ranks `model_episode_results`, completes the training episode, and stores the latest summary on the Arena state.
- Updated the roadmap progress ledger so round 1, round 2, and round 3 completed items are explicitly marked.

### verification

- `tests/runtime/test_training_arena_service.py`

### impact / risk

- Positive: multi-model episodes now have a service-level owner instead of being a loose manual sequence.
- Positive: future Arena UI can call a small service API instead of owning orchestration logic.
- Positive: PBT and checkpoint work now has a clear place to hook into after `evaluate_arena(...)`.
- Risk: Arena state is still in-process. Durable Arena rows should be added before long-running or restart-resilient training workflows.

### next actions

- Add checkpoint and lineage persistence.
- Add a minimal model population service for Hall-of-Fame and PBT mutation.
- Add Arena panel only after the service API stabilizes.

## Task 2026-04-26-model-training-04

### status

done

### goal

Start Phase 5 by adding checkpoint, Hall-of-Fame, lineage, and PBT inheritance records before connecting real neural-network checkpoint files.

### files involved

- `persistence/models_training.py`
- `persistence/models_init.py`
- `app/services/model_checkpoint_service.py`
- `app/services/model_population_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `model_checkpoints` persistence for model checkpoint metadata.
- Added `model_lineage` persistence for parent/child model inheritance records.
- Added `ModelCheckpointService` to save checkpoints, mark/list Hall-of-Fame entries, and record lineage.
- Added `ModelPopulationService` MVP that reads ranked episode results, saves top models as Hall-of-Fame checkpoints, and creates full-clone-plus-mutation lineage records for bottom models.
- Updated the roadmap progress ledger with round 4 completion markers.

### verification

- `tests/runtime/test_pbt_lineage.py`

### impact / risk

- Positive: the platform now has a durable audit trail for "winner teaches loser" cycles.
- Positive: Hall-of-Fame and lineage can be queried before real model weights are introduced.
- Positive: PBT can now be layered onto Arena evaluation without inventing storage later.
- Risk: checkpoint rows currently describe intended checkpoint artifacts; real neural-network weight materialization is still future work.

### next actions

- Add real checkpoint file writing/copying once a true policy adapter is connected.
- Add a population adapter that updates live model agents after lineage creation.
- Add Arena UI only after checkpoint/PBT service APIs settle.

## Task 2026-04-26-model-training-05

### status

done

### goal

Continue Phase 5 by turning checkpoint and PBT records into an actionable generation handoff: materialize checkpoint artifacts and optionally apply inheritance back to live Model Agents.

### files involved

- `app/services/model_checkpoint_service.py`
- `app/services/model_population_service.py`
- `app/services/agent_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- `ModelCheckpointService.save_checkpoint(...)` now writes a JSON artifact file by default and records artifact metadata in `meta_json`.
- Checkpoint artifacts include schema, checkpoint id, model id, agent id, generation, episode id, score, Hall-of-Fame flag, metrics metadata, and payload data.
- Added `AgentService.apply_model_inheritance(...)` so PBT can update a Model Agent to a child model id, increment `params_version`, persist parent checkpoint metadata, and discard stale runtime instances.
- `ModelPopulationService` can now apply full-clone-plus-mutation inheritance to losing live Model Agents when `PopulationEvolutionConfig.apply_to_agents=True`.
- PBT evolution results now report `applied_agents` alongside checkpoints, lineage, and Hall-of-Fame entries.
- Updated the roadmap progress ledger with round 5 completion markers.

### verification

- `tests/runtime/test_pbt_lineage.py`

### impact / risk

- Positive: PBT now has a minimal end-to-end handoff from ranked episode result to checkpoint artifact to loser model identity update.
- Positive: later Arena workflows can trigger population evolution without manually rewriting Agent metadata.
- Risk: checkpoint artifacts still contain JSON policy payloads and episode metrics, not real neural-network tensor weights.

### next actions

- Add a checkpoint-backed policy loader to `ModelRegistryService`.
- Add real neural-network weight save/load adapters once the first trainable policy lands.
- Expose Arena/PBT controls in a dedicated training panel after service APIs stabilize.

## Task 2026-04-26-model-training-06

### status

done

### goal

Continue Phase 5 by making checkpoint-backed child model ids executable through the model registry and runtime model agent.

### files involved

- `app/services/model_registry_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `CheckpointBackedModel`, a lightweight wrapper that runs a parent policy while preserving child model id, parent model id, checkpoint id, checkpoint path, and mutation metadata.
- `ModelRegistryService.list_models()` now discovers child models from `model_lineage`.
- `ModelRegistryService.create_policy(...)` now resolves child model ids through `model_lineage -> model_checkpoints -> JSON artifact`.
- Runtime model creation can now use a PBT child model id such as `random_weight_v1.gen5.MODEL_LOW`.
- Added a defensive fallback for unknown `*.gen*` ids whose built-in parent exists, so a stale child id does not immediately crash policy creation if lineage is temporarily unavailable.
- Updated the roadmap progress ledger with round 6 completion markers.

### verification

- `tests/runtime/test_pbt_lineage.py`

### impact / risk

- Positive: the PBT loop now has a runnable next-generation model identity instead of only an audit record.
- Positive: checkpoint artifacts and lineage can drive runtime policy loading without adding UI responsibility.
- Risk: checkpoint-backed policies still wrap built-in placeholder policies; real neural-network weights require a dedicated tensor/checkpoint adapter.

### next actions

- Add a trainable/external policy adapter contract to the model registry.
- Add real neural-network weight checkpoint save/load once the first trainable baseline lands.
- Start a dedicated Arena panel after the service API has one more integration pass.

## Task 2026-04-26-model-training-07

### status

done

### goal

Continue Phase 5 by adding a persistent adapter boundary for non-built-in, trainable, or external model policies before introducing a real PPO/LSTM implementation.

### files involved

- `app/services/model_registry_service.py`
- `docs/contracts/runtime/model-adapter-contract.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_model_registry_external.py`

### change summary

- Added `TrainableModelPolicy` protocol for optional `learn(...)` and `save_checkpoint(...)` support.
- Added `ExternalPolicyAdapter`, which normalizes adapter output into `act.v1` and preserves model/adapter metadata in action `meta`.
- `ModelRegistryService.register_external_policy(...)` can persist adapter metadata to `output/model_registry/policies.json`.
- `ModelRegistryService.create_policy(...)` can load registry-backed `static_action` policies and injected local `callable` policies.
- `RuntimeModelAgent` can run registered external policies without new runtime branching.
- Added a dedicated model adapter contract document.
- Updated the roadmap progress ledger with round 7 completion markers.

### verification

- `tests/runtime/test_model_registry_external.py`

### impact / risk

- Positive: real trainable policies now have a clean service-layer attachment point.
- Positive: external policy metadata can be registered and reloaded without changing UI or runtime agent code.
- Risk: HTTP/process adapters and real tensor checkpoint loading are still future work.

### next actions

- Add HTTP/process adapter variants if the first real model runs outside the desktop process.
- Add the first Recurrent PPO baseline behind the callable adapter.
- Add Arena UI controls after adapter and PBT APIs stabilize.

## Task 2026-04-26-model-training-08

### status

done

### goal

Continue Phase 5 by allowing external model services to run outside the desktop process through an HTTP adapter while preserving the same `act.v1` runtime path.

### files involved

- `app/services/model_registry_service.py`
- `docs/contracts/runtime/model-adapter-contract.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_model_registry_external.py`

### change summary

- Added HTTP mode to `ExternalPolicyAdapter`.
- HTTP policies can call remote `/act` endpoints and normalize either direct `act.v1` actions or `{ "action": ... }` wrappers.
- HTTP policies can optionally delegate `learn(...)` to `/learn`.
- HTTP policies can optionally delegate `save_checkpoint(...)` to `/checkpoint`, with local JSON fallback still available.
- Runtime model agents can run registered HTTP policies without new runtime branching.
- HTTP policy failures fall back to a safe `hold` action with error metadata.
- Updated the adapter contract and roadmap progress ledger with round 8 completion markers.

### verification

- `tests/runtime/test_model_registry_external.py`

### impact / risk

- Positive: real models can now live in a separate service/process boundary and still attach to the platform through the registry.
- Positive: remote model outages do not crash the model runtime loop.
- Risk: process/subprocess adapters and real neural-network tensor checkpoint management are still future work.

### next actions

- Add a subprocess adapter only if the first model should be launched and supervised by the desktop app.
- Add the first Recurrent PPO or external model service behind the HTTP/callable adapter.
- Build the dedicated Arena panel once model adapter and evolution APIs stabilize.

## Task 2026-04-26-model-training-09

### status

done

### goal

Continue Phase 5 by adding a subprocess adapter so local model workers can run outside the desktop process while still using stdin/stdout JSON and `act.v1`.

### files involved

- `app/services/model_registry_service.py`
- `docs/contracts/runtime/model-adapter-contract.md`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_model_registry_external.py`

### change summary

- Added subprocess mode to `ExternalPolicyAdapter`.
- Subprocess policies receive one JSON request on stdin and return one JSON object on stdout.
- Subprocess policies support `op=act`, `op=learn`, and `op=checkpoint`.
- Runtime model agents can run registered subprocess policies without new runtime branching.
- Subprocess policy failures return a safe `hold` action with error metadata.
- Updated the adapter contract and roadmap progress ledger with round 9 completion markers.

### verification

- `tests/runtime/test_model_registry_external.py`

### impact / risk

- Positive: models can now run in a separate local Python process or environment without requiring an HTTP service.
- Positive: adapter failure is isolated to a safe no-op action rather than crashing the runtime loop.
- Risk: subprocess mode is short-lived per call; a future long-running worker protocol may be needed for high-frequency training.

### next actions

- Add the first real external model service or Recurrent PPO baseline behind the callable/HTTP/subprocess adapters.
- Add real neural-network tensor checkpoint materialization when that baseline lands.
- Build the dedicated Arena panel for training control and observability.

## Task 2026-04-26-model-training-10

### status

done

### goal

Close the existing tensor checkpoint gap without expanding scope: add a real weight artifact adapter that can save and load neural-network-like tensor state separately from the checkpoint DB row.

### files involved

- `app/services/model_checkpoint_service.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `ModelCheckpointService.save_tensor_checkpoint(...)`.
- Added `ModelCheckpointService.load_tensor_checkpoint(...)`.
- Tensor checkpoints now write a compressed `.npz` tensor artifact plus a JSON manifest.
- Manifest metadata includes tensor names, shapes, dtypes, score, generation, episode id, model id, agent id, and Hall-of-Fame status.
- Checkpoint DB rows now record tensor artifact schema, tensor file path, and tensor count in `meta_json`.
- Updated the roadmap progress ledger with round 10 completion markers and removed the tensor checkpoint item from the not-done list.

### verification

- `tests/runtime/test_pbt_lineage.py`

### impact / risk

- Positive: future PPO/LSTM or external model adapters now have a concrete tensor artifact format to write into.
- Positive: checkpoint metadata and physical tensor files can be loaded together for restore or inspection.
- Risk: no PPO/LSTM model is trained yet; this is the storage adapter for real weights, not the model algorithm itself.

### next actions

- Implement the first real model behind the existing callable, HTTP, or subprocess adapter boundary.
- Build the dedicated Arena panel for training control and observability.

## Task 2026-04-26-model-training-11

### status

done

### goal

Finish the dedicated Arena panel promised in the roadmap without expanding the platform checklist.

### files involved

- `app/panels/arena/panel.py`
- `app/ui/adapters/arena_adapter.py`
- `app/app_context.py`
- `app/panels/__init__.py`
- `app/ui/main_window.py`
- `app/ui/docking.py`
- `app/i18n/en_US.json`
- `app/i18n/zh_CN.json`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/frontend/unit/test_arena_panel.py`
- `tests/frontend/unit/test_panel_registry_main.py`

### change summary

- Added `ArenaPanel`, a pure logic panel that wraps `TrainingArenaService` for create/start/stop/evaluate and exposes selected Arena state.
- Added `ArenaPanelAdapter`, with desktop/headless rendering for Arena rows, control buttons, status text, and episode leaderboard rows.
- Registered Arena as a built-in panel and workspace page in the desktop shell.
- Added `TrainingArenaService` to the shared app context so the UI uses one service instance.
- Added regression tests for registry presence, service-backed view state, evaluation leaderboard output, and headless adapter rendering.

### verification

- `tests/frontend/unit/test_arena_panel.py`
- `tests/runtime/test_training_arena_service.py`
- `tests/frontend/unit/test_panel_registry_main.py`

### impact / risk

- Positive: Arena control no longer has to be driven manually through service calls or overloaded Agent panel flows.
- Positive: the next real-model integration can use the Arena page as its operator-facing control surface.
- Risk: Arena state is still in-process and should become durable before long training sessions need restart recovery.

### next actions

- Implement the first real PPO/LSTM or external model through the existing adapter boundary.

## Task 2026-04-27-model-training-12

### status

done

### goal

Connect the first real model baseline through the existing platform model boundary, using the `docs/design/model-training-design.md` Phase 3 recommendation: PPO + GRU/LSTM recurrent actor-critic.

### files involved

- `rl/model_adapters/ppo_recurrent_adapter.py`
- `rl/model_adapters/__init__.py`
- `app/services/model_registry_service.py`
- `app/services/runtime_model_agent.py`
- `docs/plan/multi-agent-training-roadmap.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_recurrent_ppo_adapter.py`

### change summary

- Added `RecurrentPPOPolicyAdapter`, a PyTorch LSTM actor-critic policy that consumes `obs.v1` and emits `act.v1 target_weight`.
- Registered `ppo_lstm_v1` as a built-in model id in `ModelRegistryService`.
- Added lightweight PPO-style online learning through `learn(...)` over recent on-policy mini rollouts.
- Updated `RuntimeModelAgent` so `online_train` and `train` modes call policy `learn(...)` after each transition.
- Added checkpoint output for the adapter: JSON manifest plus `.pt` torch weights.
- Added regression tests for registry discovery, runtime order execution, online learning, and checkpoint materialization.

### verification

- `tests/runtime/test_recurrent_ppo_adapter.py`

### impact / risk

- Positive: the platform now has a real torch-backed recurrent model id instead of only hold/random/external stubs.
- Positive: users can create Model Agents with `model_id=ppo_lstm_v1` and run them through the same Arena/runtime path.
- Risk: the v1 learner is intentionally lightweight and single-process; full rollout scheduling, league sampling, and large-batch PPO updates remain service-level work after the adapter proves stable.

### next actions

- Run `ppo_lstm_v1` inside Arena against retail background agents and inspect its episode metrics before adding heavier league automation.

## Task 2026-05-07-model-training-runtime-env

### status

done

### goal

Repair the current Python/runtime dependency path so live `ArenaExperimentRunner` can import and run a PostgreSQL-backed long Arena generation series.

### files involved

- `persistence/db_config.py`
- `pyproject.toml`
- `docs/data/postgresql-runtime-migration.md`
- `docs/data/data-layering-table-plan.md`
- `tests/test_persistence_db_config.py`
- `tests/runtime/test_arena_experiment_runner.py`
- `docs/current-work-status/model-training.md`

### change summary

- Confirmed the project `.venv` runs on Python 3.11 and has SQLAlchemy, pytest, NumPy, Pydantic, and PySide6 available.
- Confirmed `psycopg[binary]` cannot be installed in this runtime and pure `psycopg` cannot load because system `libpq` is absent.
- Added `pg8000` as the declared pure-Python PostgreSQL fallback dependency.
- Added PostgreSQL driver resolution with `STOCKSIM_POSTGRES_DRIVER` override and automatic fallback from unavailable `psycopg` to available `pg8000`.
- Verified default runner import no longer depends on the broken `psycopg` path in the current environment.
- Updated the explicit no-signal Arena report test so newer audit slots in `implemented_checks` do not fail the runner suite.

### verification

- `STOCKSIM_DB_URL=postgresql+pg8000://stock_sim:stock_sim@127.0.0.1:5432/stock_sim`
- `stock_sim.persistence.models_init.ensure_models()`
- live `ArenaExperimentRunner.run_generations(...)`, 5 generations, PostgreSQL-backed
- no-env default import and no-env default live series using automatic `pg8000` fallback
- `tests/test_persistence_db_config.py tests/test_persistence_db_health.py`
- `tests/runtime/test_training_arena_service.py tests/runtime/test_arena_experiment_runner.py`

### result

- Series report: `output/arena_pg_live/arena-pg-live-1778084965-series-20260506162926.json`
- PostgreSQL rows written for the verification run: 5 `training_episodes`, 35 `model_episode_results`, 105 `model_transitions`.
- Default no-env fallback report: `output/arena_pg_live/arena-pg-default-1778085155-series-20260506163236.json`
- PostgreSQL rows written for the default fallback run: 5 `training_episodes`, 20 `model_episode_results`, 60 `model_transitions`.
- Baseline suite aggregate was complete for all 5 generations.

### impact / risk

- Positive: long Arena series can now run in the local Windows runtime without requiring system `libpq`.
- Positive: bare `postgres://...` and `postgresql://...` URLs remain compatible while explicit driver URLs are preserved.
- Risk: `pg8000` is a correctness/runtime fallback; high-throughput production profiles may still prefer `psycopg` with a working binary or `libpq` installation.

### next actions

- Keep `pg8000` as the default local Windows fallback until a managed `psycopg` binary or system `libpq` installation is standardized.
- Run the full GUI/runtime Arena path separately when the operator wants end-to-end desktop behavior rather than service-layer verification.

## Task 2026-05-07-task101-live-runtime-rerun

### status

done

### goal

Rerun Task 101 as a live PostgreSQL/database/runtime long Arena dry run and output a real runtime evidence package rather than relying on the earlier headless injected package.

### files involved

- `app/services/long_arena_dry_run.py`
- `tests/runtime/test_long_arena_dry_run.py`
- `docs/tasks/model-training/long-arena-dry-run-package-v1.md`
- `docs/current-work-status/model-training.md`
- `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-runtime-dry-run-cc0a9a6a-1233652fdd357ead.json`
- `output/task101_live_long_arena/task101-live-runtime-cc0a9a6a-series-20260507102232.json`
- `output/task101_live_long_arena/task101-live-runtime-cc0a9a6a-augmented-runtime-evidence.json`
- `output/model_registry/policies.json`

### change summary

- Reran Task 101 through `build_app_context()` and live `ArenaExperimentRunner.run_generations(...)`.
- Used real `AgentService`, `RuntimeModelAgent`, `TrainingArenaService`, `TrainingEpisodeService`, and PostgreSQL ORM persistence.
- Registered `task101_static_candidate_v2` as a static external candidate policy for the live dry run.
- Ran 3 generations with one candidate plus hold, random, naive rebalance, TWAP, VWAP, and AC-lite baselines.
- Added runtime evidence passthrough to `long_arena_dry_run_package_v1` so the package records database dialect, URL driver, episode ids, row counts, and runtime source.
- Tightened package completeness so failed evidence marks the package incomplete.
- Did not delete PostgreSQL historical data.

### verification

- Live package readback: `status=incomplete`, `go_no_go=no_go`, `actual_generation_count=3`.
- PostgreSQL row counts for the package run: 3 `training_episodes`, 21 `model_episode_results`, 38 `model_transitions`.
- Candidate evidence summary: `T101LIVE_CANDIDATE_cc0a9a6a`, 7 failed evidence slots, 0 missing evidence slots, 0 not-available evidence slots.
- `pytest tests/runtime/test_long_arena_dry_run.py tests/runtime/test_arena_experiment_runner.py tests/test_persistence_db_config.py tests/test_persistence_db_health.py`

### result

- The live long Arena dry run now produces a real database/runtime Task 101 evidence package.
- The package is a No-Go package because required independent evidence still fails: checkpoint hash, random seed ledger, calibration, hidden evaluation, exploit test, paired sensitivity, strict parent gate, and research acceptance lock.

### impact / risk

- Positive: Task 101 is no longer blocked on Python/runtime import or PostgreSQL execution.
- Positive: the package now distinguishes runtime success from evidence-gate failure.
- Risk: the candidate policy is a static external hold policy for dry-run evidence, not a trained PPO/LSTM candidate.

### next actions

- Add real checkpoint materialization and random seed ledger wiring before expecting parent-gate eligibility.
- Implement or connect live calibration, hidden-evaluation, exploit-test, and paired-sensitivity runners before allowing research acceptance.
