# Frontend V2.1 #134 — resource browser progress

Date: 2026-09-14. Predecessor `07b691236978164ccdf5b4726eaa68e0d9d33f3f`.
This is an implementation checkpoint, not #134 acceptance or a public release.
#134 was freshly read through the authenticated host CLI: OPEN, assigned m4ngod,
ready-for-agent. The sandbox credential lookup returned 401; host read succeeded.
No comments or remote state were changed. The published #132 v1.0 SHA-256 remains
`A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.

## Open-drawer identity/focus and readonly Run follow-up — 2026-09-14

Fixed predecessor `e177bcebc52f59b456d9aff455ffdc1a98c17604`; first test-only
checkpoint `4ceacd32c6b3184ffa49260f442940030c87ba20`; final source/tests
`16bdba96fbcf523d2cf56df43d48272146f08a9b`. No Feature Interface, persistent
identity, observation owner or execution behavior changed.

The new live Scenario test uses the existing public application's persisted
inventory and the real QML browser. It requires at least two scenarios, explicitly
selects index1 by keyboard, then checks that same identity/index through
wide→960x480→960x540→wide→960x480. The open drawer becomes the inline list on
widening and remains focused and within the actual client; Escape returns to its
visible trigger, and reopening/Enter returns to the same exact details. Both
100% and 200% fonts are covered. This is a new check of existing correct behavior,
not a product fix. The first test draft used a nonexistent `identity` field;
`resource-open-drawer-first.xml` has two setup failures, not behavioral reds.
Using the actual `scenario_id` fixed the test. Independent review then identified
that selecting index0 could miss a reset-to-first regression; the final test uses
the non-default Scenario and asserts index1 before and throughout reflow.

The old Run compatibility summary, however, had two genuine failures:

- `run-summary-readonly-red.xml`: QAccessible readOnly=0 despite actual readonly
  text. One failure, 1.751 s. Explicit `Accessible.readOnly: true` corrects it.
- `run-summary-readonly-matrix.xml`: all8 Ctrl+End checks still failed, cursor0
  instead of the122-character end. Explicit `selectByKeyboard: true` enables
  readonly keyboard reading. `run-summary-keyboard-matrix-green.xml`:8 passed,
  4.564 s, zero failures/errors/skips.

The final Run test checks QAccessible name/role/value/readonly, rejects attempted
typing, verifies the focused end cursor is within the client and retains the exact
Run's running→completed identity/status transition. Four logical sizes at two font
scales are recorded. The fixture is the supported fake AppContext, not a real Run
or a UIA replacement. Production correction is exactly two QML properties.

### Final verification and review

All reports are under the established issue134 scratch directory:

- `local-accessibility-reviewed-regression.xml`:104 passed,57.25s console /
  57.222s JUnit,0failures/errors/skips; source frozen16bdba9. Four complete resource,
  shell and public-entry modules. SHA-256
  `1D695BA77459C8A2116554C8D6BD069A1A6B6A2A9C02079417DF05AA6E708CA3`.
- `run-summary-native-software-16bdba9/results.xml`:8 passed,4.245s JUnit;
  SHA-256 `33B75F346699A25B03BDC7DED622942755DE465610AF68E1FFE09BFF78454578`.
- `run-summary-native-d3d11-16bdba9/results.xml`:8 passed,5.963s JUnit;
  SHA-256 `CB06E81530699FB8BBC22D55AC590B024C051591239E735B8DBB1F51708445F2`.
- Scratch native runner `run-summary-native.ps1`, SHA-256
  `0B8FC65C9D573854F3E3AC26FCB557E3FF27186562B6919E01A9F25879A5BB32`, rejects
  existing output directories and mismatched/missing actual renderer records.
  All database/artifact paths are isolated before Python starts. Both Windows
  processes exited0; every case records actual client, DPR1, font and matching API.
  These durations are not rendering latency or startup measurements; the native
  runs overlapped the separate regression. No new framebuffer inspection claimed.

Earlier `resource-open-drawer-valid.xml` (2 passed,6.149s) and
`resource-open-drawer-regression.xml` (47 passed,58.186s) tested index0 before the
review correction. Their results are retained but do not prove non-default
selection continuity. Final104 includes the strengthened two cases. Do not sum
overlapping runs as unique cases or call this a new complete332+ suite.

### Standards

Final independent range `e177bce...16bdba9`:0 hard-standard violations,
0 actionable Fowler smells. The first-row-only coverage concern was addressed;
the product still exposes a readonly projection, not another execution path.

### Spec

Same final range:0 actionable deviations. D14's identity retention, reversible
drawer, keyboard and accessible readonly expectations are more directly tested.
Both reviewers were read-only and did not run tests. Neither certifies whole#134,
native UIA, actual focus painting or full physical DPI.

Supported Computer Use still cannot initialize its kernel assets. Windows UIA
and its interactive focus-return walkthrough remain unverified; no fallback
PowerShell UIA, plugin repair or system permission changes were attempted. The
consolidated progress record contains the fresh dependency audit and user request
to report whether the official Computer Use Try now entry works.

## Truthful resource-state increment — 2026-09-14

Fixed predecessor `2822d90e7f32abb48c01f5a6cde14f5f1c9a4450`; frozen production
source `efddd31e53f411b1aea0a16b5af1a76acf38abb5`; final test-only correction
`2d70427dad8b6598ada0e2d6bfb044d2fed23082`. The official #134 body was read
again: OPEN, assigned to m4ngod. Only its body was read, not third-party comments.
This is local shell-first work, not a Feature Interface change or ticket closure.

| Before | After | Why |
| --- | --- | --- |
| An empty list claimed there were no readable resources even while the first database read was pending or failing. | The detail body retains the actual pending/error status. | Missing data is not evidence of an empty source. |
| A completed empty Scenario read used an unscoped generic message. | Only fresh ready/empty observations explain that no old Scenarios, approved versions or drafts are available. | The message describes the actual observed inventory, not future creation capabilities. |
| Lab and Archive without a requested identity exposed only raw state words. | They explicitly say no old Task/evidence was selected and no other object is selected automatically. | An absent selection is not an empty library or permission to substitute another identity. |

The shared browser now delegates its empty-detail message to the page; populated
selection, lineage navigation, scrolling, focus and retained observations are
unchanged. Two readonly Qt properties project the existing requested Task and
Evidence contexts. They create no second domain state, implicit selection,
execution owner, new Feature version or persistence schema. The UI skills guided
concise task-specific copy and preservation of immediate keyboard behavior; no
new animation or layout redesign was introduced in this increment.

### Real input and red/green boundary

`test_research_resource_states.py` uses a newly initialized SQLite database through
the public application and live AppContext. Its real Scenario snapshot is
`live_runtime`, generation 1, phase ready, freshness fresh, completeness empty;
the Scenario/version/draft tuples are all empty. Source revision is
`1af28518889c2640527176f6b32ee7686e1240d17e83973c0b9b28dfac41aff3`.
This is not an empty Combination-catalog claim: that legacy live catalog still
contains its two built-in versions. No provider or application result is replaced.

The existing real-application continuity test holds the external SQL read and
reproduces the cold pending body incorrectly asserting emptiness. A separate
external SQL read fault produces a safe unavailable state; removing the fault
and keyboard-navigating away/back recovers a genuine fresh empty observation.
Lab/Archive tests use the actual no-selection typed contexts. All database and
artifact environment settings are established before Python starts; no original
database or system configuration is used by these runs.

Retained reports under the scratch root above:

- `resource-wait-not-empty-red.xml`: 1 behavioral failure; corresponding green:
  1 passed, 3.589 s.
- `resource-real-empty-red.xml`: 1 scoped-empty wording failure; corresponding
  green including the held-read test: 2 passed, 3.740 s.
- `resource-no-selection-red.xml`: 2 wording failures; subsequent combined
  `resource-state-semantics-green.xml`: 11 passed, 4.393 s.
- `resource-real-empty-matrix.xml`: 8 passed/1 failed because the test omitted
  StrategyLibrary from the host, disabling the navigation needed for retry. This
  is a fixture error, not a product retry defect. Corrected public composition
  in `resource-real-empty-matrix-fixed-fixture.xml`: 9 passed, 3.923 s.
- `resource-state-recorded-matrix.xml`: 14 passed, 6.276 s, zero failures/errors/
  skips. SHA-256 `3C1E2E34CAE3E93D304A16625E79ABF8F2B971652595336D790571A5E1586554`.
  Recorded before the final metadata-only removal of duplicate properties and
  addition of explicit font scale to error/no-selection cases in efddd31.

### Native renderer and layout evidence

The same actual QML tests ran with the Windows platform, source efddd31, fresh
scratch persistence and reduced motion. Scenario-empty cases cover logical
960x480, 960x540, 1426x786 and 2600x1400, each at text 100% and 200%; database-error
and Lab/Archive no-selection cases cover 960x480 at both text scales. Actual
client dimensions and DPR1.0 are recorded per case. This is application font
scaling, not a changed Windows DPI setting or the full physical-DPI matrix.

- `resource-states-native-software-efddd31/results.xml`: 14 passed, 7.100 s;
  all recorded APIs are Software. SHA-256
  `8FBB4495BD3553ECC2D1722CBDDA69CC54B7642F950D1E991B10F9A126DF4283`.
- The first `resource-states-native-d3d11-efddd31/results.xml` also passed 14
  cases but **actually used Software**. Its name is not proof of a renderer.
  SHA-256 `B512F6B46BB3477DDA9F017078E40B496CB0B3EB22BF8BBB338015E09F1DF45B`.
  It is retained as a misconfigured sample, not Direct3D11 evidence.
- Cause: the imported legacy `test_evidence_and_findings_route.py` supplies
  `QT_QUICK_BACKEND=software` via `setdefault`. The native harness had removed
  the variable, allowing that default to win. The renderer-mismatch assertion
  reproduced this explicitly. The corrected harness sets an explicit empty
  backend in Python for normal RHI selection and verifies every recorded API.
  No product code changed. This environment-only correction distinguishes the
  import-default cause from hardware failure or an already initialized renderer.
- `resource-states-native-d3d11-verified-efddd31/results.xml`: 14 passed,
  10.110 s; **every actual API is Direct3D11**, checked by the runner. SHA-256
  `FC5F03DA9F08CFDEB85E3039707DB2102FD77C87E074170E3FE675646A7EE831`.
- Corrected scratch runner `run-resource-states-native.ps1` SHA-256:
  `2E4E31276E6C95F80DD76A557CFC0429F1E99319A73E472A1DBAAA1B1566234B`.

Framebuffers are retained under each run's `frames/`. Visually inspected samples
include compact Scenario empty/error at text200%, wide Scenario empty at text100%,
and compact Lab/Archive no-selection at text200%. The primary message is readable;
long limitations remain in the scrollable readonly region. Existing raw legacy
status terminology is still visible. This is not final visual acceptance.
The native runs overlapped the separate broad regression process; their suite
durations are **not** startup or rendering-latency benchmarks.

### Standards

Independent final fixed-range review `2822d90...2d70427`: 0 documented hard violations,
0 actionable baseline-smell findings. Existing typed contexts supply the new
readonly properties; public application/Feature/QML seams exercise the behavior.
The reviewer did not execute tests. The additional existing-test changes preserve
identity clearing, visible focus fallback and disconnected drill-down checks while
requiring the actual invalid reason and excluding empty/no-selection wording.

### Spec

Independent review of the same range: 0 new actionable deviations or scope creep.
D02's retained/loading distinction, D10's requested-source continuity and D15's
no-substitution boundary are preserved. The reviewer did not execute tests and
did not certify the whole ticket, native UIA/DPI or the 750 ms target.

### Regression result and corrected existing assertions

The frozen-production 20-module run `resource-state-reviewed-regression.xml`
finished with **327 passed and 3 failed**, no errors/skips, 460.79 s console
(460.699 s JUnit), SHA-256
`023DD3107F62BD109FE3600A80AE4587437F07DABEDE5FA4321D7A3A33855DE1`.
It includes the previously exercised 316 contract/old-route/product-entry/
continuity/resource/health/text cases and 14 new resource-state cases.

All three failures were old Archive invalid-reference assertions requiring the
previous generic empty-resource sentence. The actual body already showed the
correct precise invalid-reference error. Commit 2d70427 changes only those test
assertions: require the precise reason, reject generic emptiness and reject the
no-selection guide. All prior identity-clearing, list-empty, header-error and
normal/compact focus fallback assertions remain.

Both complete resource modules then passed: **45 passed**, 50.80 s console
(50.775 s JUnit), no failures/errors/skips, including the three previously failing
cases. Report `resource-state-existing-assertions-green.xml`, SHA-256
`0EA0C15E28FF6BE7407E17967C40738ACBE00E2B9998F844F4DBD16E4F90C9BD`.
Production source remained byte-identical to efddd31. The other 285 cases were
not rerun after the test-only correction; do not describe the retained 330-case
report as a single all-green final run or sum overlapping runs as unique tests.
Both processes terminated normally (first exit1, corrected resource run exit0).
The seven retained package tests from the previous entry increment were not
rerun for this readonly text change; their historical evidence remains separate.

### Remaining native accessibility boundary

QAccessible readonly/name/role and actual QML keyboard focus are checked in these
tests. They are not a substitute for Windows UIA name/role/value/state/focus.
The current Computer Use runtime failed during initialization with
`failed to write kernel assets: 系统找不到指定的路径。 (os error 3)`; resetting its
kernel and initializing once more produced the same error. No Windows app input
was sent through that tool, no fallback PowerShell UIA was used, and no tool or
system configuration was changed. Native UIA remains **unverified**. Full Narrator
and physical DPI are still later shared gates, not claimed by this increment.

## Implemented read paths

- Scenario Library: actual existing Market Scenarios, approved Recipe Versions
  and versioned Recipe Draft revisions are keyboard-readable. Identities, content
  hashes, provenance and limits are preserved. Unproved scenario types are marked
  unknown/compatibility read-only, not recategorized as Parallel. Draft revisions
  are recovery material, not newly saved formal Scenarios or migrated Build Sessions.
- Lab: an explicitly selected durable legacy Task is projected with its exact
  configuration, validation, approval, handoff and progress. Opening it does not
  create an Experiment or select another task. This is not a complete experiment
  catalogue or Attempt control implementation.
- Archive: preserved candidate evidence records expose their original identity,
  value/unit, availability, coverage and artifact/run provenance. No metrics are
  recomputed or ranked. Comparison/finding drill-down and cross-experiment analysis
  remain unfinished; this is not acceptance of the Archive journey.
- The same reusable read-only QML browser is used by all three pages. At compact
  sizes it moves the existing list into a reversible drawer. A wide Scenario
  selection exposes a separate source/dependency region when minimum content
  widths fit; at narrower sizes those facts remain in the main scrollable detail.
  Focus follows source content back into details on narrowing. Other resource
  kinds still need their full secondary-region verification.
- Six Features remain independent. Only Qt presentation properties were added;
  no Feature Interface version, typed state, command or persistence schema changed.
  No AI provider, external data, broker or manual trading operation was used.

## Test boundary and input provenance

Evidence lives in `F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
Tests use public AppContext construction, Feature commands/snapshot and actual QML
keyboard actions. The live input is produced by the existing formal-campaign
fixture through the real application, migrations, materialization and SQLite
persistence. Fake tests use the supported deterministic source; their initial
catalogue differs from the live fixture. No claim of an identical-dataset new
Feature contract is made because this checkpoint adds no Feature Interface.

