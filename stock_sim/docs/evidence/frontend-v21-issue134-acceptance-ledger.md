# Frontend V2.1 #134 — clause-level evidence and remaining acceptance

Audit date: 2026-09-15 (Asia/Shanghai). Audited source:
`c9679be1b9a6a7b43aacd117ddf610d32b9f6961`. The formal #134 body and all #133–171
bodies/states were freshly read from GitHub, without comments. #133 is CLOSED;
#134–171 are OPEN. #134 is the only open ticket whose stated blockers are closed.
Every later ticket depends on #134 directly or transitively; direct successors
include #135, #143, #165 and #167. No successor is claimed ready or complete.

This ledger replaces the generic historical remaining-work lists for the shell
slice. It does not narrow the full #132 / #133–171 objective. Evidence is evaluated
against #134's six checkboxes and explicit scope: usable four-page shell and real
existing resources; later page authoring/visual detail and shared final gates
are not reverse dependencies. No entire checkbox or acceptance group is marked
PASS while a component remains unverified.

## Clause mapping

| #134 requirement | Current evidence | Remaining boundary |
| --- | --- | --- |
| Only four primary destinations; six independent capabilities; top health overlay | `test_research_workspace_shell.py` four-route keyboard case; public live console and package entry; native four-page and health walkthroughs in [native names](frontend-v21-issue134-native-names-progress.md). | Native readonly-property verification is still missing, as detailed below. |
| Compact single primary region/reversible drawer, normal list/detail, font-dependent wide evidence | Actual 960x480 and 960x540 at text100/200, normal 1426x786, wide 1878x938/1880x940; source-column collapse and retained focus; actual-QML 2600x1400 layout cases. See [states/layouts](frontend-v21-issue134-native-state-and-run-focus.md), [contexts](frontend-v21-issue134-native-context-and-catalog-focus.md), [resource matrix](frontend-v21-issue134-resource-pages-progress.md). | Actual client/DPR is recorded per case. Full physical-DPI/4K matrix and final page visual detail remain explicitly assigned to later work. |
| Identity, status, reason and available actions remain reachable | Exact Combination version read, Scenario source/hash/limitations, persisted Lab task/config, completed Run, original Archive record/comparison/finding and reversible relation; compact Ctrl+End and native source-failure explanation. | Complete authoring and exact Attempt controls are subsequent slices and remain visibly unavailable. |
| Page observation subscriptions release without stopping application work | Existing public-Feature subscription tests and real execution/disposal/remount tests; [native pending-work sequence](frontend-v21-issue134-native-live-execution.md) closes the view before real host completion. | Native sequence proves view/application separation with an explicitly retained AppContext, not installed-process shutdown. Native remount is supplementary; existing real all-Feature remount regression covers that behavior. |
| Keyboard traversal, modal return and invalid-target fallback | Native Tab/Shift+Tab/Down/Enter/Escape; exact source and long text reads; compact trigger fallback and wide empty-list outline after invalidation, with committed focus repairs. | Visible behavior is observed. Accurate native UIA focus-property reporting remains unresolved. |
| Old six routes remain valid through compatibility entry | Retained Journey Rail/exact inspector/old Scenario, Task, Evidence and Health route suites, plus entry default/recovery tests; incremental regressions documented in [resource record](frontend-v21-issue134-resource-pages-progress.md) and [health routing](frontend-v21-issue134-health-routing-progress.md). | Historical runs and narrower corrective reruns remain separate; they are not summed into one current full-repository result. |
| Record both renderers' first actual projection and cold boundary; no skeleton 750 ms claim | Initial two-resource source probes plus four isolated public console/package-module entry samples in [progress](frontend-v21-issue134-progress.md#native-source-entry-frame-records-not-750-ms-acceptance). Both first frame and later resource endpoint are retained. | All four source-entry resource intervals exceed 750 ms. This clause requires recording them; it does not grant installed A41 PASS or waive the later target. Physical OS cache coldness was not controlled. |
| Actual empty input and real existing resources are usable | Real empty SQLite Scenario source; live two-version Combination query; real materialized Scenario, persisted Task, reopened completed Run and sealed evidence; failure does not imply emptiness. | Fake fault inputs and real application/persistence are explicitly distinguished. No external data acceptance is inferred from fixtures. |
| Public AppContext commands/snapshot/Subscription; live/fake same new-interface dataset if added | Live/fake read cases use public composition; real commands, sealing/reopening, exact contexts and source-fault inputs underpin the tests. Diff from #133 adds no file under `app/features` or new Feature contract version. | The interface-addition condition does not arise in #134. Different existing fixture datasets are not advertised as identical-contract evidence for a new interface. |
| Affected existing journeys green, source/input versions retained | Latest affected four-module suite: 112 passed. Earlier broader 327-pass/3-old-assertion-failure run is retained; both complete resource modules subsequently passed with the three assertions corrected. Every repair has a fixed source review and targeted/affected regression. | No fresh all-repository PASS is claimed. No production changes occurred in the recent native-evidence increments. |
| Product normal, empty, error and waiting states demonstrated | Native live resource reads, real-empty console entry, delayed/failing real Combination query, retained Scenario DB failure/retry, Archive disconnect/invalidation, real pending calculation. [Recovery](frontend-v21-issue134-native-live-recovery.md), [native states](frontend-v21-issue134-native-state-and-run-focus.md). | These are representative shell behaviors with supplementary actual-QML matrices; no undocumented full Cartesian state/layout/renderer certification is inferred. |
| Compact 960x480/540, normal/wide, text100/200, keyboard and actual client/DPR | Native sessions above plus per-case Qt renderer/geometry assertions and keyboard coverage in the 14-state/8-Run matrices. Wide text200 correctly combines sources when a third region cannot fit. | Those measured dimensions cover the local shell requirement. Full physical-DPI and Narrator chains remain later shared gates. |
| UIA names, roles, values, states, positions and focus return | Native heading/status naming, named lists/rows, precise values and final positions, enabled/disabled query actions, and visible modal return; Qt readonly and focus regressions pass. | **UNVERIFIED: native readonly property and reliable native focused-element reporting.** These cannot be inferred from Qt state, an X-key rejection or screenshots. |
| Large data: both renderers' latency/resource record | [1,055-item Archive measurement](frontend-v21-issue134-large-archive-renderers.md), same measured 960x480/text200/DPR1; input-to-matching-rendered-frame samples, whole-process memory/CPU/handle/thread snapshots and exact last-row read. | Single samples are records, not percentile, leak, GPU budget or installed performance verdicts. #134 adds no graph that needs a new graph benchmark. |

