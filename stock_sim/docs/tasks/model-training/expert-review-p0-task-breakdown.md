# Expert Review P0 Task Breakdown

_Created: 2026-05-03_

## Source

This task document is derived only from:

- `UTI-STOCKSIM_专家评审与落地设计.docx`
- `PROJECT_BACKGROUND_AND_GOALS.md`
- `README.md`
- `docs/design/model-training-design.md`
- `docs/plan/multi-agent-training-roadmap.md`
- Existing runtime/model-training contracts and services under `rl/`, `app/services/`, `services/`, and `persistence/`

## Purpose

The expert review changes the near-term priority from "keep adding stronger model families" to "make the training problem falsifiable and transferable".

Current project work has already completed the Arena, PPO/LSTM, PBT, checkpoint, lineage, multi-generation runner, and execution-health loop. The next work should therefore split the review's P0 recommendations into smaller implementation steps before any new model architecture is added.

## Scope Rules

- Do not add a new algorithm family in this work package.
- Do not treat Arena leaderboard rank as research acceptance.
- Do not let one PPO/LSTM model simultaneously own alpha discovery, execution, market making, and risk overlay.
- Do not use synthetic Arena profit as evidence of real-market alpha.
- Keep GUI as operator/observer; keep training orchestration in services or scripts.
- All model behavior must continue through Observation / Action / Reward contracts and runtime order/account/matching truth.

## Work Package A: Alpha-to-Execution Task Boundary

### Goal

Convert the immediate `ppo_lstm_v1` baseline into a clearly bounded Alpha-to-Execution baseline.

The model should receive a controlled alpha or target-position signal and learn how to turn it into lower-cost, lower-risk, executable order intent. It should not be evaluated as a standalone direction-prediction alpha model.

### Steps

1. Define the task card fields in a docs-first form:
   - task name
   - allowed observation inputs
   - allowed action outputs
   - reward components
   - required benchmarks
   - failure conditions
2. Map current `obs.v1`, `act.v1`, and `rew.v1` fields to the Alpha-to-Execution task.
3. Identify any current observation fields that could leak future, final-ranking, GUI-only, or persistence-only information.
4. Define the first controlled alpha input shape without changing model architecture.
5. Define target execution outputs in terms of existing `act.v1` / order-intent semantics.
6. Add a no-signal version of the task for reward-leak checks.
7. Add a doc-level acceptance rule: Alpha-to-Execution must compare against TWAP/VWAP or equivalent rule execution before being treated as useful.

### Deliverables

- `docs/contracts/runtime/` contract notes or amendments for Alpha-to-Execution semantics.
- A small task card document under `docs/tasks/model-training/` or `docs/contracts/runtime/`.
- Focused tests proving the task path does not bypass runtime order/account/matching services.

### Acceptance

- Given a controlled target/alpha input, the model emits only contract-valid order intent or target-weight style action.
- The model still submits through existing runtime services.
- No result is labeled "alpha success" unless it is compared to execution baselines.

## Work Package B: Baseline Suite

### Goal

Add strong non-neural baselines so PPO/LSTM results have meaning.

### Required Baselines From Review

- No-trade / cash
- Random constrained
- Buy-and-hold / equal weight where the task is portfolio-like
- TWAP / VWAP for execution tasks
- Simplified Almgren-Chriss style execution if impact/risk balance is available
- Rule-based market maker for market-making tasks
- Linear / logistic / GBDT only when the task uses predictive features
- Oracle-alpha plus naive execution as an upper-bound diagnostic for execution preservation

### Steps

1. Inventory which of these baselines already exist in code or tests.
2. Add only the missing baselines needed for Alpha-to-Execution first.
3. Make Arena experiment reports include baseline result rows separately from trainable model rows.
4. Ensure PBT parent eligibility excludes pure baselines unless explicitly enabled.
5. Add report fields for excess performance against each required baseline.

### Acceptance

- Every Alpha-to-Execution experiment report includes at least no-trade, random constrained, and one execution baseline.
- PPO/LSTM ranking is reported relative to baselines, not only relative to other PPO agents.

## Work Package C: Calibration Harness and World Pool

### Goal

Make each synthetic world measurable before it is used for training acceptance.

The review explicitly warns that a closed synthetic market can reward exploitation of retail settings rather than transferable trading behavior. The project therefore needs calibration scores and world hashes before stronger claims are made.

### Steps

1. Define a `World Card` schema in docs:
   - symbols/universe
   - seed
   - retail family mix
   - fees/tick/trading rules
   - regime label
   - calibration metrics
   - world hash
2. Start with metrics already supported by retail calibration and runtime reports.
3. Add market-fact metrics before adding new model complexity:
   - return distribution shape
   - volatility clustering proxy
   - bid-ask spread
   - depth
   - volume / turnover
   - order arrival/cancel/fill behavior if available