The separate live Archive case creates and seals a real formal campaign using
file-backed market/evidence artifacts, closes/reopens its application and resolves
an explicit campaign/run/package/manifest through the public read model. AppContext
owns the resulting Features. The UI reads the exact saved record; the original
sealed package remains equal through the public application read after inspection.
This is synthetic input with actual computation/persistence, not external data.

### Red/green evidence and diagnostics

- `scenario-resources-red.xml`: 2 missing-browser failures; final first-resource
  green `scenario-resources-green-verified.xml`: 2 passes. Intermediate keyboard
  failures exposed that Down does not necessarily start at row zero and Qt's Keys
  has no `onHomePressed`; explicit Home handling now uses `Keys.onPressed`.
- `scenario-version-resources-red.xml`: 2 missing-resource failures;
  `scenario-all-resources-green-composed.xml`: 4 passes. Initial draft preparation
  confused old unversioned Recipe drafts with public versioned Scenario Recipe
  drafts, then omitted the already-initialized read model at AppContext composition.
  The final fixture uses public typed authoring and passes the matching read model;
  no production persistence guard was loosened.
- `lab-resources-red.xml`: 2 failures; `lab-resources-green.xml`: 2 passes,
  live/fake exact Task/config reads with no additional creation.
- `archive-resources-red-valid.xml`: missing Archive browser; then
  `archive-resources-green.xml`: 1 fake-source pass. The earlier archive red was
  a test-edit syntax error, not a valid behavior red.
