# #133 compatibility audit — implementation checkpoint, native acceptance pending

Date: 2026-09-13. Parent specification: #132, D01/D02. This is implementation
evidence, not a replacement specification or an acceptance/release approval.

## Locked baseline and ownership

- Source: `eb7349fbc23ca3113e0f55342c70b1392fda0c71` (formal Wave 4).
- Branch: `codex/issue133-v21-feature-compat` in an independent worktree.
- No dirty main-checkout changes or prototype source were copied.
- #133 was unblocked and unassigned, then assigned to `m4ngod` and read back.
- AppContext remains the sole composition root. Exact read receipts are owned by
  its existing DiagnosticsApplication, not by a second repository or QML state machine.

## Frozen contracts

Operation names below are inherited unchanged; their initial operation versions
are their respective frozen Feature versions, not the new query-envelope version.

| Feature | Baseline and retained version | Additional legacy operations beyond snapshot/subscribe/close |
| --- | --- | --- |
| StrategyLibrary | 1.0 | compare_strategies, select_formal_strategy_set |
| ScenarioLab | 1.0 | create_recipe_draft, author_recipe_with_ai, revise_recipe_draft, validate_recipe_draft, approve_recipe, materialize_reference_path, retry_materialization, compose_scenario_set, resolve_execution_assumptions, select_formal_scenario_set |
| DiagnosticTasks | 1.0 | create_diagnostic_task, revise_configuration, validate_configuration, approve_configuration, start_formal_diagnostic_campaign, pause_diagnostic_target, resume_diagnostic_target, cancel_diagnostic_target, retry_failed_campaign_node |
| RunMonitoring | 1.2 | pause_diagnostic_task, resume_diagnostic_task, cancel_diagnostic_task |
| EvidenceAndFindings | 1.1 | none |
| SystemHealth | 1.0 | none; remains read-only |

- `ACTIVE_FEATURE_INTERFACES` and all six legacy Protocol/state shapes are unchanged.
- Diagnostic persistence remains `0021_diagnostic_selection_dependency_invalidation`.
- Journey recovery continues reading original 1.0/2.0 bookmarks. No 3.0 migration,
  route deletion, historical rewrite, or Widgets rollback removal is included.
- Existing Strategy Library application contract remains 1.0.
- New capability-catalog schema is 1.0. It reports installed contract operations;
  existing typed snapshots still determine contextual readiness and permission.
- Target Feature 2.0 operations and SystemHealth 1.1 are not registered or claimed.

## Current additive slice

`AppContext.feature_capabilities()` returns typed immutable descriptions and
explicit restrictions for unavailable interface/operation requests, equally for
the actual live and fake providers.

The public `DiagnosticsApplication.query_exact_strategy_asset` implements the
initial synchronous application path, with `exact-asset-query/1.0` envelopes and
`legacy-strategy-asset/1.0` content identity. An exact retained strategy is **not**
converted to a Factor or Combination. Identity pins kind, lineage, version and
canonical material-content hash; the hash includes source, compatibility,
candidate policy, guardrails and dependency identities, not mutable display or
readiness fields. The frozen request additionally pins the inventory revision.

Responses echo the complete request. Repeating the same operation ID and inputs
replays its application-lifetime read receipt; reusing the ID with other inputs
is rejected. Stale revision, changed frozen input, missing exact version, altered
asset content and unsupported operations return structured reasons with no asset
payload. These receipts are not persisted domain assets or restart checkpoints.

The catalog now advertises only the implemented `StrategyLibrary/exact_assets`
extension 1.0, assembled as `AppContext.strategy_library_queries`. Its schemas are
`exact-asset-query/1.0`, `legacy-strategy-asset/1.0`, and
`strategy-asset-observation/1.0`; snapshot/subscribe/refresh/query_exact_asset/close
are version 1.0. This is an additive namespace, not registration of Feature 2.0.

`strategy_asset_contract.py` owns the immutable public DTO graph and Protocol.
Backend entries cross the already-existing StrategyLibraryEntry projection;
application, persistence, Qt and concurrency objects do not cross the public
extension. The live adapter calls the same application's public methods under
its shared access gate. The fake runs a frozen versioned inventory through the
same query semantics and labels its provenance as deterministic fake.

