# Frontend V2.1 #134 — legacy health overlay checkpoint

Date: 2026-09-14. This is implementation progress, **not ticket acceptance**.
The full #133–#171 goal remains active. No remote publication, main merge,
release, production-default switch or system configuration change was performed.

## Subsequent entry checkpoint and ownership correction

Source `04a57b8b00040ae1c91cec4e0583b3b2ae05336e` now connects explicit
`--research-shell` through both public source entries. It preserves old/default
files, retains unknown isolated bookmark inputs, propagates recovery reasons and
cleans up the reproduced failed-start paths. Full entry evidence, native source
frame timings, test/report hashes and independent review are in
`frontend-v21-issue134-progress.md`.

Correction to the historical remaining-work wording below: schema3 belongs to
#165, which depends on #134; complete cross-restart research context belongs to
#164. Neither is an implicit #134 prerequisite. Full installed-candidate 750ms
and physical DPI/Narrator are later shared acceptance, not reverse blockers.
#134 retains its own real empty/existing projection, state/Subscription,
font100/200 layout and local keyboard/UIA/focus obligations. No health, startup,
full A-group or whole-ticket acceptance is implied by the entry increment.

## Per-group observation increment — 2026-09-14

Fixed predecessor `c7283f3f6ab3f93988ef1d7a0e3e8a0d871be58a`; candidate source
`d10a3c846b74c79cda0e48a15f2c49046e4daf05`; corrected source
`2ec99b140d9a4eab8e965222a2e03b5c6ce78b40`; performance correction
`e1bc5dbc47a35426d2c9e028f76e8c72ee826d20`. This is another local #134 increment,
not a complete D14 or ticket acceptance. The pure renderer uses delivered typed
facts only; it introduces no reads, clock, commands, expiry policy or Feature API.

- Runtime, data source, queue, cache, persistence and version each show their own
  observation record, scope, current affected work and safe diagnostic. Data,
  queue, cache and persistence show their own age/threshold. Runtime/version's
  existing 1.0 contract lacks independent age/threshold, so these are explicitly
  missing rather than borrowed from peers. Available successful/reliable
  observation and durable read/write timestamps remain separate facts.
- A failed queue read retaining STALE data cannot be labelled fresh in the top
  summary merely because the aggregate observation is fresh. The priority
  component's own freshness is used where that public field exists.
- Cold persistence has no successful observation timestamp even though the old
  projection emits FRESH/zero. Details explicitly state no reliable observation,
  retain the old interface marker as such, and show unknown age, not reliable zero.
  The legal Runtime RECOVERED value renders as recovered without losing all groups.
- The read-only text continues updating while a user reads. A UI-only UTF-16
  matching-span mapper keeps an unchanged middle position or forward/backward
  selection attached to surviving content; an end position follows the end.
  Removed content clamps to the replacement. There is no frozen snapshot,
  refresh/pause command or domain recovery mechanism. The UI skills informed the
  restrained factual hierarchy and keyboard continuity, not new scope.

Eleven permanent actual-QML tests cover per-group facts, independent age, failed
queue retention, unknown cold age, RECOVERED through the public live health
application input and AppContext, read-only QAccessible values, normal/compact
font scaling, reading position and both selection directions. Seven supplemental
pure offset cases initially covered initial/empty text, deletion and UTF-16
non-BMP content; two added cases cover an unchanged span within a changed line
and repeated unchanged lines (nine supplemental cases on final source).
The two existing real exact-Task cases additionally assert group facts and their
affected-work association; their original identity checks are retained.

Reports below are immutable files under the existing `issue134-20260914` root.

| Behavior | Causal red | Green / scope |
| --- | --- | --- |
| Per-group observation record | `health-detail-observation-fields-red.xml`: 1F | `health-detail-observation-fields-green.xml`: 1P |
| Retained stale queue cannot have a fresh header | `health-detail-queue-freshness-red.xml`: 1F/1P | `health-detail-queue-freshness-green.xml`: 10P |
| Reading at the end survives update | `health-detail-reading-continuity-red.xml`: 1F/6P, caret reset to zero | `health-detail-reading-continuity-green.xml`: 9P including two real exact-Task cases |
| RECOVERED, cold persistence age, middle caret and selection | `health-detail-review-findings-red.xml`: 4F | `health-detail-review-findings-green.xml`: 10P, before backward-selection and cold-label refinement |
| Cold persistence label cannot imply reliable freshness | `health-detail-cold-reading-probe.xml`: 1F/10P | Included in corrected 28P run below |
| Initial empty observation retains the beginning | `health-detail-offset-red.xml`: 1F/6P | Included in corrected 28P run below |