- Original live Archive probes repeatedly stayed loading with a Qt-only waiting
  loop. Moving the wait before QML construction passed (`archive-resources-real-feature-probe.xml`),
  but that warm-up is NOT retained. Ranked hypotheses were test-loop thread
  scheduling, simultaneous-reader interference, and an insufficient timeout.
  With the original unwarmed window restored and the same timeout, replacing the
  loop's QTest wait with Qt event processing plus a short Python-yielding sleep
  passed (`archive-resources-real-unwarmed-scheduling.xml`, 1 pass, 14.18 s including
  full input preparation). Evidence supports test scheduling, not a production
  reader fix. No production observation, identity or freshness rule was changed.
- `resource-layout-scoped-red.xml`: 3 failures. The compact minimum was too small,
  Qt accessibility did not infer read-only, and no wide source region existed.
  Explicit accessible read-only state and measured list/detail/source minima fix
  these; `resource-layout-green.xml`: 3 passes at 960×480/text200%, 960×540/text100%,
  and 2600×1400/text100%. Client/DPR/source revision are in the JUnit properties.
- `resource-wide-focus-red-valid.xml`: source collapse lost focus; then
  `resource-focus-layout-green.xml`: 4 passes including same-window source→detail
  focus continuity. The earlier wide-focus red failed because of a misplaced
  test edit; it is not counted as behavior red.

