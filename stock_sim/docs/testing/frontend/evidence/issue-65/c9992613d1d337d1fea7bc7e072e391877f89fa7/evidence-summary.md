# Issue 65 source integration evidence

- Source candidate: `c9992613d1d337d1fea7bc7e072e391877f89fa7`
- Source tree: `a52033f861ac1154c342b40bf42b6c0897b244f5`
- Candidate parent / fixed review base:
  `9a96baeb191fa3d4d32d66638472cf59da6f36de`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Gate command:
  `python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate --temporary-parent C:\Temp`
- Gate result: all ten groups exited with status 0
- Standard error: empty
- Warning summary: none

## Union gate

| Group | Result |
| --- | --- |
| Shared Feature conformance | 60 passed, 8 deselected |
| Persisted Application/QML tracer | 30 passed |
| Strategy Diagnostics V1 regression | 348 passed, 1 deselected |
| Lazy-import isolation | 1 passed |
| Frontend V2 contract | 187 passed, 21 deselected |
| Integration, E2E, accessibility | 72 passed, 1 deselected |
| Fresh-SQLite frontend unit | 299 passed |
| Fresh-SQLite EventBridge | 3 passed |
| No-manual-trading safety | 30 passed |
| Performance and packaging preflight | 128 passed |

The complete source-level gate ran continuously against the committed, clean
source candidate above. The final performance and packaging group completed
in 1919.59 seconds. The raw stdout and empty stderr are retained beside this
summary.

## TDD and focused checks

- Red: the first complete union run against the accepted Issue #64 source
  `9a96baeb191fa3d4d32d66638472cf59da6f36de` passed the first nine groups.
  The final group reported 127 passed and one failure because the source
  dependency assertion still required `QtQuick.Shapes 1.15` after the
  accepted Canvas renderer migration removed that import.
- Green: the existing source-driven dependency contract removed only the
  obsolete Shapes tuple. Exact equality against the discovered project QML
  imports, WebEngine rejection, and the independent transitive
  `pyside6-qmlimportscanner` closure remain unchanged.
- The exact dependency scan and transitive-closure targets passed: 2 passed.
- The committed candidate then passed the complete ten-group union gate above.
- Static union-manifest validation passed.
- Targeted strict mypy passed with no issues in the integration gate and
  established V1 surface-classification sources, using
  `--follow-imports=skip` to exclude unchanged legacy implementation debt.
- Ruff passed for the changed packaging test after excluding only its
  inherited unrelated `F401`, `RUF100`, `ISC004`, and `UP012` findings.
- `py_compile` passed for the changed test and relevant release modules.
- `git diff --check` passed.

## Renderer preflight

- Hardware smoke: schema 2, Direct3D11, status `smoke`, source commit
  `c9992613d1d337d1fea7bc7e072e391877f89fa7`, no errors, no main-thread
  stalls over budget, and zero manual-trading actions.
- Hardware metrics: event-to-visible p95 9.0799 ms, input p95 0.8304 ms,
  usable state 575.4501 ms, peak working set 50.253906 MiB, maximum
  main-thread interval 10.6399 ms, and 16 visible revisions.
- Software smoke: schema 2, Software renderer, status `smoke`, source commit
  `c9992613d1d337d1fea7bc7e072e391877f89fa7`, no errors, no main-thread
  stalls over budget, and zero manual-trading actions.
- Software metrics: event-to-visible p95 7.6988 ms, input p95 0.6891 ms,
  usable state 299.7292 ms, peak working set 32.566406 MiB, maximum
  main-thread interval 6.9007 ms, and 16 visible revisions.
- Both reports observe `DiagnosticTasksFeature/1.0`,
  `StrategyDiagnosticsV1DiagnosticTasksApplication/1.0`, four accepted
  create/validate/approve/start command identities, three TaskHandles,
  handoff identities, monotonic revisions, terminal completion, and zero
  manual-trading actions during active load.
- These are non-certifying source-level smoke probes. T08, T09, T10 and
  installed-offline release certification remain Issue #66 work.

## Review and scope

- Standards review against the fixed base: PASS, no findings.
- Spec review against Issues #65, #54 and the final #64 acceptance: PASS, no
  findings.
- Active Feature Interfaces remain exactly Diagnostic Tasks 1.0, Run
  Monitoring 1.2, and Evidence & Findings 1.1.
- Diagnostic Tasks Application remains 1.0; the existing read model remains
  1.0.
- Issue #65 changed no Interface version and no persistence schema.
- Issue #65 added no product capability. Its only source-candidate change
  aligns the existing packaging contract with the accepted Canvas renderer.
- The authoritative file-backed product tracer and shared live/fake
  conformance remain the existing highest-level source seams; no fourth
  acceptance seam was added.
- Legacy Widgets and routes remain present.
- No manual-trading capability is present.
- Strategy Library, Scenario Lab, System Health, the complete Journey Rail,
  and Waves 3–4 remain unimplemented.
