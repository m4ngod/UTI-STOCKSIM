# Frontend V2.1 #134 — implementation progress, not acceptance

Date: 2026-09-14. Ticket: https://github.com/m4ngod/UTI-STOCKSIM/issues/134.
Parent: published specification #132 v1.0. Audited predecessor:
`f354f0328ba33e10f98b8018e886d170c8d72c0d` (#133).

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

## Required next work (not waived or deferred out of #134)

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
2. Finish context-aware read-only health summaries, each group's observation age
   and impact, broader semantic focus recovery and modal containment. Basic legacy
   health parent/overlay routing is implemented; generation-3 durable migration
   and real execution continuity are not complete.
3. Extend the now-tested real page switching and observer disposal to full Host
   remount, active Lab task/run selection and late completion across context
   generations. The confirmed eager-construction blocking read is still open;
   view disposal passing is not remount acceptance.
4. Finish compact/normal/wide layout and evidence-region behavior, resizes with open
   drawers, text 100/200%, UIA name/role/value/state and actual client/DPR records.
5. Extend the recorded source probes to the finished shell and formal package's
   dual-renderer cold-start and first actual usable frame gates. The two source
   samples above exceed 750 ms, and the initial untimed TDD projections remain
   a recorded gap. Formal entry/package integration must not use skeletons,
   warmed state, a smaller boundary, or inherited Wave 4 exemptions to pass.
6. Wire the finished shell into normal and packaged entries with explicit legacy
   compatibility entry; preserve old bookmark generations and exact identities.
7. Complete ticket-local standards/spec review, retained journeys and native tests,
   bind final evidence to exact source/input versions, then consider #134 closure.

Full Narrator and formal physical DPI matrix are later shared gates. That does not
remove #134's local QML and accessibility obligations. No full acceptance group or
the V2.1 implementation goal is declared complete here.