Observation epochs and source generations suppress late results after a new
target, disconnect/reconnect, disposal or close. Inventory source revision and
freshness are independent of query-receipt provenance: a rejected or replayed
receipt never refreshes unread directory rows. A current command result is also
separate from retained verified content. Re-reading the same exact target keeps
that content, marked stale, during loading/transient failure; changed or invalid
targets clear it. Unsubscribing only detaches observation, not application work.

The product Strategy Library contains a read-only inspector with explicit future
capability restrictions. Both normal and packaged entry points pass the composed
extension to the existing MainWindow/JourneyWorkspaceHost. No prototype UI,
second window process, new execution, chart or trading action is introduced.
Its six named read-only controls are registered individually in the existing
interactive-action safety allowlist; no wildcard or forbidden-action rule was
relaxed.

## Evidence so far (not a completion claim)

- TDD: missing handshake failed in live and fake, then both passed.
- TDD: missing application query failed; exact read and identical-ID replay passed.
- TDD: seven mismatched-input cases failed, then passed with typed rejection and
  no stale asset content under a different target.
- 123 tests passed: the 10 new checks, retained six Feature contract files,
  retained pair conformance and Strategy Library live/fake conformance.
- Two retained file-backed real run-to-evidence journey tests passed in 20.70s.
  Both suites exited 0; total 125 tests with zero failures/errors/skips. This is
  local regression evidence, not completion of #133 or the V2.1 acceptance matrix.
- Those 125 checks preceded the later Feature/QML changes and are historical
  slice evidence, not the final regression verdict.
- Added malformed-envelope, source-outage, independent material-hash and
  changed-source/replayed-receipt tests. Initial 12 red cases became green;
  application errors remain sanitized, field-specific and correctly retryable.
- Review regressions first failed for backend-type leakage, same-target content
  loss and false catalog freshness; public type-graph and live/fake checks now
  pass. A second review found malformed targets being misclassified during DTO
  conversion; its four failing live/fake cases were corrected without bypassing
  application validation.
- `projection-and-handoff-green.xml`: 53 passed (new application/Feature checks
  plus retained exact setup handoff), 29.42s, exit 0. This also caught and fixed
  one missed call site during the shared projection helper rename.
- `inspector-keyboard.xml`: 29 passed, 11.47s, exit 0. Product QML uses live/fake,
  960x480/540, 1426x786, 2560x1440 and 3840x2160 logical clients, text 100/200%,
  waiting/empty/error/normal states, readable CJK font, Qt accessible name/role/
  read-only value, long-content cursor visibility and Escape focus return.
  Four added live/fake compact tests traverse all five popup controls with real
  Tab/Shift-Tab (no forced focus within the popup), check modal containment and
  same-target content continuity through a transient failure.
- Offscreen render evidence reports DPR 1.0. Where the sandbox enumerated no
  fonts, the test application loaded an existing Windows CJK font only; no font
  install or system setting was changed. Earlier tofu renders are not visual PASS.
- `safety-green.xml`: 5 passed, 2.91s, exit 0 after adding exact read-action names.
- Strict mypy passed on all six new production modules, including the local
  QML-window accessible focus provider. This is not a full
  repository typecheck.
- Broad regression `regression-slice2.xml`: **679 passed, 7 failed**, 716.35s.
  Two packaging assertions were caused by the newly added read-action names not
  yet appearing in the strict safety allowlist. Five evidence-handoff assertions
  require a final rerun after sandbox artifact-root correction; they are not
  silently waived.
- A minimal evidence failure reproduced on untouched eb7349f. A scratch-only
  exception probe identified PermissionError at the default user evidence root.
  Setting the existing artifact-root environment options to isolated F: test
  directories made the same baseline test pass (6.87s), with no backend change.
- A subsequent mixed large suite (`regression-slice3`) was started before the
  missed projection call-site fix, then **crashed in native Qt with an access
  violation**. It exited 1 without a final XML. Do not count its partial dots as
  passes. Required regression remains unfinished; the old crash is not relabeled
  as a pass or attributed to a cause that has not been proven.