Captured `resource-frames/research-scenario-*.png` were visually inspected. They
show an operable compact scroll region and the wide source pane. These are source
offscreen Software/QAccessible observations, not native Windows UIA, Narrator or
the full physical-DPI matrix. English legacy status terminology, long-identity
presentation and remaining per-page layout work still require refinement.

## Resource checkpoint review and verification

Resource implementation checkpoint: `fbc915a43413419d31331c89f41963e04647f157`.
Independent reviewers used the fixed, nonempty range
`git diff 07b691236978164ccdf5b4726eaa68e0d9d33f3f...fbc915a43413419d31331c89f41963e04647f157`;
the only commit was fbc915a. Both reviews were read-only; neither agent ran tests.

### Standards

No hard documented-standard violation or concrete baseline smell was reported.
The public Feature projections and original identities remain intact. List/source
reflow captures or transfers focus before hiding content, and details remain
read-only. This is a review of this increment, not full #134 acceptance.

### Spec

One P2: the shared browser retained a selected row after the authoritative resource
projection removed it. It therefore failed D02's distinction between invalid
references (clear old content and show the target error) and same-identity
temporary unavailability (retain reliable content). No scope creep was reported;
the already documented unfinished ticket work was not counted as a new finding.

The fix now resolves the selected exact key only against the current Feature
projection and clears it when absent. The Feature already owns last-reliable
retention during transient failures, so no duplicate QML cache, new Feature
Interface, string-error classification or persistence schema was introduced.
`resource-invalid-reference-red.xml` reproduces the displayed invalid record;
`resource-invalid-reference-green.xml` passes with the old identity cleared,
target error visible and detail focus retained. A separate regression drives
completed -> disconnected -> partial -> recovered and checks that the same
selection remains, its availability updates and its reliable content returns.
Both agents independently rechecked the fixed, nonempty increment
`git diff fbc915a43413419d31331c89f41963e04647f157...6d33e7175d04829e83b5b5c87755798f9cf49a31`.
Standards maintained zero findings and found no new hard violation or concrete
smell. Spec confirmed the P2 resolved with no new deviation. These were read-only
rechecks, not independent test runs or live invalidation/native certification.

