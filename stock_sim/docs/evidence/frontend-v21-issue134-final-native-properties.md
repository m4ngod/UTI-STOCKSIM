# Frontend V2.1 #134 — bounded native property assessment

Observed on 2026-09-15 with Microsoft Accessibility Insights for Windows
1.1.2924.01, operated exclusively through official Computer Use. Production
source is `51157cc4586813c2612b000dfc018b955a179dac`. This record completes all
three specific native property items in the [acceptance ledger](frontend-v21-issue134-acceptance-ledger.md).
It does not certify later shared acceptance groups.

## Source and capture boundaries

The unchanged `observe_context_states.py` launcher composes the public
`build_app_context` and production `MainWindow`. It adds no replacement QML,
native reader, IPC or second product UI. Microsoft inspection is an external
observation tool, not a product UI stack. Its installer and publisher signature
were previously verified with the user's installation authorization.

Archive fault sessions use the existing deterministic fake adapter with 36
objects. Their disconnect and invalidation are controlled source inputs, not
claims about real external outages. Exact original identities and values remain
visible and distinguish this fixture from the real persisted Run session.

For accepted focus records, the matching product target settles, the inspector
is paused while StockSim is foreground, and only then is the inspector brought
forward. A separate settled read must match the target AutomationId, process,
role and properties. The frozen focus value describes the capture instant,
not foreground focus while reading the inspector. First reads after switching
windows sometimes retain the preceding tree while showing the new screenshot;
those reads are not accepted as the new target's evidence. Direct
`sky.focused_element` is not declared repaired.

## Observed results

| Behavior | Official native result | Source boundary |
| --- | --- | --- |
| Normal empty Archive catalog after source invalidation and unavailable parent return | `researchArchivePageList`, List(50008), PID 301156: HasKeyboardFocus=True and IsKeyboardFocusable=True. | 1426x786, D3D11, text100, DPR1. Empty catalog, unavailable original parent and no replacement object are separately visible. |
| Parent return during retained Archive disconnect | `researchArchivePageDetails`, Edit(50004), PID 302100: HasKeyboardFocus=True, IsKeyboardFocusable=True, ValuePattern.IsReadOnly=True. | 960x540, Software, text100, DPR1. The same CMP-MODEL-B17-FEE, E-MODEL-B17-EXEC-BASE and E-MODEL-B17-EXEC-ISO are retained while disconnected. |
| Compact focused reference link invalidates | `researchArchivePageListButton`, Button(50000), PID 302100: HasKeyboardFocus=True and IsKeyboardFocusable=True. | Source invalidation automatically removes the link and focuses the drawer trigger. No intervening Tab or click selects this fallback target. No replacement identity appears. |
| Reopened legacy Run summary | `researchExistingResourceSummary`, Edit(50004), PID 306364: HasKeyboardFocus=True, IsKeyboardFocusable=True, ValuePattern.IsReadOnly=True. | 960x480, D3D11, text200, DPR1. Real application persistence/sealing, completed lifecycle, 70 / 70; tabbing through Archive navigation reaches the summary without changing the Run. |

The normal-session Back button also exposes native focused=True and
focusable=True during disconnect. That property record is accepted separately
from the later failed timing of the return action.

The Run's native ValuePattern contains the same persisted identities:
`diagnostic-campaign-8b301ccde7f9cb85f3467628` and
`strategy-run-81b24de948b5f52a69bd8599`. The fixture created and sealed package
`diagnostic-evidence-e1bdf2b77dc40c7cfc38f43c` with manifest
`reproduction-manifest-0ae683b78c46bc1bf1514d98` through the existing real
application path. This proves local persistence/application behavior, not
external data acceptance or a new production run.

The first normal-session attempt labelled
`archive-disconnected-return-comparison` was made after the source became
invalid. Its label records the intended action, not a successful disconnected
return. It is excluded from that claim and retained as invalidation behavior.
The compact-session return occurred between the actual disconnected and invalid
source events. Input timestamps, product captures and native captures must agree.

The native properties come from the Microsoft inspector's displayed property
tree and matching screenshots. Product telemetry is explicitly labelled
`product_telemetry_not_UIA`; it supplies source, renderer, geometry and input
timing only. It cannot substitute for native focus or readonly evidence.

## Evidence location

Local evidence is retained beneath
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.
Normal Archive session: `native-archive-return-51157cc-01`.
Compact Archive session: `native-archive-compact-51157cc-01`.
Real Run session: `native-sealed-run-51157cc-01`.
Each contains original JSONL, labelled screenshots, isolated inputs and
application lifecycle records. All three exited normally with status 0,
`context_closed=True` and `bridge_stopped=True`; settled official window
inventories contain no StockSim window.

`audit_final_native_properties.py` parses only retained files and verifies:
six complete native property records; process/target/provider identity; three
measured source/geometry/renderer sessions; source-event ordering; exact parent
and child identities; automatic link-to-trigger fallback; real Run identity and
value; final application cleanup; and 96 manifest files. The resulting
`final-native-properties-audit.json` SHA-256 is
`945E0CEA5C1B880D178F04737A523473A447AD28A0656377B369DDEEA4643940`.
The unchanged launcher's SHA-256 is
`F9411194F7B41CBD6F1D22BAE20DCAEB07968BBD0FF1C549BD860C92EA64039C`.
The three earlier audits' hashes were rechecked and their bytes remain unchanged.

## Regression and acceptance boundary

No production source or test changed during this observation increment.
The preceding affected regression remains **120 passed**, zero failures,
errors or skips, 57.39 seconds with 39 existing warnings. Its XML hash was
reverified; it was not rerun or relabelled as a new test execution. Earlier
failed reproductions and their independent corrective reviews remain in the
[catalog record](frontend-v21-issue134-catalog-native-remediation.md).

The official #134 body was reread on 2026-09-15 and is unchanged from the prior
clause audit. These observations resolve its three explicit remaining native
property items without adding a new interface or expanding the shell's scope.
Full Narrator, formal physical-DPI, installed-candidate A41 and later page
authoring retain their own gates. The full #132 / #133–171 initiative remains
incomplete; this record is not a whole-initiative or whole-group PASS.
