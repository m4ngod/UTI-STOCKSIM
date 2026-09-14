# Frontend V2.1 #134 — real execution / page observation checkpoint

Date: 2026-09-14. This is local implementation progress, **not ticket acceptance**.
The full #133–#171 goal remains active. No #134 push, PR, main merge, release,
production-default switch, paid AI invocation or system settings change occurred.

## Source and exact scope

- Predecessor: `bde63b0269ed425841c1594c11af35b76015d8ba`.
- Initial execution isolation: `f55db4e98b9d0bfd3291ec21434fa0e6dd85e98a`.
- Reviewed observation-state fix: `80f33e502c782042880b01bae7df25518988c31a`.
- Published #132 v1.0 specification SHA-256:
  `A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.
  Relevant clauses: D01 application ownership, D02 observation freshness, D09
  execution continuity; ADR0036 and the explained fallback in ADR0038.

The opt-in research composition no longer activates the unused legacy Strategy
selection observer while displaying the independent exact-query Combination page.
It also does not connect read-only resource observations to the unmounted legacy
task creation form's upstream refresh. These two synchronous inventory reads
could otherwise wait for the running computation's application lock on the Qt
thread. Default legacy six-route activation and form linkage remain unchanged.

Scenario page activation now acquires its public Feature Subscription on a worker
thread. Qt receives typed state through queued delivery; view/context generation
checks reject obsolete delivery, and a late-installed Subscription is disposed
when its page has already closed or changed generation. This changes observation,
not the execution owner, Feature Interface, persistent task or approved input.

While a read is pending or fails, reliable retained Scenario content is marked
`stale` in the page observation. The authoritative Feature state is not rewritten.
A database read exception ends the waiting message with a sanitized explanation;
leaving and re-entering the page retries the read. The database failure test
verifies retained detail identity/content, no leaked private error marker and
return to `fresh` after the fault is removed.

## What the real-execution test proves

The test composes the actual AppContext with live Features, isolated SQLite,
locally admitted fixture inputs and the real embedded production strategy host.
It submits **one** public `StartFormalDiagnosticCampaign` command on a caller
thread. A test timing gate delays the first embedded decision invocation, then
delegates to its actual calculation; it does not replace the calculation or
manufacture a lifecycle transition.

While that invocation is held, real keyboard navigation enters Archive,
Combination or Scenario; a fourth case first establishes reliable Scenario
content. The same window opens and closes the read-only health overlay, returns
focus to its trigger, then closes its page adapters and view. None of these
actions completes or cancels the held command or disposes an independent public
Feature Subscription. Releasing the gate produces an accepted exact task/campaign
receipt and **one actually completed Campaign Case**. Public application queries
confirm its member runs used `ptrade-embedded-production-host.v1`. The public
task remains RUNNING; the test records exact campaign and input identities.

This is **not** an automatic scheduler, full campaign completion, Experiment/
Attempt model, all A/B selection semantics, restart recovery or remount proof.
There is no test-driven loop calling `advance_diagnostic_campaign`. The 10-second
invocation gate is a fail-safe that reveals blocked navigation, not a performance
acceptance budget. No real broker, external data feed or manual order is involved.

## Red / green evidence

Reports and isolated runtime artifacts are under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
Tests use the previously agreed public AppContext, Feature, Host and QML-input
seams. Database fault injection is at the actual SQLite execution boundary.

| Behavior | Failure / diagnostic evidence | Passing evidence |
| --- | --- | --- |
| Archive observation can be closed during real execution. | The first probe already passed; no artificial red is claimed. | `execution-continuity-first-probe.xml`: 1 passed. |
| Combination page must not wait for the old observer's read. | `execution-combination-switch-red.xml`: 1 failed, 1 passed. | `execution-combination-switch-green.xml`: 2 passed. |
| Scenario read and hidden form linkage must not block navigation. | `execution-scenario-switch-red.xml`: 1 failed. Despite its name, `execution-scenario-switch-green.xml` still has 1 failure and is NOT green. `execution-scenario-blocking-stack.xml` identifies `upstreamSelectionChanged → refresh → read_inventory` on Qt. | `execution-page-isolation-green.xml`: 3 passed. |
| Retained content is stale while a new observation waits. | `execution-retained-freshness-review-red.xml`: 1 failed; valid content was still labelled fresh. | `execution-retained-freshness-review-green.xml`: 1 passed. |
| Database failure must end waiting and permit recovery. | `execution-database-failure-review-red.xml`: 1 failed with an unhandled worker exception warning. | `execution-database-failure-review-green.xml`: 1 passed; `execution-review-fixes-targeted.xml`: all 5 cases passed. |

Initial source f55db4e regression: **189 passed**, 114.80 seconds.
Final source 80f33e5 regression: `execution-continuity-reviewed-regression.xml`,
**191 passed**, 143.75 seconds; zero failures, errors, skips or warnings.
Counts: 5 real execution/observation cases, 25 research shell, 31 resource pages,
25 legacy Journey Rail, 30 legacy health, 21 exact-query contract, 39 exact
inspector and 15 legacy Scenario route tests.

Runtime: Python 3.11.9 / PySide6 6.9.1, offscreen Qt Quick Software. The new
execution cases request a 1426×786 client and use the existing process-local CJK
font fixture. No new native screenshot, measured DPR, physical DPI matrix,
UIA/Narrator or startup acceptance is claimed. The independent remount diagnostic
ran concurrently during part of the regression; elapsed suite time is not a
performance benchmark.

| Artifact | SHA-256 of local bytes |
| --- | --- |
| `execution-continuity-full-regression.xml` (initial 189) | `02BC2F8565520D6FAC9313ECDE258B7687364B86FC0D5C49033937183F1B975D` |
| `execution-continuity-reviewed-regression.xml` (final 191) | `3C7916E40E64A2FA3DE898A4B10D715B3CC91445D4A40A708A96CE2108202345` |
| `execution-review-fixes-targeted.xml` | `D949C081C9AA653425E7A837A094B7F52B4E667421A1E0441DECC47FEDF938AC` |
| `app/ui/journey_workspace.py` | `D7DB62E717CCB8E887EEEC6EFC20AEEA54F9A16681878E51F39DD10EF559B469` |
| `tests/frontend/integration/test_research_execution_continuity.py` | `C76E111113A250F9D08AB03D78321ADB75DED4CEB0355B574CA62C5C9D4314AC` |

## Standards

Independent fixed-range review of `bde63b0...f55db4e` found one P2 hard issue:
catching only RuntimeError left an unexpected database read exception uncaught,
so the page remained waiting. Review-stage fix 80f33e5 catches read-boundary
exceptions and presents the explained fallback. The reviewer rechecked
`bde63b0...80f33e5`: the original hard finding is resolved, no new hard findings.

One original heuristic, possible lifecycle branch drift between activation and
construction, remains unresolved. Constructor snapshots are still synchronous.
It is not counted as a new finding or hidden by the passing page-switch test.

## Spec

Independent review found one P2 D02 error: retained content was still labelled
fresh while the new observation waited. The reviewer rechecked the fixed range
and confirmed the stale observation projection resolves it without changing
authoritative state; no new deviation was found. D09 evidence remains explicitly
local to the running command, navigation and view disposal, not full continuity.

Review summary: Standards 1 P2 hard finding resolved, 1 lifecycle heuristic still
open; Spec 1 P2 resolved, no new finding. Both agents read source and targeted
reports; neither reran tests or certified the complete ticket.

## Confirmed unfinished remount path — must not be counted as PASS

The separate debug probe `test_execution_remount_probe.py` opens the full research
Host with all Features, observes Scenario resources, disposes that view, starts a
real command against the same live AppContext, and reconstructs the Host while
the decision invocation is held. `execution-remount-known-gap.xml` fails once;
`execution-remount-targeted-stack.xml` repeats the failure in 15.38 seconds.
These are separate known failures, not members of the passing 191-case suite.

The second probe targets its thread dump **only at replacement construction**.
It shows Qt blocked in `StrategyLibraryQtAdapter.__init__ → Feature.snapshot →
StrategyLibraryApplication.read_inventory` while the other thread is inside the
actual campaign calculation. This confirms the first synchronous construction
read in the full Host; it does not establish that it is the only such path.
Scenario's constructor and hidden form initialization also require subsequent
isolation. The first probe's global timeout happened during initial preparation
and is not used as a causal remount stack.

The debug probe and targeted report are retained in the scratch directory, not
silently skipped, weakened or added as an expected pass. Probe SHA-256:
`12B253FAFFDCFB8A9CCC8FC1B5EBAD5FCE5E3B4CD23AEBD9777F35287E847513`.
Targeted failing report SHA-256:
`C7703C8EEC5F0876A0FA9DD2CE6294154F4DA8C66D9BBF7658269BBCCBBF787D`.
Only the debug probe uses temporary faulthandler timing; production contains no
new debugging instrumentation.

Next: fix and lock down real remount/initial observation, then broaden live
task/run selection, health context updates, generation-3 recovery, native logical
reflow/accessibility and normal/package startup evidence. All previously recorded
#134 unfinished obligations remain open. Older 6d33e71 startup samples remain
over 750 ms and are not relabelled as current-source passes.