Review summary: Standards 0 findings; Spec 1 P2 resolved, zero outstanding new
findings after recheck. Neither axis grants a whole-ticket PASS.

| Before | After | Why |
| --- | --- | --- |
| The other three pages only summarized status. | Existing scenes, exact selected tasks and original evidence have keyboard-readable lists/details. | Make the first shell slice useful without inventing successor authoring or statistics. |
| Wide source collapse hid a focused region. | Its exact content and focus move into visible details. | Preserve keyboard continuity as space changes. |
| The browser kept content after its reference was invalidated. | Removed authoritative data clears; same-identity retained Feature data stays visible. | Distinguish invalid references from temporary source loss. |

Completed verification for this resource increment:

- `resource-pages-regression.xml`: 90 passed in 63.72 s (14 shell, 12 resource,
  39 exact-inspector, 25 Journey Rail cases).
- `resource-pages-legacy-routes.xml`: 38 passed in 182.31 s (old Scenario, Task
  and Evidence routes); these routes do not instantiate the changed resource browser.
- `resource-review-fix-regression.xml`: 14 resource cases passed in 26.31 s
  after the fix. Three JUnit warnings concern `record_property` versus default
  xunit2 formatting; the final combined run uses legacy JUnit explicitly.
- `resource-review-fixes-full-regression.xml`: **92 passed in 63.67 s**, no warnings
  (14 shell, 14 resource, 39 exact-inspector and 25 Journey Rail cases). This final
  combined run includes the unwarmed sealed-file live Archive read again.

