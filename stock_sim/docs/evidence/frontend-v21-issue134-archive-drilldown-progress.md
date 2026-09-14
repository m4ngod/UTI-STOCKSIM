# Frontend V2.1 #134 — preserved Archive relations

Date: 2026-09-14. Audited local predecessor:
`a5c702b9abbd0d56538f8c3383f5ee97efb1534d`.
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

## Remaining #134 work

This increment does not complete old-health route overlay migration, all exact
context/focus recovery paths, real running continuity across page observation
disposal, per-page live waiting/empty/error/native accessibility coverage, formal
normal/package entry, or startup performance. Previous source-only timing binds
to 6d33e71 and exceeded 750 ms; it is not a pass for this changed source. The full
#133–#171 goal remains active and unchanged.
