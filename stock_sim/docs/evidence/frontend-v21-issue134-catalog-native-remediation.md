# Frontend V2.1 #134 — native catalog state and exact keyboard return repairs

Observed 2026-09-15, Asia/Shanghai. Three concrete catalog defects are repaired
and independently reviewed. Microsoft Accessibility Insights supplies native
property evidence for the repaired controls. This is a bounded increment, not
whole-#134 or full #132 / #133–171 acceptance.

## Source and official observation boundary

Worktree: `F:/PythonProjects/_codex_issue133_v21_compat`.
Starting source: `ac9c0b9710bdd0a1db1a1e40940bdbbb1a60e5b5`.

| Commit | Change |
| --- | --- |
| `29c9364965592b016aab5c773e7be75b4271a48b` | Both catalog delegates explicitly expose keyboard focusability. |
| `f74abbc0f0724b011c2928af37c4748ce97eacbc` | Both delegates expose selectable state and committed selection. |
| `84db01596accdefcd602ef8b10b9caf5b6abb305` | Combination mouse selection synchronizes the keyboard cursor, retaining the exact version on return. |

The [previous record](frontend-v21-issue134-microsoft-native-properties.md)
retains the authorized Microsoft installation, valid Microsoft signature and
package hash. No installation or system-setting change was repeated here.
Official Computer Use `@oai/sky` was the only native input and capture route;
the Microsoft inspector read the target's `qwindows.dll` provider. Saved-file
audit scripts do not query UIA or operate Windows. Qt 6.9.1 accessibility tests
and telemetry are separately identified supplementary evidence.

All session directories below are under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.

| Session | Source / PID | Actual client / renderer / text / DPR | Composition |
| --- | --- | --- | --- |
| `native-focusable-fixed-29c9364-01` | `29c9364` / 270220 | 960×540 / Software / 100% / 1 | Public `setup_frontend_entry.main --research-shell`, isolated SQLite. |
| `native-selection-fixed-f74abbc-01` | `f74abbc` / 263056 | 1426×786 / Direct3D11 / 100% / 1 | Public `build_app_context` and production MainWindow; real persisted Scenario fixture, then real two-version Combination query. |
| `native-asset-mouse-return-84db015-01` | `84db015` / 292520 | 1426×786 / Software / 100% / 1 | Public source entry, isolated SQLite. |

The unchanged public-entry launcher is
`../issue134-native-20260914/observe_product.py`, SHA-256
`C165C2B65D673556849AC9AF9F550E10840288F0FA82E1EF1BB27F2AC1AFD567`.
The composed launcher `observe_context_states.py` retains SHA-256
`F9411194F7B41CBD6F1D22BAE20DCAEB07968BBD0FF1C549BD860C92EA64039C`.
The composed session is not a public-CLI cold-start sample. All three sessions
closed normally, exited 0, released their contexts/bridges as applicable and
have settled official inventories with no StockSim window.

## Diagnosis and native results

