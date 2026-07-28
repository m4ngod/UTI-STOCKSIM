# Strategy Diagnostics V1 + Frontend V2 integration runbook

This runbook reproduces the Issue #52 integration quality gate. It is not the
Issue #53 release-certification procedure.

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
Application read-model 1.0 boundary, the Run Monitoring 1.2 and Evidence &
Findings 1.1 two-interface registry, and the absence of synthetic dictionary
producers across the persisted Application-to-QML tracer's complete source
closure.

## Gate execution

Run every group:

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate
```

Run one reproducible group while investigating:

```powershell
python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate `
  --group persisted-application-qml-tracer
```

The gate deliberately uses separate pytest processes for:

1. shared fake/live Feature conformance and static architecture;
2. the file-backed persisted Application-to-QML tracer;
3. Strategy Diagnostics V1 regression under the pinned interpreter;
4. root-package lazy-import isolation under a clean system Python 3.11;
5. Frontend V2 contract;
6. Frontend V2 integration, E2E, and accessibility;
7. Frontend V2 unit tests against a fresh temporary SQLite database;
8. EventBridge unit tests in their own fresh-database process;
9. no-manual-trading safety;
10. performance and packaging contracts.

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

Issue #53 must independently produce the specified T08/T09/T10, package,
sandbox, rollback, and release artifacts before any release certification is
claimed.