`health-detail-age-and-unknown-probe.xml` (1F/3P) used an invalid wait for domain
phase to leave LOADING. A valid delivered unknown snapshot can remain LOADING;
the corrected test waits for the actual rendered observation. It is a test setup
correction, not a causal product red.

Corrected source targeted report `health-detail-corrections-targeted-green.xml`:
**28 passed in 71.84 s** (11 details + 7 offset + 10 exact-observation), no failures
or errors. SHA-256 `444AD7B9B7F3E7B2F524F9A799CE29B3CC709587E08F0946E20507306E2B9FF5`.
The four-failure review red SHA-256 is
`69DABF5931E6F7208DC36FFF0A0B2A3AE3C789CE24E97AD286612919E39D270E`.
The cold-label red SHA-256 is
`94BD723B9E08E73C689C38C526EB6B31EC535E6E4E589B788247A83B08A9AA05`.

### Native crash investigation, not a repaired-crash claim

The candidate full run on `d10a3c8` (terminal session 47909, exit 1) emitted
`Windows fatal exception: access violation` in the retained Tasks test
`test_real_diagnostic_tasks_route_renders_each_terminal_inventory_state`, line
3470 (`app.processEvents()`). It terminated before a final JUnit report existed;
`health-detail-candidate-full-regression.xml` is absent. The tool trace records
the crash; it is not a passing 264-case report and no missing XML was fabricated.
The diagnostic skill required a reproducing loop before causal speculation.

On unchanged candidate production source, the exact parametrized test replay
passed 5 cases in 2.68 s (`health-detail-crash-isolated-replay.xml`, SHA-256
`855941AF65330CDF5044E0CF0EF567F949484977292BF256D2C27374B51A829D`).
The original first-two-module order then passed 40 cases in 174.79 s
(`health-detail-crash-prefix-replay.xml`, SHA-256
`F718A9900FD0CA6F6B55BFCAB2D4222BBEB8221D44E4465B34DDD30139FFD3FB`).
Neither reproduced the crash. Cause is still unknown; no native-crash fix,
environmental explanation or flaky-test exemption is asserted. The independent
health rendering defects were reproduced separately and do not explain this crash.

### Corrected-source review and regression

Fixed nonempty review range:
`git diff c7283f3f6ab3f93988ef1d7a0e3e8a0d871be58a...2ec99b140d9a4eab8e965222a2e03b5c6ce78b40`.
Spec independently confirms its original 2 P2 resolved, 0 new deviation. Standards
confirms the original hard-standard P2 resolved, then identified a separate P2
performance issue with whole-text character matching. Neither executed tests or
certified the whole ticket. The performance recheck is recorded below separately.

Source `2ec99b1` related regression `health-detail-reviewed-full-regression.xml`
completed **275 passed in 450.63 s**, zero failures/errors/skips. The native crash
did not recur in this run, but its cause remains unknown. This report predates
the performance correction and must not be relabelled as final `e1bc5db` evidence.
SHA-256 `55DDC9EAEA5D83C86025E05A6C55472AEC71B263E7F214EFA5913AF56AA6C5BE`.

### Matching performance correction

The bounded scratch probe `health_detail_selection_timing.py` used a public fake
Feature snapshot and a second typed-valid snapshot with six 480-character safe
explanations. These are synthetic inputs, not production workload measurements.
Initial full-text UTF-16 matching took 143.599–151.391 ms for 3835 characters
(five calls); a repeated isolation probe measured 153.164–163.977 ms. Encoding
alone took 0.293–0.381 ms and line matching 0.070–0.119 ms. These observations
support the fine-grained full-text matching cost, not a Qt-layout-only cause.

`e1bc5db` first matches whole lines and refines only a changed line block that
contains a selection endpoint. Both endpoints share that block's refinement.
The same long legal descriptions with a middle Version-heading selection took
0.101–0.160 ms (five calls); ordinary 1292-character observations took
0.087–1.271 ms. Actual QML keyboard behavior plus nine supplemental offset cases
passed: `health-detail-local-diff-targeted.xml`, **20 passed in 6.38 s**.
SHA-256 `F8F59DF8531EF9969E1D862BAD75540A6CD681381382EA6C0FFEA85C9D0EA6DD`.
No text, UI-state, execution or observation-timing contract was relaxed.

This is a local isolated-function comparison, not a guarantee about every legal
input, full UI frame latency, native renderer or machine. The scratch probe is
retained as clearly labelled diagnostic evidence; no debug instrumentation was
added to production.

### Final independent review

Both axes rechecked the fixed nonempty performance range
`git diff 2ec99b140d9a4eab8e965222a2e03b5c6ce78b40...e1bc5dbc47a35426d2c9e028f76e8c72ee826d20`
and retained their earlier review of the full increment.