4. Split worlds into train, validation, and hidden sets by seed/config hash.
5. Persist calibration run summaries separately from training episode rankings.

### Acceptance

- A training run can state which world config/hash it used.
- A validation or hidden report does not reuse the exact training world hash.
- Calibration pass/fail is visible in report metadata before model ranking is interpreted.

### Progress Update 2026-05-04: World Card Metadata

- Added `docs/tasks/model-training/arena-world-card-metadata.md`.
- New Arena experiment reports include top-level `world_card`.
- `experiment_record_metadata.world_card` exposes existing world/config inputs in a compact world-card shape.
- Arena generation summaries include `world_card`.
- Arena series aggregates include `aggregate.world_card`.
- World split remains `training_only` and calibration remains `not_available` until world-pool split rules and calibration metric ownership are documented.

### Progress Update 2026-05-04: World Card Completeness

- Added `docs/tasks/model-training/arena-world-card-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_card`.
- `experiment_record_completeness.field_status` now tracks `world_calibration`.
- Calibration status remains explicit as `not_available`; no calibration pass/fail is claimed.

### Progress Update 2026-05-04: Calibration Score Slot

- Added `docs/tasks/model-training/arena-world-card-calibration-score-slot.md`.
- World-card metadata now includes an explicit calibration-score slot.
- `world_card.calibration.score_status` remains `not_available`.
- Arena generation summaries expose calibration-score status and reason.
- Arena series aggregates count `aggregate.world_card.calibration_score_status_counts`.
- No calibration score computation or pass/fail threshold was added.

### Progress Update 2026-05-04: Calibration Score Completeness

- Added `docs/tasks/model-training/arena-world-calibration-score-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_calibration_score`.
- Explicit unavailable score slots mark `world_calibration_score` as `not_available`.
- Missing score slots remain `missing`.
- Real scores can later become `present` without changing the aggregate shape.

### Progress Update 2026-05-04: World Split Completeness

- Added `docs/tasks/model-training/arena-world-split-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_split`.
- Current `training_only` world cards mark `world_split` as `not_available`.
- Missing split metadata remains `missing`.
- Future validation/hidden split statuses can become `present` without changing the aggregate shape.

### Progress Update 2026-05-04: Retail Family Mix Completeness

- Added `docs/tasks/model-training/arena-world-retail-family-mix-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_retail_family_mix`.
- Current `retail_family_mix_status=not_available` remains explicit as `not_available`.
- Missing retail family mix metadata remains `missing`.
- Future retail-family-mix evidence can become `present` without changing the aggregate shape.

### Progress Update 2026-05-04: Liquidity Seed Completeness

- Added `docs/tasks/model-training/arena-world-liquidity-seed-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_liquidity_seed`.
- Explicit training-liquidity seed configuration is counted as `present`.
- Missing liquidity-seed metadata remains `missing`.
- No liquidity behavior or matching behavior was changed.

### Progress Update 2026-05-04: World Clock Completeness

- Added `docs/tasks/model-training/arena-world-clock-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_clock`.
- Complete world-card clock configuration is counted as `present`.
- Missing clock metadata remains `missing`.
- No simulation clock behavior was changed.

### Progress Update 2026-05-04: World Universe Completeness

- Added `docs/tasks/model-training/arena-world-universe-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_universe`.
- Non-empty world-card symbol/universe metadata is counted as `present`.
- Missing world-card universe metadata remains `missing`.
- No symbol selection or universe filtering behavior was changed.

### Progress Update 2026-05-04: Record Kind Metadata

- Added `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`.
- New Arena experiment reports include top-level `record_kind`.
- `experiment_record_metadata.record_kind` marks current Arena reports as `arena_experiment_report` with `primary_stage=training`.
- Separate calibration, hidden-evaluation, and exploit-test artifact statuses remain `not_available` until their runners and artifact boundaries are documented.

### Progress Update 2026-05-04: Record Kind Completeness

- Added `docs/tasks/model-training/arena-record-kind-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `record_kind`.
- `experiment_record_completeness.field_status` now tracks separate calibration, hidden-evaluation, and exploit-test artifact boundaries.
- These statuses remain report metadata only and do not create separate artifacts.

### Progress Update 2026-05-04: Transition Evidence

- Added `docs/tasks/model-training/arena-transition-evidence-summary.md`.
- Arena generation summaries now include `transition_evidence`.
- Arena series aggregates now include `aggregate.transition_evidence`.
- Existing audit samples remain bounded and summarized; this does not add raw transition dumps or replay artifacts.

### Progress Update 2026-05-04: Transition Evidence Completeness

- Added `docs/tasks/model-training/arena-transition-evidence-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `transition_evidence`.
- Episodes with transitions mark compact transition evidence as `present`.
- Episodes without transitions mark compact transition evidence as `not_available`.

## Work Package D: Hidden Evaluation and Exploit Detector

