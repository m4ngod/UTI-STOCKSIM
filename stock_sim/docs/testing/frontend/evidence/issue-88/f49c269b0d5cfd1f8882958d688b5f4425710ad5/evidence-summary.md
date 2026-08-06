# Issue 88 installed offline five-Feature release certification

## Immutable candidate

- Issue: <https://github.com/m4ngod/UTI-STOCKSIM/issues/88>
- Frozen product source:
  `f49c269b0d5cfd1f8882958d688b5f4425710ad5`
- Source tree:
  `c483f66c3ed82a25e34c2f60ad6363ac8c73b734`
- Product-source PR and ordinary merge:
  <https://github.com/m4ngod/UTI-STOCKSIM/pull/104>,
  `4ff597da24035448910b188cd4dbd1b18ed7d6d0`
- Issue 87 evidence commit, PR, and ordinary merge:
  `cb383b1112f715f460f234d170f14740b4efc481`,
  <https://github.com/m4ngod/UTI-STOCKSIM/pull/105>,
  `62c4b6a9bc8758af19160becac1c116722affa75`
- Release tag:
  `strategy-diagnostics-v1-frontend-v2-wave3-rc-f49c269b0d5c`
- GitHub prerelease:
  <https://github.com/m4ngod/UTI-STOCKSIM/releases/tag/strategy-diagnostics-v1-frontend-v2-wave3-rc-f49c269b0d5c>

Issue 88 changed no product source, Feature Interface version, Application
Interface, or persistence schema. It certifies the immutable product source
frozen by Issue 87 and retains the resulting installed evidence.

## Locked toolchain and packages

The candidate was built with Python 3.11.9, PySide6 6.9.1, Qt 6.9.1,
NumPy 2.3.1, and Nuitka 2.6.8. The sealed dependency lock digest is
`sha256:f53b1b7245e48a33420ee7a2657c7d7bedc35a61cefbe0fc86ce0a1232bfaf1f`.
The dependency inventory, exact import closure, and both Nuitka reports are
retained.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `qml-journey-f49c269b0d5c.zip` | 143490033 | `3903c9b1cd7535fd6abe7f73581603fd1fb48643d7e8d671601b4d358f2b7f87` |
| `widgets-rollback-f49c269b0d5c.zip` | 133606793 | `cb2dcc91856ebaa7163dace7a7984b297f71942e9251649b30572f8964c30ad5` |

The two archives were built from the same frozen source. An independent
3,878-file inventory found zero missing, extra, or mismatched installed
files. The source and automated QML import scans passed, the packaged
WebEngine/WebView set is empty, and the QML packaging delta is 31,392,302
bytes, below the 52,428,800-byte limit. Both Nuitka dependency audits and
the forbidden-surface safety checks passed.

## Mandatory gates

- T08 accessibility: 16 passed, with no failures, errors, or skips. JUnit
  SHA-256:
  `cef70e3c6282f1a5ff1d159af685ffcfe0b5b124e2019e38dc852fc84893506d`.
- T09 no-manual-trading: passed. Report SHA-256:
  `a4093e1dd8d64a42ab402742818f4e7998e1d6a19263fcb89fe1b40d7bc9b062`.
- T10 performance: certified. Aggregate SHA-256:
  `84309568c0b225cbdd22ef658bf6538372fad28efe3c2d314a17a01591a39265`.
- Mandatory gate manifest SHA-256:
  `67b64fe118f74aa9f89cb5d28523b5a099ac876456796c86ca769c953adb7395`.
- Clean-room report SHA-256:
  `a1aac14fd003dde01f0f07ed92c0eda65625f81653ded561436435106a0474f0`.
- Toolchain identity SHA-256:
  `0868789918094ea360bf7a636d90a15f655e60725a0c2dd700f4fb05af1eb737`.

Both T10 lanes ran continuously for at least 60 seconds with zero runtime
errors, zero manual-trading actions, zero stalls over budget, strictly
monotonic revisions, and a visible terminal state:

| Lane | Duration | Visible p95 | Input p95 | Usable state | Max stall | Peak RSS | Terminal visible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct3D 11 | 60.003481 s | 17.5311 ms | 0.6573 ms | 621.3969 ms | 30.7114 ms | 83.824219 MiB | 15.9732 ms |
| Software | 60.000742 s | 18.0488 ms | 0.5795 ms | 396.7445 ms | 30.2349 ms | 39.398438 MiB | 9.8854 ms |

