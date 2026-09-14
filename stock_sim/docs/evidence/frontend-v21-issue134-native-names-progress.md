# #134 native observation and accessible text repair

Date: 2026-09-14. This is incremental evidence, **not #134 acceptance**.
Owner task: `01a0a072-6f56-7d13-9284-903d054fa6d5`.
Fixed baseline: `b209b2326dcb3011f5c913dccf3707f61587fd34`.
Production and tests: `b16ddf7a4e3a6286443e551ec22c06392e4aa448`.
Worktree: `F:/PythonProjects/_codex_issue133_v21_compat`.
All report paths below are under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260914/`.

## Tool recovery and actual product boundary

The new task successfully imported `@oai/sky` using the official `node_repl`
entry, printed `runtime-ready`, and enumerated applications. The previous task's
kernel-assets initialization failure did not recur. This does not establish its
original cause or certify the entire Computer Use implementation.

Both native sessions invoked the unchanged public
`setup_frontend_entry.main(['--research-shell'])`. The scratch launcher sets a
new current directory, SQLite database, evidence/artifact paths, process-local
text/renderer preferences and disabled QML disk cache before product imports.
It verifies the actual database URL, sets the requested initial geometry and
records read-only Qt window telemetry; it neither replaces AppContext nor drives
input. All native input and Windows accessibility reads used official sky APIs.
No alternative UIA reader, custom native helper, system setting or plugin change
was used. No external data, paid service or broker was contacted.

| Session | Source | Actual QML/client | DPR | Renderer | Text |
| --- | --- | --- | --- | --- | --- |
| `public-normal100-software-01` | b209b232 | 1426x786 | 1 | Software | 100% |
| `public-compact200-d3d11-b16ddf7-01` | b16ddf7 | 960x480 | 1 | Direct3D11 | 200% |

Both report Microsoft YaHei UI, application font 9pt/15.234375 logical height,
screen 1920x1080 and available screen 1920x1032. Text scale is the product's
process-local accessibility override, not a changed Windows font/DPI setting.
These sessions do not represent the complete dimensions x fonts matrix.

## Reproduced product defects and repair

Native UIA originally returned unnamed text/status nodes where the product
visibly displayed page headings and resource status. A focused product-QML
regression reproduced the same empty names before any fix:

- `status-name-red.xml`: all four page status cases failed with nonempty visible
  messages and empty accessible names.
- `status-and-heading-red.xml`: five failures covering four pages and the health
  popup heading. Roles already existed; names were empty.
- `combination-readonly-red.xml`: the separate Combination details TextArea had
  `readOnly=true` but accessible `readOnly=0`. This is not the previously repaired
  legacy Run summary.
- After adding names and explicit readonly state,
  `names-green-keyboard-red.xml` reported five passes and one failure: Ctrl+End
  left the Combination detail cursor at zero rather than the text end.

The repair adds six `Accessible.name: text` bindings for page headings/status,
health title and route-recovery explanation, plus `Accessible.readOnly: true`
and `selectByKeyboard: true` to Combination details. No domain state, navigation,
operation, Feature version or source identity changed.

The red-capable invocation uses the existing isolated runner with
`test_research_workspace_shell.py -k 'visible_accessible_name or combination_details_expose'`.
After the repair, `names-and-exact-reading-green.xml` passed ten cases, including
existing live/fake exact-asset reads in normal100 and compact200. The four
record_property warnings concern its initial xunit2 report format only.

Final four-module regression, `accessible-names-regression.xml`: **110 passed**,
0 failures/errors/skips, 69.19s console / 69.151s JUnit, with legacy report format.
Includes 38 shell, 33 resource-page, 14 resource-state and 25 public-entry cases.
SHA-256: `A16BBC2D0A15A820DB07ECC2D929328258ADC1C6634920C85FB5C745583E5255`.
This is a new affected-module regression, not a full repository rerun. The prior
104-case report and native Qt renderer matrices remain untouched historical evidence.

## Native observations after repair

The Direct3D11 product UIA tree now includes the visible four page names, their
current status strings, and the health title. The Combination status changes
from `2 个精确版本 · 真实应用数据` to `精确版本已核验 · 真实应用数据` after the
actual read. This externally confirms that the repaired name follows the result.
The tool renders the heading as text; Qt's Heading role is separately tested.

At 960x480/text200, the actual object drawer opens, Down selects the second
version, and Enter closes the drawer with visible focus on the enabled Read
button. Space reads `quentx-live-minute-scenario-native.v1`. UIA document text
contains the exact version, content hash
`ebe0e20f185b4957197a492f9e320c9ada82c394880716151aa3b55c032d39c1`, frozen-input
hash `960fe1d867e9733e327d16c612ba8f016cfd4992c5e5456111acbdc1c4ed9391`, fixed
source revision and six material dependencies. Tab visibly focuses the details;
Ctrl+End scrolls the last limitation sentence into view. Pressing X leaves the
observed document unchanged.

Both sessions showed the real empty Scenario inventory, Lab with no selected
task and Archive with no selected evidence, without silently choosing another
object. Both health overlays expose the six facts and limitations; keyboard
reading reaches the end. Escape visibly returns to the health trigger and Space
reopens the same overlay. These establish observed keyboard behavior, not
accurate native focus-property reporting.

## Remaining native observer limitations

- `focused_element` still names a background detail TextArea while the visible
  focus and supplemental Qt telemetry identify navigation, the health Close
  button, facts or the returned trigger. Settled fresh reads reproduce this
  discrepancy. No product focus fix is inferred from that field alone.
- One supported `set_value` attempt against the health facts, requesting their
  existing value, failed before a write with
  `read UIA value read-only state: 所需属性不在 CacheRequest 中 (0x80070057)`.
  This is not proof of native IsReadOnly. It was not retried through another
  Windows automation stack. The new asset IsReadOnly property still needs a
  reliable external native observation despite the passing Qt regression.
- Immediate post-input trees can lag the screenshot. Stable rereads were
  recorded; stale indexes were not used to target changed controls.
- A proposed resize from client 960x480 towards 960x540 was rejected because its
  endpoint was outside the tool's window bounds. A fresh read and telemetry
  confirmed unchanged geometry. This is **not** a 960x540 reflow pass.
- Initial occluded capture displayed another surface; activating the uniquely
  selected product window resolved the screenshot. No input targeted that surface.

Raw external observations are `windows-uia.jsonl` in each session directory;
supplemental telemetry is `product-observations.jsonl`. UIA hashes are respectively
`25DB825EAB3F5579072637CC0969CB48EDC3544340657FCC40A46618C5C9AF86` and
`D5C3C81CC5CC44CFDB7EB93275CA441695BDD6ADC237A008D796551F3E675E08`.
Screenshots were inspected in the official tool transcript; the JSON files do
not contain image payloads. The first scratch telemetry observer sampled during
shutdown after its QML root disappeared and printed an AttributeError; its product
entry still exited 0. A null guard corrected the observer before the second
session, which closed without that diagnostic. Both released their bridge, and a
fresh native window enumeration confirmed no remaining StockSim window.

## Standards

Independent fixed-range review `b209b232...b16ddf7a`: 0 hard standard violations
and 0 actionable smells. Repeated declaration of each component's accessible
name needs no shared abstraction. The reviewer performed no edits or test runs.

## Spec

Independent review of the same range: 0 actionable deviations. The repair matches
D14's name/role/value/state requirement and D15's readonly legacy resources. The
reviewer explicitly did not certify native focus/readonly, Narrator or physical DPI.

## Continuation

#133 remains CLOSED; #134 OPEN and assigned m4ngod. A fresh read of all 39 official
implementation bodies/states found every later ticket dependent directly or
transitively on #134, including direct dependency #167 as well as #135/#143/#165.
No comments were used as requirements and no remote state changed.

The full #132 / #133-171 goal remains ACTIVE after substantive progress in this
new task. Continue the remaining local native state/keyboard matrix, including
960x540, normal/wide and controlled error/wait inputs. Do not repeat the resolved
kernel-startup diagnosis or already completed tests without a new cause. A reliable
supported native readonly/focus observation is still required before #134 closure.
Do not waive it, claim blocked successors, or use another UIA/helper stack without
the required authority. Full Narrator, formal physical DPI and installed-candidate
A41 remain successor/shared gates. Earlier above-750ms cold samples remain failures
at their recorded source boundaries, not installed-candidate passes.