- `contracts-slice4.xml`: 640 passed in 217.37s, exit 0. This includes the five
  previously failing evidence/lifecycle checks with isolated artifact roots.
- `ui-regression-slice4.xml`: 15 passed in 22.55s, exit 0 (retained strategy route,
  frontend entry and real persisted run-to-evidence journey).
- `ui-mixed-slice5.xml`: 44 passed in 38.84s, exit 0 (new inspector plus the same
  retained route/entry/journey in one process). Its 20 warnings concern the XML
  property format, not failed or skipped checks.
- `contracts-ui-mixed-slice5.xml`: 655 passed in 277.56s, exit 0. This repeats all
  contracts followed by the retained route/entry/journey in one process; a
  scratch-only native-stack/current-test probe records normal exit. The prior
  native crash did not recur. These results precede the accessible-root repair
  below; they are not a claim that the combined source-packaging suite passed.
- `ui-focus-final.xml`: 46 passed in 39.39s, exit 0 after the accessible-root
  repair; uses the legacy XML format to retain actual client/DPR/text properties.
- `retained-routes-final.xml`: 97 passed in 222.26s, exit 0 after the focus repair
  (retained accessible journey, workspace navigation, Scenario Lab, Diagnostic
  Tasks and System Health product routes).
- `focus-safety-final.xml`: 4 passed in 0.76s, exit 0 on the repaired source;
  these are the selected installed-manual-trading surface checks, not the entire
  packaging directory. The other 74 tests were deselected, not passed.
- `stable-feature-ui-final.xml`: **686 passed in 309.04s**, exit 0 on the repaired
  source (all contracts, inspector, retained Strategy/entry/real journey in one
  process). The native-stack/current-test log ends EXIT0; no crash reproduced.
  `verified-source-manifest.json` records the 20 actual changed Python/QML paths
  reread after exit; every byte hash matches the complete pre-run read-only
  snapshot from tool chunk c60494. No code source changed across this run.
  An earlier oversized manifest export was tool-truncated and is explicitly
  invalidated in `final-source-manifest-INVALID.md`; its file-read errors are
  not a successful verification. Only the replacement verified manifest is used.
- Complete packaging coverage was collected (61 + 78 + 60 + 53 + 4 = 256
  distinct cases). The long run stopped at **169 passed / 1 failed** in 2227.39s;
  the remaining offline-certification file produced **58 passed / 2 failed**,
  and both Wave 4 ledger/rollback files produced **57 passed**. The two distinct
  failures stopped at CIM OS inventory, before the intended negative archive /
  missing-executable boundary. The unchanged baseline reproduces the first, and
  both release scripts have identical SHA-256
  `f223a7612fbc6ce530f1f5bf5c41a2540871c85df76eee9ab65fe373593b80ae`.
  Exact normal-user reruns passed (2 cases in `preflight-normal-user.xml`, one in
  `missing-executable-normal-user.xml`), without changing the script or gates.
  The union contains **256 distinct cases with passing evidence, none missing**;
  this is not a claim that the original sandbox invocation passed.
- The real Qt product journey repeated twice in one process also passed in the
  packaging run (392.177s); both schema-4 software smoke reports have clean_exit
  true and empty errors. This child started after the accessible-root repair and
  used offscreen rendering, not desktop input. Installed/native certification is
  still a separate obligation.
- `frontend-v21-issue133-checkpoint.json` binds the source file hashes, report
  hashes/counts and the limitations. No raw environment inventory or credentials
  are included in this checkpoint receipt.
- XML and runner evidence are under
  `F:/PythonProjects/.scratch/frontend-v21-goal/issue133-20260913/`.

## Native Windows check — partial, focus bridge repaired locally

An isolated source-product MainWindow was opened with live adapters, the native
Windows platform, software rendering, a 1100x700 client and DPR 1.0. Computer Use
observed the real Windows accessibility tree, not a Qt-only substitute. It exposed
the inspector's names/roles, disabled-to-enabled query state, status and complete
exact result text (including both hashes and source revision). Keyboard navigation
opened the popup, selected and read an exact version, and visually returned to
the trigger on Escape. The owned test window was then closed; its process exited 0.