### Goal

Prevent PBT from spreading simulated-market loopholes.

### Steps

1. Define hidden evaluation inputs:
   - unseen seeds
   - unseen retail mix
   - altered fees
   - altered liquidity depth
   - altered tick/spread regime when supported
2. Add exploit checks from the expert review:
   - no-signal world
   - frozen-policy hidden seed
   - fee sensitivity
   - impact sensitivity
   - timestamp audit
   - mark-to-market audit
   - order anomaly audit
   - cross-world transfer
3. Make each check return explicit pass/fail/warn status and reason.
4. Require hidden evaluation and exploit checks before a model can become a PBT parent under strict mode.

### Acceptance

- Parent eligibility is based on hidden evaluation, risk, activity, diversification, and exploit flags.
- A model with high training leaderboard score but exploit flags is not eligible as a parent.

## Work Package E: Experiment Record Completeness

### Goal

Make each training/evaluation artifact reproducible enough to audit.

### Steps

1. Add or confirm report fields for:
   - code hash
   - sim version
   - reward hash/profile
   - world hash/config
   - data cutoff when replay/hybrid data is used later
   - random seed
   - model id / parent id / mutation
2. Keep training, calibration, evaluation, and exploit-test records distinguishable.
3. Keep transition storage compact where needed, but preserve enough samples and summaries to reproduce failures.

### Acceptance

- A generated report can answer: what code, what world, what reward, what seed, what model, and what parent lineage produced this result.

### Progress Update 2026-05-03

- Added `docs/tasks/model-training/arena-series-experiment-record-completeness.md`.
- Arena generation summaries now include `experiment_record_completeness`.
- Arena series aggregates now include `aggregate.experiment_record_completeness`.
- The current report layer distinguishes `present`, `missing`, `not_available`, and `not_applicable` fields.
- Missing `code_hash`, `sim_version`, `reward_hash`, `world_hash`, and `random_seed` remain explicit gaps until their sources are documented.
- Replay/hybrid `data_cutoff` remains `not_applicable` until replay/hybrid data is added through a documented task.

### Progress Update 2026-05-03: Reward/World Hashes

- Added `docs/tasks/model-training/arena-experiment-record-metadata-hashes.md`.
- New Arena experiment reports include top-level `reward_hash` and `world_hash`.
- `reward_hash` is a deterministic canonical JSON hash of reward profile, task name, and reward contract version.
- `world_hash` is a deterministic canonical JSON hash of the current Arena world/config identity.
- These hashes are report metadata only and do not claim hidden-world calibration or real-market validation.
- `code_hash`, `sim_version`, and `random_seed` remain explicit missing sources until their local ownership is documented.

### Progress Update 2026-05-03: Code Identity

- Added `docs/tasks/model-training/arena-experiment-code-identity-hash.md`.
- New Arena experiment reports include top-level `code_hash` when local Git identity is available.
- `experiment_record_metadata.code_identity` records Git HEAD, branch, dirty flag, status count, and status hash.
- Dirty worktree state remains explicit; this is not a clean release artifact claim.
- `sim_version` and `random_seed` remain explicit missing sources until their local ownership is documented.

### Progress Update 2026-05-03: Sim Version

- Added `docs/tasks/model-training/arena-experiment-sim-version-source.md`.
- New Arena experiment reports include top-level `sim_version` from `stock_sim.__version__`.
- `experiment_record_metadata.sim_version_identity` records the source as `stock_sim.__version__`.
- `random_seed` remains the remaining explicit missing Work Package E source until stochastic services can consume and report it.

### Progress Update 2026-05-03: Random Seed Status

- Added `docs/tasks/model-training/arena-experiment-random-seed-status.md`.
- New Arena experiment reports include `random_seed_identity.status=not_available`.
- `random_seed` remains missing by design because the current services do not expose one seed that controls Arena config, retail persona sampling, model training RNG, and market/world RNG.
- The task records required prerequisites before `random_seed` can become present.

### Progress Update 2026-05-04: Identity Summary

- Added `docs/tasks/model-training/arena-series-experiment-record-identity-summary.md`.
- Arena generation summaries now include `experiment_record_identity`.
- Arena series aggregates now include `aggregate.experiment_record_identity`.
- The identity summary surfaces existing code hash, sim version, reward hash, world hash, random-seed status, dirty-code state, missing sources, and not-applicable sources.
- No new identity values are fabricated; `random_seed` remains unavailable until the documented stochastic-service prerequisites are implemented.

### Progress Update 2026-05-04: Record Kind Metadata

- Added `docs/tasks/model-training/arena-experiment-record-kind-metadata.md`.
- Arena generation summaries now include `record_kind`.
- Arena series aggregates now include `aggregate.record_kind`.
- Current Arena reports are explicitly training-stage records with embedded evaluation/exploit sections, not separate calibration or hidden/exploit artifacts.

