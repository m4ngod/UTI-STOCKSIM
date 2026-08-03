# Strategy Diagnostics V1 ↔ Frontend V2 Integration Contract Vertical Slice

These release notes describe only the Integration Contract Vertical Slice
defined by GitHub issue #47, extended through the Wave 2 source-level gate in
Issue #65, and submitted to the Issue #66 release gates. The current source
candidate joins persisted Strategy Diagnostics V1 commands and results through
typed in-process Application boundaries.

## Included scope

- `DiagnosticTasksFeature` 1.0 is active.
- `RunMonitoringFeature` 1.2 is active.
- `EvidenceAndFindingsFeature` 1.1 is active.
- `StrategyDiagnosticsV1DiagnosticTasksApplication` 1.0 creates, validates,
  approves, and starts real persisted Diagnostic Tasks and Formal Diagnostic
  Campaigns through the production QML route.
- The installed package starts from an authoritative input fixture containing
  zero Diagnostic Tasks and zero Formal Diagnostic Campaigns. Each renderer
  lane copies it to writable local storage, then creates the Task and Campaign
  through the real `DiagnosticsApplication`.
- `LiveStrategyDiagnosticsV1ApplicationAdapter` maps those backend-owned
  results to immutable typed frontend read values.
- The installed QML Journey retains exact Task, TaskHandle, Campaign, Case,
  Run, Strategy, Approved Recipe, Evidence Package, Manifest, and artifact
  identities within each renderer lane. It keeps the Campaign nonterminal
  through three-route navigation, disconnection, authoritative reconnection,
  stale-generation rejection, remount, and Application reopen before
  continuing to terminal Evidence/Manifest presentation and clean exit.
- The same-source legacy Widgets rollback package remains available as the
  independent recovery path.

Orders, fills, positions, and account details remain read-only diagnostic
context. This release includes no manual trading, order entry, cancel,
replace, bulk-order, Buy, or Sell capability. It introduces no HTTP, REST,
OpenAPI, WebSocket, IPC, queue, second frontend process, or generic frontend
façade. The installed QML executable has no PTrade worker entry. It executes
the public backend behavior and all live Feature Adapters in one process.

## Explicitly not included

- Strategy Library is not complete.
- Scenario Lab is not complete.
- System Health is not complete.
- Waves 3–4 are not complete.

No later Feature Module is active or claimed by this source candidate.

## Certification boundary

The candidate is certifiable only when one immutable integration source commit
and the locked Python 3.11.9, PySide6 6.9.1, Qt 6.9.1, NumPy 2.3.1, and
Nuitka 2.6.8 toolchain identify every T08, T09, T10, package, Sandbox, and
rollback artifact.

- T10 combines the fixed 100,000-point/50-candidate QML load projection with
  a retained real V1 preflight in the same lane process. Hardware and software
  reopen the exact same source-bound sealed fixture archive rather than
  generating separate Campaign identities.
  Before the renderer startup clock begins, that preflight repeatedly reads
  the reopened Formal Campaign, Run, and sealed Evidence through
  `DiagnosticsApplication`,
  `LiveStrategyDiagnosticsV1ApplicationAdapter`, and SQLite/JSON/Parquet.
  It then closes persistence and removes its temporary storage so the
  continuous 60-second renderer window measures only the locked T10 fixture
  and is not distorted by certification setup work.
- The installed QML executable must retain the exact typed Feature identity
  graph at every launch, disconnected, stale reconnect, fresh reconnect, and
  remount checkpoint through the rendered QML/QAccessible object graph.
- The build seals authoritative datasets, recipes, and materialized paths into
  `strategy-diagnostics-v1-wave2-input-fixture.zip`, binds it to the same
  source commit, and proves that it initially contains no Task or Campaign.
  The installed executable verifies and extracts a writable temporary copy,
  then uses the typed create, revise, validate, approve, and start commands.
  While the Campaign is still nonterminal, it traverses all three routes,
  disconnects and reconnects, rejects an old generation, closes the
  Application, and reopens the same persisted Task, TaskHandles, and
  Campaign. Only then does it advance the real Campaign and receive
  backend-generated Evidence and Reproduction Manifest identities. Hardware
  and software lanes validate their own complete identity graphs; generated
  Task/Campaign/Run/Evidence UUIDs are not required to match across the two
  independent installed processes.
- The offline Windows Sandbox must install both same-source archives, run the
  QML journey in hardware and software renderer lanes, and launch the real
  read-only legacy Widgets rollback executable.

## Wave 2 release procedure

1. Freeze a clean source commit on formal `master` and run the required T08
   suite with JUnit output.
2. Run and certify both continuous 60-second T10 lanes. The certifier must
   produce the same-source T09 no-manual-trading report.
3. Build both archives from that exact clean commit:
   `python -m stock_sim.release.frontend_v2_packaging --output-root
   <OUTPUT_ROOT> --source-commit <SOURCE_COMMIT>`.
4. Launch `scripts/run_frontend_v2_windows_sandbox.ps1` with the QML archive,
   Widgets archive, both checksums, source commit, and a new evidence
   directory. Networking remains disabled; package and scripts are mapped
   read-only; only evidence output is writable.
