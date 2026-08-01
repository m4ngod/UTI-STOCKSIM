# Issue 65 source integration evidence

- Source candidate: `c88a6d9ce6e78121e9e2212a5832551f76385e3e`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Gate command: `python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate --temporary-parent C:\Temp`
- Gate result: all ten groups exited with status 0
- Standard error: empty

## Union gate

| Group | Result |
| --- | --- |
| Shared Feature conformance | 60 passed, 8 deselected |
| Persisted Application/QML tracer | 30 passed |
| Strategy Diagnostics V1 regression | 348 passed, 1 deselected |
| Lazy-import isolation | 1 passed |
| Frontend V2 contract | 187 passed, 21 deselected |
| Integration, E2E, accessibility | 71 passed, 1 deselected |
| Fresh-SQLite frontend unit | 299 passed |
| Fresh-SQLite EventBridge | 3 passed |
| No-manual-trading safety | 30 passed |
| Performance and packaging preflight | 124 passed |

The complete source-level gate ran continuously against the committed,
clean source candidate above. The raw stdout and empty stderr are retained
beside this summary.

## Focused checks

- The initial union run exposed an order-dependent wait in the existing
  production-QML Evidence contract: the backend Feature snapshot could become
  ready before its queued Qt projection displayed the same identities.
- The existing Seam was tightened to wait for both Feature readiness and the
  exact projected Evidence Package and Reproduction Manifest identities. No
  product behavior or new acceptance Seam was added.
- Exact formerly failing production-QML target: 1 passed.
- Full Frontend V2 contract group after the repair: 187 passed, 21 deselected.
- Gate contract plus V1 acceptance/surface classification: 27 passed.
- Targeted mypy for the integration gate and V1 surface classification:
  passed with no issues in 2 source files.
- Ruff and `py_compile` for the changed test: passed.
- `git diff --check`: passed; only Git line-ending notices were emitted.

## Renderer preflight

- Hardware smoke: schema 2, Direct3D11, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Hardware metrics: event-to-visible p95 8.6582 ms, input p95 0.7577 ms,
  usable state 717.4031 ms, peak working set 62.011719 MiB, maximum
  main-thread interval 9.8776 ms, terminal visible in 7.2249 ms.
- Software smoke: schema 2, Software renderer, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Software metrics: event-to-visible p95 9.146 ms, input p95 0.6118 ms,
  usable state 406.2092 ms, peak working set 41.515625 MiB, maximum
  main-thread interval 9.3346 ms, terminal visible in 8.3286 ms.
- Both lanes are bound to the same source candidate and observed
  `DiagnosticTasksFeature/1.0`,
  `StrategyDiagnosticsV1DiagnosticTasksApplication/1.0`, four accepted
  create/validate/approve/start command identities, three persistent
  TaskHandles, handoff identities, monotonic revisions, terminal completion,
  and zero manual-trading actions during active load.
- These are non-certifying source-level smoke probes. T08, T09, T10 and
  installed-offline release certification remain Issue 66 work.

## Review and scope

- Fixed review base: `a44ff6ccbc7ccd16ce0260a03c69eb241a6dc7d6`.
- Standards review: PASS, no findings.
- Spec review: PASS, no findings.
- Active Feature Interfaces remain exactly Diagnostic Tasks 1.0, Run
  Monitoring 1.2, and Evidence & Findings 1.1.
- Diagnostic Tasks Application remains 1.0; the existing read model remains
  1.0.
- Issue 65 changed no Interface version and no persistence schema.
- Issue 65 added no product capability. Its only source-candidate change
  makes the existing production-QML contract wait for its queued projection.
- Legacy Widgets and routes remain present.
- No manual-trading capability is present.
- Strategy Library, Scenario Lab, System Health, the complete Journey Rail,
  and Waves 3–4 remain unimplemented.