- Standards: original RECOVERED hard-standard P2 resolved. The separate concrete
  performance P2 is also resolved on its reproduced path; it was not relabelled
  as a Fowler smell or hard-standard violation. No new hard-standard violation
  or actionable smell. The reviewer read the 20-pass report but did not run tests.
- Spec: original two P2 (RECOVERED and unknown persistence age) remain resolved;
  no new deviation in localized matching. It only adjusts the reader's position,
  never the incoming facts or execution state. Static review only.

Counts remain per axis: Standards 1 hard P2 + 1 performance P2 resolved,
0 outstanding in this increment; Spec 2 P2 resolved, 0 outstanding. Shared
RECOVERED findings are not counted as different defects. Neither axis certifies
the full ticket, the native-crash cause/fix, native UIA or overall frame budget.

### Final source-bound regression and visible frames

Frozen source `e1bc5dbc47a35426d2c9e028f76e8c72ee826d20`:
`health-detail-localized-full-regression.xml`, **277 passed in 459.11 s** console
(459.039 s JUnit), zero failures, errors or skips. SHA-256
`8E0061BFA0B32AF919ADD24B39723CA30ACFD586A1911C922596F11FD141EDB7`.
The 16 modules comprise the prior 257-case related suite, 11 new detail cases and
9 supplemental offset cases. Session 49560 terminated successfully; source/tests
were unchanged during the run (only these evidence documents were edited).
The native crash again did not recur; this is not evidence of its cause or repair.

Four final-source images in `health-detail-frames-localized-final/` were inspected:

| Frame | SHA-256 |
| --- | --- |
| `health-details-top-1426x786.png` | `DECEF2E2BAC983732A36082F5C9EE5184578CB2CF16A0426DE883141CD997CD8` |
| `health-details-end-1426x786.png` | `2ACA7DAD60C6F7C361E53F6C006183484434CB450BA8F1553B97A6632B97BC8C` |
| `health-details-top-960x480.png` | `0844E6646919C23C962A6D921F95E98BFEC47207F1B7F6DE9E69891C64F1B30E` |
| `health-details-end-960x480.png` | `081609E46DCD22677236E320CAB4001D683D6A7EB29191F8D4DFFB4B5F6878AD` |

Recorded actual logical clients are 1426×786/text100% and 960×480/text200%, DPR1.0.
Text wraps, Close remains visible, and keyboard reading reaches the final line.
The legacy aggregate/impact diagnostic copy is still technical and tall at text
200%; these images certify bounded scroll/read-only reachability, not final
language, information-density, appearance or full D14 acceptance. They are
offscreen Software/QAccessible evidence, not native Windows UIA/Narrator,
system text scale, physical DPI, Direct3D11 or formal packaged cold-start evidence.

Checkpoint locally complete; #134 and the full implementation goal remain open.
At that checkpoint, source entries, startup and local focus/accessibility remained.
See the newer entry evidence and corrected ownership above: generation-3 recovery
and the full physical DPI matrix are successor work, not #134 prerequisites.

## Header-summary increment — 2026-09-14 (previous)

Fixed predecessor `ab30fc85ad8bf63b18e4dd36af5651955b190019`; candidate source
`b3cb493d4ce5e762f3a1b7fd7b4b2c551ab50433`. This increment presents existing
typed SystemHealth observations in the top bar; it does not change the Feature
Interface, action capabilities, execution ownership or persistence schema.

- A readable overall label, observation freshness and highest-priority component
  concern replace the raw presentation enum. The existing aggregate includes
  cache and queue, unlike the former runtime presentation alone. Known failure
  with a fresh observation remains a failure; unverified recovery is not normal.
- The complete summary explains the affected legacy work from typed component
  impacts. It never invents an associated Task when none was selected.
- The header measures actual font advance before using a compact summary on the
  same button. The complete accessible name remains available. No animation,
  additional commands, cards or decorative panels were introduced. The UI skills
  informed the restrained content priority and measured layout, not new scope.
- Six permanent public fake-Feature/QML cases cover failure, exact scope, reflow,
  cache aggregation, paused queue versus failed Task, and unverified recovery.
  Two existing live AppContext/exact-Task cases also check the readable accessible
  header without replacing their persisted identity and keyboard assertions.

All reports below are in the existing `issue134-20260914` scratch evidence root.

