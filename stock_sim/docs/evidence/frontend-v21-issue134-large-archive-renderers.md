# Frontend V2.1 #134 — large Archive renderer and resource observations

Date: 2026-09-15 (Asia/Shanghai). Source: `c9679be1b9a6a7b43aacd117ddf610d32b9f6961`.
This records the explicit #134 large-data measurement clause; it is not a whole
ticket, installed-launch, memory-budget or performance-percentile PASS.
No production code or tests changed.

## Source and measurement scope

Both processes use public live AppContext composition and the production
MainWindow, with a requested and measured 960x480 client, text200%, DPR1 and
reduced motion. The existing `_persist_real_formal_v1_through_application` fixture
executes synthetic local cases, seals file-backed evidence, disposes its first
engine and reopens the application/database/artifacts. It supplies the exact
Campaign/Run/package/manifest through the existing supported selection inputs.
The Archive projects 1,055 original records, comparisons and findings. Its status
remains `fresh · degraded · partial`; reading does not create new statistics.

`observe_large_archive.py` observes delivered Qt input events, synchronizes the
displayed state at `beforeSynchronizing`, and timestamps `afterRendering`. It
does not inject input or replace QML. All desktop actions and native UIA captures
use official Computer Use `sky`. The four latency samples below require a frame
with the actual expected result, such as current index 1 or the selected final
finding. They exclude the external screenshot/UIA tool's execution time.

The endpoint is Qt rendering, not an OS compositor presentation timestamp. Each
action has one retained sample per renderer. Mouse-drag duration is not reported
as rendering latency because the gesture itself spans multiple input updates.
Process memory, CPU, handles and threads are read for the recorded task PID before
interaction and after the last finding. These include the fixture preparation,
Qt/native accessibility activity and allocator caches; GPU memory is not sampled.

## Observed values

| Measurement | Software | Direct3D11 |
| --- | ---: | ---: |
| First visible frame from AppContext composition start | 943.00 ms | 573.34 ms |
| Loaded 1,055-object Archive state from composition start | 2,573.88 ms | 1,937.29 ms |
| Open drawer: delivered click to matching rendered state | 37.86 ms | 30.20 ms |
| Down to second row: delivered key to matching rendered state | 7.54 ms | 6.26 ms |
| Open second record: delivered Return to matching rendered state | 13.79 ms | 11.09 ms |
| Open last finding: delivered click to matching rendered state | 33.43 ms | 34.76 ms |
| Maximum instantiated row delegates observed | 11 | 11 |
| Working set, initial / final | 283.61 / 372.85 MiB | 338.98 / 433.34 MiB |
| Private bytes, initial / final | 955.61 / 1,044.47 MiB | 1,049.66 / 1,146.25 MiB |

The first frame is not the loaded-resource endpoint. The loaded state occurs with
the drawer closed; actual row rendering is separately measured when it opens.
Composition timing starts after real fixture preparation and QApplication creation;
it is not cold-start or installed 750 ms evidence. QML disk cache is disabled and
OS cache state is uncontrolled. These separate fixture executions generate
different IDs and wrapping, so the table is a paired source profile, not a
controlled claim that one renderer is faster. The memory increase is recorded
without a leak or stability verdict; two samples cannot establish either.

## Native navigation and identity checks

In each session, the initial named list reports 1,055 items. Down visibly focuses
row 2; Return closes the drawer and opens the exact `execution erosion` record,
original value `0 currency`. Ctrl+End reaches the long source/limitation ending.
Shift+Tab returns to the list trigger and Space reopens the drawer. Native wheel
scrolling and dragging the observed scrollbar thumb reach row 1,055. Clicking
that final finding opens its original identity at the start of details.

| Exact reference | Software | Direct3D11 |
| --- | --- | --- |
| Second record | `diagnostic-metric-91232173240009688f1af80b` | `diagnostic-metric-2a9b7a5775f4c30d0a6fdebd` |
| Final finding | `diagnostic-finding-7d233e2fbaa8279d5de2148c` | `diagnostic-finding-4f954eaee8ecd22287f18fa4` |
| Evidence package | `diagnostic-evidence-38285892d4a29266defac0d7` | `diagnostic-evidence-997ab6875f544895ec97c053` |
| Reproduction manifest | `reproduction-manifest-153b95bbf49178c9a0527fb7` | `reproduction-manifest-018c96306fb4ee2907915dba` |

The second record belongs to `quentx-5.2.3-scenario-native.v1`; the last finding
belongs to `quentx-live-minute-scenario-native.v1`. The original record's source
Run and the selected journey Run are both preserved; a package can contain
evidence from multiple Runs. No cross-session identity equality is claimed.

Both final UIA documents equal the corresponding rendered TextArea text after
normalizing UIA paragraph separators. The final list position/total is present in
settled native UIA. The immediate Direct3D11 drag capture had a stale tree; its
subsequent settled capture is used for the final-index assertion. Both sessions
closed normally with exit0, stopped the bridge and closed AppContext. The final
official window inventory contained no StockSim window.

## Reproducible artifacts

Artifact root:
`F:/PythonProjects/.scratch/frontend-v21-goal/issue134-native-20260915/`.
Session directories are `large-archive-960x480-text200-software-01` and
`large-archive-960x480-text200-d3d11-01`. Each contains delivered-input/rendered-state
JSONL, native UIA JSONL, process resource JSONL, the reopened SQLite database and
sealed files. Screenshots are `second-record.png`, `list-end.png` and
`last-finding.png`.

`audit_large_archive.py` verifies source/renderer/geometry, expected input-state
endpoints, the original package/manifest in both selected details, native final
position, text equality and resource PID identity. Archive keys are opaque tuple
strings, not Scenario-style JSON keys; the audit retains their exact representation.
The separate `large-archive-artifact-manifest.json` hashes 135 files, including
the sealed inputs. No older manifest is overwritten.

- Launcher SHA-256: `21E7F8DB551FCFB6DD03512F2F5877CCA12A99792E962127A1C4BD7F546E7E39`.
- Audit JSON SHA-256: `8FD19AA6AB5D2D34D63711A670BA3E8F05D4816C328A1F1D6AED5F34D8914B61`.

Native readonly/focus-property evidence remains unresolved. Visible keyboard
behavior, native names/roles/values/positions and supplemental Qt focus do not
stand in for those missing properties. The preceding 112-case affected regression
is unchanged; it was not rerun for this evidence-only increment.