### Progress Update 2026-05-04: Record Kind Completeness

- Added `docs/tasks/model-training/arena-record-kind-completeness-status.md`.
- `experiment_record_completeness` now tracks `record_kind` and separate artifact boundary statuses.
- Separate calibration, hidden-evaluation, and exploit-test records remain `not_available` until documented artifact schemas and runners exist.

### Progress Update 2026-05-04: Transition Evidence

- Added `docs/tasks/model-training/arena-transition-evidence-summary.md`.
- Arena generation summaries now include `transition_evidence`.
- Arena series aggregates now include `aggregate.transition_evidence`.
- Existing audit samples remain bounded and summarized; this does not add raw transition dumps or replay artifacts.

### Progress Update 2026-05-04: Transition Evidence Completeness

- Added `docs/tasks/model-training/arena-transition-evidence-completeness-status.md`.
- `experiment_record_completeness` now tracks `transition_evidence`.
- Episodes with no transitions keep this field explicit as `not_available`.

### Progress Update 2026-05-04: Model Lineage Evidence

- Added `docs/tasks/model-training/arena-model-lineage-evidence-summary.md`.
- Arena generation summaries now include `model_lineage_evidence`.
- Arena series aggregates now include `aggregate.model_lineage_evidence`.
- The summary reads existing `config.model_specs`, `pbt.lineage`, and `pbt.applied_agents` only.
- Reports now expose model ids, parent model ids, child model ids, applied model ids, and mutation keys without changing PBT behavior.

### Progress Update 2026-05-04: Model Lineage Evidence Completeness

- Added `docs/tasks/model-training/arena-model-lineage-evidence-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `model_lineage_evidence`.
- Generations with PBT lineage rows mark `model_lineage_evidence` as `present`.
- Generations without PBT lineage rows mark `model_lineage_evidence` as `not_available`.

### Progress Update 2026-05-04: World Identity Completeness

- Added `docs/tasks/model-training/arena-world-identity-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `world_identity`.
- Existing world-identity metadata can now be counted as `present` separately from `world_hash` and `world_card`.
- Missing world-identity metadata remains explicit as `missing`.

### Progress Update 2026-05-04: Reward Identity Completeness

- Added `docs/tasks/model-training/arena-reward-identity-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `reward_identity`.
- Existing reward-identity metadata can now be counted as `present` separately from `reward_hash`.
- Missing reward-identity metadata remains explicit as `missing`.

### Progress Update 2026-05-04: Contract Versions Completeness

- Added `docs/tasks/model-training/arena-contract-versions-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `contract_versions`.
- Existing observation/action/reward contract-version metadata can now be counted as `present`.
- Missing contract-version metadata remains explicit as `missing`.

### Progress Update 2026-05-04: Hash Method Completeness

- Added `docs/tasks/model-training/arena-hash-method-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks `hash_method`.
- Existing hash-method metadata can now be counted as `present`.
- Missing hash-method metadata remains explicit as `missing`.

### Progress Update 2026-05-04: Metadata Source Completeness Batch

- Added `docs/tasks/model-training/arena-metadata-schema-completeness-status.md`.
- Added `docs/tasks/model-training/arena-code-identity-completeness-status.md`.
- Added `docs/tasks/model-training/arena-sim-version-identity-completeness-status.md`.
- Added `docs/tasks/model-training/arena-random-seed-identity-completeness-status.md`.
- Added `docs/tasks/model-training/arena-missing-sources-completeness-status.md`.
- Added `docs/tasks/model-training/arena-not-applicable-sources-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks these existing metadata source fields separately from their derived values.
- The real `random_seed` remains missing by design until stochastic-service prerequisites are documented and implemented.

### Progress Update 2026-05-04: Record Kind Detail Completeness Batch

- Added `docs/tasks/model-training/arena-record-kind-schema-completeness-status.md`.
- Added `docs/tasks/model-training/arena-record-kind-kind-completeness-status.md`.
- Added `docs/tasks/model-training/arena-record-primary-stage-completeness-status.md`.
- Added `docs/tasks/model-training/arena-record-task-name-completeness-status.md`.
- Added `docs/tasks/model-training/arena-record-embedded-sections-completeness-status.md`.
- `experiment_record_completeness.field_status` now tracks these existing `record_kind` subfields separately from the existence of the `record_kind` object.
- Separate calibration, hidden-evaluation, and exploit-test artifacts remain `not_available` until their documented runners and schemas exist.

### Progress Update 2026-05-04: Evidence Runner Phase Charter