| Behavior | Causal red | Initial green |
| --- | --- | --- |
| Visible persistence impact | `health-header-impact-red.xml`: 1 failed | `health-header-independent-observations-green.xml`: 1 passed |
| Exact affected-work scope | `health-header-scoped-impact-red.xml`: 1 failed, 1 passed | `health-header-scoped-impact-green.xml`: 2 passed |
| Long header fits 960 logical width at text 200% | `health-header-reflow-red.xml`: 1 failed, 2 passed; right edge 1100 > 960 | `health-header-reflow-green.xml`: 3 passed |
| Cache failure cannot appear normal | `health-header-cache-summary-red.xml`: 1 failed, 3 passed | `health-header-cache-summary-green.xml`: 4 passed |
| Failed Task is not global system failure | `health-header-context-failure-red.xml`: 1 failed, 4 passed | `health-header-context-failure-green.xml`: 5 passed |
| Partial recovery does not imply reliable observation | `health-header-unverified-recovery-red.xml`: 1 failed, 5 passed | `health-header-unverified-recovery-green.xml`: 6 passed, 3.89 s console |

Review-stage shared setup plus both live cases:
`health-header-reviewed-setup-live.xml`: **8 passed**, 6.38 s console.
SHA-256 `639C0F526AA28657739DA1611BF0F3B0C5E7905E96CB1AA833E36DD91AA4476E`.
The unverified-recovery red SHA-256 is
`FFEA7090D2A15D918710CAA6B61DBEC8055C0A9B7D7A573294C4F6A9AB6D9C3F`.

Intermediate reports with `impact-green`, `impact-delivered-green`,
`impact-authoritative-green`, `impact-state-probe`, `impact-exact-input-green`
and `queue-summary-red` in their names contain setup/wait or classification
assumptions, not additional causal product reds. Runtime and data-source delivery
are independent; snapshot revision is not a promise of QML notification; a queue
read failure retains a degraded prior observation rather than becoming unavailable.
Those reports remain unchanged and are not relabelled as passing evidence.

### Initial independent review

- Standards identified two P2 findings. First, compact text lacked a width check in the
  application's reachable 640×360 minimum. With text 200%, a superseded Task
  association and awaiting-first-state freshness, the actual button ended at
  x=673 while the actual client remained width 640.
- Both axes identified the other P2: in 960×480/text 200%, a completed Task hid an
  independent persistence failure in the visible compact summary. The accessible
  name retained the failure but did not substitute for visible priority impact.
- Both were reproduced through public inputs in
  `health-header-review-longest-observation-red.xml`: **2 failed**, 3.20 s console.
  `health-header-review-combinations-red.xml` and `health-header-review-longest-red.xml`
  each have 1 failed/1 passed; their shorter fresh text did not reproduce overflow.

### Review correction and source binding

The candidate `b3cb493` combined regression completed with **255 passed** in
438.10 s console. This confirms its retained journeys, not the two review cases
that were discovered separately. It is not the corrected-source final report.

Correction `55b4f803fdb51a42cbc0028e2b8cb24c7360fe33` shares one presentation-only
component concern selection between full and compact text. Compact text now
keeps the priority component and its failure; the associated Task's terminal
state stays in the full summary and accessible name. The actual compact text is
also measured. When it cannot share the row with branding, branding is hidden
first; the same health button and text size remain. No document string parsing,
Feature-contract change or action gating was introduced.

Both public reproducers are permanent tests. The long-text case checks actual
640×360 → 960×480 → 3840×2160 → 640×360 clients at text 200%, visible button and
label bounds, preserved focus, Space opening and Escape return without changing
route. The completed-Task case requires a visible persistence failure and retains
the terminal Task explanation in its full accessible name. The summary module
now has eight cases; together with both retained live cases the targeted report
`health-header-review-fixes-targeted-green.xml` is **10 passed**, 6.87 s console.

| Review artifact | SHA-256 |
| --- | --- |
| `health-header-candidate-full-regression.xml` | `3176056241D721C7E17AD75698EDCC9C7A1FF4F14A71EFEE55BDF5FEFA811AF9` |
| `health-header-review-longest-observation-red.xml` | `A78E72B76397F5068FA9010176401B1B3E824DBC2CEBC7B33F51CC645BA98C20` |
| `health-header-review-fixes-targeted-green.xml` | `5A65838B35ACF0025C9429B7816A1765AE422E6557DCDCB5277761EF334F3090` |

#### Standards

Independent recheck of verified nonempty `ab30fc8...55b4f80` confirms both P2
findings resolved: no new hard-standard violation or actionable heuristic smell.
Measured compact reflow conforms to ADR0039; component-first visible impact and
retained task details conform to ADR0042. The reviewer inspected source and the
targeted XML, did not run tests or edit files, and did not certify the whole ticket.

#### Spec

Independent recheck of the same range confirms its P2 resolved, with no new
deviation. Compact component impact and freshness conform to D14; hiding the
brand first respects its content priority. No Feature contract or execution
capability was changed. The reviewer did not run tests or certify all D14/#134.

