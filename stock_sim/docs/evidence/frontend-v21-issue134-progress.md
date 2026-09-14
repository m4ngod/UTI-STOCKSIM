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
  The new shell is **not yet the normal application/package entry**. Other three
  new pages currently contain only existing status projections, not their required
  usable resource views. This transitional condition is not the intended end state.

Visual direction: restrained dark work surface, clear row selection and precise
identity text, no card mosaic or decorative motion. Content order: navigation,
current resource identity/status, explicit read action, details and limitations.
Frequent navigation and keyboard/drawer actions have no transition delay.

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

## Required next work (not waived or deferred out of #134)

1. Replace the other three pages' status-only surfaces with usable, exact existing
   resource projections and honest capability limitations. Preserve independent
   task/run capabilities inside one Lab; do not expose legacy AI source selection
   as V2.1 scenario creation or infer new Attempt/checkpoint semantics.
2. Finish context-aware read-only health summaries, each group's observation age
   and impact, legacy-health routing, semantic focus fallback and modal containment.
3. Test switching pages during real execution and late read completion; demonstrate
   disposal of page observations without cancellation of application work.
4. Finish compact/normal/wide layout and evidence-region behavior, resizes with open
   drawers, text 100/200%, UIA name/role/value/state and actual client/DPR records.
5. Instrument and record both renderer cold-start boundaries and first actual usable
   projection frames. No 750 ms measurement or PASS exists in this checkpoint;
   the initial source-level test projections above did not collect timing evidence.
   Keep that gap explicit. Formal entry/package integration must not use skeletons,
   warmed state, a smaller boundary, or inherited Wave 4 exemptions to pass.
6. Wire the finished shell into normal and packaged entries with explicit legacy
   compatibility entry; preserve old bookmark generations and exact identities.
7. Complete ticket-local standards/spec review, retained journeys and native tests,
   bind final evidence to exact source/input versions, then consider #134 closure.

Full Narrator and formal physical DPI matrix are later shared gates. That does not
remove #134's local QML and accessibility obligations. No full acceptance group or
the V2.1 implementation goal is declared complete here.
