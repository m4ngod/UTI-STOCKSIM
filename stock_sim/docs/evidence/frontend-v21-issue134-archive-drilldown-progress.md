# Frontend V2.1 #134 — preserved Archive relations

Date: 2026-09-14. Audited local predecessor:
`a5c702b9abbd0d56538f8c3383f5ee97efb1534d`.
Implementation checkpoint: `f0e0ef0d00189a067e492ee4777e50847a4553f8`.
This is an implementation checkpoint, not #134 closure or V2.1 acceptance.
#134 was freshly read: OPEN, assigned m4ngod, ready-for-agent. Published #132 v1.0
SHA-256 remains `A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.
No issue comments, remote source, system settings, external data or AI provider
were changed or used. The unrelated dirty main workspace remains untouched.

## Scope and implementation

D15 requires the old Evidence route to preserve original record/comparison/finding
drill-down. The four-page Archive now projects all three through its existing Qt
adapter and typed Feature snapshot. It displays original comparison identities,
reference/observed evidence, interpretation, finding disposition and failure
reason, sensitivity-breakpoint details and exact package/candidate/run provenance.
It neither recalculates results nor elevates incomplete evidence to a conclusion.
This remains a legacy compatibility path, not cross-experiment analysis or the
final Archive workflow delivered by later vertical slices.

Association buttons read exact related objects. The return stack contains keys,
not copied records. Going back resolves against current authoritative rows;
missing parents or an invalidated source show an explained empty detail instead
of old content or a replacement object. Actual references may cross candidates
inside the same evidence package: the public typed payload permits that and
enforces package-wide uniqueness and referential validity. The key index therefore
uses the target's actual owner, not the selected candidate by assumption.

The shared QML resource browser provides keyboard-operable related actions and a
return control. Tab exposes the focused action in the scroll region, Enter/Space
activate it, and successful return focuses details. Layout changes re-expose a
focused link after its geometry settles. Removing a focused related action through
source invalidation falls back to the visible parent list, or its compact drawer
trigger. Same-identity temporary disconnection retains the reliable selection and
focused action. No motion or command execution was added to these navigation paths.

No Feature Interface version, domain model, command, subscription contract or
persistence schema changed. This is not a durable recovery-generation migration;
that remaining work is not implicitly satisfied by the local return stack.

## Test seams and provenance

The pre-agreed seams remain public AppContext assembly and Feature snapshots,
commands/scripted fake delivery, with actual QML keyboard input and observable
details/focus/geometry/QAccessible facts. No test calls a private production helper
or edits a persisted database to obtain its expected result.

Fake cases use the supported deterministic source and validated typed replacement
states. Cross-candidate input is explicitly constructed through the public typed
payload. Live cases create and seal a real formal campaign in file-backed SQLite
and artifacts, close/reopen the application, resolve exact campaign/run/package/
manifest identities through the public read model and display the preserved data.
The sealed package remains unchanged through the public application read. These
are synthetic inputs with real application computation/persistence, not external
market or AI acceptance data.

Evidence directory: `F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.

- `archive-comparison-red.xml`: 1 missing-comparison failure;
  `archive-comparison-green.xml`: 1 pass.
- `archive-drilldown-red.xml`: 2 missing-link failures. Initial implementation
  probes still reported missing controls because QObject ownership traversal
  omitted dynamically created QML delegates. A visual-tree lookup exposed the
  actual buttons, then `archive-drilldown-visual-tree.xml` caught 2 genuine Enter
  activation failures. Explicit Return/Enter support fixed them:
  `archive-drilldown-green.xml`, 2 passes. No timing delay or domain change was
  used to fix the observer mismatch.
- `archive-finding-red.xml`: 2 missing-finding failures;
  `archive-relations-green.xml`: 4 comparison/finding round-trip passes.
- `archive-relations-live-sealed.xml`: 3 passes in 40.96 s, original record,
  comparison and finding reads from reopened sealed artifacts. No prewarming the
  Feature before QML construction was added.
- `archive-related-focus-red.xml` is misnamed: it passed on its first run and is
  retention regression evidence, not a behavioral red or a production fix.
- `archive-missing-relations.xml` rejected 2 invalid test inputs at typed payload
  construction. These are setup failures, not product behavior failures. The
  production referential guards were preserved; final missing-parent and invalid
  source cases use valid public states.
- `archive-cross-candidate-red.xml`: 2 failures for incorrectly assuming every
  referenced record belongs to the current candidate, plus 2 valid missing-parent/
  source passes. Resolving the actual package-wide owner fixes the former.
- `archive-relations-edges-green.xml`: 8 passes, 1 compact high-text failure with
  a focused link outside the client after a relation layout change. The final
  browser re-exposes the focused control on position/height changes; geometry is
  asserted after the next Qt layout/render opportunity. Then
  `archive-relations-edges-green-verified.xml`: 9 passes in 4.63 s.
- `archive-invalid-link-parent-focus-red.xml`: 1 failure and 1 retention pass;
  `archive-invalid-link-focus-green.xml`: 2 passes. The lost link focus now returns
  to the actual parent list; the final suite also tests the compact trigger path.

