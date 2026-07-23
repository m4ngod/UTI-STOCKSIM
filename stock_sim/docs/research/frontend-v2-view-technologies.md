# Frontend V2 view technologies: decision evidence

Date: 2026-07-24

Decision ticket: #28, “Research the viable Frontend V2 view technologies”

Repository baseline inspected: `67543454623f82c4c9aefa4b0cd0ab3e6f58c424`

## Question and decision boundary

This note compares three viable view-layer families for Frontend V2:

1. PySide6 with Qt Widgets;
2. PySide6 with Qt Quick/QML;
3. an HTML/CSS/JavaScript Web UI shell connected to the Python runtime.

It does **not** select the final technology. The purpose is to expose the constraints, trade-offs, and prototype evidence needed before that choice is made.

The product direction already decided by Wayfinder is a desktop strategy-diagnostics laboratory for researchers: strategy/scenario selection, experiment launch, run monitoring, evidence inspection, and comparison. It will not offer manual discretionary order entry.

## Repository facts that materially constrain the choice

- The installed application stack already declares `PySide6>=6.6.0`, `pyqtgraph>=0.13.3`, NumPy, and pytest; it declares no JavaScript runtime, Web framework, Electron/Tauri, Qt WebEngine, or QML-specific dependency. See [`pyproject.toml`](../../pyproject.toml).
- The current entry point creates a `QApplication`, starts the runtime and event bridge in-process, constructs a `QMainWindow`, and opens registered panels. It also has a dedicated headless path. See [`setup_frontend_entry.py`](../../setup_frontend_entry.py).
- The existing UI is a Qt Widgets implementation. The main window uses `QMainWindow`, `QStackedWidget`, and `QDockWidget`; the UI tree contains 23 Python modules, with `market_adapter.py` alone around 94 KB. See [`app/ui/main_window.py`](../../app/ui/main_window.py), [`app/ui/docking.py`](../../app/ui/docking.py), and [`app/ui/adapters/market_adapter.py`](../../app/ui/adapters/market_adapter.py).
- The current market view uses pyqtgraph and custom `QPainter`/`QPicture` rendering. pyqtgraph describes `PlotWidget` as a `GraphicsView` widget, and its plotting system is implemented on Qt’s Graphics View framework. It explicitly targets fast interactive and real-time scientific graphics. [pyqtgraph introduction](https://pyqtgraph.readthedocs.io/en/latest/getting_started/introduction.html), [PlotWidget API](https://pyqtgraph.readthedocs.io/en/latest/api_reference/widgets/plotwidget.html).
- The runtime already has an in-process `EventBridge` that batches snapshots every 50 ms by default, emits a PySide `Signal(list)`, and also publishes to the local event bus. It can fall back between Redis and the local bus. See [`app/event_bridge.py`](../../app/event_bridge.py).
- GUI tests are mostly pytest tests around Python adapters and Qt widgets, with several conditional skips or stubs when PySide6 is unavailable. No tracked QML, HTML/JS/TS, Electron/Tauri, WebEngine, `pysidedeploy.spec`, or PyInstaller `.spec` files were found at this baseline.
- The repository has useful architectural seams (`AppContext`, `RuntimeGateway`, DTOs, panel adapters, and `EventBridge`), but the current view code still directly imports Qt classes and contains headless replacements. See [`app/app_context.py`](../../app/app_context.py), [`app/runtime_gateway.py`](../../app/runtime_gateway.py), and [`app/event_bridge.py`](../../app/event_bridge.py).

These facts make “view technology” inseparable from two other decisions: whether pyqtgraph remains the production chart engine, and whether the Python runtime stays in the same process as the UI.

## Evidence matrix

The ratings below are project-relative judgments, not generic framework scores.

| Constraint | PySide6 Qt Widgets | Qt Quick/QML | Web UI shell |
|---|---|---|---|
| Python runtime integration | **Direct / lowest new boundary.** Existing `QObject`, signal/slot, DTO, and service calls can remain in process. | **Direct but requires an explicit QML-facing API.** Python objects must expose Qt `Property`, `Signal`, `Slot`, registered QML types, or `QAbstractItemModel` roles. | **Indirect.** Embedded WebEngine can expose `QObject`s through WebChannel; a separate browser/Electron/Tauri shell needs an HTTP/WebSocket/IPC contract and lifecycle management. |
| Existing pyqtgraph reuse | **Native fit.** `PlotWidget` is a QWidget/GraphicsView component. | **Not directly QML-native.** A Widgets shell may host QML screens via `QQuickWidget` while keeping pyqtgraph beside them, but a pure QML screen needs a chart replacement or a proven hybrid boundary. | **No direct reuse in the DOM.** Retaining pyqtgraph requires a separate native surface, rendered-image transport, or keeping a Qt chart window; otherwise charts must be rebuilt in a Web charting stack. |
| High-density/realtime chart risk | **Lowest unknown.** pyqtgraph documents real-time use, large-data preprocessing, downsampling, and clip-to-view. Project code already uses it. | **Medium/high unknown.** Qt Quick has a GPU-backed scene graph, but the required financial chart behavior and throughput are not yet implemented or benchmarked. | **Medium/high unknown.** Browser Canvas/WebGL can be capable, but no chart library, data-volume contract, or benchmark exists in the repository. Serialization and copying become part of the budget. |
| Desktop packaging | **One Python/Qt stack.** Qt’s official `pyside6-deploy` supports PySide applications. | **Same deployment family**, but QML files/imports/plugins must be detected and bundled. | **Embedded WebEngine:** still Qt packaging but adds Chromium/WebEngine process and resources. **Separate shell:** packages Python plus Electron/Tauri/runtime IPC, creating two build/deployment lifecycles. |
| Worker/realtime update path | **Existing path is reusable.** Queued Qt signals can marshal updates to the GUI thread; batching already exists. | **Same Qt worker mechanics**, but data must be converted into QML-facing properties/models and updates must respect the GUI/model owner thread. | **Adds a transport.** WebChannel automatically transmits QObject property/signal changes and batches property updates; a separate shell similarly needs WebSocket/IPC batching, reconnect, versioning, and backpressure behavior. |
| Accessibility | **Strong baseline with standard controls.** Qt ships accessible interfaces for its built-in widgets; custom-painted charts need custom accessible metadata/events. | **Strong baseline with Controls, explicit work for custom items.** Qt Quick Controls have built-in support, while custom QML items need `Accessible` metadata. | **Standards-rich but implementation-dependent.** Semantic HTML/ARIA gives a strong testable model; canvas/WebGL charts need a parallel semantic representation. |
| Visual polish and motion | **Possible but mostly imperative.** Native styles, Qt Style Sheets, custom painting, and animation APIs are available; maintaining a highly bespoke system is code-heavy. | **First-class fit.** Qt describes Quick as declarative and designed for fluid UIs; its scene graph, states, transitions, and animations suit a cohesive custom desktop experience. | **First-class fit.** HTML/CSS/JS and browser rendering provide a large design surface and mature layout/animation primitives; desktop integration remains a separate concern. |
| Automated UI testing | **Incremental fit.** PySide exposes Qt Test helpers (`QTest`, `QSignalSpy`, model tester), and current pytest tests can be retained. Visual regression still needs to be built. | **Dedicated framework exists.** Qt Quick Test provides QML `TestCase`/`SignalSpy` and offscreen execution, but introduces a second test language/harness alongside pytest. | **Strong end-to-end tooling.** Playwright provides role/accessible-name locators, auto-retrying assertions, ARIA snapshots, and screenshot assertions. Python runtime contract tests are still separate. |
| Incremental migration | **Lowest code-motion risk**, provided V2 is a new view/state layer rather than a restyling of existing adapters. | **Moderate.** A Widgets host can migrate screen-by-screen to QML, but `QQuickWidget` has documented rendering costs; a pure Quick shell moves more infrastructure at once. | **Highest initial boundary cost.** It can be migrated screen-by-screen inside `QWebEngineView`, but adds WebChannel plus a Web build/test stack; a separate shell adds process orchestration before the first production screen. |

## Option 1 — PySide6 Qt Widgets

### What the primary sources establish

Qt describes Widgets as its stable, imperative technology for classic desktop interfaces. Standard widgets integrate with layouts, model/view classes, native-like `QStyle`, Qt Style Sheets, Designer, keyboard focus, and desktop windowing. [Qt for Python: Widgets vs. Quick](https://doc.qt.io/qtforpython-6/gettingstarted.html), [Qt Widgets module](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/index.html).

pyqtgraph is already aligned with this stack: `PlotWidget` is a GraphicsView widget, and pyqtgraph states that its core goal is fast interactive data display, including real-time plots. Its `PlotDataItem` supports clip-to-view, automatic/manual downsampling, NumPy arrays, and other performance controls for large data. [pyqtgraph introduction](https://pyqtgraph.readthedocs.io/en/latest/getting_started/introduction.html), [PlotDataItem performance](https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotdataitem.html).

Qt requires widgets and other GUI classes to stay on the main thread. Worker objects can send results through queued signal/slot connections, whose slots execute in the receiver’s thread. This matches the shape of the current batched `EventBridge`, but does not make arbitrary direct widget updates from worker threads safe. [Qt: Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html), [Qt: Synchronizing Threads](https://doc.qt.io/qt-6/threads-synchronizing.html).

Qt provides accessible interfaces for built-in widgets and recommends using standard widgets where possible. Custom UI elements must implement accessible interfaces and send accessibility events. This is especially relevant to the project’s custom-painted charts. [Accessibility for QWidget applications](https://doc.qt.io/qt-6/accessible-qwidget.html).

PySide exposes Qt Test tools for GUI testing and benchmarking, including `QTest`, `QSignalSpy`, and `QAbstractItemModelTester`; Qt recommends pytest for ordinary Python unit tests. [PySide6.QtTest](https://doc.qt.io/qtforpython-6/PySide6/QtTest/index.html).

### Project-specific implications

- Widgets retain the current process model, PySide knowledge, pyqtgraph, and most test infrastructure.
- Reusing current adapters wholesale would also retain the current architectural problems. The low-risk path is therefore **new Widgets views over new immutable view-state and command interfaces**, not “apply a new QSS theme to the old panels.”
- A highly polished diagnostic product is feasible, but the team must build and enforce a component system: spacing/type/color tokens, consistent empty/loading/error states, reusable table and evidence components, focus behavior, and restrained animation. Widgets do not provide that product discipline automatically.
- Custom plots need a separate accessibility design (text summary, keyboard navigation, current selection description, and/or accessible data table), regardless of their visual quality.

### Evidence still needed

1. A V2 evidence timeline with 100k–1m points, multiple overlays, zoom, cursor, and live append.
2. Screenshot and interaction tests at three window sizes and Windows scaling settings.
3. A design-system spike proving that the required polish can be maintained without widespread per-widget QSS and custom painting.

## Option 2 — Qt Quick/QML

### What the primary sources establish

Qt Quick provides a declarative QML UI language, a visual canvas, data models/views, input handling, delayed instantiation, and animation primitives. Qt explicitly positions Quick for fluid interfaces. [PySide6.QtQuick](https://doc.qt.io/qtforpython-6/PySide6/QtQuick/), [Qt for Python: Widgets vs. Quick](https://doc.qt.io/qtforpython-6/gettingstarted.html).

Python can be exposed to QML through registered types and slots; QML-bound Python state must use Qt `Property` with change notification rather than plain Python properties. Qt item models are usable by both Widgets and QML, although QML-specific roles must be declared. [Calling Python methods from QML](https://doc.qt.io/qtforpython-6/examples/example_qml_signals_qmltopy1.html), [PySide6 `Property`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/Property.html), [`QAbstractItemModel`](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractItemModel.html).

Qt Quick’s scene graph targets fluid rendering and can use a threaded render loop, but Qt’s performance guidance still requires asynchronous work, small GUI-thread operations, careful delegate/binding counts, and profiling. [Qt Quick performance guidance](https://doc.qt.io/qt-6/qtquick-performance.html), [Qt Quick scene graph](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html).

`QQuickWidget` permits QML content inside a QWidget application and avoids some stacking restrictions, making screen-level incremental migration possible. Qt also documents two costs: an additional offscreen render pass and disabling the threaded render loop on all platforms. [QQuickWidget performance considerations](https://doc.qt.io/qt-6/qquickwidget.html#performance-considerations).

Qt Quick Controls supply an accessibility baseline. Custom items need `Accessible` name, description, role, actions, and relationships as appropriate. [Accessibility for Qt Quick applications](https://doc.qt.io/qt-6/accessible-qtquick.html).

Qt Quick Test supplies QML `TestCase` and `SignalSpy`; tests can run with the offscreen platform, although the framework normally creates a window. [Qt Quick Test](https://doc.qt.io/qt-6/qtquicktest-index.html).

Qt’s official deploy tool supports QML files and module discovery, but deployment must include QML files/imports/plugins. Its documentation calls out Qt Quick, Qt Quick 3D, Qt WebEngine, and several other modules as size-heavy plugins that deployment tooling tries to exclude when unused. [`pyside6-deploy`](https://doc.qt.io/qtforpython-6.8/deployment/deployment-pyside6-deploy.html).

### Project-specific implications

- QML preserves one Python/Qt application and the current worker/event-loop model, but it creates a deliberate API boundary. This is architecturally useful: each screen would consume `QObject` view models or `QAbstractItemModel`s instead of importing services.
- The existing `EventBridge` signal can remain behind that boundary, but its raw list/dict payloads should not become the public QML contract. QML-facing models need stable roles, batched mutations, lifecycle ownership, and explicit loading/stale/error state.
- pyqtgraph is not QML-native. A hybrid Widgets host can keep the chart in a QWidget region while QML owns other screens, but a pure QML shell cannot assume direct reuse of `PlotWidget`. A chart-engine decision and performance prototype are therefore prerequisites.
- The `QQuickWidget` route is credible for incremental screen experiments, not automatically the target production composition. Its documented render-loop cost matters for a high-frequency, animation-rich laboratory.
- QML adds source types, tooling, deployment inputs, and a second UI test idiom that the repository does not currently have.

### Evidence still needed

1. A QML view-model spike with batched campaign/run updates and a large `QAbstractTableModel`.
2. A chart spike comparing: pyqtgraph kept outside the QML surface, a supported QML chart implementation, and any custom `QQuickItem` approach.
3. Frame-time profiling with the real update cadence, especially if `QQuickWidget` is used.
4. A packaged Windows artifact proving QML import discovery, fonts, styles, GPU fallback, and startup behavior.

## Option 3 — Web UI shell

“Web UI shell” is not one architecture. At least two materially different variants must be distinguished:

- **Embedded Web UI:** keep `QApplication` and host local HTML/JS in `QWebEngineView`; connect it to Python with Qt WebChannel.
- **Separate desktop/browser shell:** run the Python diagnostics runtime as a service or packaged sidecar and use a browser, Electron, or Tauri shell over HTTP/WebSocket/IPC.

### What the primary sources establish

`QWebEngineView` is itself a QWidget and embeds Chromium-rendered Web content. Qt WebChannel bridges Python/QML `QObject`s to HTML/JavaScript clients; properties, public slots/methods, and signals can be transmitted automatically. QWebChannel batches property updates on a configurable interval, 50 ms by default. [QWebEngineView](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineWidgets/QWebEngineView.html), [PySide6.QtWebChannel](https://doc.qt.io/qtforpython-6/PySide6/QtWebChannel/index.html), [QWebChannel update behavior](https://doc.qt.io/qt-6/qwebchannel.html#propertyUpdateInterval-prop).

Embedded WebEngine is not a zero-cost styling layer. Qt WebEngine uses Chromium and a separate WebEngine process; deployed applications must include its libraries, process executable, resources, translations, and relevant imports/plugins. [Qt WebEngine overview](https://doc.qt.io/qt-6/qtwebengine-overview.html), [Deploying Qt WebEngine applications](https://doc.qt.io/qt-6/qtwebengine-deploying.html).

Electron also embeds Chromium and Node.js. Its official architecture has separate main and renderer processes, a preload/IPC boundary, and a Web bundler toolchain; distribution packages Electron binaries and application resources. [Electron process model](https://www.electronjs.org/docs/latest/tutorial/process-model), [Electron packaging](https://www.electronjs.org/docs/latest/tutorial/application-distribution).

Tauri can bundle an external binary such as a Python CLI or API server as a sidecar. That demonstrates a viable separate-shell route, but it also makes the sidecar protocol, target-specific binary naming, startup, shutdown, failure reporting, and update compatibility part of the product. [Tauri external binaries](https://v2.tauri.app/develop/sidecar/).

Web accessibility has standardized semantics through HTML and WAI-ARIA, especially for dynamic content and advanced controls. This does not make a Web UI automatically accessible; custom controls and canvas/WebGL visualizations must expose equivalent semantics and keyboard interaction. [WAI-ARIA overview](https://www.w3.org/WAI/standards-guidelines/aria/), [WAI-ARIA 1.2](https://www.w3.org/TR/wai-aria/).

Playwright supports accessible-role/name assertions, auto-retrying asynchronous assertions, ARIA snapshots, and screenshot comparison. This is the strongest out-of-the-box visual and semantic regression story among the three families evaluated, although it does not test the Python runtime by itself. [Playwright assertions](https://playwright.dev/docs/test-assertions), [screenshot assertions](https://playwright.dev/docs/api/class-pageassertions#page-assertions-to-have-screenshot-1).

### Project-specific implications

- A Web UI offers the broadest layout, typography, responsive-design, animation, and automated browser-testing surface.
- It creates a serialization boundary that does not currently exist. The current DTO/event bridge can inform that boundary, but raw event-bus topics and arbitrary Python objects should not be exposed directly.
- For an embedded shell, WebChannel is the shortest bridge, but the team must define batching, snapshot size, command/error envelopes, schema versions, reconnect/reload behavior, and whether a renderer crash can recover without restarting the simulation.
- For a separate shell, the same contract must additionally handle process discovery, authentication/origin policy even on localhost, port selection, startup readiness, shutdown, logging, and version skew.
- pyqtgraph cannot simply move into HTML. The Web option therefore carries a chart rewrite or a deliberately split native/Web UI, plus objective performance and fidelity validation.
- The repository would gain a second language ecosystem, dependency lockfile, build pipeline, lint/type/test stack, and possibly a second desktop packager. This is a strategic investment, not a screen-library swap.

### Evidence still needed

1. A realistic Web chart spike using the intended library, with the same large datasets, overlays, cursor/selection, append rate, and export requirements as the native spike.
2. A WebChannel or WebSocket contract spike measuring serialization size, update latency, main-thread utilization, and backpressure during bursty runs.
3. A packaged Windows proof for the chosen embedded/separate shell, including offline startup and clean runtime shutdown.
4. Recovery tests for renderer reload/crash, Python runtime crash, transport disconnect, and schema mismatch.

## Cross-option findings

### 1. The chart decision is the strongest discriminator

If production must retain pyqtgraph, Qt Widgets has a direct integration advantage. Qt Quick remains viable through a hybrid boundary, but a pure-QML screen needs a different chart plan. A Web UI implies a chart rewrite or an awkward split surface. This follows from pyqtgraph’s documented QWidget/GraphicsView architecture, not from a benchmark; visual fidelity and throughput still require the same controlled prototype across all candidates.

### 2. All three options need a new view contract

Changing toolkit without fixing data ownership would reproduce the current coupling in a new syntax. The reusable target should be technology-neutral:

```text
runtime/events
    -> feature presenter / view-model
    -> immutable screen state + bounded streams
    -> view

view command
    -> typed command port
    -> application service
    -> explicit accepted/rejected/progress result
```

Widgets can consume Python dataclasses/models directly; QML needs Qt properties/models; Web needs serialized schemas. Defining this contract before the toolkit decision reduces lock-in and makes the candidate prototypes comparable.

### 3. “Realtime” must mean bounded visual updates, not event-for-event rendering

Qt’s own guidance says GUI work must remain on the main thread and expensive work should be asynchronous. The current bridge already batches snapshots at 50 ms. QWebChannel also defaults to a 50 ms property-update batch. These independent signals support a prototype requirement: define a maximum visual refresh rate, coalesce state, and preserve full-fidelity evidence outside the paint path rather than trying to render every backend event. [Qt threading](https://doc.qt.io/qt-6/threads-qobject.html), [QWebChannel update interval](https://doc.qt.io/qt-6/qwebchannel.html#propertyUpdateInterval-prop).

### 4. Accessibility risk concentrates in custom charts, not standard controls

Qt Widgets and Qt Quick Controls both provide platform accessibility integration; Web has HTML/ARIA semantics. In every option, a dense custom chart needs nonvisual semantics. The decision package should therefore require a selected-point description, keyboard traversal, textual summary, and accessible tabular alternative as acceptance criteria, not treat toolkit choice as sufficient.

### 5. Packaging is currently an unmeasured risk

The repository has a console entry point but no tracked desktop deployment specification at the inspected baseline. Widgets and QML can share the official PySide deployment family; QML adds import/plugin inputs. Embedded WebEngine adds Chromium processes and resources; a separate Web shell adds another package and process lifecycle. No candidate should be accepted without producing and smoke-testing an offline Windows artifact.

## Prototype protocol for a fair decision

Build the same read-only diagnostic slice in each still-viable candidate:

- campaign/run header and status;
- a 50-row comparison table with sorting, filtering, selection, and keyboard navigation;
- an evidence timeline with the agreed worst-case point count and overlays;
- live batched updates at the current 50 ms source cadence, with an explicit capped paint rate;
- loading, empty, stale, disconnected, partial-result, failed, and completed states;
- no manual order-entry controls;
- one details drawer and one restrained transition;
- deterministic fake adapter plus a real runtime adapter.

Measure rather than judge by demo impressions:

| Measure | Required observation |
|---|---|
| Startup | cold and warm time to usable shell |
| Update path | p50/p95 event-to-visible latency, dropped/coalesced visual updates |
| Responsiveness | UI main-thread stalls and input latency during burst load |
| Chart | frame time while append/zoom/pan/cursor are active at target density |
| Memory | idle and peak working set during the same run |
| Packaging | artifact size, clean-machine/offline launch, missing-resource failures |
| Accessibility | complete keyboard path, screen-reader names/roles, nonvisual chart equivalent |
| Testing | deterministic component test, end-to-end path, visual-regression result |
| Migration | changed production modules and new toolchains needed for one vertical slice |
| Maintainability | size and stability of the Python-to-view public interface |

Use native profiling/test tools where available: QML Profiler for Quick, Qt Test/pytest for native UI behavior, and Playwright for Web semantics and screenshots. Do not compare a polished Web mockup against an unstyled native spike; apply the same design tokens, content, states, and interaction specification.

## Decision gates, without selecting a winner

- **Keep Qt Widgets in contention** if it can meet the visual-system prototype without returning to monolithic adapters or pervasive one-off painting.
- **Keep Qt Quick/QML in contention** if a chart strategy meets the density target and the Python/QML model boundary stays small, typed, and testable; separately measure any `QQuickWidget` hybrid cost.
- **Keep the Web shell in contention** if the product values browser portability or Web delivery enough to justify a chart rewrite and new IPC/build lifecycle, and if the packaged prototype meets latency, recovery, and offline requirements.
- **Do not choose a hybrid by default.** A hybrid is justified only when its boundary is explicit and temporary or when it permanently isolates a uniquely suitable component such as pyqtgraph. Otherwise it can accumulate both ecosystems’ costs.

The final decision therefore depends on evidence not yet available: target chart density and interactions, whether browser delivery is a real product requirement, packaging constraints, and measured prototype results. The primary-source evidence narrows the risks but does not determine the product trade-off.

## Limitations

- No candidate prototype, runtime benchmark, screen-reader pass, or packaged executable was created as part of this research task.
- “Web UI shell” covers multiple architectures; embedded Qt WebEngine and separate Electron/Tauri/browser shells have different operational costs and must not be scored as one implementation after a direction is chosen.
- The worktree baseline did not contain the requested root `AGENTS.md` or `stock_sim/CONTEXT.md`. The domain glossary was recovered read-only from repository history at commit `a844b4e`; current repository files and the Wayfinder decisions supplied with the task were used for the remaining constraints.
- pyqtgraph’s current documentation was used for architectural and performance capabilities; the project’s declared minimum is 0.13.3, so every intended optimization/API must be verified against the actually locked deployment version.
- Claims about relative migration cost are reasoned from the inspected repository and official framework architecture. They are decision evidence, not measured engineering estimates.
