# Issue #118 completion audit

Audit source: `3cbf9683c76dc935853d37d584973a3432d5131a`.

Acceptance status: **accepted with a user-approved performance deviation**.
The formal machine verifier remains failed because both renderer lanes exceed
the unchanged 750 ms usable-state threshold. This audit does not relabel that
result as a pass.

## Prerequisites and delivery state

| Requirement | Current evidence | Result |
| --- | --- | --- |
| #116 blocker | GitHub issue #116 closed at 2026-08-10T06:25:45Z; ten-group source verification retained in `../3cbf9683c76dc935853d37d584973a3432d5131a/`. | Passed |
| #117 blocker | GitHub issue #117 closed at 2026-08-10T12:30:10Z; migration ledger and reversible-route facts are retained in `installed-verification.json`. | Passed |
| #118 state | GitHub issue #118 remains open, as required. | Preserved |
| Pull request | No PR exists for branch `codex/issue-118-offline-certification`; no push or PR creation was authorized. | Status recorded; external delivery pending authorization |
| Forbidden follow-on work | #119 was not executed, the 14-day observation was not started, #118 was not closed, and #107 was not modified. | Preserved |

## Acceptance criteria mapping

| #118 criterion | Authoritative retained evidence | Result |
| --- | --- | --- |
| Exact production toolchain and dependency versions | `../3cbf9683c76dc935853d37d584973a3432d5131a-build-host/dependency-manifest.json`, both native toolchain attestations, and toolchain identity in `build-host-verification.json`. | Passed |
| Automatic QML import/plugin discovery | Dependency manifest QML source imports and resolved closure; package-assembly renderer reports. | Passed |
| Clean offline Windows 11 x64 install and launch | `installed-verification.json` clean environment, guest-local package installation, DPI preflight, and external schema-8 report binding. | Passed |
| Complete highest Seam under D3D11 | Installed hardware schema-4 journey with Direct3D11, six routes, live state/recovery/reopen/accessibility, zero journey errors, and clean exit. | Passed |
| Complete highest Seam under Qt Software | Installed software schema-4 journey with Software rendering and the same complete assertions. | Passed |
| Disconnect/degradation/reconnect/late generation/retry/terminal/reopen/clean exit | Both installed lane projections and unchanged schema-4 raw journey evidence. | Passed |
| No missing DLL/module/QML/plugin or renderer error | Both installed journey reports have `errors=[]`; exact artifacts passed package dependency and renderer gates. Performance raw errors contain only the waived usable-state messages. | Passed apart from the explicitly waived timing failures |
| Exact six Feature Interfaces | Exact registry appears in both source and installed machine-readable projections. | Passed |
| Durable Strategy/Recipe/Task/Campaign/Run/Evidence/Finding/Breakpoint/Manifest continuity | Installed journey identity graph, reopen assertions, and candidate-Widgets-candidate rollback projection. | Passed |
| Accessibility: keyboard, Narrator, focus, 200%, contrast, reduced motion, chart/table narrative | DPI preflight plus eight installed accessibility checkpoints in each lane; installed accessibility, no-color, preferences, focus, and same-revision assertions are true. | Passed |
| Security/redaction/no-infrastructure-management | Source safety group passed; installed manual-trading count is zero; retained evidence leak scans found zero absolute paths, hostnames, sensitive fields, or secret URIs. | Passed |
| Fresh install, copied Wave3, bookmark/schema migration, reopen, rollback | Fresh and copied-Wave3 reports plus both-lane candidate→Widgets→candidate drill. | Passed |
| Candidate and same-source Widgets manifests/checksums | `build-host-verification.json`, dependency manifest, distribution checksum inventory, and native attestations. | Passed |
| QML package delta no greater than 50 MiB | 40,915,622 bytes versus 52,428,800 bytes. | Passed |
| Observation-ledger configuration and legacy inventory | Ledger schema/metric-set present; eight legacy routes; observation window not started. | Passed |
| No legacy route/panel/rollback artifact/Widgets shell deletion | Eight legacy routes retained; read-only Widgets artifact and all eight real panels verified; non-destructive migrations and rollback true. | Passed |

## Release-gate mapping

| Gate | Hardware | Software | Result |
| --- | ---: | ---: | --- |
| Fixed fixture | 100000/4000/3/50/50ms/20fps | 100000/4000/3/50/50ms/20fps | Passed |
| Event-to-visible p95 ≤20 ms | 11.8089 ms | 15.2916 ms | Passed |
| Input p95 ≤16 ms | 0.9827 ms | 0.8227 ms | Passed |
| Usable state ≤750 ms | 1779.4271 ms | 1286.6223 ms | **Failed; user-approved deviation** |
| Main-thread stalls >50 ms | 0 | 0 | Passed |
| Maximum observed stall | 16.4442 ms | 15.7182 ms | Passed |
| Peak memory ≤180 MiB | 79.152344 MiB | 70.921875 MiB | Passed |
| Accepted revisions strictly monotonic | true | true | Passed |
| Terminal visible ≤100 ms | 7.6749 ms | 14.1084 ms | Passed |
| Required renderer | Direct3D11 | Software | Passed |
| Manual trading actions | 0 | 0 | Passed |

The exact raw performance files are retained under `performance/`. They remain
`status=failed`, have installed exit code 1 in the clean-room aggregate, and
retain the original 750 ms messages. The user-approved deviation is limited to
these two usable-state observations. It changes no production threshold,
schema, verifier, parent specification, or future release rule.

## Safety and packaging mapping

- WebEngine file/import/plugin/payload count is zero.
- No IPC, second UI process, QML island, hybrid chart, pyqtgraph, or
  QQuickPaintedItem production chart was introduced; the source safety and
  packaging-contract groups passed.
- Installed no-trading object-tree, action, dispatch, shortcut, log, and
  package gates passed in both renderer lanes.
- System Health remained read-only and exposed no infrastructure-management or
  arbitrary-command surface.
- Diagnostic lifecycle/order isolation passed; no order-lifecycle dispatch was
  introduced.
- All retained evidence files are covered by local SHA-256 indexes. The two
  archives and all 3,885 distribution files were independently rehashed with
  zero missing, duplicate, or mismatched paths.

## Completion decision

Implementation, artifacts, source gates, clean-offline installed journeys,
accessibility, security, migration, rollback, and retained evidence are
complete for this exact candidate. The raw 750 ms machine gate is not complete;
the user explicitly accepted that deviation for #118. The only remaining
delivery action is optional remote publication of this branch as a PR, which
requires separate push/PR authorization and must not close #118 or trigger
#119.
