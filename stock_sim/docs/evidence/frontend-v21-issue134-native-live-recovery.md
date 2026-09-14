# Frontend V2.1 #134 — native recovery of retained live Scenario observations

Date: 2026-09-15 (Asia/Shanghai). This is incremental evidence, not ticket acceptance.
Specification: published #132 v1.0, D14/D15 and the #134 real-source/failure clauses.
Observed production commit: `8507b6dac46a1acdb7c9a6f90d6e65b12192c991`.
The production source and tests were unchanged throughout this increment.

## Input and observation boundary

The production `MainWindow` uses the public live `AppContext` and an isolated
SQLite-backed diagnostics application. The existing `_formal_live_stack` fixture
admits a local synthetic historical segment, approves recipes and materializes
their reference paths through the real application. This is real persistence and
live projection over controlled local input; it is not an external market-data
outage, an installed-candidate run or a cold-start benchmark.

`observe_live_recovery.py` deliberately warms the public Scenario source before
opening the window. Native input then selects the second saved Scenario, leaves
the page and reenters it. A timed SQLAlchemy source fault holds the first actual
SELECT for 25 seconds and raises `OperationalError`; subsequent reads would also
fail until the timed restoration. Neither arming nor restoring the fault forces
the page to refresh. Native page navigation initiates the read and later retry.

Every desktop action and screenshot uses the official Computer Use `sky` tool.
No QTest input, alternate UIA reader or system-setting change is used. The separate
250 ms Qt telemetry records the displayed projection, actual client/DPR, renderer
and active QML object. It does not claim to be native accessibility evidence and
does not call the live Feature snapshot on the GUI thread during the held read.

Artifacts are under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.
The launcher SHA-256 is
`600A3580776881F897DA30863EE753834E1DA5221367EFA6EE35AFEA1519DBE9`.

## Observed sessions

| Session directory | Actual client / text / renderer | Observed result |
| --- | --- | --- |
| `live-recovery-1426x786-text100-software-01` | 1426x786 / 100% / Software, DPR 1 | Selected second Scenario; retained exact details while waiting, after failure and after successful retry. |
| `live-recovery-960x480-text200-d3d11-02` | 960x480 / 200% / Direct3D11, DPR 1 | Same sequence through the compact drawer; visible failure/retry explanation and keyboard access to source versions and limitations. |
| `live-recovery-960x480-text200-d3d11-01` | 960x480 / 200% / Direct3D11, DPR 1 | Excluded from recovery coverage: fault timers elapsed before native selection, so no SELECT entered the fault. Second-row reading and Ctrl+End were observed. |

All three sessions exited with code 0, closed the application context and stopped
the bridge. The final official window inventory contained no StockSim window.
The two valid held reads lasted 25.002 and 25.001 seconds respectively; those are
controlled source delays, not performance samples.

## Exact identity and visible behavior

Both valid sessions retained all 28 catalog entries and the same six-part selected
identity throughout the fault and recovery. No default or alternate record was
selected. The full UIA document text at waiting, failed and restored checkpoints
matches the selected record's pre-fault text exactly, including source identities
and compatibility restrictions.

| Field | Normal Software session | Compact Direct3D11 session |
| --- | --- | --- |
| Scenario | `campaign-case-1f102b16a91f367ed4f58dfd` | `campaign-case-3cfac1eb32f54f7a3b7d1e5e` |
| Approved recipe | `recipe_version_9f4af025629d52343411a8a00279476fff70ace6a6ee28acb0628703593b77c9` | `recipe_version_6e199fec559f4a51d731c7e41d0a851de3b6faec389c4cfd81b62900259a4ea4` |
| Recipe content hash | `28e88e0c2f655b09489b924e0e2e141b4f86be6bfdb73ad633ac0df34eed58c0` | `bc5374c180582dfed97dfd369937bbe4759ce708f32e2047ca1cddf39a71f2d7` |
| Reference path | `c3acdd153dcfb40c74c1ec014fa07e48588cab03402d9dbd5ddbcf0f290842a1` | `2df07735183583ab223ae6048914c26be52115b67efafcdad89299c26fd8c58e` |
| Full detail text SHA-256 | `62C1BBEE8587F7AE8D7FAA7BA22F7BECD0A8493E5777D4D05B8D918959F8C56A` | `9FB54421606A4D16B48FC0A9FBF702C87A2FD1413C73FE967FC6C1A2B7FC12AE` |