Final combined run: `archive-drilldown-full-regression.xml`, **107 passed in
90.51 s**, no warnings (29 resource cases, 14 shell, 39 exact-inspector, 25 retained
Journey Rail). Its SHA-256 is
`0CF72F80AABD3A14704E87AFB3F212BA52133462208DE250FC6704AAAF60578B`.
The 6 comparison/finding/cross-candidate navigation cases record actual client,
DPR, text scale and evidence package. Their links expose accessible names,
button roles, focusable/enabled state and on-client geometry. Independent review
is pending for this checkpoint. QAccessible and offscreen screenshots do not
substitute for native Windows UIA, Narrator, or the full physical-DPI matrix.

The separate unchanged legacy Evidence route is also green:
`archive-drilldown-legacy-evidence-route.xml`, **4 passed in 1.76 s**. Source
screenshots in `archive-drilldown-frames/` were inspected at 1426×786/text100% and
960×480/text200%. They show the comparison's exact relation buttons and an
operable compact scroll region. The legacy English terms, long-text density and
default scrollbar styling remain refinement work, not a full visual acceptance.

| Before | After | Why |
| --- | --- | --- |
| Archive exposed only original record values. | Comparisons and findings retain their original relationships and support exact, reversible drill-down. | Preserve the legacy analytical path without recomputing conclusions. |
| Dynamic related buttons did not respond to Enter. | Enter and Space both activate the exact related object. | Keep keyboard behavior consistent across the workspace. |
| A focused relation could move off-client after layout changed or disappear after source invalidation. | Layout re-exposes the action; invalidation returns focus to the visible parent list entry point. | Keep the currently actionable keyboard target reachable. |

## Independent review and follow-up behavior checks

Both independent review agents inspected the fixed, verified nonempty range
`git diff a5c702b9abbd0d56538f8c3383f5ee97efb1534d...f0e0ef0d00189a067e492ee4777e50847a4553f8`;
f0e0ef0 was its only commit. Both were read-only and did not run tests.

### Standards

The initial fixed-code review found no confirmed hard violation or concrete smell.
It correctly identified three scroll behaviors requiring actual input validation:
long-text keyboard navigation after wrapping TextArea in a Column; retaining an old
scroll offset when selecting another resource; and cutting off a focused link by
shrinking height without changing width. Main-task follow-up tests then confirmed
these behavior gaps. Their fixes and evidence are below; final independent
classification/recheck is pending, so the initial zero count is not presented as
final acceptance of the follow-up.

### Spec

One P2: when a return-stack parent no longer resolved, `resolveRelated()` cleared
the content but focused empty details instead of the parent list/title required
by D14. The test also incorrectly expected detail focus. The corrected normal and
compact tests both require the visible parent list or list trigger. The shared
`focusParent()` path now handles missing returns as well as removed focused links.
`archive-review-parent-return-red.xml`: 4 failures; then
`archive-review-parent-return-green.xml`: 14 relevant navigation cases pass.
Independent recheck is pending for this tested fix.

### Scroll red/green evidence

- `archive-long-detail-keyboard-red.xml` passed but only inspected the unchanged
  cursor rectangle. It was a weak check, not a valid keyboard-navigation pass.
  Adding an assertion that Ctrl+End actually reaches the text end produced
  `archive-long-detail-keyboard-position-red.xml`: 2 failures. Enabling read-only
  keyboard selection then exposed the compact cursor outside the visible area
  (`archive-long-detail-keyboard-enabled.xml`: 1 fail, 1 pass). Cursor movement now
  scrolls its actual region into view; text remains read-only.
- `archive-height-resize-focus-red.xml`: 1 failure at 1426×786 -> 1426×480 with
  width held constant and the same link still focused below the client. Changes
  to available scroll height now re-expose the focused link or text region.
- `archive-catalog-reselection-scroll.xml`: 1 compact failure, 1 normal pass.
  Selecting another long finding after scrolling links retained the old offset;
  the first line was above the viewport. Explicit catalogue selection now resets
  the content offset. It does not reset the source or replace identities.
- `archive-review-all-navigation-green.xml`: 14 passed in 5.78 s, including both
  return-failure states at normal/compact size, source retention/invalidation,
  original and cross-candidate relations, same-window height resize, true text-end
  navigation, text-home navigation and subsequent catalogue selection.
- Final follow-up combined run: `archive-review-fixes-full-regression.xml`,
  **109 passed in 86.80 s**, no warnings (31 resource, 14 shell, 39 exact-inspector,
  25 Journey Rail cases), including all three reopened sealed-file live reads.

| Before | After | Why |
| --- | --- | --- |
| Invalid return focused empty details. | It focuses the visible parent list or compact list trigger. | Match D14's semantic fallback. |
| Ctrl+End was inert, then exposed a cursor outside the viewport when enabled. | Read-only keyboard selection works and its actual cursor region is scrolled into view. | Reading and copying long details must remain keyboard-operable. |
| Height-only resizing or selecting another long resource could retain an unusable scroll offset. | Available-height changes preserve focused content; catalogue selection opens details at the beginning. | Keep focus and precise identity visible when layout or selection changes. |

## Remaining #134 work

This increment does not complete old-health route overlay migration, all exact
context/focus recovery paths, real running continuity across page observation
disposal, per-page live waiting/empty/error/native accessibility coverage, formal
normal/package entry, or startup performance. Previous source-only timing binds
to 6d33e71 and exceeded 750 ms; it is not a pass for this changed source. The full
#133–#171 goal remains active and unchanged.