## Supported native observation remains the unresolved requirement

A [fresh-process and fresh-tool-session retry](frontend-v21-issue134-native-property-retry.md)
at `1190560` reproduced the missing readonly result and conflicting focus fields.
It also records that a failed readonly probe can move focus before its error,
so the successful modal-return sequence is observed separately without a probe.

The official `sky.get_window_state` field `focused_element` repeatedly names a
background details Edit while the screenshot shows a navigation, list or popup
focus outline and separately labelled Qt telemetry identifies that actual QML
target. This recurred in the names, state/Run, context/catalog, live recovery and
current large-Archive sessions. It is a conflict in the native observation chain;
these observations alone do not prove whether the cause is the observer or Qt's
native accessibility provider.

The supported same-value `sky.set_value` readonly guard previously failed with
`read UIA value read-only state: 所需属性不在 CacheRequest 中 (0x80070057)`.
The current supported API reference offers no separate raw readonly-property
reader or cache-control option. That failed guard supplies no IsReadOnly result.
Repeating it unchanged, weakening the requirement, or substituting a custom UIA
helper would not produce the authorized proof.

Native names/roles/value text and visible behavior have already exposed real
defects, which were repaired and independently reviewed. That progress does not
turn the remaining unknown properties into passes. With the large-data clause
now recorded, the older generic demands for more local state/layout examples
do not justify repeating already-covered workflows indefinitely.

Closing #134 requires reliable supported native observations of readonly and
focus/return, followed by assessment and any necessary product correction. The
existing user constraint permits only official Computer Use for these native
checks. Full Narrator, formal DPI and installed-candidate A41 are separate later
gates, not reasons to leave this shell ticket open.

The full initiative remains incomplete. A blocker in #134 does not authorize
skipping its dependencies, implementing an easier substitute, deleting fallback
assets, using a second UI stack or certifying later tickets. Fresh formal bodies
are retained in scratch `formal-issue-frontier-audit.json`; no remote issue state,
label, source branch, release or user system setting changed during this audit.
