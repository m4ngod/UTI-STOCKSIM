# Issue #118 installed acceptance with user-approved deviation

## Acceptance status

**Accepted for Issue #118 with a user-approved performance deviation.**

This is not a claim that the formal 750 ms usable-state gate passed. The
official runner exited with code 1, both raw performance reports remain
`status=failed`, and the production verifier still reports six messages that
derive from exactly two startup overruns:

| Lane | Renderer | Observed usable state | Formal limit | Disposition |
| --- | --- | ---: | ---: | --- |
| Hardware | Direct3D11 | 1,779.4271 ms | 750.0 ms | User waived for this candidate |
| Software | Qt Software | 1,286.6223 ms | 750.0 ms | User waived for this candidate |

User authorization:

> 本次不考虑750ms门槛了，我认为现在的状态属于可用，不强求把时间压到750ms门槛下，因为sandbox有性能瓶颈

The 750 ms threshold, raw values, raw errors, raw runner exit, and verifier
result were not modified or reclassified. This deviation applies only to
Issue #118, source `3cbf9683c76dc935853d37d584973a3432d5131a`, the two exact archives below,
and this clean Windows Sandbox run. It does not change #34/#107, establish a
future release threshold, authorize #119, or start the 14-day observation.

## Exact candidate

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `qml-journey-3cbf9683c76d.zip` | 158,210,835 | `39a2362b55562851c9adf3458a5a568064575b09ffd3fddf660281ce80c0533c` |
| `widgets-rollback-3cbf9683c76d.zip` | 145,315,837 | `a77c9f33b4d5aa600223034f412a7e0cab7236ebfb84fd903006d3976b5dbe50` |

## Gates that passed without deviation

- Clean Windows 11 x64 Sandbox: offline, no enabled/up adapter or default
  route, no Python/compiler/cache/source checkout, guest-local execution.
- Installed DPI preflight: native `GetDpiForWindow=192`, Qt DPR 2.0, 200%
  text scale, no guest DPI override, exact external UIA acknowledgement, clean
  candidate exit.
- Installed hardware and software journeys: exact production path, six routes,
  queued/running/partial/failure/retry/terminal states, reconnect and old-
  generation isolation, System Health context/accessibility, reopen, distinct
  screenshots, eight accessibility checkpoints, no color-only meaning, zero
  manual-trading actions, and clean exits.
- Formal performance metrics other than usable-state: event 11.8089/15.2916
  ms (limit 20), input 0.9827/0.8227 ms (limit 16), zero stalls over budget,
  peak memory 79.152344/70.921875 MiB (limit 180), strict monotonic revisions,
  and terminal visibility 7.6749/14.1084 ms (limit 100).
- Fresh and copied-Wave3 migration, bookmark/schema/identity retention,
  deterministic idempotent reopen, and non-destructive behavior.
- Candidate-to-Widgets-to-candidate rollback in both renderer lanes with the
  same source and dependency lock, durable identity/task/order continuity,
  read-only Widgets smoke, reopen, and clean exit.
- Observation ledger configuration and eight legacy routes are present;
  `observation_window_started=false`.
- Guest result acknowledgement completed; after normal terminal-window Close,
  WindowsSandbox/vmwp/non-template HCS counts were all zero.

## Supporting differential, not installed evidence

The exact compiled QML artifact on the same host at native 200% and Direct3D11
completed the full 60-second fixed fixture with usable state 682.9986 ms and
zero errors. This supports the Windows Sandbox display-overhead diagnosis, but
is explicitly marked `installed_gate=false` and is not used as a substitute
for the installed run.

The unchanged 12.5 MB schema-8 clean-room report remains outside Git and is
bound by size and SHA-256 in `installed-verification.json`. The three retained
performance files and DPI preflight are exact copies. No GitHub release claim
is made; Issue #118 remains open, and no #119 or observation action occurred.