- Added `docs/tasks/model-training/evidence-runner-phase-charter.md`.
- Task 82 now freezes further horizontal completeness expansion as the default next step.
- Future model-training work should prioritize separate evidence artifact schemas, runner ownership, WorldSpec hashing, RandomSeedLedger, calibration, baselines, hidden evaluation, paired sensitivity, exploit tests, and evidence-gated parent eligibility.
- Calibration, hidden evaluation, exploit tests, paired sensitivity, and parent-gate evidence remain `not_available` until independent artifacts/runners exist.
- No training, execution, reward, account, PBT, checkpoint, GUI, or PostgreSQL behavior was changed.

### Progress Update 2026-05-04: Separate Artifact Schemas v1

- Added `docs/tasks/model-training/separate-artifact-schemas-v1.md`.
- Task 83 now documents common Evidence Runner artifact fields and six artifact kinds:
  - `calibration_artifact_v1`
  - `baseline_artifact_v1`
  - `hidden_eval_artifact_v1`
  - `exploit_test_artifact_v1`
  - `paired_sensitivity_artifact_v1`
  - `parent_gate_artifact_v2`
- Pass/fail boundaries and stable failure reason keys are documented before runner implementation.
- Parent eligibility, checkpoint promotion, and research claim eligibility are explicitly separate.
- No artifact persistence, artifact writer, runner, strict parent gate v2 behavior, GUI behavior, or PostgreSQL behavior was changed.

### Progress Update 2026-05-05: WorldSpec Canonical Hash

- Added `docs/tasks/model-training/worldspec-canonical-hash.md`.
- Task 84 now documents the proposed `world_spec_v1` shape and canonical hash boundary.
- Existing Arena `world_identity` and `world_card` fields are mapped to supported WorldSpec fields.
- Unsupported fields remain explicitly `not_available` until their owners and implementations exist.
- Required implementation tests are documented for hash stability, input sensitivity, explicit `not_available`, and self-hash exclusion.
- No `world_spec_v1` code, `world_spec_hash` code, hidden-world registry, RandomSeedLedger, calibration, artifact persistence, runner behavior, or PostgreSQL behavior was changed.

### Progress Update 2026-05-05: RandomSeedLedger v1

- Added `docs/tasks/model-training/random-seed-ledger-v1.md`.
- Task 85 now documents the proposed `random_seed_ledger_v1` schema and `sha256_label_derivation_v1` contract.
- Required seed labels are documented for retail population, liquidity noise, model initialization, episode sampling, hidden-world selection, world generation, calibration, baselines, paired perturbations, exploit worlds, and PBT mutation.
- Artifact blocking rules are documented for calibration, baseline, hidden evaluation, exploit test, paired sensitivity, and parent gate artifacts.
- Current `random_seed_identity.status=not_available`, `random_seed=None`, and `missing_sources=random_seed` remain unchanged.
- No seed injection, seed ledger code, artifact pass/fail enforcement, stochastic behavior, or PostgreSQL behavior was changed.

### Progress Update 2026-05-05: Market Metrics Extractor v0

- Added `docs/tasks/model-training/market-metrics-extractor-v0.md`.
- Task 86 now documents normalized input boundaries for orders, trades, snapshots, bars, accounts, account-equity snapshots, and optional holding samples.
- Existing persisted runtime tables and `RetailCalibrationReportCollector` samples are mapped to supported metric groups.
- Supported metric groups now have documented boundaries for price stylized facts, microstructure, liquidity, behavior, and rule consistency.
- `metric_coverage` statuses and stable missing/not-available reasons are documented before calibration scorecard or artifact writer code is added.
- Calibration score, `calibration_artifact_v1`, WorldSpec code, RandomSeedLedger code, hidden-world runner, paired runner, exploit runner, and PostgreSQL behavior remain unchanged.

### Progress Update 2026-05-05: Calibration Scorecard v0

- Added `docs/tasks/model-training/calibration-scorecard-v0.md`.
- Task 87 now documents target profile schema, metric eligibility, normalized distance, weighted score parts, critical failures, and pass/fail boundaries.
- The scorecard consumes Task 86 `metric_coverage` and must not turn missing or not-available required metrics into zero-distance passes.
- Current `world_card.calibration.status=not_available`, `score=None`, and `score_status=not_available` remain unchanged.
- The scorecard output shape for Task 88 `calibration_artifact_v1` writer is documented.
- No scorecard code, target profile storage, calibration score computation, artifact writer, runner behavior, or PostgreSQL behavior was changed.

### Progress Update 2026-05-05: Task 82-87 Completion Audit

- Re-checked Task 82-87 against the second expert review.
- Task 82 and Task 83 are docs/contract tasks and remain complete.
- Task 84-87 were previously docs-only and therefore not fully complete.
- Added `app/services/evidence_core.py`.
- Added `tests/runtime/test_evidence_core.py`.
- Task 84 now has runnable WorldSpec canonical hash helpers.
- Task 85 now has runnable RandomSeedLedger derivation and hash helpers.
- Task 86 now has runnable Market Metrics Extractor v0 metrics and coverage output.
- Task 87 now has runnable Calibration Scorecard v0 normalized distance, weighted score, critical failure, and coverage failure logic.
- No hidden-world registry, full calibration runner, target profile storage, PostgreSQL persistence, GUI behavior, strict parent gate v2, or PostgreSQL data deletion was added.