However, the tool's `focused_element` continued to report the old Strategy Library
search input while visible focus moved through the inspector. An initial indexed
click also reported `coordinate input geometry is unavailable`; native keyboard
input worked. Root cause (application bridge versus observer/tool behavior) is not
yet fully established. Native ValuePattern read-only state was not separately observed.
`native-uia-partial.json` preserves the read-only tree/text evidence and limitations.
Therefore native UIA/focus acceptance is **not PASS**, and full Narrator, hardware
renderer and physical Windows DPI coverage have not been claimed.

A further native check was stopped by the user's physical Escape key. No further
desktop input was issued; the isolated test window's 300-second timer closed it
and its process exited 0. Resuming desktop verification requires the user's go-ahead.

The public Qt accessible-root seam exposed a narrower, deterministic defect
without controlling the desktop: focus traversal stopped at JourneyWorkspaceHost,
not the focused QML control. Both live and fake tests failed (`accessible-root-probe.xml`).
The unchanged eb7349f baseline reproduces this with its original search field
(`baseline-focus-red.xml`, 1 failed). Qt 6.9.1's QWidget implementation returns the
focused widget, while its Windows provider relies on `focusChild()`; see the
[Qt widget implementation](https://github.com/qt/qtbase/blob/v6.9.1/src/widgets/accessible/qaccessiblewidget.cpp#L303)
and [Windows provider](https://github.com/qt/qtbase/blob/v6.9.1/src/plugins/platforms/windows/uiautomation/qwindowsuiamainprovider.cpp#L796).

The local repair opts only QML product MainWindow instances into a Qt accessible
window provider that overrides focusChild to return the embedded QML focus leaf.
Qt's original child enumeration, names, roles, values and actions remain in use;
the QQuickWidget tree is not replaced, and old Widgets windows are not opted in.
`legacy-focus-green.xml` passes the original-search comparison (1 test), and
`accessible-root-green.xml` passes both live/fake popup checks (2 tests). The full
post-fix 46-test UI run also verifies that each focused leaf remains reachable
in the original accessible tree. This fixes the proven Qt-root defect; it does
**not** prove that all native tool focus/state discrepancies are resolved.

## Two-axis review

### Standards

Initial findings: backend domain objects leaked through the new Feature state;
query receipts could falsely refresh the directory. Both were fixed and the
independent re-review reported no remaining concrete standards violations in the
revised scope. Runtime regression subsequently found the missed projection helper
call site; that fix is covered by retained exact handoff tests. Subsequent read-only
review of the opt-in accessible-root provider found no further concrete standards
findings; runtime native acceptance is separate from that conclusion.

### Spec

Initial findings: valid same-target content was cleared; keyboard/native UIA
evidence was incomplete. Retention and real Tab-cycle coverage are now implemented
and tested. Re-review found the malformed DTO-target error classification defect;
it is fixed and covered through composed live/fake commands. Final read-only
re-review found no new concrete implementation defects or scope expansion.
The local accessible-root repair was also independently re-reviewed with no new
concrete spec deviations. Native UIA focus and read-only state still need
verification after the local repair.

## Outstanding before #133 completion

- Resolve the native focus-observation discrepancy and verify the remaining local
  UIA semantics. Do not imply full physical DPI/Narrator/renderer acceptance.
- All local test processes have exited. Current-source contracts plus inspector/
  old journeys pass together, and every packaging case has passing evidence with
  the source/environment limitations recorded above. The original unexplained
  crash remains separate from the successful reruns.
- Preserve this reviewed implementation as a local checkpoint, not acceptance.
  After native verification, record any further fix/test evidence before the
  issue-completion commit and truthful #133 update. No push/PR/issue closure or
  release is authorized by this checkpoint's test counts alone.
- Receipts are application-lifetime in-memory immutable read observations, not
  durable domain assets or restart checkpoints. No arbitrary eviction rule has
  been added that would silently weaken same-ID replay semantics.
