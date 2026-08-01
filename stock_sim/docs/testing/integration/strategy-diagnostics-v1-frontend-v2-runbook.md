# Strategy Diagnostics V1 + Frontend V2 Wave 2 integration runbook

This runbook reproduces the Issue #65 source-level integration gate.
It does not claim T08, T09, or T10 and is not the Issue #66 installed offline
release-certification procedure.

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
`StrategyDiagnosticsV1DiagnosticTasksApplication` 1.0,
`DiagnosticTasksFeature` 1.0, `RunMonitoringFeature` 1.2, and
`EvidenceAndFindingsFeature` 1.1. It also rejects forbidden types and
substitutes across the exact persisted product tracer.

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

1. Seam 2, including unchanged-body live/fake conformance and static
   architecture in `test_diagnostic_tasks_live_fake_conformance.py`;
2. Seam 1, the source-bound file-backed tracer suite whose primary
   Application-to-QML path is
   `test_live_qml_tracer_recovers_retries_and_reopens_exact_evidence`, plus
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

Seam 3 remains owned by Issue #66. It must independently produce T08/T09/T10,
same-source QML and Widgets packages, clean-room reports, checksums, dependency
manifests, screenshots, logs, tag, assets, and remote verification before any
Wave 2 release certification is claimed.