### Progress Update 2026-05-05: Calibration Artifact Writer

- Added `docs/tasks/model-training/calibration-artifact-writer.md`.
- Added `app/services/evidence_artifact_writer.py`.
- Added `tests/runtime/test_evidence_artifact_writer.py`.
- Task 88 now writes a separate `calibration_artifact_v1` JSON artifact from supplied metrics and scorecard output.
- The artifact includes common Evidence Runner identity fields, dependencies, metrics, scorecard, pass/fail, failure reasons, and a canonical `artifact_hash`.
- Missing `code_identity_hash`, `sim_version_identity`, `world_hash`, `random_seed_ledger_hash`, `contract_versions`, or `scorecard` blocks a passing artifact.
- This does not implement calibration runner execution, market metrics extraction, scorecard computation, target profile storage, PostgreSQL artifact persistence, strict parent gate v2, GUI behavior, or PostgreSQL data deletion.

### Progress Update 2026-05-05: Unified Baseline Runner

- Added `docs/tasks/model-training/unified-baseline-runner.md`.
- Extended `app/services/evidence_artifact_writer.py`.
- Extended `tests/runtime/test_evidence_artifact_writer.py`.
- Task 89 now writes a separate `baseline_artifact_v1` JSON artifact from the existing Arena `baseline_suite`,
  baseline result rows, and `benchmark_comparison`.
- The artifact requires current executable baseline kinds: `no_trade_cash`, `random_constrained`, and
  `target_weight_naive_rebalance`.
- Missing required identity fields, baseline suite, baseline results, benchmark comparison, or required baseline kinds
  blocks a passing artifact.
- This does not implement TWAP, VWAP, AC-lite, a new baseline scheduler, PostgreSQL artifact persistence, GUI behavior,
  strict parent gate v2, or PostgreSQL data deletion.

### Progress Update 2026-05-05: TWAP/VWAP Baselines

- Updated `docs/tasks/model-training/twap-vwap-report-slots.md`.
- Updated `docs/tasks/model-training/baseline-suite-inventory-and-plan.md`.
- Added `ScheduledExecutionBaselineModel`.
- Added built-in `twap_execution_v1` and `vwap_execution_v1`.
- Both policies emit `act.v1 target_weight` actions with schedule metadata through the existing model registry path.
- Arena default model specs now include TWAP/VWAP as collect-only baselines.
- Arena default PBT exclusions include TWAP/VWAP.
- `baseline_artifact_v1` now requires `twap` and `vwap`.
- True order-level slicing, arrival-price capture, implementation shortfall reward wiring, strict parent gate v2, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: AC-lite Baseline

- Added `docs/tasks/model-training/ac-lite-baseline.md`.
- Extended `ScheduledExecutionBaselineModel` with AC-lite schedule progress.
- Added built-in `ac_lite_execution_v1`.
- AC-lite emits `act.v1 target_weight` actions with AC-lite risk/cost schedule metadata.
- Arena default model specs now include AC-lite as a collect-only baseline.
- Arena default PBT exclusions include AC-lite.
- `baseline_artifact_v1` now requires `ac_lite`.
- Order-level AC slicing, calibrated impact/risk inputs, arrival-price capture, implementation shortfall reward wiring,
  strict parent gate v2, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Hidden World Registry

- Added `docs/tasks/model-training/hidden-world-registry.md`.
- Extended `app/services/evidence_core.py`.
- Extended `tests/runtime/test_evidence_core.py`.
- Task 92 now has a split registry for `visible`, `validation`, `hidden`, and `exploit` world specs.
- `train` is normalized to `visible`.
- Registry pass requires `visible`, `validation`, and `hidden`.
- Registry hash excludes `registry_hash`.
- Hidden-World Runner v0, frozen checkpoint evaluation, no-learning enforcement, hidden_eval artifact persistence, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Hidden-World Runner v0

- Added `docs/tasks/model-training/hidden-world-runner-v0.md`.
- Added `app/services/hidden_world_runner.py`.
- Added `tests/runtime/test_hidden_world_runner.py`.
- Task 93 now evaluates only hidden split specs selected from `hidden_world_registry_v1`.
- The runner calls the supplied evaluator with `allow_learning=False` for the frozen checkpoint policy and for every baseline.
- Hidden evaluation writes a separate `hidden_eval_artifact_v1`.
- Pass/fail includes hidden results, baseline presence, median-baseline win threshold, strongest-baseline win threshold, no-signal positive-alpha blocking, and configured risk-limit checks.
- Real checkpoint loading, world construction, Arena integration, paired fee/impact sensitivity, exploit tests, strict parent gate v2, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Paired Fee/Impact Sensitivity Runner v0

