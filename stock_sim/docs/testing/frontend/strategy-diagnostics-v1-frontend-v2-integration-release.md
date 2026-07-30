# Strategy Diagnostics V1 ↔ Frontend V2 Integration Contract Vertical Slice

These release notes describe only the Integration Contract Vertical Slice
defined by GitHub issue #47 and submitted to the issue #53 release gates. The
candidate joins the previously certified Frontend V2 Wave 1 presentation with
persisted Strategy Diagnostics V1 results through one in-process typed
Application read-model boundary.

## Included scope

- `RunMonitoringFeature` 1.2 is active.
- `EvidenceAndFindingsFeature` 1.1 is active.
- A persisted V1 Formal Diagnostic Campaign, selected Strategy Run, sealed
  Diagnostic Evidence Package, and Reproduction Manifest are reopened from
  SQLite, JSON, and Parquet storage by the real `DiagnosticsApplication`.
- `LiveStrategyDiagnosticsV1ApplicationAdapter` maps those backend-owned
  results to immutable typed frontend read values.
- The installed QML Journey retains exact Campaign, Case, Run, Strategy,
  Approved Recipe, Evidence Package, Manifest, and artifact identities across
  launch, navigation, disconnection, authoritative reconnection, terminal
  presentation, remount, and clean exit.
- The same-source legacy Widgets rollback package remains available as the
  independent recovery path.

Orders, fills, positions, and account details remain read-only diagnostic
context. This release includes no manual trading, order entry, cancel,
replace, bulk-order, Buy, or Sell capability. It introduces no HTTP, REST,
OpenAPI, WebSocket, IPC, queue, second frontend process, or generic frontend
façade. The installed QML executable has no PTrade worker entry and only
reopens sealed backend state in-process.

## Explicitly not included

- Diagnostic Tasks creation and launch are not complete.
- Strategy Library is not complete.
- Scenario Lab is not complete.
- System Health is not complete.
- Waves 2–4 are not complete.

No later Feature Module is active or claimed by this release. A separate
readiness decision is required before Wave 2 `DiagnosticTasksFeature` work may
begin.

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
- The build creates the Formal Campaign through the real public
  `DiagnosticsApplication`, closes and reopens its SQLite/JSON/Parquet state,
  seals every retained file and backend identity into
  `strategy-diagnostics-v1-fixture.zip`, and binds that archive to the same
  source commit. Formal Campaign creation preserves the V1 backend's existing
  mandatory isolated PTrade execution policy; this is build-time domain
  execution, not an installed frontend service or integration façade. The
  installed executable verifies and extracts a temporary copy, reopens it
  read-only through the real Application and live adapter, and removes the
  copy on exit. It never ships a worker entry or regenerates the campaign
  during installed smoke.
- The offline Windows Sandbox must install both same-source archives, run the
  QML journey in hardware and software renderer lanes, and launch the real
  read-only legacy Widgets rollback executable.

Source changes alone do not certify the candidate. Certification exists only
after the retained issue-53 evidence and GitHub release bind the immutable
source commit to the checksums of both offline archives.

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

This certification remains limited to the two active Feature Interfaces named
above. It does not certify Diagnostic Tasks, Strategy Library, Scenario Lab,
System Health, or any other Wave 2–4 scope.
