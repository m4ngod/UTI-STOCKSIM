# Strategy Diagnostics V1 + Frontend V2 Wave 3 integration runbook

This runbook reproduces the incremental Wave 3 source-level integration gate,
including Issues #77–#84 and the inherited Wave 2 union. It does not claim T08, T09, or T10
and is not the Issue #88 installed offline release-certification
procedure.

## Preconditions

- Use a clean independent worktree.
- Use the repository-pinned Python 3.11 / Qt / packaging toolchain.
- Keep `QT_QPA_PLATFORM=offscreen` and `QT_QUICK_BACKEND=software` for the
  deterministic software-renderer lane.
- Do not reuse an embedded interpreter for the clean lazy-import isolation
  check; its `_pth` startup preload changes that test's premise.

## Static validation

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate `
  --validate-only
```

This validates the checked-in union manifest, both contract documents, the
`StrategyDiagnosticsV1ApplicationReadModel` 1.0 boundary,
`StrategyDiagnosticsV1StrategyLibraryApplication` 1.0,
`StrategyDiagnosticsV1ScenarioLabApplication` 1.0,
`StrategyDiagnosticsV1DiagnosticTasksApplication` 1.0,
`StrategyLibraryFeature` 1.0, `ScenarioLabFeature` 1.0,
`DiagnosticTasksFeature` 1.0,
`RunMonitoringFeature` 1.2, and
`EvidenceAndFindingsFeature` 1.1. It also rejects forbidden types and
substitutes across the exact persisted product tracer.
For Issue #78 it also binds public formal-set validation, explicit comparison
dimensions, exact immutable selection references, durable bookmark reread,
typed stale/conflict/unavailable recovery, and focus restoration.
For Issue #79 it binds admitted Historical Segment, immutable Reference Path,
Campaign Case, Transformation Catalog, bounded preview, reconstruction honesty,
typed unavailable write capability, and the exact five-Feature registry.
For Issue #84 it also binds the exact independent Strategy/Scenario setup
selection, unchanged Diagnostic Tasks 1.0 configuration, migration 0021,
validation/approval dependency hashes, successor invalidation, and start
fail-closed behavior. The handoff exercises frozen typed inputs through the
five existing Diagnostic Tasks operations, with no additional Feature or
Application operation. An AppContext-owned immutable setup coordinator feeds
both adapters for task reread; only explicit typed variants carry setup identity
into a command. The live reread proves invalidation through the public backend
task-read path, an unknown current setup fails closed, and legacy base-command
replays remain binding-free across coordinator changes.

## Gate execution

Run every group:

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate
```

On Windows hosts where file scanners contend with repeated DuckDB Parquet
publishes, use an existing short temporary root outside the checkout:

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate `
  --temporary-parent C:\Temp
```

The override fails closed unless the supplied path is an existing directory.
It changes only the isolated pytest and SQLite scratch location; the checked-in
groups, product persistence adapters, and source candidate remain unchanged.

Run one reproducible group while investigating:

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate `
  --group persisted-application-qml-tracer
```

The gate deliberately uses separate pytest processes for:

1. Seam 2, including unchanged-body Strategy Library conformance in
   `test_strategy_library_live_fake_conformance.py`, unchanged-body Scenario
   Lab conformance in `test_scenario_lab_live_fake_conformance.py`, inherited Diagnostic Tasks
   conformance in `test_diagnostic_tasks_live_fake_conformance.py`, and static
   architecture. The Strategy Library body includes exact comparison/selection,
   idempotency, source conflict, bookmark reopen, and capability truth;
2. Seam 1, the source-bound file-backed tracer suite whose primary
   Application-to-QML path is
   `test_live_qml_tracer_recovers_retries_and_reopens_exact_evidence`, plus
   `test_live_strategy_library_traces_public_inventory_into_qml` for the real
   public inventory-to-production-QML slice, and
   `test_real_backend_inventory_traces_through_live_feature_into_qml` for real
   admission → approved Recipe → Reference Path → Campaign Case → production
   Scenario Lab QML tracing, and
   `test_live_exact_setup_selection_is_bound_through_approval` for exact
   Strategy + Scenario selection → task validation/approval → successor
   invalidation and start rejection, and
   exact live targets for input/revision, command/idempotency, lifecycle/retry,
   connection-generation, disposal, and no-late-callback edges;
3. Strategy Diagnostics V1 regression under the pinned interpreter;
4. root-package lazy-import isolation under a clean system Python 3.11;
5. Frontend V2 contract;
6. Frontend V2 integration, E2E, and accessibility;
7. Frontend V2 unit tests against a fresh temporary SQLite database;
8. EventBridge unit tests in their own fresh-database process;
9. no-manual-trading safety;
10. performance and packaging preflight, including the typed Diagnostic Tasks
    command and persistent `TaskHandle` observation load.

The gate creates and removes the temporary unit-test databases itself. On
Windows it uses the `py -3.11` launcher for the lazy-import probe because the
pinned embedded interpreter intentionally preloads the checkout through its
startup path; on other platforms it uses the invoking interpreter.

Any non-zero group stops the gate. Record the exact commit, interpreter and
dependency versions, command, pass/fail counts, elapsed time, and any isolated
rerun needed to distinguish a deterministic failure from a renderer timing
flake.

## Manual audit

- Verify the visible and accessibility identities match the durable campaign,
  case, run, strategy, recipe, evidence-package, manifest, artifact, metric,
  comparison, curve, breakpoint, and finding records.
- Verify Run-to-Evidence and back navigation, keyboard focus, Narrator status,
  chart narrative/table revision synchronization, 200% scale, reduced motion,
  high contrast, disconnect/reconnect announcements, terminal state, remount,
  and clean close.
- Search the changed source for manual-trading commands, direct QML data
  injection, dictionary-based live certification fixtures, HTTP/IPC, and new
  Feature Interfaces.
- Verify the Strategy Library route exposes only the two backend-declared
  formal entries and preserves exact source, manifest, Guardrail, dependency,
  status, revision, freshness, and generation facts across search, filtering,
  disconnect, reconnect, and remount.
- Compare the formal set and verify source identity/hash, capabilities,
  Guardrail thresholds, and dependency provenance are visible without scores,
  ranks, or recommendations. Select it, restart through a fresh `AppContext`,
  and verify the persisted exact references and focused Strategy are restored
  only after authoritative validation.
- Verify Scenario Lab shows exact admitted segment/content/source identities,
  provenance and coverage; a verified content-addressed Reference Path with
  bounded preview and explicit reconstruction notice; and a separate backend
  `CampaignCaseId` Market Scenario identity. Confirm effective execution is
  `not_yet_resolved` and all Recipe/materialization/composition actions are
  typed unavailable in Issue #79.
- Verify the Diagnostic Tasks route remains disabled until both current formal
  selections exist, displays the exact selection/set/resolution/revision/source
  identities, and creates the unchanged typed task configuration. After an
  upstream successor, verify the prior validation and approval remain in
  history, the active task returns to Draft, and start fails closed.

Wave 3 Seam 3 remains owned by Issue #88. It must independently produce T08/T09/T10,
same-source QML and Widgets packages, clean-room reports, checksums, dependency
manifests, screenshots, logs, tag, assets, and remote verification before any
Wave 3 release certification is claimed. Issue #66 remains the immutable Wave 2
certification baseline.
