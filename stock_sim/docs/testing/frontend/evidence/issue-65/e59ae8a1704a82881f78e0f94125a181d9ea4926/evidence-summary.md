# Issue 65 source integration evidence

- Source candidate: `e59ae8a1704a82881f78e0f94125a181d9ea4926`
- Source tree: `63ea0063ca74e2e5fc158589fbbfbfdbf386b286`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Fixed review base: `98d95ee2492c5087e2506ea671d96bbbb440fc46`
- Gate command: `python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate --temporary-parent C:\Temp`
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
| Performance and packaging preflight | 127 passed |

The complete source-level gate ran continuously against the committed,
clean source candidate above. The raw stdout and empty stderr are retained
beside this summary. The performance and packaging group completed in
1605.20 seconds and emitted no warnings.

## TDD and focused checks

- Red: the first full union run against the pre-#65 candidate completed with
  two `PytestUnhandledThreadExceptionWarning` instances. A clean-room
  negative test allowed a localized PowerShell error stream to crash
  `subprocess` reader threads while decoding as UTF-8.
- Green: the existing clean-room packaging Test Seam now decodes captured
  subprocess text with `errors="backslashreplace"`. Return-code checks,
  cleanup boundaries, and preservation assertions are unchanged.
- Exact clean-room reset target with reader-thread warnings treated as errors:
  1 passed.
- The target plus its eight preceding packaging-contract neighbors with
  reader-thread warnings treated as errors: 9 passed.
- Full immutable-candidate union rerun: all ten groups exited 0; the
  performance and packaging group reported 127 passed with no warnings.
- Ruff passed for the changed test after excluding only its inherited,
  unrelated `F401`, `RUF100`, `ISC004`, and `UP012` findings.
- `py_compile` passed for the changed test.
- Targeted mypy passed with no issues in the integration gate and V1
  surface-classification source files.
- `git diff --check` passed.

## Renderer preflight

- Hardware smoke: schema 2, Direct3D11, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Hardware metrics: event-to-visible p95 8.9205 ms, input p95 0.5662 ms,
  usable state 523.2160 ms, peak working set 53.554688 MiB, maximum
  main-thread interval 9.2103 ms, terminal visible in 6.7223 ms.
- Software smoke: schema 2, Software renderer, status `smoke`, no errors, no
  main-thread stalls over budget, manual-trading action count 0.
- Software metrics: event-to-visible p95 8.5200 ms, input p95 0.5807 ms,
  usable state 271.0674 ms, peak working set 35.914062 MiB, maximum
  main-thread interval 7.0983 ms, terminal visible in 7.9975 ms.
- Both reports are bound to the same source candidate and observe
  `DiagnosticTasksFeature/1.0`,
  `StrategyDiagnosticsV1DiagnosticTasksApplication/1.0`, four accepted
  create/validate/approve/start command identities, three TaskHandles,
  handoff identities, monotonic revisions, terminal completion, and zero
  manual-trading actions during active load.
- These are non-certifying source-level smoke probes. T08, T09, T10 and
  installed-offline release certification remain Issue 66 work.

## Review and scope

- Standards review: PASS, no findings.
- Spec review: PASS, no findings.
- Active Feature Interfaces remain exactly Diagnostic Tasks 1.0, Run
  Monitoring 1.2, and Evidence & Findings 1.1.
- Diagnostic Tasks Application remains 1.0; the existing read model remains
  1.0.
- Issue 65 changed no Interface version and no persistence schema.
- Issue 65 added no product capability. Its only candidate change hardens
  decoding in the existing clean-room packaging test.
- The authoritative file-backed product tracer and shared live/fake
  conformance remain the existing highest-level source seams; no fourth
  acceptance seam was added.
- Legacy Widgets and routes remain present.
- No manual-trading capability is present.
- Strategy Library, Scenario Lab, System Health, the complete Journey Rail,
  and Waves 3–4 remain unimplemented.