The original inspector exposed `HasKeyboardFocus=True` with
`IsKeyboardFocusable=False`. Actual-QML tests reproduced that mismatch in both
catalog implementations. Adding `Accessible.focusable: enabled` made the tests
and native Combination row focusability pass. This is consistent with the
[Qt Accessible role defaults](https://doc.qt.io/qt-6/qml-qtquick-accessible.html#focusable-attached-prop);
the runtime verdict comes from Qt 6.9.1 tests and Windows samples, not an assumed
match to the current documentation version.

The next compact native sample exposed a separate defect: after Enter committed
the second version, reopening the list still reported
`SelectionItemPattern.IsSelected=False`. The same value before Enter is expected;
the retained product sequence establishes that this failure was after commitment.
Actual-QML tests reproduced missing selected and selectable states. Both
delegates now bind `Accessible.selected` to their existing committed highlight
and `Accessible.selectable` to enabled state. Direction keys continue to move
the cursor without changing the committed resource.

| Native target and sequence | Recorded result |
| --- | --- |
| Compact Combination row at `29c9364`, before Enter | Focused=True, focusable=True, selected=False. |
| Compact Combination after Enter | `researchAssetReadButton` focused=True and focusable=True. |
| Same compact row after committed choice at `29c9364` | Selected=False: retained defect, superseded by `f74abbc`. |
| Scenario row 2 of 28 at `f74abbc`, direction key only | Focused=True, focusable=True, selected=False; details still show row 1. |
| Same Scenario row after Enter and keyboard return | Focused=True, focusable=True, selected=True; exact resource identity unchanged between the two property captures. |
| Scenario details immediately following Enter | `researchScenarioPageDetails`: focused=True, focusable=True, `ValuePattern.IsReadOnly=True`. |
| Combination row 2 of 2 at `f74abbc`, committed choice | Focused=True, focusable=True, selected=True. |
| Combination Enter at `f74abbc` | `researchAssetReadButton` focused=True and focusable=True. |
| Mouse-chosen Combination row after keyboard return at `84db015` | Focused=True, focusable=True, selected=True; subsequent Enter retains the same version. |

The Scenario before/after pair names
`campaign-case-21b2c14ec51cffdde2c25d60`, recipe version
`f6f22ffc5fcfa5ff12e3e3c720c9d3ca5abe4d5f59275609a30321843ac0a596`.
The Combination row names
`QuentX Live Minute Scenario-native · quentx-live-minute-scenario-native.v1`.
Raw records retain full AutomationIds, position/total, control roles, PID and
provider descriptions; screenshots alone are not used to infer those values.

The normal Combination walkthrough also revealed that mouse-selecting row 2
left the keyboard index on row 1. Shift+Tab could therefore return to a different
version and Enter could replace the choice. Four actual-QML mouse reproductions
failed across live/fake and compact/normal layouts. Synchronizing `currentIndex`
inside the existing explicit `choose` operation resolved all four and preserved
cursor-only behavior. No application selection ownership moved into QML.

## Native exclusions and capture timing

Pause the inspector while StockSim is still foreground, after the highlighter
has followed the intended keyboard target; then bring the inspector forward.
The frozen `HasKeyboardFocus` value describes that captured moment. It is not a
claim about OS foreground focus while the inspector is active.

The first `f74abbc` selected Scenario capture has focused=False after the inspector
was foregrounded. It proves selected/focusable state only; later before/after
captures establish focus. The `29c9364` both-focus-properties screenshot has null
accessibility text and is supplementary to the accepted complete record.

At `84db015`, the first mouse-return capture matched the selected row but had
focused=False and was excluded from focus PASS. The second sequence used Tab to
the read button, waited for its matching highlighter, then Shift+Tab to row 2 and
a settled capture before freezing. That snapshot confirms native focus and
selection without intervening direction keys or replacing the selected version.
The initial visual mouse return and the full actual-QML regression are retained
separately. This does not assert a cause for the first observer discrepancy.

The direct `sky.focused_element` conflict is not declared repaired. No custom
native reader or `.a11ytest` export is claimed.

## Tests

Tests run against the production QML host and public AppContext composition.
The offscreen QTest inputs are process tests, not an alternate native desktop
automation route. Each failure report remains alongside its corrective result.

| Reports | Outcome |
| --- | --- |
| `catalog-focusable-red.xml`, `shared-catalog-focusable-red.xml` | 4 + 2 failures reproducing focused but not focusable. |
| `catalog-focusable-green.xml` | 6 passed. |
| `catalog-focusable-regression.xml` | 116 passed. |
| `catalog-selected-red.xml`, `catalog-selectable-red.xml` | 6 failures each, exposing the two missing state declarations. |
| `catalog-selection-state-green.xml`, `catalog-selection-state-regression.xml` | 6 passed; then 116 passed. |
| `asset-mouse-return-red.xml`, `asset-mouse-return-green.xml` | 4 failed; then 8 passed including cursor/selection regression. |
| `asset-mouse-return-regression.xml` | **120 passed**, zero failures/errors/skips, 57.39 s; 39 existing record_property/xunit2 warnings. |

The final affected suite covers `test_research_workspace_shell.py`,
`test_research_resource_pages.py`, `test_research_resource_states.py` and
`test_research_product_entry.py`. Its SHA-256 is
`4A4B72FEBB0B19FEC3D0D08DEC8955C12250DDE9F9364686161EB2E8D19AAC1E`.
Historical counts are not added to this result; no fresh all-repository pass is
claimed.

## Standards

Independent reviews of `ac9c0b9...29c9364`, `29c9364...f74abbc` and
`f74abbc...84db015`: 0 documented violations and 0 actionable heuristic smells
per range. The final review checked actual repository guidance and the existing
shared browser implementation. ADR0038/0039 standalone source files were not
located, so it does not claim to have reread them. Reviewers made no edits or
native UI actions and did not repeat the tests.

## Spec

Independent reviews of the same three fixed ranges: 0 actionable findings per
range. The changes implement #134 keyboard/UIA state and focus-return behavior,
preserve exact identity and do not expand page authoring scope. These reviews
do not certify the whole ticket.

## Evidence integrity and remaining work

`catalog-native-states-audit.json` accepts 10 complete property records from the
first two sessions and hashes 41 files. SHA-256:
`60647ACB9C9F6686EC7633430F9C255E1BA024BC80E945603193F0099F8B347F`.
`asset-mouse-return-audit.json` accepts the final returned-row record and hashes
15 files. SHA-256:
`B895249FB0B8518725FC0AF2C09F154CAACCACD51BC91100FF8CCC8290698798`.
Both scripts parse saved output only. Earlier native-readonly audit bytes remain
unchanged. Each session retains JSONL captures, labelled non-UIA telemetry,
screenshots, isolated data and close records.

The concrete catalog focusability, committed-selection and mouse-return defects
are resolved. Remaining native property coverage is listed explicitly in the
[acceptance ledger](frontend-v21-issue134-acceptance-ledger.md); generic requests
to repeat already-covered state/layout samples are not a substitute for that
list. #134 remains open. Full Narrator, formal physical DPI, installed A41 and
all later implementation tickets retain their separate gates. No remote issue,
branch, publication or release state changed in this increment.