Review summary: Standards 2 P2 resolved, 0 new; Spec 1 P2 resolved, 0 new. One
finding overlaps between axes; this represents two distinct product defects.

### Final corrected-source evidence

On unchanged committed source `55b4f803fdb51a42cbc0028e2b8cb24c7360fe33`,
`health-header-reviewed-full-regression.xml` reports **257 passed**, 394.12 s
console (394.046 s JUnit), zero failures, errors or skips. All test processes
terminated; source/tests were not edited during the run. The prior 249 cases plus
eight header cases ran across 14 modules, including real Task retry/reopen,
persisted exact observation, execution continuity and retained six-Feature paths.
This is a related regression, not the entire repository suite or ticket acceptance.

Final actual QML frames were inspected in `health-header-frames-final/`: compact
960×480 and 960×540/text 200% retain the visible persistence failure; 3840×2160
keeps the full impact scope; 640×360 shows the longest superseded/unknown-age text
without branding and without truncating the header. All record DPR 1.0, with
application text scale independent of DPI. The wide inspection preview was resized
to 2048×1152 by the image viewer; its saved source remains 3840×2160. Focus, Space
and Escape assertions run against actual QML, not the resized preview.

The 640 frame is header-specific evidence, not complete operability certification
for the rest of that small workspace. The read-only legacy content density and
technical-language popup are not final visual acceptance. Python 3.11.9 / PySide6
6.9.1, isolated offscreen Software and QAccessible do not prove native UIA,
Narrator, physical DPI, Direct3D11, startup or normal/package entry. No full D14,
#134, production-default change or release PASS is claimed.

| Final artifact | SHA-256 |
| --- | --- |
| `health-header-reviewed-full-regression.xml` | `5CB7F5C4CF89338344D9E6E7E5E8980846650BA44FC8B6DDBCB6FB20FED3D52D` |
| `health-header-frames-final/health-header-640x360-2.0.png` | `B86A61D20A1806253E9E687E175971890B25A1763B020CE9C0FC398E4709BEDE` |
| `health-header-frames-final/health-header-960x480-2.0.png` | `61883342A0B65E4F646D9472EE84C76C9F745BF5A28783E12EFED0168528CA27` |
| `health-header-frames-final/health-header-960x540-2.0.png` | `D38480F35F73310979050965878725FBF8DA43F5D87C85ED6B26A6C0C846FF10` |
| `health-header-frames-final/health-header-3840x2160-2.0.png` | `38E33607E896D744B9995EDD3F03D1E1D2150BE94C51FE9BB5736D051FD5D310` |

## Exact-observation increment — 2026-09-14

Predecessor `571904c94ccd2d3a99bf83acb8d771216a3ca340`; initial source
`b05f62edf2ef443c33990bd551eb242373c7e91b`. This increment addresses public
research observation and the existing SystemHealth 1.0 context. It does not
introduce the successor Feature 1.1 contract or certify all D14 requirements.

- Research Task projection requires an explicit Task identity. A new Host with
  no Task selection does not display the Feature's default most-recent Task or
  inherit its health association. One adapter observation policy covers reads,
  commands and handoffs; legacy default Task behavior remains unchanged.
- Health follows the explicitly observed Run or Evidence member of a Campaign,
  not the Task's default handoff member. Hidden Archive evidence from a different
  Run is excluded from the health identity graph, without changing the Archive's
  own retained selection. Returning to that Archive restores its exact manifest.
- The read-only popup exposes its exact associated Task/configuration/Run facts.
  State and impact precede the concise observation; complete version identities
  remain at the end for keyboard reading and copying. This restrained ordering
  follows the UI skills without adding cards, controls or motion. The existing
  technical-language density and native scroll appearance are not final visual
  acceptance.
- The permanent `test_research_exact_observation.py` promotes the earlier two
  exact-entry remount probes and adds six health cases. It uses real AppContext,
  live Features, persisted records, public typed Host entries and actual QML
  content/input. Explicit application advance prepares completed Campaign A;
  the independent active Task B uses one real public Start. This is not proof
  of an automatic campaign scheduler or all generation-3 recovery paths.

Initial source evidence, retained under the scratch root below:

| Behavior | Red | Green |
| --- | --- | --- |
| Actual popup includes exact Task/configuration identity | `health-exact-scope-visible-red.xml`: 2 failed | `health-exact-scope-visible-green.xml`: 2 passed |
| Same-Campaign non-default Run/Evidence association | `health-observed-member-red.xml`: 2 failed | `health-observed-member-green.xml`: 2 passed |
| New unselected Host does not adopt the previous Task | `health-cleared-observation-probe.xml`: 1 failed | `health-cleared-observation-green.xml`: 1 passed |
| Another Run's retained manifest is not joined to current health | `health-cross-run-evidence-red.xml`: 1 failed | `health-cross-run-evidence-green.xml`: 1 passed, 13.045 s JUnit |

