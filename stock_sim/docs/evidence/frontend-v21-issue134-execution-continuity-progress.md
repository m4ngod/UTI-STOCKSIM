# Frontend V2.1 #134 — real execution / page observation checkpoint

Date: 2026-09-14. This is local implementation progress, **not ticket acceptance**.
The full #133–#171 goal remains active. No #134 push, PR, main merge, release,
production-default switch, paid AI invocation or system settings change occurred.

## Latest remount and exact-selection checkpoint

The earlier remount failure below is historical, not the current result for the
tested Scenario entry. Source `044db2afe32801bc2ab5ae16939edfc7d0a877cd` defers
initial research observations; review fix
`35f64e4d51027252476553c1df24ae5bd6b9f0d2` protects exact selections and corrects
cold-read wording. Both descend from evidence checkpoint
`0e08b085fd9bfdaac2907b0db44d700597ebfb6d`. The formal specification hash below
was reverified unchanged; D10 exact observation supplements D01/D02/D09.

### Implementation and limits

- Strategy, Scenario and Diagnostic Tasks research projections now share
  `FeatureObservation` for initial and later public reads/Subscriptions. Pending,
  failure and cancellation belong to observation only. The adapters retain typed
  state or no observation; they do not invent source generations or domain state.
  Context, mount and read generations reject obsolete delivery; a late-acquired
  Subscription is disposed if its observation is no longer current.
- The unmounted legacy task creation form no longer initializes upstream
  selection providers in the research shell. Legacy default constructors,
  subscriptions, commands and form wiring retain their original behavior. No
  public Feature Interface, AppContext ownership or persistent schema changed.
- Two public live remount cases exercise Scenario-only and all-Feature Host
  composition with an exact Task. They first observe Scenario, dispose the view,
  submit one real Start, then reconstruct on the same AppContext while the real
  embedded invocation is held. Health keyboard interaction remains responsive;
  releasing the invocation yields an accepted exact receipt, one completed case
  and readable Scenario resources. The unchanged original full-Host scratch
  reproducer also passes on 044db2a. This does not cover every exact Run/Evidence
  constructor or an automatic execution scheduler.
- Review found that a hidden Task's first asynchronous read could replace an
  explicitly observed member of the same legitimate Campaign with its default
  handoff member. In research composition, passive recovery now fills only an
  empty selection. Existing Run/Evidence selections remain pinned even while
  loading; explicit Start/Retry navigation remains a separate replacement path.
  Both initialization and late handoffs use the same passive guard.
- Four live Host cases cover Run/Evidence entry with an explicit alternative
  member or no selection. The latter must still recover the Task's exact default.
  They create and finish records through public commands/application queries;
  their explicit `advance_diagnostic_campaign` call is **test preparation only**,
  not evidence of an automatic scheduler. Assertions inspect actual QML content
  and the public Journey evidence manifest, never private adapter state.
- A real SQLite read gate reproduces typed initial loading without reliable
  inventory. This must not claim an old valid observation. Warm reliable content
  still retains its stale explanation. The gate is test-only, not a pause API.
- Two existing approved-version/draft resource tests now wait for the actual QML
  list to receive its rows rather than treating backend readiness as UI delivery.
  Their exact identities, counts, hashes and draft/approved distinction are
  unchanged; no frame-paint or startup threshold is inferred from this wait.

### Remount/review evidence

All reports are in the scratch evidence directory stated below. Earlier failures
are retained without relabelling, skipping or replacing their bytes.

| Behavior | Red / diagnostic | Green |
| --- | --- | --- |
| Cold Scenario construction during real computation | `scenario-remount-isolated-red.xml`: 1 failed. | `scenario-remount-isolated-green.xml`: 1 passed. |
| Full Host construction after fixing Scenario alone | `full-remount-after-scene-red.xml`: 1 failed. | `full-remount-deferred-read-probe.xml`: 2 passed; original reproducer `execution-remount-original-green.xml`: 1 passed, 4.65 s. |
| Queued approved/draft delivery reaches QML | `remount-resource-regression-probe.xml`: 2 failed, 51 passed; list still had zero rows after backend readiness. | `remount-shared-observation-targeted.xml`: 5 passed, including both resource cases, both remount cases and DB failure recovery. |
| Hidden Task must not replace an explicit member | `exact-member-initial-read-public-red.xml`: 2 failed, 14.14 s; wrong Run and wrong exact evidence manifest. | `exact-member-and-missing-recovery-green.xml`: 4 passed, 23.01 s, including missing-selection recovery. |
| Cold wait cannot claim retained reliable data | `cold-scenario-wait-message-public-red.xml`: 1 failed, 2.89 s, exact false retention message. | Included in `remount-selection-review-targeted-green.xml`: all 12 cases passed, 42.06 s. |

