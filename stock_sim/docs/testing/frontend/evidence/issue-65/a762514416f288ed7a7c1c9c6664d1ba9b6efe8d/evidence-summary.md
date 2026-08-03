# Issue 65 source integration evidence

- Immutable source candidate:
  `a762514416f288ed7a7c1c9c6664d1ba9b6efe8d`
- Source tree: `698cb76e1deb1b987b2c2847d5edb60967d36cff`
- Candidate parent / fixed ticket review base:
  `4cbd038b267505fb0eb497f5ba8d64f05433e565`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Gate command:
  `python -m stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate --temporary-parent F:\PythonProjects`
- Gate result: all ten groups exited with status 0
- Standard error: empty
- Warning summary: none

## TDD and gate corrections

The first complete run against the accepted Issue 64 source established two
observable failures in existing Issue 65 gates. Neither correction adds
product behavior.

1. The first run passed shared conformance and the persisted tracer, then
   failed Strategy Diagnostics V1 regression with 12 failures and 45 errors.
   The installed-source test copied the checkout's ignored `tmp` scratch tree
   (362,325 files / 99.02 GiB) into its isolated source root, exhausting the
   configured `C:\Temp` volume. The existing installed-package source-copy
   Seam now excludes the repository-defined `tmp` runtime scratch root.
   The exact installed-package target passed, its complete file passed
   2 tests, and the complete V1 regression group passed 361 tests with
   1 deselected.
2. The next continuous run passed the first six groups, then fresh-SQLite
   frontend unit reported 3 failures because the authoritative public
   Application inventory classified
   `read_diagnostic_campaign_case_inventory` as unknown. That read method was
   already delivered by Issue 56. It is now explicitly classified as a Wave 2
   allowed command without becoming a V1 required command. The strengthened
   classification test first failed, then the focused set passed 4 tests, the
   V1 acceptance file passed 11 tests, fresh-SQLite frontend unit passed
   300 tests, and V1 regression again passed 361 tests with 1 deselected.

The fixed source candidate then passed the complete continuous union gate
below. No fourth highest-level Test Seam was introduced.

## Immutable-candidate union gate

| Group | Result |
| --- | --- |
| Shared Feature conformance | 61 passed, 8 deselected |
| Persisted Application/QML tracer | 30 passed |
| Strategy Diagnostics V1 regression | 361 passed, 1 deselected |
| Lazy-import isolation | 1 passed |
| Frontend V2 contract | 188 passed, 21 deselected |
| Integration, E2E, accessibility | 73 passed, 1 deselected |
| Fresh-SQLite frontend unit | 300 passed |
| Fresh-SQLite EventBridge | 4 passed |
| No-manual-trading safety | 30 passed |
| Performance and packaging preflight | 152 passed |

Every group exited 0 in one continuous run against the committed, clean
candidate. The final performance and packaging group completed in
385.33 seconds. Raw stdout and empty stderr are retained beside this summary.

## Types and quality

- Static union-manifest validation: passed.
- Strict mypy for the integration gate and V1 surface-classification source:
  success, no issues in 2 files (`--follow-imports=skip`).
- `py_compile` passed for the changed Python files.
- `git diff --check` passed.
- Ruff was not installed in either pinned repository environment, so the
  dependency set was not changed to add it.

## Hardware/software source preflight

Both reports are schema 2, bind the candidate source and locked
Python/PySide6/Qt/NumPy/Nuitka toolchain, use the same fixture and
toolchain-lock digests, observe strictly monotonic revisions, four accepted
create/validate/approve/start command identities, three TaskHandle identities,
exact handoff identities, terminal completion, zero errors, zero stalls over
budget, and zero manual-trading actions during active load. TaskHandle
persistence is covered by the real persisted tracer group, not inferred from
these source-smoke reports.

- Hardware: Direct3D11; event-to-visible p95 8.7868 ms; input p95
  0.6720 ms; usable state 512.0532 ms; peak 49.515625 MiB; maximum
  main-thread interval 11.4663 ms; terminal visible 7.3484 ms.
- Software: Software renderer; event-to-visible p95 7.8238 ms; input p95
  0.6249 ms; usable state 290.0164 ms; peak 32.160156 MiB; maximum
  main-thread interval 9.6514 ms; terminal visible 7.8238 ms.

These are truthful source-level `smoke` preflights. T08, T09, T10 and
installed-offline release certification are not claimed here and remain
Issue 66 work.

## Review and scope

- Standards review against the fixed ticket base: PASS, no findings.
- Spec review against Issues 65 and 54 plus the final Issue 64 acceptance:
  PASS, no findings.
- Active Feature Interfaces remain exactly Diagnostic Tasks 1.0, Run
  Monitoring 1.2, and Evidence & Findings 1.1.
- Diagnostic Tasks Application remains 1.0; the existing read model remains
  1.0.
- Issue 65 changes no Interface version and no persistence schema.
- Issue 65 adds no product capability. Its two candidate commits only stabilize
  the existing installed-source staging boundary and classify an already
  existing Wave 2 read method.
- The authoritative file-backed product tracer and shared live/fake
  conformance remain the existing highest-level source Seams.
- Legacy Widgets and legacy routes remain present.
- No manual-trading capability is present.
- Strategy Library, Scenario Lab, System Health, the complete Journey Rail,
  and Waves 3–4 remain unimplemented.