`health-exact-observation-targeted-reviewed.xml`: **8 passed**, 48.580 s JUnit.
Painted QML frames in `health-exact-frames-reviewed/` record logical clients
1426×786 at text 100% and 960×480 at text 200%, both DPR 1.0. QAccessible exposes
readOnly and the exact Task in Value. Ctrl+End reaches the actual final cursor
inside the client; Escape returns focus. These are offscreen Software frames,
not native UIA, Narrator, physical DPI, Direct3D11 or startup evidence.
`health-explicit-selection-compatibility.xml`: **50 passed**, 209.83 s console,
covering retained Task journeys and research resource pages. Its nine warnings
are JUnit family/record_property compatibility warnings; the combined run uses
the legacy JUnit family explicitly.

The intermediate `health-exact-observation-targeted.xml` has 2 failures and
5 passes from a test-fixture refactor's missing local variable, subsequently
corrected. It is not a product red and has not been overwritten or relabelled.

| Initial artifact | SHA-256 |
| --- | --- |
| `health-exact-observation-targeted-reviewed.xml` | `0D38F9E4F94F4AE960E8B4CFA95414FF70B1AFD5EA23715B172A73D2711EE5E4` |
| `health-explicit-selection-compatibility.xml` | `0346506EF7A8946AB6AFD52FDD3E7C92F4AFBEFC896411421B524C9905E19FE6` |
| `health-cross-run-evidence-red.xml` | `2A89F4004BA44A49D166D6774DC0A6FE8814DA3E7011B90B63295E84DB4A0943` |
| `health-cross-run-evidence-green.xml` | `117EC96543EA2F55BE6F130AF1689CF3B38466D32B299B4D34E2C04BE674A804` |

### Cross-Campaign review correction

Both independent review axes identified a P2: an incompatible retained Task
could still be shown as the active association. Public live reproducer
`health-unrelated-campaign-review-red.xml` failed at both Run and Evidence
entries, with the unrelated Task visible in the actual popup facts.

Source `2d11870fbd7d93aa032dae580882a67a1dfeaeee` now returns no association
when Campaign identities differ and explicitly applies an empty typed health
context. Existing context/generation guards reject old deliveries. The popup
explains that no verifiable Task association exists and only system-level facts
are shown. This does not rewrite Lab, Run or Archive selections; returning to
Lab establishes its explicitly retained Task association again.

Two permanent public regression cases now cover this transition and return,
bringing the exact-observation module to **10 cases**. Independent Task approval
preparation is shared with the remount cases; no new production helper or command
was introduced. `health-cross-campaign-review-targeted-green.xml`: **35 passed**
in 76.06 s, combining all 10 exact cases and 25 retained Journey Rail cases.

The initial combined source report `health-exact-observation-full-regression.xml`
has **246 passed, 1 failed**, 398.37 s console (398.300 s JUnit), not a full pass.
Its failure is an existing internal-helper unit fixture's missing mode field.
The fixture now explicitly states legacy mode; all its identity and revision
assertions remain unchanged. No production getattr/debug accommodation was added.
The new behavior tests continue to use public Feature/Host and actual QML seams.

| Review artifact | SHA-256 |
| --- | --- |
| `health-unrelated-campaign-review-red.xml` | `A2571A361A249978179BD36962A94B57DCB4058F0DD1A6A85119A11DA06582F3` |
| `health-cross-campaign-review-targeted-green.xml` | `C4D05DE4AAF30EC2B886A513375E36A6B7F78CBB8FCBAE78E115D9DAAE1E0817` |
| `health-exact-observation-full-regression.xml` | `0CD63EBD533C616B2803E54528DA00A7AC6C70DF2A7264B9236B9FAB3D5A38D5` |

### Final source-bound regression

On unchanged committed source `2d11870fbd7d93aa032dae580882a67a1dfeaeee`,
`health-exact-observation-reviewed-full-regression.xml` reports **249 passed**,
442.44 s console (442.336 s JUnit), zero failures, errors and skips. Only evidence
documents were edited during the run. Python 3.11.9 / PySide6 6.9.1, isolated
offscreen Software, no production data or settings. Counts: 10 exact observation,
12 execution continuity, 25 research shell, 31 research resources, 25 Journey
Rail, 12 Journey workspace, 21 exact-query contract, 39 inspector, 19 Tasks,
15 Scenario, 8 Strategy, 30 health and 2 live Run-to-Evidence cases.