The first `cold-scenario-wait-message-red.xml` failed on an incorrect test wait
for a literal English `loading` label; it is not causal behavioral red. The
corrected public test waits for the exposed typed source generation to reach QML
and then asserts the actual user-visible text. The earlier evidence-detail probe
incorrectly expected a manifest in a row's text; the decisive two-case red above
uses the public Journey manifest selection instead.

Source 044db2a expanded regression: `remount-full-regression-candidate.xml`,
**234 passed**, 250.03 s. Source 35f64e4 final related regression:
`remount-reviewed-full-regression.xml`, **239 passed**, 290.88 s console total
(290.842 s JUnit suite), zero failures, errors or skips. Counts: 12 execution/
remount/selection, 25 shell, 31 resources, 25 Journey Rail, 12 Journey workspace,
30 health, 21 exact-query contract, 39 inspector, 15 Scenario, 19 Tasks,
8 Strategy and 2 live Run-to-Evidence journey tests.
Runtime remains Python 3.11.9 / PySide6 6.9.1, isolated offscreen Software. No new
native frames, physical-DPI, UIA/Narrator or startup acceptance was recorded.

| Artifact | SHA-256 |
| --- | --- |
| `remount-full-regression-candidate.xml` | `D71D8A8C4C127254CFDA0F6388FE2DCB4BB16DC3EE1C208C60EE23C80A236A1A` |
| `remount-reviewed-full-regression.xml` | `82516DA58E080518FB84B203CDD3F6B9D955BE21BB850F3A6ADA67FBE122845E` |
| `remount-selection-review-targeted-green.xml` | `5FFAC8C12E45A2BBA537F054C94F49ACE60BBB0F86FC0A68E6D899911F76D046` |
| `exact-member-initial-read-public-red.xml` | `A9716D01E319A2E75BC768CA6A54734159C1BFB0DB514AF45C766780CB38EDAD` |
| `cold-scenario-wait-message-public-red.xml` | `2BEB6649F033956CA6D0FD90D6D2263212B2FB68E9A7B8A9C7B813A70DA9A24D` |
| `execution-remount-original-green.xml` | `2FFE1405EC7858C2C7171B292D2F2B6EE34BF15769A1ED0060A029BDDC025590` |

### Separate exact-entry diagnostic after the final regression

On unchanged source 35f64e4, the original full Scenario scratch reproducer passed
again. A new isolated public probe then prepared completed Campaign A, created and
approved a distinct Task B, and submitted one real public Start for B. Its test
gate was rearmed only at the embedded-host timing boundary. While B's invocation
was held, it rebuilt the full Host on exact Run A or exact Evidence A, verified
the pinned identity and health keyboard return, released B and verified A was
still observed while B had actually completed one case.

`exact-entry-remount-pinned-observation-probe.xml`: **2 passed**, 14.80 s. This
separate scratch diagnostic is not included in the 239 committed-test count;
promotion into permanent regression and broader selection/lifecycle cases remain.
The initial `remount-original-and-exact-entry-diagnostic.xml` is **1 passed and
2 setup failures**: it tried to obtain sealed manifests before its preparation
had completed a campaign. The next `exact-entry-remount-two-tasks-diagnostic.xml`
also has **2 setup failures**, from expecting the first typed task-loading
snapshot to contain a task. Neither report establishes a product remount failure.
After correcting preparation through existing public helpers,
`exact-entry-remount-two-tasks-public-probe.xml` passed both cases, then the final
pinned-observation probe added identity checks before and after B completed.

| Separate artifact | SHA-256 |
| --- | --- |
| `test_execution_exact_entry_remount_probe.py` | `31E86DECBCC1B2EBD09CD2F8E3CF80D91D5185D68E92C508501E448266E15207` |
| `exact-entry-remount-pinned-observation-probe.xml` | `8ACABE20FB6B57C394573816B04C9618E8C98B509C7DDA49E0895D616BCCE704` |

### Standards

Independent review of fixed `0e08b08...044db2a` identified one P2 hard violation:
passive initial Task delivery could replace an exact observation (ADR0036/0038).
Recheck of verified nonempty `0e08b08...35f64e4` confirms it resolved, with zero
new hard violations and zero new specific heuristic smells. The shared initial
observation resolves the earlier three-adapter lifecycle branch drift in research
composition; this does not prove other exact-entry lifecycle paths.

### Spec

The independent Spec axis identified P2 D10 late selection contamination and P3
D02 false retention wording. Recheck of the same final range confirms both fixed,
with zero new deviations. Explicit Start/Retry remains distinct from passive
recovery and no execution/domain-state owner was added. Both reviewers read code
and test assertions without rerunning tests; neither certified the full ticket.

Review summary: Standards 1 P2 resolved, 0 new; Spec 1 P2 and 1 P3 resolved, 0 new.
Next is to promote the exact-entry diagnostic and broaden live selection and
health-context continuity, generation-3 durability,
native reflow/accessibility, normal/package entry and startup gates. #134 remains
OPEN. Previously recorded over-750-ms samples are not waived or called current
passes.

## Historical execution checkpoint — source and exact scope

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
