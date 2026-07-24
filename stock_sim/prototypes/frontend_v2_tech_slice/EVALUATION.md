# Frontend V2 view-technology decision evidence

> THROWAWAY PROTOTYPE — GitHub issue #33. This is decision evidence, not
> production UI and not an authorization to replace the current frontend.

## Decision

Use **Qt Quick/QML as the primary Frontend V2 view technology**.

- Keep the current Qt Widgets application as the migration host, legacy route,
  and rollback boundary while screens move one at a time.
- Put technology-neutral, immutable, revisioned ViewState objects between
  runtime services and every new view.
- Use a QML-native scene-graph chart in production. The prototype's
  `QQuickPaintedItem` proves the state, sampling, interaction, and accessibility
  contract; it is not the final chart renderer.
- Keep embedded Web UI as a future delivery option, not the current Windows
  desktop V2 implementation.
- Do not use the current pyqtgraph path until its PySide6/Qt compatibility is
  resolved and locked.
- Do not add manual ordering. Market, account, position, order, and fill data
  remain read-only diagnostic context.

Human verdict: **accepted** in the active Wayfinder task on 2026-07-24.

## Same-spec slice

All candidates rendered the same:

- 50-row sortable/filterable candidate comparison;
- 100,000 source-point timeline, 4,000 display points, and three overlays;
- deterministic 50 ms source cadence and 20 fps paint cap;
- loading, empty, stale, disconnected, partial, failed, and completed states;
- `Ctrl+K`, arrow navigation, Enter details, and Escape close;
- text and table equivalents for the chart;
- deterministic fake and production `EventBridge` adapters;
- 1280 × 800 window, shared tokens/content, and the same read-only boundary.

## Final 3-second measurements

Numbers are directional local measurements, not release SLO certification.
Lower is better for latency, stalls, and memory.

### Deterministic fake adapter

| Technology | Usable ms | Event→visible p95 ms | Input p95 ms | >50 ms stalls | Peak MB | Runtime warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qt Widgets + QPainter | 132.831 | 79.393 | 12.497 | 2 | 77.559 | 0 |
| Qt Quick/QML | 184.974 | **7.466** | **0.803** | **0** | 102.355 | 0 |
| Embedded WebEngine | 474.387 | 27.837 | 11.881 | **0** | 163.188 | 2 |

### Production EventBridge adapter

| Technology | Usable ms | Event→visible p95 ms | Input p95 ms | >50 ms stalls | Peak MB | Runtime warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qt Widgets + QPainter | 556.636 | 78.310 | 12.448 | 4 | **115.457** | 0 |
| Qt Quick/QML | 588.895 | **11.850** | **0.426** | **0** | 140.121 | 0 |
| Embedded WebEngine | 898.717 | 28.766 | 8.137 | **0** | 196.824 | recurring |

Interpretation:

- Widgets wins on memory and slightly on initial source startup, but its
  event-to-visible tail is roughly 6.6× QML under the real adapter and it is
  the only candidate with repeated main-thread stalls.
- QML has the best update and input latency without WebEngine's process,
  renderer, and distribution overhead.
- Web is viable and visually polished, but uses about 1.4× QML peak memory and
  1.7× Widgets peak memory under the real adapter. Offscreen runs repeatedly
  reported GLES/shared-image failures even though the UI recovered and exited
  successfully.

Raw JSON and screenshots live in `artifacts/final-fake/` and
`artifacts/final-runtime/`.

## Packaging evidence

Every final candidate was rebuilt from the current prototype source with
Nuitka 2.6.8 and then launched as a standalone executable.

| Technology | Standalone result | Dist files | Dist size | 1 s smoke wall ms | Internal usable ms |
| --- | --- | ---: | ---: | ---: | ---: |
| Qt Widgets | pass | 78 | 114.33 MiB | 2,612 | 552.497 |
| Qt Quick/QML | pass | 223 | 143.32 MiB | 2,908 | 614.103 |
| Embedded WebEngine | pass | 106 | 345.92 MiB | 3,124 | 843.736 |

Packaging constraints discovered by running the executables:

1. Parallel MinGW compilation failed while writing the generated PySide6
   object. `--jobs=1` is required in the current environment.
2. The PySide deployment chain did not discover
   `numpy._core._exceptions`; the module must be explicitly collected for
   NumPy 2.3.1.