Final painted frames were inspected from `health-exact-frames-final/` and retain
the previously described actual client/DPR/text-scale and keyboard checks. At
960×480/200% long facts require scrolling; Ctrl+End reaches the end and Escape
returns focus. This is readable/reachable evidence, not final content-density
or native visual approval. The same native/startup limitations still apply.

| Final artifact | SHA-256 |
| --- | --- |
| `health-exact-observation-reviewed-full-regression.xml` | `0357C5F28B90EF09E0E6C10C4AF27B31F5201DF3F78C7E934D14FA5547D9D638` |
| `health-exact-frames-final/health-exact-scope-1426x786-1.0.png` | `8FF619A9D08D0EA5EADB5DF68D5B77E01110E47409562EF78866E6D44122AE5B` |
| `health-exact-frames-final/health-exact-scope-960x480-2.0.png` | `5688461195F7EF66BCAB8E48CA6C45FCF5E4F8CB219230ADAE0CA031799EC4F6` |

### Standards

The initial cross-Campaign P2 violates ADR0036 exact observation and ADR0042
affected-work scope. Independent recheck of verified nonempty
`571904c...2d11870` confirms it resolved; zero new hard-standard violations and
zero new concrete heuristic smells. Clearing health leaves the other page
selections and legacy branch intact. Existing unit-fixture clarification and
shared public approval preparation do not weaken the assertions.

### Spec

The independent initial P2 concerns D10 late/cross-object contamination and D14
current impact. Recheck of the same fixed range confirms it resolved with no
new deviation. The applied empty context and old-generation rejection also
respect D02. Both axes read source and assertions only; neither independently
reran tests or certified the entire ticket.

Review summary: Standards 1 P2 resolved, 0 new; Spec 1 P2 resolved, 0 new. These
are independent assessments of the same defect, not two distinct product bugs.

At that earlier checkpoint, top-level visible freshness/priority impact, complete
per-group observation age, local native reflow/UIA/focus, source entries and
cold-start records remained unfinished. Later checkpoints above record bounded
progress, not full acceptance. Generation-3 migration remains #165 successor work.

## Source and scope

- Fixed predecessor: `b662dc73f9c7c5620da605f39e6890a19262c517`.
- Initial implementation: `4c96d10432818dbf5a7146a14e9ee70fe4b69bc2`.
- Missing-health review fix: `e75ce98080cf6458d0057d3591e15b020b0889a3`.
- Isolated CJK evidence fixture: `5dd9bd98ab6455937e51e5a394c6b278bda8fefe`.
- Specification: published #132 v1.0, especially D14/D15; source SHA-256
  `A4D64B033E55DCD5203B6204AA01932501EEBD06AE55BAB45EDF2FCDF48C839E`.
  ADR0038 requires explained health-parent recovery and untouched old bookmarks;
  ADR0039 requires usable keyboard reading at logical size/text-scale limits.

The public `JourneyWorkspaceHost.activate_route(SYSTEM_HEALTH)` now opens the
read-only overlay in the opt-in research shell without replacing the active page
or its observation. A selected exact Run Monitoring context can receive completion
while the overlay is open. Escape closes it and returns focus to the top trigger.
This particular completion test uses deterministic fake events, **not proof of
real background execution continuity**.

When the initial route is legacy health, an available non-health page explicitly
supplied in the typed bookmark can be retained. A bookmark whose only route is
health contains no reliable parent and falls back to Combination Library with an
explanation. No parent is guessed from arbitrary resource IDs or a latest-version
lookup. If Combination Library itself is unavailable, the existing available-route
fallback is explained. Startup opens the overlay only once; hide/show does not
replay a dismissed health entry. A missing health Feature keeps the safe page and
explicitly explains why no overlay was opened; it is not reported as EXACT.

The research host no longer invokes the legacy Journey bookmark sink. This prevents
its translated page/focus state from overwriting Wave 3/4 navigation. The default
six-route host still writes through its original sink. This is an opt-in host
write guard, **not completed generation-3 durable migration**: the new shell's
navigation is currently session-only, and the existing AppContext legacy decoder
and its version-1-to-2 normalization are not changed or certified here.

The health facts TextArea exposes its actual read-only state through QAccessible
and supports keyboard selection/navigation. Tab and Shift+Tab cycle between facts
and Close; Ctrl+End reaches the real end, with the cursor inside the viewport.
No health command, task lifecycle operation or new Feature Interface was added.

## Red/green and visual evidence

