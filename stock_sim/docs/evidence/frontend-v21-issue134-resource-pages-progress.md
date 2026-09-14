# Frontend V2.1 #134 — resource browser progress

Date: 2026-09-14. Predecessor `07b691236978164ccdf5b4726eaa68e0d9d33f3f`.
This is an implementation checkpoint, not #134 acceptance or a public release.
#134 was freshly read through the authenticated host CLI: OPEN, assigned m4ngod,
ready-for-agent. The sandbox credential lookup returned 401; host read succeeded.
No comments or remote state were changed. The published #132 v1.0 SHA-256 remains
`A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.

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
Reviewer recheck of this fix is pending at this checkpoint.

Review summary: Standards 0 findings; Spec 1 P2 with a tested local fix, pending
independent recheck. Neither axis grants a whole-ticket PASS.

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

## Outstanding local gates

The first native startup samples still refer to a07793c, not this changed shell;
they exceeded 750 ms. This resource checkpoint has NOT passed new dual-renderer
cold-start or first-usable-frame timing, native UIA or installed-package gates.
Empty/error/waiting resource states, observation disposal/real running continuity,
health routing and complete semantic recovery still need ticket-local evidence.
The inherited global goal and all remaining tickets are unchanged.
