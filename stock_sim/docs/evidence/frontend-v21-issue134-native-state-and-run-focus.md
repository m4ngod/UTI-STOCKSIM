# #134 native state coverage and legacy Run focus repair

Date: 2026-09-14–15. Incremental evidence, **not #134 acceptance**.
Owner task: `01a0a072-6f56-7d13-9284-903d054fa6d5`.
Baseline: `6eafca4a80b67b5a09542e754d7de3e643d49ebc`.
Run focus repair: `54617ac8203a0879fa30ce9af396c7448613aa08`.
Worktree: `F:/PythonProjects/_codex_issue133_v21_compat`.
Artifacts below are relative to
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260914/`.

## Composition and observation boundary

`observe_composed_product.py` supplies controlled inputs to public
`build_app_context` and the production `MainWindow(research_shell=True)`. It
sets an isolated SQLite URL and artifact/settings directories before imports,
checks the actual default database URL, and sets only initial window geometry,
process-local text/renderer preferences and the initial bookmark. It adds no
replacement QML, test controls, alternate native reader, IPC or second UI.
All desktop input and external UIA reads use official `node_repl` / `@oai/sky`.
Read-only Qt telemetry is explicitly labelled `product_telemetry_not_UIA`.

These are composed product sessions, not the public console-entry cold-start
lane. Their setup and controlled delays must not be used as startup performance
results. Earlier console-entry observations remain in the preceding report.

- Query profile injects an Executor through the existing public constructor
  seam. The first request fails after 60 seconds; a keyboard retry executes the
  actual application read after 1.2 seconds. No visible status is injected.
- Scenario profiles use `_formal_live_stack` from the existing contract tests.
  Synthetic local market inputs are admitted, approved and materialized through
  the real application and read through its live adapter and SQLite persistence.
- Sealed Run profiles use `_persist_real_formal_v1_through_application`, which
  executes the existing local simulation fixture, seals evidence, disposes its
  first engine and reopens persisted data. Returned exact identities enter
  AppContext through the supported environment selection. No external market
  source, paid service, broker or manual order is involved.

Final launcher SHA-256:
`E23924459D03AF2B1FD6EE184B6443B40C412D37DA1C89FFA48AAAD8704C76C4`.
The screen-geometry telemetry and sealed profile were added during this turn;
this final hash identifies the reproducible superset, not each earlier script
revision. Source/test files were unchanged until the focus repair below.

## Measured native sessions

| Session directory | Product source | Stable client | DPR | Renderer / text |
| --- | --- | --- | --- | --- |
| `controlled-query-960x540-text100-software-01` | 6eafca4 | 960x540 | 1.5 | Software / 100% |
| `live-scenarios-wide-text100-d3d11-01` | 6eafca4 | 1878x938, then 931x938 | 1 | Direct3D11 / 100% |
| `live-scenarios-960x540-text200-software-01` | 6eafca4 | 960x540 | 1 | Software / 200% |
| `sealed-run-960x480-text200-d3d11-01` | 6eafca4 | 960x480 | 1 | Direct3D11 / 200% |
| `sealed-run-960x480-text200-d3d11-54617ac-02` | 54617ac | 960x480 | 1 | Direct3D11 / 200% |

The wide session passed through different geometry/DPR values at startup.
Its requested 1880x940 is not reported as its stable client. No Windows display
or font setting was changed. The 931-wide resize is supplementary reflow
evidence below the supported minimum, not a 960-wide boundary pass. Independent
960x540 sessions provide that exact client observation. These samples are not
the complete physical DPI, renderer, font and state matrix.

## Observed behavior

The controlled query showed `正在读取 · 真实应用数据`, with refresh and exact-read
disabled. After the controlled failure it showed the safe reading limitation;
refresh became enabled, exact-read remained disabled, and the internal error
path was absent. Shift+Tab focused refresh and Space retried. The public
snapshot and native UI then showed two real application assets. The object
drawer opened; Escape visibly returned to its trigger and Space reopened it.
This is an initial-failure recovery case, not proof of retaining a previously
loaded object across disconnection.

The wide Scenario page exposed a named 28-item list, exact details and a separate
named source Edit control. The selected second object's recipe version was
`recipe_version_f0d05ab8b247a4fff07e7b9bbd4b1ff0c234ea0f0557619e51c352f24340e881`,
with content hash
`3503415691549f8eb9878bfd07d6419643110c2e83198a1bda6c0ddde78aa53c`.
Tab visibly focused sources. A border drag did not resize the window; the
subsequent native window Size menu operation narrowed it. After settling,
the same identity and source text remained in the combined detail, and focus
fell back to that visible detail. Shift+Tab/Space opened the compact drawer;
Escape returned to its trigger. An exploratory End key did not move to the last
row and is not recorded as a successful shortcut.

At 960x540/text200 the second Scenario was chosen with Down/Enter. UIA contained
its full recipe identity and content hash
`8d67f9222deb7d131d61791d43cf5524000f699c35050eb96ee0f9958e1c8e83`.
Ctrl+End revealed the last limitation line; X left the document text unchanged.
Separate fixtures generate different identities, so no cross-session equality
is claimed.

At 960x480/text200 the real reopened Run showed exact campaign/run IDs,
`completed`, and `70 / 70`. X did not alter its summary. Opening and closing the
health overlay preserved the same Run; Escape visibly focused the health trigger.
Archive exposed 1,055 saved evidence/comparison/finding objects. Enter opened
record `diagnostic-metric-ee07b83b5e166f266897f838`, original value `0 currency`,
package `diagnostic-evidence-d62b19ff9f26659059ef8e74` and manifest
`reproduction-manifest-032f4b2533fab310de22c2ed`, with candidate/source identities
and artifact hashes. This list contains campaign evidence beyond the selected
Run; the selected journey and the record's original Run are separately shown.
The aggregate remains explicitly degraded/partial. Ctrl+End reached the final
limitations and X left the document unchanged. No new statistics were produced
by reading the page.

## Reproduced and repaired Run focus defect

The first sealed session showed no focus outline on the legacy Run summary even
when Qt telemetry identified it as the active item. Other detail controls already
displayed an outline. The summary background lacked a focus border.

The existing eight Run cases cover four client sizes (960x480, 960x540, 1426x786,
2600x1400) at 100%/200% text. The added assertion inspects an actual framebuffer
pixel at the focused summary boundary, accounting for image DPR. All eight
failed before the repair: the pixel was background rather than the focus color.
The minimal repair binds this control's border width to its active focus and
uses the existing focus color/width tokens. The eight cases then passed.

- `legacy-run-focus-outline-red.xml`: 8 failures, 30 deselected.
- `legacy-run-focus-outline-green.xml`: 8 passed, 30 deselected.
- `legacy-run-focus-regression.xml`: **110 passed**, 0 failures/errors/skips,
  64.96 seconds; the same four affected modules as the previous 110-case run.
  SHA-256: `2316A41AAAF80B953EC952BF26B20AD85C22F9B6EB354745E0D593BCD6456057`.

The final native session uses committed 54617ac. Tab from Lab navigation to
Archive navigation and then the summary displays the border. Shift+Tab removes
it and visibly focuses Archive navigation, without changing the observed Run.
Screenshot: `sealed-run-960x480-text200-d3d11-54617ac-02/visible-keyboard-focus.png`.
This externally verifies the visual repair, not native focus-property accuracy.

## Raw evidence and limitations

Each session contains `windows-uia.jsonl` and `product-observations.jsonl`.
UIA SHA-256 values, in the table's order:

1. `14F9BE8DA478B81CCEFEBB0B7BB64F9AD0E9EB633573441F23EB3F62C751564B`
2. `D7A23FD1C090C95A5D8A859A74CA05F55ACD775EE138B49D5BB6C8206FBA040E`
3. `E4A95112D9F131528D7937644354C90563A3A23D3E38BEC60CAA0456B9ABD4DA`
4. `24FA264AD751296A2D702278763490EC602BB540202326C19F25793ADC71C68E`
5. `414AA84B5BEC488FD2EE88B95FB7D85BBEF4D87BDC1F071975EE92A3D6136A48`

Screenshots were inspected through the official tool; JSON records do not contain
image payloads. All five processes exited 0 and recorded closed contexts and
stopped bridges. No session reported a cleanup error.

The supported readonly guard was tried once on the newly repaired Combination
details with its existing value. It again failed with
`read UIA value read-only state: 所需属性不在 CacheRequest 中 (0x80070057)`.
It can focus the control before that error; it did not establish IsReadOnly or
write a value. No retry through an alternate UIA implementation was used.
`focused_element` also continued to identify background detail controls despite
visible and supplemental Qt focus elsewhere. These remain unverified native
properties; the new visible focus border does not repair the observer.

## Standards

Independent fixed-range `6eafca4...54617ac` review: 0 documented violations and
0 actionable heuristic smells. The local border follows the existing tokens
and needs no additional abstraction. The reviewer did not run tests or edit files.

## Spec

Independent fixed-range `6eafca4...54617ac` review: 0 actionable deviations.
D14 requires visible focus; D15 retains exact Run compatibility. The change
only adds the existing focus presentation and rendered regression, preserving
identity and observation behavior. The reviewer did not run tests or certify
native properties, Narrator or whole-ticket acceptance.

## Continuation

Full #132 / #133–171 goal remains ACTIVE after substantive native coverage and
a new product repair. #134 is not closed. Remaining work includes native exact
reference invalidation/related-resource paths, persisted Lab selection and the
rest of the relevant local state/size/font matrix. Native readonly/focus
properties need a reliable supported observation before closure. Full Narrator,
formal physical DPI and installed-candidate A41 remain successor/shared gates.
Earlier source-entry cold samples above 750ms remain failures at their original
boundaries. No dependency was waived and no successor ticket was claimed.