Reports live under
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-20260914/`.
Tests use the already agreed public AppContext/Feature, Host and QML-input seams.

| Behavior | Red | Green |
| --- | --- | --- |
| Old health entry must not replace the observed run. | `health-route-red.xml`: 1 failure, active route incorrectly became health. | `health-route-green.xml`: 3 health cases passed. |
| Initial health uses a safe parent or explained Combination fallback. | `health-startup-red.xml`: 2 failures. | `health-startup-green.xml`: 5 health cases passed. |
| Opt-in routing must not write to the legacy bookmark sink. | `health-bookmark-red.xml`: 2 failures, 2 old-entry passes. | `health-bookmark-green.xml`: 4 live/fake × research/legacy cases passed. |
| Read-only keyboard reading must be accessible. | `health-keyboard-red.xml`: 2 missing QAccessible readOnly failures; after fixing that, `health-keyboard-cursor-red.xml`: 2 inert Ctrl+End failures. | `health-keyboard-green.xml`: 2 passed. |
| Missing health must be explained even with a safe parent. | `health-unavailable-review-red.xml`: 2 failures. | `health-unavailable-review-green.xml`: 13 health cases passed. |

Initial source regression `health-routing-full-regression.xml`: 130 passed in
90.98 s (23 shell, 31 resource, 25 Journey Rail, 30 old health, 21 exact-query
contract cases). SHA-256:
`C03ABBF22E4F66D09EA16940CD6642ABBAAF5E6CA5D03251AF1A6899BD3DC6A0`.
The separate initial exact-inspector run passed 39 cases in 15.43 s.
These initial reports precede the missing-health fix and are not the final report.

Final source `5dd9bd9`: `health-routing-reviewed-full-regression.xml`, **171 passed
in 104.19 s**, no failures, errors or warnings. Counts: 25 research shell, 31
resource pages (including reopened sealed live evidence), 25 legacy Journey Rail,
30 legacy health route, 21 exact-query contracts, 39 exact-inspector integration.
SHA-256: `6D0F3DE024859D32EE64C0CF177AF95C2474093E7A33ABE4E1F3D5E018AB76BC`.
The isolated font loading is included, so this result is not dependent on a
different fixture running first to populate the font database.

The first isolated screenshot run produced missing-glyph boxes because no font
was enumerated. Its `health-keyboard-frames/` images and report are retained for
diagnosis, **not accepted as visual or representative font-layout evidence**.
The research fixture now loads the same existing CJK font as the other QML fixtures
when offscreen enumeration is empty. Loading an application font is confined to
the test process; it does not install a font or modify Windows preferences.

`health-keyboard-readable-frames.xml`: 2 passed in 1.90 s; SHA-256
`9FD7D6C02918CB605BB9D84C4BBCB370B9E6D7BEB67EBE2A0A376AAAB5A0AFB1`.
Both images in `health-keyboard-readable-frames/` were inspected: 1426×786/text100%
and 960×480/text200%, DPR1. Chinese is readable; the text end and Close remain
inside the client. This is offscreen Software QML/QAccessible evidence, not native
Windows UIA/Narrator, system text-scale, DPI, Direct3D11 or full visual acceptance.

## Independent review

### Standards

Fixed initial range: `git diff b662dc73f9c7c5620da605f39e6890a19262c517...4c96d10432818dbf5a7146a14e9ee70fe4b69bc2`.
One hard-standard P2: with a safe parent but no health Feature, startup silently
reported EXACT without opening the requested overlay or explaining the missing
capability. This violated ADR0038's explained read-only fallback. It was reproduced
and fixed. Follow-up range
`git diff 4c96d10432818dbf5a7146a14e9ee70fe4b69bc2...5dd9bd98ab6455937e51e5a394c6b278bda8fefe`
was independently rechecked: P2 resolved; no new hard-standard issue or concrete
baseline smell. The reviewer inspected the 13-case local report but did not rerun
tests or certify the whole ticket.

### Spec

One P2, independently identifying the same missing-capability explanation under
D15. The fixed branch retains the safe page/existing recovery reason while
explicitly explaining that health observations are unavailable and no popup
opened. The reviewer confirmed it resolved on the same follow-up range, with no
new scope deviation. This was a read-only review, not an independent test rerun.

Summary by axis: Standards 1 hard-standard P2 resolved, 0 outstanding; Spec 1 P2
resolved, 0 outstanding. Their counts are separate, not two different defects.

## Remaining work

This historical checkpoint did not close #134. Later checkpoints above verify
bounded execution continuity, exact-context health and source-entry behavior.
The authoritative current remainder is in `frontend-v21-issue134-progress.md`:
local empty/error/waiting/usable-state and per-page accessibility/reflow evidence
still need consolidation/completion. Schema3 persistence is #165, not a reverse
blocker. Old `6d33e71` measurements are superseded as current-source observations
by the new `04a57b8` records, but neither set passes formal 750ms acceptance.
