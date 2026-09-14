# #134 native exact-context coverage and catalog focus repair

Date: 2026-09-15. Incremental evidence, **not #134 acceptance**.
Owner task: `01a0a072-6f56-7d13-9284-903d054fa6d5`.
Baseline: `f50d519836ee3b62baa93228ffb2e752606bca49`.
Repair: `854e1d1eae6d5715f95e05de8e00896916f10aa8`.
Worktree: `F:/PythonProjects/_codex_issue133_v21_compat`.
Artifact paths below are relative to
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.

## Inputs and observation boundary

`observe_context_states.py` extends the preceding composed-product launcher in
a new artifact directory, preserving the older launcher's recorded hash.
It uses public `build_app_context` and production `MainWindow`, isolated database
and artifact paths set before imports, and initial geometry/bookmark inputs.
All desktop input and external accessibility reads use official `node_repl` /
`@oai/sky`. Qt focus/renderer telemetry is marked `product_telemetry_not_UIA`;
its `query_*` fields describe the Combination query, not Archive source state.

- `persisted-lab` uses the existing `_persistent_live_stack` contract fixture.
  A public create command persists one draft task, then its exact task context
  enters the production Lab. This session does not reopen the application.
- `controlled-evidence` uses the existing deterministic fake adapter through
  public AppContext composition. It starts with the completed 36-object fixture,
  then supplies disconnected revision 3 and invalid-source revision 4 through
  existing public fake controls. The latter clears `last_reliable_data` and sets
  failed/unknown state. These are controlled source inputs, not real external
  outages or newly executed research. `fake40` remains visible in provenance.

Launcher SHA-256:
`F9411194F7B41CBD6F1D22BAE20DCAEB07968BBD0FF1C549BD860C92EA64039C`.
These composed sessions are not source-entry or installed cold-start benchmarks.
No Windows display setting, alternate native reader, UI test button, second UI,
IPC, paid service or external dataset was introduced.

## Native sessions

| Directory | Source | Actual client | DPR | Renderer / text |
| --- | --- | --- | --- | --- |
| `persisted-lab-1426x786-text200-d3d11-01` | f50d519 | 1426x786 | 1 | Direct3D11 / 200% |
| `controlled-evidence-960x540-text100-software-01` | f50d519 | 960x540 | 1 | Software / 100% |
| `controlled-evidence-wide-text200-d3d11-01` | f50d519 | 1880x940 | 1 | Direct3D11 / 200% |
| `controlled-evidence-wide-text200-d3d11-854e1d1-03` | 854e1d1 | 1880x940 | 1 | Direct3D11 / 200% |

All four observed sessions exited 0, closed contexts and stopped bridges. Fresh
official window inventory confirmed no remaining StockSim window. At 1880x940
and 200% text the available logical space supports a list and combined details;
sources remain in details. This is not evidence of a third column at that size,
nor a complete physical-DPI/state/font matrix.

One additional launch, `controlled-evidence-wide-text200-d3d11-854e1d1-02`,
produced internal telemetry but no targetable official-tool window after two
selection attempts. Its verified task-owned PID 270124 was stopped; the process
exited 1 and has no clean-close record. It is excluded from native results.
Relaunching the same committed source with desktop execution elevation produced
the observable `-03` session. No alternate window-automation implementation was
used to recover the excluded attempt.

## Persisted Lab observation

The named one-item Lab list opened exact task
`diagnostic-task-52943fbf9caf53bfbc3dd873`, revision 2, lifecycle `draft`, with
configuration identity
`sha256:a7d932ab8cf222966305765a85c37fc180ea5defff90286c3983b8bd286796ec`.
Details showed no validation, active approval or campaign handoff. The completed
100% handle described `diagnostic_task_created`, not a completed experiment.
Ctrl+End reached the final limitation; X did not change the accessible document.

After closing, SQLite URI `mode=ro` inspection of `diagnostic-tasks.db` found the
same identity, revision, lifecycle and configuration. There was one create
command (`native-lab-create`), two configuration revisions, zero campaigns,
validations, approvals, mutation commands and campaign handoffs. The audit is
`persisted-lab-1426x786-text200-d3d11-01/persistence-after-native-read.json`,
SHA-256 `03AEBBFD95DAC98921791F0D375204B837846F8C79153D726360E738DF146A3A`.
The unrelated default `runtime.sqlite` has no tables; it is not the task store.

## Exact references through disconnect and invalidation

Both controlled Archive layouts exposed the full comparison identity
`CMP-MODEL-B17-FEE`, with reference `E-MODEL-B17-EXEC-BASE` and observation
`E-MODEL-B17-EXEC-ISO`. Keyboard drill-down read the original reference value
`-1.1 return delta percentage points`, with the same package, candidate and
source identities. No comparison was recalculated.

The compact session retained the comparison and focused reference while the
source became disconnected. It read the original reference. Invalidation then
arrived before the attempted parent return; the UI explained that the original
parent was unavailable, selected no replacement and visibly focused the drawer
trigger. Space showed a named empty list; Escape returned to the trigger.
Raw label `controlled-disconnected-parent-return` records the intended action,
not its actual source state: it was already invalid, as the subsequent settled
snapshot and timed source records demonstrate.

