# Issue 66 installed offline release certification

## Immutable candidate

- Issue: <https://github.com/m4ngod/UTI-STOCKSIM/issues/66>
- Frozen product source and formal `master` commit:
  `f3e7c2a45bb32b512bb9ce045208dc508b0851bc`
- Source tree:
  `36809cb268f4cf98e848d8a0613f1d3bc959be98`
- Integration branch: `codex/wave2-diagnostic-tasks`
- Product history promotion:
  <https://github.com/m4ngod/UTI-STOCKSIM/pull/74>
- Release tag:
  `strategy-diagnostics-v1-frontend-v2-wave2-rc-f3e7c2a45bb3`
- GitHub prerelease:
  <https://github.com/m4ngod/UTI-STOCKSIM/releases/tag/strategy-diagnostics-v1-frontend-v2-wave2-rc-f3e7c2a45bb3>

Issue 66 changed no product source, Interface version, or persistence schema.
It certifies the immutable source promoted by Issue 65 and retains the
resulting evidence.

## Locked toolchain and packages

The candidate was built with Python 3.11.9, PySide6 6.9.1, Qt 6.9.1,
NumPy 2.3.1, and Nuitka 2.6.8. The sealed toolchain lock digest is
`sha256:f53b1b7245e48a33420ee7a2657c7d7bedc35a61cefbe0fc86ce0a1232bfaf1f`.
The dependency inventory and both Nuitka reports are retained.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `qml-journey-f3e7c2a45bb3.zip` | 215638255 | `75a9dbc884dbcc513acd936d0567a94f02ecb78efdc466fe7370ecded9478070` |
| `widgets-rollback-f3e7c2a45bb3.zip` | 200485698 | `83a748d2fb850b69f8083ea5275a7315a453aa78bac50fea22cc1ff4c02d7a97` |

The two archives were built from the same source. Packaged hardware,
software, and Widgets smoke checks passed before clean-room install.
QML dependencies were discovered from both a source import scan and the
automated `pyside6-qmlimportscanner` closure; the retained renderer report
binds both scan digests to the candidate. Both Nuitka dependency audits
passed, the packaged WebEngine/WebView file set is empty, and the packaging
and safety gates rejected the forbidden network, process, development,
production-fake, and transaction-bearing surfaces.

## Mandatory gates

- T08 accessibility: 18 passed in 31.70 seconds. JUnit SHA-256:
  `71aac981f23a53525857a7345e79c25dbc147772c79e4ff7d0b8feca8369122c`.
- T09 no-manual-trading: passed. Report SHA-256:
  `13c2e8fd0cb24eed54b50cf0ce671daad190626438ae0f488de3b8c64251243f`.
- T10 performance: certified. Aggregate SHA-256:
  `5492f7cff8adc2433bf34e9ad2cdf1a58545827450c269552b493a2f8ecc80c9`.
- Mandatory gate manifest SHA-256:
  `79e15f4015ca201125b452c1852c6886d842e7ee924b078090874b017cb6cee2`.

Both T10 lanes ran continuously for at least 60 seconds with zero runtime
errors, zero manual-trading actions, zero stalls over budget, real V1
identity continuity, strictly monotonic revisions, and a visible terminal
state:

| Lane | Duration | Visible p95 | Input p95 | Usable state | Max stall | Peak RSS | Terminal visible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct3D 11 | 60.002484 s | 16.1040 ms | 0.7682 ms | 639.8324 ms | 18.7934 ms | 77.992188 MiB | 17.0050 ms |
| Software | 60.013366 s | 18.9139 ms | 0.6769 ms | 340.9108 ms | 26.8837 ms | 34.234375 MiB | 17.4404 ms |

The same frozen source also passed the final focused release regression:
172 packaging, release-candidate, performance-certification, and
no-manual-trading tests in 304.11 seconds. The accepted Issue 65 union gate
on this exact source remains green. The formal static type gate passed with
no issues in the integration-gate and V1 release-fixture modules
(`--follow-imports=skip`), and `py_compile` passed for all eight release
modules.

## Installed Windows 11 clean room

Windows Sandbox returned exit code 0 on Microsoft Windows 11 Enterprise
10.0.26100 AMD64 under `WDAGUtilityAccount`. The report records:

- no network adapters up;
- no Python on `PATH` and no Python installation;
- no compiler on `PATH` and no compiler installation;
- no dependency cache;
- successful offline QML and Widgets installation;
- a real Widgets rollback launch with eight real panels, no placeholders,
  zero manual-trading actions, and clean exit.

Both installed Direct3D 11 and Software lanes used the production path:

`DiagnosticsApplication`
→ `FileBackedV1Persistence`
→ `LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter`
→ `LiveDiagnosticTasksAdapter`
→ `LiveStrategyDiagnosticsV1ApplicationAdapter`
→ `EventBridge`
→ `LiveRunMonitoringAdapter`
→ `LiveEvidenceAndFindingsAdapter`
→ `JourneyWorkspaceHost`.

Each lane used the authoritative writable Wave 2 fixture and verified:

- post-install creation of a real persisted Diagnostic Task and Formal
  Diagnostic Campaign;
- accepted typed create, revise, validate, approve, and start commands;
- three distinct persistent TaskHandles;
- exact task, Campaign, run, Evidence Package, and Reproduction Manifest
  identity continuity;
- writable file-backed persistence and authoritative reread;
- background continuation, route remount, and Application reopen;
- disconnect/reconnect, old-generation quarantine, and terminal monotonicity;
- task-cancel/order isolation;
- keyboard navigation, accessibility preferences, and distinct screenshots;
- the exact Diagnostic Tasks → Run Monitoring → Evidence & Findings route;
- zero manual-trading actions, read-only context, zero errors, and clean exit.

The clean-room report SHA-256 is
`56d1d7cd4b3725f941e89d3cfbdcf87f3b3fbfaf15fe69c97644c37f9cc27c9d`.
Raw renderer reports and screenshots are retained in `hardware/` and
`software/`.

## Remote release verification

GitHub reports the release tag target as the exact frozen source commit and
both assets as uploaded. For each archive, server and local full sizes and
SHA-256 digests match. Independent HTTP 206 probes of the start, middle, and
tail 1024-byte ranges also match the corresponding local bytes.
`release-asset-verification.json` records asset IDs, stable URLs, ranges, and
digests.

## Interface, schema, and scope

The active production Feature Interface registry remains exactly:

- `DiagnosticTasksFeature 1.0`
- `RunMonitoringFeature 1.2`
- `EvidenceAndFindingsFeature 1.1`

`StrategyDiagnosticsV1DiagnosticTasksApplication 1.0` remains the typed
Application boundary. Issue 66 made no Interface or persistence-schema
change. Backend-owned truth, frontend-owned presentation state, AppContext
composition, and live/fake Adapter separation remain unchanged.

No manual-trading capability exists. Legacy Widgets remains installed and
certified. Strategy Library, Scenario Lab, System Health, the complete
Journey Rail, Waves 3–4, manual trading, and legacy deletion remain
incomplete and outside this candidate.