The same frozen source passed the final focused release regression: 178
packaging-contract, release-candidate, performance-certification, and
no-manual-trading tests in 847.27 seconds. Issue 87's exact-source union gate
also remains green: 1,467 passed and one optional `openpyxl` skip across
1,468 collected tests. Shared live/fake conformance, the public type graph,
security, QML import, accessibility, performance, and the complete Wave 2
regression were included in that gate.

## Installed Windows 11 clean room

Windows Sandbox returned exit code 0 on Microsoft Windows 11 Enterprise
10.0.26100 AMD64 under `WDAGUtilityAccount`. The report records:

- no network adapters up;
- no Python or compiler available;
- no dependency cache;
- successful offline installation of both same-source archives;
- successful Direct3D 11 and Software renderer lanes;
- a real, read-only Widgets rollback launch with eight panels, no
  placeholders, zero manual-trading actions, and clean exit.

Both installed renderer lanes used the production path:

`DiagnosticsApplication`
→ `FileBackedV1Persistence`
→ `LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter`
→ `LiveStrategyLibraryAdapter`
→ `LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter`
→ `LiveScenarioLabAdapter`
→ `LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter`
→ `LiveDiagnosticTasksAdapter`
→ `LiveStrategyDiagnosticsV1ApplicationAdapter`
→ `EventBridge`
→ `LiveRunMonitoringAdapter`
→ `LiveEvidenceAndFindingsAdapter`
→ `JourneyWorkspaceHost`.

Each lane began at the authoritative Strategy Under Test inventory and
verified the complete installed five-Feature chain:

- formal Strategy Under Test comparison and selection;
- admitted historical data and Market Scenario projections;
- Recipe Draft creation, exact validation, approval, and immutable version;
- Reference Market Path materialization with a persistent TaskHandle;
- Formal Campaign Scenario Set composition and typed Diagnostic Tasks
  handoff;
- persisted Diagnostic Task and Formal Diagnostic Campaign creation;
- exact strategy, guardrail, recipe, path, case, task, campaign, run,
  Evidence Package, and Reproduction Manifest identity continuity;
- route remount, disconnect/reconnect, old-generation quarantine, and
  Application reopen before terminal continuation;
- terminal identity immutability, zero manual trading, and clean exit.

Raw installed reports and screenshots are retained in `hardware/`,
`software/`, and `smoke/`. The raw build logs are not committed; their sizes
and hashes are recorded in `retained-log-checksums.json`.

## Remote release verification

The published prerelease is non-draft and points to the exact frozen source.
Its lightweight tag resolves directly to
`f49c269b0d5cfd1f8882958d688b5f4425710ad5`. GitHub reports exactly two
uploaded assets. For both archives, the GitHub server digest, local source
digest, reconstructed full public-download digest, and byte size match.
Independent public HTTP 206 probes of the start, middle, and tail 1,024-byte
ranges also match local bytes. `release-asset-verification.json` records the
asset IDs, stable URLs, complete range coverage, sizes, and digests.

## Interface, schema, review, and scope

The active production Feature Interface registry is exactly:

- `StrategyLibraryFeature 1.0`
- `ScenarioLabFeature 1.0`
- `DiagnosticTasksFeature 1.0`
- `RunMonitoringFeature 1.2`
- `EvidenceAndFindingsFeature 1.1`

Strategy Library and Scenario Lab remain separate typed Feature Interfaces
with separate live/fake Adapters. The Issue 80 migrations remain
`0019_scenario_recipe_dependency_bindings` and
`0020_scenario_lab_commands_and_materialization_handles`; the Issue 84
migration remains `0021_diagnostic_selection_dependency_invalidation`.
Issue 88 added no migration or contract change.

The final Standards review and Spec review both passed with zero blocking
findings after validating the immutable source, installed evidence, Release,
and remote assets. Backend-owned truth, immutable typed presentation state,
AppContext composition, QML-only Feature dependencies, shared unchanged-body
live/fake conformance, and the five-Feature persisted tracer remain intact.

No manual-trading capability or AI-generated/modified diagnostic evidence is
present. Legacy Widgets remains installed and certified. System Health, the
complete six-destination Journey Rail, Wave 4, manual trading, and legacy
Widgets deletion were not started and remain outside this candidate.