Both refer to `segment_b386a0441c0bba7eac13`, segment hash
`b386a0441c0bba7eac13cb48416eafaa0041603f13fe7e4b5ea858eb5eea8128`,
snapshot `snapshot_1a46b8c3ce093eb168e2`, seed 17 and the original isolated
sensitivity / compare-to-baseline diagnostic layer. The source generation is 1;
the source revision tokens are recorded in `live-recovery-audit.json`.

The waiting status reads `正在读取场景资源；后台计算继续，保留上次有效观察。 · stale`.
On failure it becomes `场景资源观察暂不可用；可重新进入场景库重试。 · stale`.
After restoration, leaving for Archive and reentering Scenario returns the status
to `Authoritative Scenario Lab inventory is ready. · fresh`. The generic waiting
copy is not evidence of an active calculation: these sessions started no run.

The health overlay opens during the held read. Escape closes it and the health
trigger has a visible focus outline; by the Escape captures, the source read has
already failed. The earlier raw normal-session label `live-read-wait-health-return`
describes the intended sequence, not proof that the read was still waiting then.
The health fixture itself reports stale historical context, with periodic health
sampling disabled; this is separate from the Scenario recovery state.

At 200% text, the compact list drawer closes after selecting its second row and
the details receive visible focus. During the failed state, Ctrl+End exposes the
transformation/market-rule versions and the full compatibility restriction. After
retry, that scroll position and the complete source text remain available.
Saved images include `retained-waiting.png`, `retained-failure.png`,
`restored-exact-source.png` and compact `failed-source-end.png`.

## Evidence audit and limitations

`audit_live_recovery.py` parses the recorded literal-LF JSONL, checks exact text,
selected identity, 28-entry retention, source-fault entry/raise and recovery order,
and reads each database after clean shutdown. No private exception marker is
present in any captured UIA tree or document. Task, task-command, approval,
validation, handoff, Campaign and strategy-Run tables remain empty. The schema's
single initialized task-sequence row is recorded separately from those tables.

`live-recovery-artifact-manifest.json` records hashes and sizes for 23 files,
including the three databases, launch/audit scripts, logs and screenshots.
`live-recovery-audit.json` SHA-256:
`D2F433811033CD880466407811235DEB23309DCC1E2C98960214268B59CB3524`.
The valid normal and compact UIA log hashes are respectively
`850B33F28ADD48273EC28A438FFF8E9DF5C6367E328DF497F1E813F446FF4E8E`
and `54B21D5AD4D57D7C0C0D372C8A9E1325251FBA72ACD10472A1611A2A1AB10656`.

Immediate native UIA trees can lag screenshots after navigation; the comparisons
above use fresh settled observations. The tool's focused-element field still
misidentifies the background details control. Its earlier readonly-property
CacheRequest failure remains unresolved and was not repeated here. A compact
details click by UIA index also failed because its reported center was outside the
window; after a new screenshot, clicking the visible text region succeeded.
These tool outcomes are retained as limitations, not property passes.

No production code changed, so the preceding 112-case affected regression remains
the latest result; it was not rerun for evidence-only additions. The existing
real-source integration case is
`test_scenario_database_read_failure_ends_waiting_and_preserves_stale_content`.
This increment adds native composed-product observations over the same source
boundary rather than a new duplicate test.

#134 remains OPEN. The full #132 / #133–171 goal remains ACTIVE. A separate
[real execution observation](frontend-v21-issue134-native-live-execution.md) now
covers pending work during native navigation, the health overlay and view
disposal. Remaining local state/layout coverage and supported, reliable native
readonly/focus observation still need completion. Full Narrator, formal physical
DPI and installed A41 are later shared gates; none is implied by these sessions.