In the first wide session, disconnected parent return successfully reopened
the exact comparison. A subsequent invalidation removed the focused related
control and moved Qt focus to the empty catalog. Its missing visible outline,
and the missing outline after mouse selection followed by keyboard return,
prompted the repair below. These failures are retained, not counted as passes.

## Reproduction, repair and regression

The minimal actual-QML mouse reproduction clicked the second Scenario row,
then used Shift+Tab from details. The keyboard current index was still 0 even
though row 1 was selected. The focused row could therefore differ from the
mouse selection or be outside the viewport. The empty catalog had current index
-1 and no delegate capable of drawing a border. Extending the render wait from
30 to 300 ms did not fix either symptom.

The repair synchronizes the keyboard index only when the user explicitly chooses
a row, and draws the existing focus tokens around the catalog when no row is
current. It does not choose an alternate object on invalidation. Tests inspect
the actual framebuffer border pixel, then verify Return reopens the same exact
details. The two mouse cases use 1426x786/text100 and 1880x940/text200; the existing
normal invalid-reference case now checks the empty-list frame as well.

- `catalog-focus-red.xml`: 3 failed, 3 passed, 29 deselected, 3.50 s.
- `catalog-focus-red-settled.xml`: same 3 failures after the longer wait, 4.20 s.
- `catalog-focus-green.xml`: 6 passed, 29 deselected, 3.05 s.
- `catalog-focus-regression.xml`: **112 passed**, zero failures/errors/skips,
  54.72 s console / 54.685 s JUnit. The same four affected modules cover the
  shell, resource pages, resource states and public product entry. Existing
  `record_property`/xunit2 compatibility warnings are recorded (39 warnings).
  SHA-256: `03D9267CBC54DDEB4D5470428EB38A2500C67FE3EDBE97577C0A4C4E2112BB4B`.

Reproduction uses the isolated `run-issue134-tests.ps1` runner in the parent
artifact directory, passing `test_research_resource_pages.py -q -k
'mouse_selection_returns or related_focus_tracks'` as its test-argument array.
Temporary `[DEBUG-catalog-focus]` probes were removed before the green run and
commit. No unrelated repeat regression was performed after these checks.

The final native `-03` session verified the committed fix: mouse-selecting
`E-MODEL-B17-RISK-BASE` and pressing Shift+Tab outlined that second row; Return
reopened the same `-12.6 percent` observation. The original longer comparison /
reference / Shift+Tab path now visibly outlined the comparison row. Disconnected
parent return retained the exact comparison. With a reference link focused,
invalid-source input cleared the list and content and displayed the empty-list
outline. Tab then visibly focused the failure explanation, with no focus trap.
Saved screenshots: `mouse-keyboard-visible-focus.png` and
`invalidation-visible-focus.png` inside the final session directory.

## Standards

Independent fixed-range `f50d519...854e1d1` review: 0 documented violations and
0 actionable baseline smells. The local index update and token-based frame
conform to ADR 0038/0039; the shared rendering assertion is appropriately scoped.
The reviewer performed no edits, tests or native UI actions.

## Spec

Independent fixed-range `f50d519...854e1d1` review: 0 actionable findings.
D14 requires visible focus and fallback when a target becomes invalid; D15
prohibits substituting another identity after a local failure. The explicit
selection update and empty-list frame preserve those behaviors. The reviewer
did not certify whole-ticket acceptance or native accessibility properties.

## Raw evidence and remaining boundary

`artifact-manifest.json` records hashes and sizes of the launcher, test results,
all observation logs, persistence audit and saved screenshots. UIA JSON hashes
in the native-session table's order are:

1. `ED82BC70ADB5568AD638DE46C79BEE2A1CA991C9C34D63FD54C89EE786C0E0BE`
2. `4D10D1E41073AF9D7DE9B4CCCB19343BA9762142C71F3382FFD301626CFAFF90`
3. `BE319B626FF5013DBB619ADF431F84F8859596782DC86C05AACB78120B74F0EC`
4. `EF3CB8FD7A49A4C6B5FD2EEF968E0643B42054DC9AECC9454B75C6DE773C4D17`

The official tool's `focused_element` still reports a background details control
when the visible outline and separately labelled Qt telemetry identify the
catalog or a reference button. This is not accurate native-focus-property proof.
The earlier readonly guard's CacheRequest `0x80070057` failure is also unresolved;
it was not retried against unchanged observer behavior in this increment.

#134 remains OPEN and the full #132 / #133–171 goal ACTIVE after this substantive
native coverage and product fix. Remaining relevant work includes retained live
source recovery, active task/run lifecycle combinations and the unfinished local
state/layout matrix. Reliable supported native readonly/focus observation is
still required before whole-ticket closure. Full Narrator, formal physical DPI
and installed-candidate A41 remain later shared gates. Prior above-750ms source
entry samples remain failures at their recorded boundary. No successor ticket,
remote publication, installed gate or full goal is claimed complete.