SHA-256 bindings:

| Artifact | SHA-256 |
| --- | --- |
| `resource-pages-regression.xml` | `9DAF2BB0131D4A2C7514530FD44373B560B92BE817444FA58148546A343D69FD` |
| `resource-pages-legacy-routes.xml` | `11D169428A684C01C6C4BAFABAFA9F76384C690E418F92E833C05A7A69987220` |
| `resource-invalid-reference-red.xml` | `A060B909B80B408D5B399BB248F38A75FD57CE8C14394F7175376960146A4047` |
| `resource-invalid-reference-green.xml` | `6C8577F2B8B798FAC5FCE93969A8CE4F88E0FBE12BE7CF4600343BAA6B4F4A22` |
| `resource-review-fixes-full-regression.xml` | `875DE312A6C9B9DE044D7E63A9C13175093432CB4A7B9EBC023D425765DD8BC0` |

## Current-source native startup diagnostics

The same source-only probe was rerun on the committed fix
`6d33e7175d04829e83b5b5c87755798f9cf49a31`, with a separate new process and
settings/data directory per renderer. Software observed the actual fresh two-row
frame at **896.4478 ms, DPR 1.5**; Direct3D11 at **1015.8907 ms, DPR 1.0**.
Both exceed 750 ms. Differing actual DPR and one sample each prohibit an equal-DPR
renderer comparison or a performance regression/improvement conclusion. No display
settings were changed. Both probes exited 0 because a usable frame was captured,
not because the speed gate passed. Captured frames were inspected.

Exact clocks, source/input revisions, report hashes and limitations are in
`frontend-v21-issue134-resource-startup-source-probe.json`. As before, a ready
public state with zero rendered rows was excluded. Only the initial Combination
page was timed; these measurements do not certify the other page projections or
the empty-resource, packaged-entry and controlled-cold-start requirements.

## Outstanding local gates

Both old a07793c and current 6d33e71 source samples exceed 750 ms. This resource
checkpoint has NOT passed formal dual-renderer cold-start or first-usable-frame
timing, native UIA or installed-package gates. Fake invalidation and transient
retention now have local evidence; the full live empty/error/waiting and exact
context-switch matrix still needs verification. Observation disposal/real running continuity,
health routing and complete semantic recovery still need ticket-local evidence.
The inherited global goal and all remaining tickets are unchanged.