- Added `docs/tasks/model-training/paired-fee-impact-runner-v0.md`.
- Added `app/services/paired_sensitivity_runner.py`.
- Added `tests/runtime/test_paired_sensitivity_runner.py`.
- Added `EvidenceArtifactWriter.write_paired_sensitivity_artifact(...)`.
- Task 94 now evaluates base/stressed world pairs with the same frozen policy and `allow_learning=False`.
- V0 supports required `fee`, `impact`, and `latency` perturbation kinds.
- V0 also records paths for `queue`, `spread`, `liquidity`, `partial_fill`, and custom path operations.
- `paired_sensitivity_artifact_v1` includes per-perturbation base/stressed metrics, metric deltas, a degradation curve, warnings, pass/fail, and failure reasons.
- Real checkpoint loading, world construction, Arena integration, multi-seed sensitivity aggregation, exploit tests, strict parent gate v2, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Exploit Test Runner v0

- Added `docs/tasks/model-training/exploit-test-runner-v0.md`.
- Added `app/services/exploit_test_runner.py`.
- Added `tests/runtime/test_exploit_test_runner.py`.
- Added `EvidenceArtifactWriter.write_exploit_test_artifact(...)`.
- Task 95 now evaluates exploit world specs with a frozen policy and `allow_learning=False`.
- V0 implements required probes for `no_signal_world`, `timestamp_leakage`, `mark_to_market_leakage`, `order_boundary`, `fee_accounting`, `fill_rule_exploit`, and `clock_boundary`.
- `exploit_test_artifact_v1` includes per-world metrics, runtime audit output, probe results, probe status counts, pass/fail, and failure reasons.
- Missing required probe evidence remains `not_available` and blocks pass/fail success instead of being treated as a pass.
- Real checkpoint loading, world construction, Arena integration, statistical multi-seed significance tests, strict parent gate v2, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Strict Parent Gate v2

- Added `docs/tasks/model-training/strict-parent-gate-v2.md`.
- Added `app/services/strict_parent_gate.py`.
- Added `tests/runtime/test_strict_parent_gate.py`.
- Added `EvidenceArtifactWriter.write_parent_gate_artifact(...)`.
- Task 96 now creates a separate `parent_gate_artifact_v2`.
- Gate v2 requires experiment record completeness, checkpoint hash, lineage evidence, baseline artifact, calibration artifact, hidden-eval artifact, exploit-test artifact, and paired-sensitivity artifact.
- Gate v2 keeps `eligible_for_pbt_parent`, `eligible_for_checkpoint_promotion`, and `eligible_for_research_claim` separate.
- Live PBT parent selection, automatic checkpoint promotion, research acceptance lock v2, series aggregate, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Research Acceptance Lock v2

- Added `docs/tasks/model-training/research-acceptance-lock-v2.md`.
- Added `app/services/research_acceptance_lock.py`.
- Added `tests/runtime/test_research_acceptance_lock.py`.
- Task 97 now consumes `parent_gate_artifact_v2` instead of Arena leaderboard rank.
- Research claims are accepted only when the parent gate passes, `eligible_for_research_claim=True`, required evidence has no failures, required evidence hashes are present, and claim/candidate fields are present.
- The lock writes `research_acceptance_lock_v2` JSON records with status, failure reasons, required evidence, required evidence hashes, and `lock_hash`.
- Existing Arena research acceptance sections, report writing, series aggregate, GUI behavior, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Series Evidence Aggregate v1

- Added `docs/tasks/model-training/series-evidence-aggregate-v1.md`.
- Added `app/services/series_evidence_aggregate.py`.
- Added `tests/runtime/test_series_evidence_aggregate.py`.
- Task 98 now aggregates candidate evidence slots into `pass`, `fail`, `missing`, and `not_available`.
- The aggregate tracks baseline, calibration, hidden eval, exploit test, paired sensitivity, parent gate, and research acceptance lock evidence.
- The aggregate writes `series_evidence_aggregate_v1` JSON records with candidate summaries, status counts, evidence-kind status counts, `go_no_go`, failure reasons, and `aggregate_hash`.
- Long Arena dry run execution, live Arena report wiring, GUI Evidence Board, Evidence Contract Tests, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: GUI Evidence Board v1

- Added `docs/tasks/model-training/gui-evidence-board-v1.md`.
- Added `app/services/evidence_board_service.py`.
- Updated `app/panels/arena/panel.py`.
- Updated `app/ui/adapters/arena_adapter.py`.
- Added `tests/runtime/test_evidence_board_service.py`.
- Updated `tests/frontend/unit/test_arena_panel.py`.
- Task 99 now exposes an Arena `evidence_board` view derived from `series_evidence_aggregate_v1`.
- The board shows baseline, calibration, hidden, exploit, fee/impact sensitivity, parent eligible, and research claim eligible statuses.
- The board preserves `pass`, `fail`, `missing`, and `not_available` and includes debt metadata for not-available evidence.
- Full visual redesign, color-coded styling, artifact click-through, long Arena dry run, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Evidence Contract Tests v1

