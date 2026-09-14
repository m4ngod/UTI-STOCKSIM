# Frontend V2.1 #134 — implementation progress, not acceptance

Date: 2026-09-14. Ticket: https://github.com/m4ngod/UTI-STOCKSIM/issues/134.
Parent: published specification #132 v1.0. Audited predecessor:
`f354f0328ba33e10f98b8018e886d170c8d72c0d` (#133).

## Latest product-entry increment and scope correction

Fixed predecessor `2e8222ecfa1e46b4804311ec49aebbe10f058481`; entry source
`59d944036b3f8b389cf0f583fdffbbd5f22e7a6a`; corrected source
`04a57b8b00040ae1c91cec4e0583b3b2ae05336e`. This remains local #134 work,
not whole-ticket acceptance, a default switch, a new specification or a release.

Both existing public entry functions now accept explicit `--research-shell`:
`setup_frontend_entry.main` and `stock_sim.release.frontend_v2_package_entry.main`.
They mount the actual AppContext/MainWindow four-page QML, using separate
`frontend-v21-settings.json` and `layout_v21.json`. The ordinary legacy defaults
and fallback assets remain. Console research startup does not start the legacy
runtime support services or register the legacy panels. No Feature version,
execution owner, real broker or creation capability was added.

### Reproduced boundary failures and corrections

- Public console startup with an invalid Adapter mode, and package startup with
  a Run ID but no Campaign ID, each raised while leaving a started EventBridge.
  Fresh-process/public singleton checks and successful explicit stopping exclude
  a pre-existing bridge and a broken stop operation for these repros. Research
  entry lifetime cleanup now covers bridge, completed AppContext and window;
  console research show/exec errors are not silently converted to success.
- A future-schema bookmark in the new isolated settings was overwritten by the
  legacy load normalizer. The package entry also lost the existing recovery
  reason and displayed EXACT. New research entries disable **only load-time**
  normalization and pass that typed recovery reason to QML. The whole input file
  remains byte-identical after navigation/exit. Default legacy normalization is
  unchanged. This is input preservation, not schema3 migration or general backup.
- The package entry rejects all explicitly supplied legacy Wave 4 certification
  report/auxiliary options when research mode is selected, before starting or
  creating reports. Both `--name value` report paths and `--name=value` auxiliary
  inputs are covered; renderer choice remains valid. No old certificate is used
  as V2.1 evidence.

Public-entry tests drive actual QML navigation with keyboard Space, open the
read-only health popup and return focus with Escape. They also verify the three
old settings/layout files are unchanged. The entry module has 25 cases; the
expanded targeted run including old console and recovery contracts is **39 passed
in 3.06 s**, zero failures/errors/skips, in
`research-entry-corrections-expanded-green.xml`, SHA-256
`9321F0AAA364042CCE65D8F2F0029E663BF516CED2355B6A29DB81EC12954961`.
These are offscreen Software QML checks, not installed/native UIA certification.

The earlier `research-startup-failure-red.xml` had a mistaken test error-message
match, and `research-package-failure-red.xml` had a test syntax error; neither is
a causal red. Corrected `*-causal-red.xml` reports reproduce actual bridge leaks.
`research-unknown-bookmark-red.xml` reproduces the byte rewrite and lost reason;
`research-legacy-aux-arguments-red.xml` reproduces silent acceptance. Subsequent
green reports and the final regression remain separate artifacts; failures were
not overwritten or relabelled.

### Native source-entry frame records (not 750 ms acceptance)

Scratch root: `F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
Probe: `measure_research_product_entry.py`, final SHA-256
`3A2C352750B82AE54865CFA2F6E27DF7B837AB1AD27A7CC5F7B7884F050439DE`.
All four retained isolated samples bind to source `04a57b8`; each has a new PID,
empty settings, disabled QML disk cache, live built-in catalog, Windows native Qt,
Microsoft YaHei UI, DPR1.0, full timing samples and a saved framebuffer.
They are not samples from an installed binary or physically cold OS/disk caches.

The external observer creates the real QApplication at the recorded origin;
the unmodified public entry reuses it. No MainWindow or AppContext is replaced.
The interval includes QApplication and the public startup; separate script times
also retain imports. Console measurement includes its default database check.
The first visible frames still say loading; the measured later resource frames
show two actual exact legacy versions, not a skeleton substituted for resources.

| Source entry | Actual renderer | PID | Logical client | Pre-QApplication to resource frame |
| --- | --- | --- | --- | --- |
| Console | Software | 265420 | 1280x820 | 1770.1008 ms |
| Console | Direct3D11 | 271848 | 1280x820 | 2006.7906 ms |
| Package module | Software | 283124 | 1024x640 | 878.1782 ms |
| Package module | Direct3D11 | 284108 | 1024x640 | 1040.7195 ms |

Directories follow `product-entry-<console|package>-<software|d3d11>-isolated-04a57b8`.
Report SHA-256, in the table's order:

- `66BA1D40F3592E1643BF7C588176E4FED59D9B66AD9170FFB2D5275E4D13DAA8`
- `0505531B302C094EE47C57FF14CBF4F7492D8051F633429AA3838173937A6A90`
- `916954D33A8822BDAC3616379E424F784B4BB60502098D8F879A1117A7A9FE7B`
- `63F7335411ADFEA737BE93C01911D3C2F58654B9D2D469197B191BFD870606CC`

All four exceed 750 ms; none is PASS. The observer checks public QML resource
count/status/busy/availability, not typed freshness or source-revision attestation.
There is no empty-input proof in this probe, no complete startup usability proof,
and no input interaction or native UIA proof in its screenshots. All four
framebuffers were visually inspected: four destinations,
readonly health, actual two-version catalog and explicit unavailable-creation copy.
All entries returned zero and their public bridge was absent afterward.

The first, **non-isolated** console Software sample (PID302448, 1780.8975 ms) is
retained in `product-entry-console-software-04a57b8`. Its default health check
reached the pre-existing local PostgreSQL and called `ensure_models`; it must not
be counted as an isolated run. No before/after schema audit was captured, so no
claim of unchanged schema is made. Later measurements set the database URL before
Python startup and verify the actual engine matches the exact scratch SQLite
path before invoking the public entry. No connection or system setting was edited.

### Two-axis review

Both reviewers pinned the complete nonempty range
`git diff 2e8222ecfa1e46b4804311ec49aebbe10f058481...04a57b8b00040ae1c91cec4e0583b3b2ae05336e`.

- Standards: 0 new hard-standard violations/actionable smells. Previously raised
  lifetime/ignored-argument boundary concerns are resolved for the reproduced
  paths; no claim that every possible partially constructed resource is tested.
- Spec: both original P2 findings (unknown input rewrite and lost recovery reason)
  resolved, 0 new actionable deviations. No schema3 or whole-ticket acceptance.

Reviews were independent, read-only, without reviewer test execution.

### Final corrected-source regression

Both processes terminated with exit0 on frozen source `04a57b8`; only the two
existing evidence documents changed during their runs. XML readback confirms
zero failures, errors or skips:

- `research-product-entry-full-regression.xml`: **316 passed**, 450.65s console
  (450.574s JUnit), 19 modules. Includes prior277 related cases, 25 new public
  entry cases, 5 retained console cases and 9 legacy recovery contracts. SHA-256
  `64E6AC3E608FB4DB5ADD56BAC38D54E28354DB89D4A222DB20747BB4980B4DCA`.
- `research-entry-corrected-legacy-package.xml`: **7 passed**, 71 deselected,
  185.74s console (185.743s JUnit), the bounded retained package-entry/certification
  selection. SHA-256
  `5793DB8D3F6B7557589988791655F9312F59B18FC7B0A4818417FD74ED3B12DA`.

The suites ran in separate offscreen Software processes with per-process scratch
database/artifact paths. Native startup measurements finished before these test
runs; the measured frames were not captured while these suites were competing.
The old retained-Tasks native crash did not recur, but its cause/fix remains
unproven. These runs are not full-repository or installed-package certification.

### Corrected ticket boundaries

Fresh official bodies confirm #134 OPEN/assigned to m4ngod. #165 explicitly
depends on #134 and owns schema1/2 to schema3 migration; #164 depends on #142,
#145 and #162 and owns cross-restart research context. These must **not** become
reverse prerequisites for this shell-first ticket. No specification/ADR/ticket
was rewritten. Full installed-candidate A41 750ms certification and complete
physical DPI/Narrator are later shared gates, not implicit #134 prerequisites.
Their original requirements remain mandatory for their owning deliveries.

#134 still owns truthful dual-renderer first-projection records, real empty and
existing resources, local normal/wait/error behavior, subscription continuity,
compact/normal/wide font100/200 operability and local keyboard/UIA/focus evidence.
Resource-frame timing alone does not complete those obligations. The source
entry increment is complete; #134 and the complete implementation goal are not.

## Previous per-group health increment

Source `d10a3c8`, corrections `2ec99b1` and `e1bc5db`: the read-only popup now explains each of
the six existing observation groups with its own timestamps, available expiry
basis, safe diagnostic and current affected-work scope. Unprovided Runtime/
Version thresholds are labelled missing. Cold persistence cannot imply a reliable
zero age; the existing legal RECOVERED state remains renderable. The header uses
the priority component's own freshness when the old contract supplies it.

Actual keyboard tests reproduce and correct lost middle/end reading positions
and cleared selections during updates. Facts are not frozen; forward/backward
selection follows unchanged content. Corrected targeted regression: 28 passed
in 71.84 s. The corrected `2ec99b1` related regression passed 275 cases in 450.63 s.
A subsequent independently flagged long-text matching cost was reproduced and
reduced by localizing character matching; 20 targeted cases pass on `e1bc5db`.
Its final related regression passed **277 cases in 459.11 s**, zero failures,
errors or skips, on frozen source `e1bc5dbc47a35426d2c9e028f76e8c72ee826d20`.
Both axes rechecked: Standards 1 hard P2 and 1 separate performance P2 resolved;
Spec 2 P2 resolved; no new findings on either axis. Final ordinary/compact frames
at text100/200%, DPR1, were inspected for read-only scroll/keyboard reachability.
Dense legacy diagnostic wording is not certified as final visual/language polish.
An initial candidate full run crashed natively in retained Tasks; isolated and
original-prefix replays pass, but the crash cause remains unknown. Detailed
reports, scope and limitations are in `frontend-v21-issue134-health-routing-progress.md`.
No full #134/D14 acceptance, release or native DPI/UIA certification is implied.

## Previous header-summary increment

Local source `b3cb493`, review correction `55b4f80`: the top bar presents readable
status, freshness and priority component impact, with full affected-work scope
in the accessible name. Unknown observation freshness cannot appear normal.
Cache failure is included, and a completed Task no longer conceals an independent
system limitation in compact view. Text width is measured; when the compact
summary cannot share a narrow row with branding, branding yields first without
shrinking text or replacing the focused button.

The two review defects were reproduced publicly and corrected. Standards reports
2 P2 resolved/0 new; Spec reports 1 P2 resolved/0 new (one overlaps). Eight header
cases plus two real exact-Task cases pass the targeted run, 10 passed in 6.87 s.
The candidate source's related regression was 255 passed in 438.10 s; corrected
source `55b4f803fdb51a42cbc0028e2b8cb24c7360fe33` final related regression is
**257 passed in 394.12 s**, with zero failures, errors or skips. Actual final
frames were inspected at 640×360, 960×480, 960×540 and 3840×2160, text 200%, DPR1;
the 640 check certifies the header only, not the entire small workspace. Detailed
scope, immutable red/green reports and hashes remain in
`frontend-v21-issue134-health-routing-progress.md`.

These are offscreen Software/QAccessible checks, not native Windows UIA,
physical DPI, Narrator, normal/package entry or cold-start acceptance. The popup's
complete per-group observation times/expiry and the other ticket gates remain open.

## Previous exact-observation increment

Local source `b05f62e`, review correction `2d11870`: exact Run/Evidence remount
probes are now permanent; health identifies the observed Campaign member, excludes
another Run's retained evidence, and does not adopt an unselected default Task.
For an unrelated Campaign it clears the health association, explicitly explains
system-only facts, preserves both page selections and restores the Task association
on return to Lab. No Feature Interface or execution owner changed.

Final fixed-source regression: **249 passed**, 442.44 s console, zero failures,
errors or skips; actual source `2d11870fbd7d93aa032dae580882a67a1dfeaeee`.
Offscreen Software health frames record 1426×786/100% and 960×480/200%, DPR 1.0,
read-only accessible values, keyboard-to-end reading and Escape focus return.
They are not native Windows DPI, Narrator or full visual acceptance.

Two independent review axes confirmed their cross-Campaign P2 resolved with no
new findings. Detailed scope, failing reports retained without relabelling,
targeted regression and source-bound final evidence are maintained in
`frontend-v21-issue134-health-routing-progress.md`. The previous full-Host blocking
failure in the historical section below is resolved for the tested Scenario,
exact Run and Evidence remount paths; all-case continuity is not certified.

## Scope of this checkpoint

This is an unfinished implementation checkpoint. #134 remains OPEN and none of
its complete acceptance criteria is marked passed. The full #133–#171 goal is
unchanged. No release, main-branch merge or public upload is part of this checkpoint.

- A four-destination QML shell is composed through the existing public
  `MainWindow(..., research_shell=True)` / `JourneyWorkspaceHost` entry. It uses
  the same AppContext Features and existing Qt projections. There is no second
  application, domain store or execution owner.
- The Combination Library lists and reads real, exact legacy strategy resources
  through #133's public query extension. It discloses legacy identity and missing
  authoring capability; it does not manufacture Factors or Combinations.
- Measured text width determines whether this first list/detail surface uses a
  side-by-side view or a reversible drawer. One ListView is reparented, not copied.
- Top health observation remains subscribed while pages change. Its read-only
  overlay displays the six existing fact categories; Escape returns to its trigger
  without changing the observed route. Unknown is not presented as healthy.
- The legacy six-route QML entry and Widgets rollback are unchanged by default.
  The new shell is **not yet the normal application/package entry**. The current
  resource checkpoint replaces status-only Scenario/Lab/Archive surfaces with
  exact read-only resource browsers, as detailed in
  `frontend-v21-issue134-resource-pages-progress.md`. These remain incomplete
  product workflows, not the intended final authoring or analytical capabilities.

Visual direction: restrained dark work surface, clear row selection and precise
identity text, no card mosaic or decorative motion. Content order: navigation,
current resource identity/status, explicit read action, details and limitations.
Frequent navigation and keyboard/drawer actions have no transition delay.

Latest local resource checkpoint: fbc915a, followed by invalid-reference fix
6d33e71. The final combined offscreen run passes 92 cases; separate old Scenario,
Task and Evidence route coverage passes 38. Resource increment Standards review:
0 findings. Spec review: 1 P2 fixed and independently rechecked. The latest source
startup samples bind to 6d33e71, not the earlier a07793c: Software 896.4478 ms
(DPR 1.5), Direct3D11 1015.8907 ms (DPR 1.0), both over 750 ms, with no equal-DPR
comparison or formal acceptance claim. See the resource progress document and
`frontend-v21-issue134-resource-startup-source-probe.json` for exact evidence.

Archive drill-down is now implemented at f0e0ef0 with original comparisons and
findings, exact related-object navigation (including same-package cross-candidate
references), and reversible key-based returns. Its first combined run passes 107
cases and the old Evidence route separately passes 4. Follow-up return-focus and
scroll fixes at 231748a pass **109 cases**; both independent review axes confirmed
their identified issues resolved. Details are tracked in
`frontend-v21-issue134-archive-drilldown-progress.md`;
native/startup and remaining shell gates below are not waived.

Latest health-routing checkpoint: `4c96d10`, review fix `e75ce98`, and isolated
CJK evidence fixture `5dd9bd9`. Legacy health activation now opens an overlay over
the observed page, startup retains a safe explicit parent or explains a fallback,
missing health is explained, and the opt-in host does not write the old Journey
bookmark sink. Its navigation remains session-only until generation-3 persistence.
Read-only keyboard navigation and modal return are verified at normal/compact
sizes. Final combined regression: **171 passed in 104.19 s**. Standards and Spec
each identified the same P2 missing-capability explanation and independently
confirmed it resolved; no outstanding new findings. Scope limits and source-bound
reports are in `frontend-v21-issue134-health-routing-progress.md`. This does not
prove real background execution continuity or complete #134.

Latest execution/remount checkpoint: `044db2a` unifies the research Strategy,
Scenario and Tasks initial/subsequent observation lifecycle; `35f64e4` prevents
passive Task recovery from replacing exact Run/Evidence selections and corrects
cold-read wording. The real in-flight Scenario remount probe now passes both
minimal and all-Feature composition. Default legacy behavior remains unchanged.
Final related offscreen regression on 35f64e4: **239 passed in 290.88 s**, including
12 new execution/observation cases and the retained Strategy, Scenario, Tasks,
Run-to-Evidence, Journey and health paths. Standards confirmed its P2 resolved
with 0 new hard/specific heuristic findings; Spec confirmed P2/P3 resolved with
0 new deviations. Full reproduction history and scope limits are recorded in
`frontend-v21-issue134-execution-continuity-progress.md`. These are local progress
results, not complete #134, an automatic scheduler, formal DPI or startup PASS.

## Evidence recorded so far

Evidence folder: `F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
The new tests exercise AppContext live/fake instances and actual QML keyboard
input; scheduling is controlled through the existing public Executor input.

- `research-navigation-red.xml`: missing research-shell interface; then
  `research-navigation-green.xml`: 1 passed.
- `research-health-red.xml`: missing overlay. Subsequent source-control probes
  are retained as failures, not passes. The fake initially has unknown data:
  runtime availability, admitted data revision, and aggregate observation are
  separate events. `research-health-observation-green.xml`: 2 passed after all
  three explicit fixture events. No production freshness gate was weakened.
- `research-assets-red.xml`: 4 failures before the resource-page observation
  existed. `research-assets-green.xml`: 6 passed, including the two preceding
  behaviors and live/fake exact reads at 1426×786/text100% and 960×480/text200%.
- `research-first-slice-current.xml`: 9 passed including empty and source-failed
  page states. Rendered frames under `frames-current/` were visually inspected.
- `research-main-window-red-valid.xml`: 2 expected failures for the missing public
  MainWindow argument; `research-main-window-green.xml`: 2 passed. The earlier
  `research-main-window-red.xml` was a test-edit syntax error, not behavioral red.
- `research-first-slice-regression-current.xml`: **75 passed**, 31.59 seconds:
  11 new shell cases, 25 retained Journey Rail cases, and 39 exact-inspector cases.
  The last change after this run only improves read-only action descriptions;
  final validation of the finished ticket remains required.

### Focus-frame observer correction

The first combined run had 66 passes and 7 failures in existing focus-edge pixel
checks. An isolated run had 2 passes and 6 failures. An unmodified archived f354f03
source tree reproduced the same symptom (5 passes, 3 failures), with keyboard
focus assertions still true. Therefore those failures did not establish a new
shell regression.

Reading the current Qt Quick framebuffer instead of QWidget's potentially stale
composited capture made all 8 pixel cases pass (`legacy-focus-framebuffer-probe.xml`).
The test still requires no edge before focus and a painted edge after real Tab
input; it does not assert a private border property. The 75-case run above used
that observer correction. This is offscreen painted-QML evidence, not native UIA,
Narrator or a new formal physical-DPI acceptance claim.

### First native startup follow-up on a07793c

After the initial untimed TDD projections, two dedicated Windows processes loaded
the actual AppContext/live MainWindow shell with independent settings and data:
Software PID 273352, **1031.3021 ms**; Direct3D11 PID 278044, **871.8108 ms**.
Both are over the unchanged 750 ms target. These are source-composed diagnostics,
not installed-package acceptance. Both exact samples and hashes are recorded in
`frontend-v21-issue134-startup-source-probe.json`; the scratch probe and raw reports
are retained. Actual client 1426×786, DPR 1.0, Microsoft YaHei UI, 2 real assets.
OS file caches were not cleared or controlled; no cold-cache/percentile claim.

The probe captured an intermediate frame whose public query state was ready but
whose QML list still had zero rows. Only the later rendered two-row projection
counted as usable. The initial TDD timing gap remains explicit rather than being
retroactively labelled measured. Native first-frame images were visually inspected.

## Two-axis review and fixes

Both independent review agents reviewed the implementation checkpoint pinned to
`git diff f354f0328ba33e10f98b8018e886d170c8d72c0d...a07793c07cc6852e877c1b9927cd2461b387c23b`.
The only commit in that range was a07793c. They subsequently performed read-only
targeted rechecks of the fixes below. Neither reviewer ran tests or changed files.

### Standards

One P2 documented-standard finding: entering compact layout reparented a focused
list into a closed drawer, violating ADR-0039's semantic-focus reflow rule. The
fix captures actual list focus before moving the existing ListView, opens the
drawer when necessary and restores list focus on widening. The reviewer confirmed
this finding resolved and found no concrete new hard-standard problem in the fix.
No additional baseline smell was reported as a concrete behavioral problem.

### Spec

One P2 implementation-error finding: the retained run-monitoring route displayed
the inactive task adapter's status rather than the subscribed run projection.
The explicit run branch now reads existing campaign/run identities, status,
lifecycle and progress, labelled as a legacy-run compatibility view. No Attempt,
checkpoint, latest-selection or execution semantics were invented. The reviewer
confirmed this finding resolved with no new specification deviation in the fix.
The previously recorded unfinished #134 scope below remains unfinished.

Review summary: Standards 1 P2 resolved, no outstanding new finding; Spec 1 P2
resolved, no outstanding new finding. This is not whole-ticket acceptance.

| Before | After | Why |
| --- | --- | --- |
| Shrinking a focused list hid its keyboard target. | The same list remains focused in an opened compact drawer and returns on widening. | Preserve keyboard continuity without duplicating selection or adding motion. |
| An exact run route showed the task list's stale summary. | It shows its subscribed exact run identity, lifecycle and progress. | Keep the displayed resource consistent with its active observation. |

### Review-fix regression evidence

- `run-route-review-red-valid.xml`: 1 behavior failure for the absent exact run;
  `run-route-review-green.xml`: 1 passed. The earlier `run-route-review-red.xml`
  failed in test preparation because the default context had no selected run;
  it is not counted as a valid behavioral red. The corrected test uses the public
  host constructor with an exact typed context and observes running → completed.
- `reflow-focus-review-red.xml`: 2 failures (live/fake); then
  `reflow-focus-review-green.xml`: 2 passed. A single live QML window changes
  1426×786 → 960×480 → 1426×786 → 960×480, retains the exact selection, returns
  focus on Escape and completes the same exact read. Resizing while details hold
  focus must not open the drawer or steal focus.
- `research-review-fixes-regression.xml`: **78 passed**, 38.23 seconds: 14 new
  shell cases, 25 retained Journey Rail cases and 39 exact-inspector cases.
  These are offscreen software tests, not native UIA or physical-DPI acceptance.

SHA-256 binding for the final review-fix run (local file bytes before commit):

| Artifact | SHA-256 |
| --- | --- |
| `research-review-fixes-regression.xml` | `F670CE6AA12B55F8A4B6FAD0A9D5B769BF2D618E8895C3322C4D220BA9AFF16A` |
| `app/ui/qml/ResearchAssetPage.qml` | `846CF1255B5A4083AF6BA3B2298EF3EBCF2E7599502D80A9672F5E915510772C` |
| `app/ui/qml/ResearchWorkspace.qml` | `4298BB88AAE8944A89A51EFBABF6F22E7DE9FBF274B6712C187DDA1A7477C4C8` |
| `tests/frontend/integration/test_research_workspace_shell.py` | `360DA065F682F14A2A675A13121BC6B3AF891CD3FD45FECE91493B50853D5743` |

## Remaining shell-first work (corrected ownership)

### Execution observation checkpoint — 2026-09-14

Source `80f33e502c782042880b01bae7df25518988c31a` adds real in-flight public
Start evidence for page switching, health overlay use and view-observer disposal.
Unused legacy selection/form reads no longer block these research page changes;
Scenario observation reads are asynchronous and retained content is marked stale
while waiting or after an explained, recoverable read failure. Final local
regression: **191 passed**. This is one real completed Campaign Case, not a new
automatic scheduler or full campaign completion.

An independent full-Host remount probe still **fails**. Its targeted stack shows
an initial legacy Strategy snapshot waiting for the running calculation; other
eager construction reads remain to be isolated. The 191 passing regression cases
do not include or negate that known failure. Full review details, source/report
hashes and scope are in
`frontend-v21-issue134-execution-continuity-progress.md`. #134 remains OPEN.

### Remaining implementation and verification

1. Finish resource-state coverage after the existing Scenario/Lab/Archive reads
   and Archive relation drill-down: live unavailable-source recovery and retained
   exact context; independently usable task/run observation inside the Lab.
   Do not expose legacy AI authoring as V2.1 creation or invent Attempt/checkpoint
   semantics. Full creation and cross-experiment analysis remain successor slices.
2. Finish ticket-local semantic focus fallback and modal containment. Schema3
   migration belongs to #165, and complete cross-restart research context to #164;
   neither is a #134 prerequisite. Basic legacy health parent/overlay routing, readable header
   and per-group observation facts are implemented in the newer checkpoints;
   their bounded evidence is not full health or migration acceptance.
3. Extend the now-tested real page switching, observer disposal and full Host
   remount to broader active Lab task/run selection and late completion across
   context generations. The historical eager-construction blocking repro above
   was resolved for the tested Scenario/exact Run/Evidence paths by the later
   `2d11870` checkpoint; it is not a currently reproduced defect for those paths.
   That does not certify every remount/lifecycle combination.
4. Finish compact/normal/wide layout and evidence-region behavior, resizes with open
   drawers, text 100/200%, UIA name/role/value/state and actual client/DPR records.
5. Complete the ticket-local usable-state evidence beyond the now-recorded public
   entry resource frames: typed freshness/source identity, empty input and core
   operability. Retain the above-budget measurements. Formal installed-candidate
   A41 certification is later shared work; never claim it from skeletons, warmed
   state, a smaller boundary or inherited Wave 4 exemptions.
6. The source console/package-module research entries are now wired explicitly;
   legacy defaults and original input bytes are preserved. This does not prove
   the future built/installed candidate, whose evidence belongs to its own gate.
7. Complete ticket-local standards/spec review, retained journeys and native tests,
   bind final evidence to exact source/input versions, then consider #134 closure.

Full Narrator and formal physical DPI matrix are later shared gates. That does not
remove #134's local QML and accessibility obligations. No full acceptance group or
the V2.1 implementation goal is declared complete here.