3. Nuitka's umbrella `--include-qt-plugins=qml` scan exceeded the prototype's
   10-minute limit. The working QML package uses a checked minimum manifest:
   QtQml, QtQuick, Controls Basic/impl, Layouts, Templates, Window, and their
   imported Qt runtime DLLs.
4. WebEngine automatically adds its helper process, ICU/V8 data, PAK
   resources, and `qt6.conf`, which explains most of its package-size premium.

The QML minimum manifest is prototype evidence. A production build must replace
it with an automated import scan and a clean-Windows packaging test.

## States, keyboard, accessibility, and recovery

- The final seven-state matrix completed with 3/3 technologies and zero
  process failures for every state.
- The full keyboard path passed 3/3 for stale, disconnected, partial, failed,
  and completed. Candidate navigation/details are not applicable to loading and
  empty because those states intentionally contain no rows.
- Every timeline exposes a concise textual summary and a 12-row sampled table
  equivalent. Canvas/painted pixels are not the only source of evidence.
- All three production-adapter recovery probes passed:
  disconnected became visible, reconnect advanced revision, and completed
  became visible again. Web also survived a renderer reload.
- Recovery exposed two cross-technology requirements:
  quarantine an in-flight batch after adapter stop, and reject a ViewState whose
  revision is lower than the latest accepted revision.

## Chart finding

The installed PySide6 6.9.1 / Qt 6.9.1 combination failed the compatibility
probe with pyqtgraph 0.13.7:

- the curve had no expected graphics parent;
- expected X range was `0..99975`, observed roughly `-2088..46439`;
- expected Y range was `94.21..111.14`, observed roughly `0.788..0.790`.

Widgets therefore receives credit only for the shared QPainter fallback, not
for a working pyqtgraph integration.

For production QML:

- retain 100,000-point source fidelity outside the renderer;
- send a deterministic viewport sample to the view;
- render through a dedicated `QQuickItem`/scene-graph node;
- keep overlay data and text/table equivalents in the shared ViewState;
- certify the hardware renderer and software fallback separately.

## Emil design-engineering review

| Before | After | Why |
| --- | --- | --- |
| Three technologies could drift into different layouts and copy | Shared tokens, content, density, status language, and a floating evidence switcher | Makes the technology comparison visual rather than conceptual |
| Web used a fixed viewport calculation and produced outer-page scrolling | 100vh grid with only the candidate table scrolling; narrow screens regain natural page scrolling | Prevents clipped controls and keeps the diagnostic workspace stable |
| Candidate details risked generic modal motion | Side/drawer motion uses transform + opacity, ease-out, keyboard actions unanimated, and reduced-motion support | Preserves spatial continuity without decorative motion |
| Charts were visually complete but could become inaccessible | Every chart has a compact narrative and a sampled data table | Evidence remains available without interpreting pixels |
| Late runtime batches could overwrite a newer failure state | Adapter generation quarantine plus monotonic revision guards in all views | Makes failure and recovery honest instead of timing-dependent |

Static checks found no `transition: all`, `scale(0)`, or disallowed ease-in
motion. Hover feedback is pointer-capability gated.

## Required migration constraints

1. Define one versioned Feature Interface/ViewState contract before migrating
   screens. Views do not import mutable domain services directly.
2. Migrate at screen/route granularity. Do not scatter many QML islands through
   legacy Widgets.
3. Start with Run Monitoring + Evidence & Findings because it exercises cadence,
   comparison, failure states, charts, keyboard navigation, and read-only
   safety in one slice.
4. Keep the old route available as a rollback path; never dual-write from old
   and new views.
5. Treat the QML package manifest, renderer fallback, and clean-Windows launch
   as release artifacts.
6. Preserve the no-manual-order boundary in navigation, commands, shortcuts,
   service interfaces, and telemetry.
7. Do not delete a legacy screen until its V2 replacement passes the same
   seven states, keyboard/accessibility checks, revision recovery probe, real
   adapter cadence, packaging test, and stakeholder acceptance.

## What issue #34 still must decide

Issue #33 selects the technology combination. Issue #34 must stress the chosen
composition as one migration slice and turn these directional observations into
release gates, migration waves, and explicit old-frontend deletion conditions.
