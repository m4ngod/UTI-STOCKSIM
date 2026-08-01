# Issue 65 source integration evidence

- Source candidate: `e960dee9872aae36d81496ccdaa8047c01b31f50`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Gate command: `python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate --temporary-parent C:\Temp`
- Gate result: all ten groups exited with status 0
- Standard error: empty

## Union gate

| Group | Result |
| --- | --- |
| Shared Feature conformance | 60 passed, 8 deselected |
| Persisted Application/QML tracer | 30 passed |
| Strategy Diagnostics V1 regression | 345 passed, 1 deselected |
| Lazy-import isolation | 1 passed |
| Frontend V2 contract | 186 passed, 21 deselected |
| Integration, E2E, accessibility | 71 passed, 1 deselected |
| Fresh-SQLite frontend unit | 299 passed |
| Fresh-SQLite EventBridge | 3 passed |
| No-manual-trading safety | 30 passed |
| Performance and packaging preflight | 124 passed |

The complete source-level gate ran continuously against the candidate above.
The raw stdout and empty stderr are retained beside this summary.

## Focused checks

- Hardware smoke: schema 2, Direct3D11, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Software smoke: schema 2, Software renderer, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Both lanes observed `DiagnosticTasksFeature/1.0`,
  `StrategyDiagnosticsV1DiagnosticTasksApplication/1.0`, create/validate/
  approve/start command identities, persistent TaskHandle identities, handoff,
  and terminal completion during active load.
- Gate contract tests: 16 passed.
- V1 acceptance and surface classification: 12 passed.
- Recovered headless and GUI V1 acceptance workflows: 2 passed.
- Exact fresh-SQLite unit gate group after classification: 299 passed.
- Ruff: passed on Issue 65 files, with only inherited unrelated I001/C413
  findings excluded for `v1_acceptance.py` and its existing test module.
- Targeted mypy: passed for the gate and V1 acceptance source files.
- `git diff --check`: passed; only Git line-ending notices were emitted.

## Review and scope

- Standards review: passed after all material findings were fixed.
- Spec review: passed after all material findings were fixed.
- Active Feature Interfaces remain exactly Diagnostic Tasks 1.0, Run
  Monitoring 1.2, and Evidence & Findings 1.1.
- Diagnostic Tasks Application remains 1.0.
- No Interface version or persistence schema changed in Issue 65.
- No product capability was added by the final integration fixes.
- Legacy Widgets and routes remain present.
- No manual-trading capability is present.
- This is source-level integration and preflight evidence only. Installed
  offline certification, T08, T09, T10, release tags, and release assets remain
  owned by Issue 66.