5. Require both installed renderer reports to show the exact three-route
   production path, post-install Task/Campaign creation, five accepted typed
   command kinds, at least three distinct persistent TaskHandles, writable
   persistence, nonterminal three-route/disconnect/Application-reopen
   continuation, task-cancel/order isolation, zero manual trading actions,
   and a clean exit.
6. Run the packaging command again with
   `--certify-clean-room-report`, `--accessibility-junit`, and
   `--performance-evidence-dir`. Publish only the two archives and evidence
   whose local and remote sizes and SHA-256 digests match.

Source changes alone do not certify the Wave 2 candidate. The Issue #65 result
is not an installed Wave 2 release-certification claim. Certification exists
only after Issue #66 binds its immutable source commit, clean-room evidence,
and GitHub release to the checksums of both offline archives.

## Certified candidate

Issue #53 certified the following immutable prerelease on 2026-07-30:

- Source commit:
  `3359bce1eb14c10ecbbc2fd1cab17a17db31e5a4`
- Release tag:
  `strategy-diagnostics-v1-frontend-v2-integration-rc-3359bce1eb14`
- GitHub prerelease:
  <https://github.com/m4ngod/UTI-STOCKSIM/releases/tag/strategy-diagnostics-v1-frontend-v2-integration-rc-3359bce1eb14>
- Retained evidence:
  `docs/testing/frontend/evidence/issue-53/3359bce1eb14c10ecbbc2fd1cab17a17db31e5a4/`

The final gates passed on the same source commit:

- T08: 12 accessibility tests passed.
- T09/T10: the aggregate certification status is `certified`; both the
  Direct3D 11 and Software renderer lanes completed 60 continuous seconds
  with zero stalls and zero manual-trading actions.
- Hardware p95 visible latency was 7.2405 ms, p95 input latency was
  0.6411 ms, and peak RSS was 78.386719 MiB.
- Software p95 visible latency was 9.3986 ms, p95 input latency was
  0.6252 ms, and peak RSS was 38.335938 MiB.
- Windows Sandbox reported exit code 0 with zero network adapters up, no
  Python, compiler, or dependency cache available, successful installation
  of both archives, clean hardware/software QML journeys, and a clean real
  Widgets rollback launch.
- Raw packaging and Sandbox launch logs are retained alongside their sizes and
  SHA-256 checksums in `retained-log-checksums.json`.

The published offline archives are:

- `qml-journey-3359bce1eb14.zip`
  (`sha256:bb625996e569807de258547797621c6149f5d8b757dda4e754ea714e3fdb4b1e`,
  208341173 bytes)
- `widgets-rollback-3359bce1eb14.zip`
  (`sha256:8d8b2507ac1614363b2f4c758121bf788bedd1aca7bfa239ef7d47c81be4eaa5`,
  199829115 bytes)

GitHub server digests, local digests, sizes, and distributed start, middle,
and tail byte ranges were independently matched for both assets. The retained
`release-asset-verification.json` records those checks.

This historical Wave 1 certification remains limited to the two Feature
Interfaces and immutable source commit it named. It did not certify the
Wave 2 source candidate; the separate Issue #66 certification of Diagnostic
Tasks and all three active Feature Interfaces is recorded below. Strategy
Library, Scenario Lab, System Health, and Waves 3–4 remain outside scope.

## Wave 2 certified candidate

Issue #66 certified the immutable Wave 2 prerelease on 2026-08-03:

- Source commit:
  `f3e7c2a45bb32b512bb9ce045208dc508b0851bc`
- Release tag:
  `strategy-diagnostics-v1-frontend-v2-wave2-rc-f3e7c2a45bb3`
- GitHub prerelease:
  <https://github.com/m4ngod/UTI-STOCKSIM/releases/tag/strategy-diagnostics-v1-frontend-v2-wave2-rc-f3e7c2a45bb3>
- Retained evidence:
  `docs/testing/frontend/evidence/issue-66/f3e7c2a45bb32b512bb9ce045208dc508b0851bc/`

The same source commit passed T08 with 18 tests, the T09 no-manual-trading
gate, certified Direct3D 11 and Software T10 lanes, and the installed
Windows 11 Sandbox black-box journey. The clean room had no network adapters
up, Python, compiler, or dependency cache. It created a real persisted
Diagnostic Task and Formal Diagnostic Campaign after install, preserved
TaskHandles and identities across disconnect/reconnect, remount, and
Application reopen, reached terminal Evidence & Findings state, launched the
real Widgets rollback, and exited cleanly.

The published offline archives are:

- `qml-journey-f3e7c2a45bb3.zip`
  (`sha256:75a9dbc884dbcc513acd936d0567a94f02ecb78efdc466fe7370ecded9478070`,
  215638255 bytes)
- `widgets-rollback-f3e7c2a45bb3.zip`
  (`sha256:83a748d2fb850b69f8083ea5275a7315a453aa78bac50fea22cc1ff4c02d7a97`,
  200485698 bytes)

GitHub server digests, local digests, sizes, and distributed start, middle,
and tail byte ranges match for both assets. The certified registry contains
exactly Diagnostic Tasks 1.0, Run Monitoring 1.2, and Evidence & Findings
1.1. No manual-trading capability is present, legacy Widgets remains
available, and Strategy Library, Scenario Lab, System Health, the complete
Journey Rail, Waves 3–4, manual trading, and legacy deletion remain
incomplete and outside scope.