- Added `docs/tasks/model-training/evidence-contract-tests-v1.md`.
- Added `tests/runtime/test_evidence_contracts.py`.
- Task 100 now has a cross-runner contract test layer for schema, hash, seed, reproducibility, no-learning, and bad-policy rejection.
- Contract tests verify `world_spec_v1` canonical hash self-field exclusion and meaningful-change sensitivity.
- Contract tests verify `random_seed_ledger_v1` deterministic seed derivation and seed-ledger hash self-field exclusion.
- Contract tests verify separate evidence artifact common fields, reproducible artifact hash output, and artifact self-hash exclusion.
- Hidden-World, Paired Fee/Impact, and Exploit runners are jointly checked for `allow_learning=False`.
- A constructed bad-policy signal is rejected by `exploit_test_artifact_v1`, and `parent_gate_artifact_v2` rejects the candidate when exploit evidence fails.
- Pytest environment repair, long Arena dry run, GUI screenshot verification, PostgreSQL artifact persistence, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Long Arena Dry Run Package v1

- Added `docs/tasks/model-training/long-arena-dry-run-package-v1.md`.
- Added `app/services/long_arena_dry_run.py`.
- Added `tests/runtime/test_long_arena_dry_run.py`.
- Task 101 now has a hashable `long_arena_dry_run_package_v1` that joins a multi-generation series report summary,
  generation report hashes, `series_evidence_aggregate_v1`, Evidence Board rows, parent eligibility review, research
  acceptance review, `go_no_go`, failure reasons, and `package_hash`.
- Produced a deterministic headless package at `output/evidence_artifacts/long_arena_dry_run_package_v1/task101-headless-dry-run-6fb719d531f4c733.json`.
- Attempted the existing live `ArenaExperimentRunner` path, but the available runtime cannot import it because `sqlalchemy` is not installed.
- Rechecked the project `.venv` and sibling `Quent\.venv`; both point to a missing Python311 launcher, so neither can
  be used as a live Arena fallback.
- The live PostgreSQL/runtime long Arena series therefore remains blocked; the completed portion is the evidence-package boundary and headless package output, not a live database-backed run.
- Pytest environment repair, live long Arena run, GUI screenshot verification, PostgreSQL artifact persistence, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Evidence Runner Go / No-Go Review

- Added `docs/tasks/model-training/evidence-runner-go-no-go-review.md`.
- Applied the section 15 Go / No-Go criteria after Task 82-101 work.
- Recorded a No-Go decision for more complex model work.
- Reason: schema, runners, gate, aggregate, board, contract-test, and package boundaries exist, but the live
  PostgreSQL/runtime long Arena series remains blocked by the Python dependency environment.
- The headless Task 101 package is explicitly not accepted as live research evidence.
- Allowed next work is limited to dependency repair and re-running Task 101 through the live database-backed Arena path.
- Transformer, complex MARL, new alpha-claim routes, research claims based on the headless package alone, and PostgreSQL data deletion remain out of scope.

### Progress Update 2026-05-05: Model Route Gate v1

- Added `docs/tasks/model-training/model-route-gate-v1.md`.
- Added `app/services/model_route_gate.py`.
- Added `tests/runtime/test_model_route_gate.py`.
- Section 16 model-route guidance is now represented as a machine-readable `model_route_gate_v1` record.
- While Evidence Runner is No-Go, the gate allows current P0/P1 routes such as `ppo_lstm_v1` and rule baselines.
- While Evidence Runner is No-Go, the gate blocks advanced route tokens such as `transformer`, `gtrxl`, `marl`,
  `historical_replay`, `hybrid_env`, and `alpha_claim`.
- The gate writes allowed/blocked route status, failure reasons, and a canonical `route_gate_hash`.
- Direct registry/runtime enforcement, advanced model registration, research claims, and PostgreSQL data deletion remain out of scope.

## Suggested Immediate Sequence

1. Write the Alpha-to-Execution task card.
2. Inventory existing baseline support and add report slots before adding new learning logic.
3. Add world-card and calibration-score metadata to Arena experiment reports.
4. Add hidden-evaluation and exploit-detector result structures.
5. Tighten PBT parent eligibility to use the new evaluation/exploit fields.

## Explicitly Deferred

- Transformer / GTrXL upgrade.
- New world agent or generative order-flow model.
- Full replay/hybrid implementation.
- Alpha strategy claims based only on synthetic Arena profit.

These items are present in the expert review, but they are not the next safe step until Alpha-to-Execution, calibration, baselines, hidden evaluation, and exploit checks exist.
