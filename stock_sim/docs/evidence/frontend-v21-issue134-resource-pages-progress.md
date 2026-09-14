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

## Outstanding local gates

The first native startup samples still refer to a07793c, not this changed shell;
they exceeded 750 ms. This resource checkpoint has NOT passed new dual-renderer
cold-start or first-usable-frame timing, native UIA or installed-package gates.
Empty/error/waiting resource states, observation disposal/real running continuity,
health routing and complete semantic recovery still need ticket-local evidence.
The inherited global goal and all remaining tickets are unchanged.
