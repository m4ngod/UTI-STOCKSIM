# Frontend V2 view-technology vertical slice

> THROWAWAY PROTOTYPE — evidence for GitHub issue #33, not production UI.

Question: which view technology and chart combination can satisfy the same Strategy Diagnostics vertical slice under this repository's actual runtime, density, accessibility, recovery, testing, and Windows packaging constraints?

The three implementations intentionally share:

- one immutable read model and the same 50 candidate rows;
- one 100,000-point timeline artifact with candidate, baseline, and stress overlays;
- one 50 ms source cadence and a 20 fps visual paint cap;
- loading, empty, stale, disconnected, partial, failed, and completed states;
- filter, sort, selection, details, and keyboard paths;
- a textual and tabular chart equivalent;
- deterministic fake and production `EventBridge` adapters;
- the same visual tokens, content, window size, and read-only safety boundary.

The candidates are:

- `widgets` — Qt Widgets model/view plus a shared QPainter fallback. The included
  `pyqtgraph_compatibility_probe.py` records why pyqtgraph is not credited as
  passing under the current PySide6/Qt environment.
- `qml` — standalone Qt Quick/QML plus a prototype `QQuickPaintedItem` timeline.
- `web` — embedded `QWebEngineView` plus semantic HTML and Canvas, bridged with `QWebChannel`.

Decision: use **Qt Quick/QML for Frontend V2**, keep Qt Widgets as the
migration/rollback host, and do not use embedded WebEngine as the current
desktop V2 primary technology. See [`EVALUATION.md`](EVALUATION.md) for the
measurements, packaging findings, recovery constraints, and accepted verdict.

## One command

Run one interactive candidate from the repository root:

```powershell
python prototypes/frontend_v2_tech_slice/run.py --technology widgets --adapter fake
```

Switch with the floating arrows or use:

```powershell
python prototypes/frontend_v2_tech_slice/run.py --technology qml --adapter fake
python prototypes/frontend_v2_tech_slice/run.py --technology web --adapter fake
```

Capture the same benchmark and screenshot for all candidates:

```powershell
python prototypes/frontend_v2_tech_slice/run.py --technology all --adapter fake --state completed --benchmark-ms 3000
python prototypes/frontend_v2_tech_slice/run.py --technology all --adapter runtime --state completed --benchmark-ms 3000
```

Artifacts are written under `prototypes/frontend_v2_tech_slice/artifacts/` and are prototype evidence only.

Exercise the production EventBridge disconnect/reconnect path:

```powershell
python prototypes/frontend_v2_tech_slice/recovery_probe.py widgets --output artifacts/widgets-recovery.json
python prototypes/frontend_v2_tech_slice/recovery_probe.py qml --output artifacts/qml-recovery.json
python prototypes/frontend_v2_tech_slice/recovery_probe.py web --output artifacts/web-recovery.json
```

Build a standalone candidate from PowerShell 7:

```powershell
pwsh -NoLogo -NoProfile -File prototypes/frontend_v2_tech_slice/package_candidate.ps1 -Technology qml
```

The packaging script is intentionally explicit about the current NumPy and
minimum-QML-module constraints discovered by executable smoke tests.

## Keyboard path

`Ctrl+K` focuses the filter. Use Tab to reach the comparison table, Up/Down to move, Enter to open evidence details, and Escape to close. Left/Right switches technology when text input does not own the key.

## Boundary

There is no manual-order capability, experiment mutation, gate override, checkpoint promotion, or backend-domain rewrite. The state buttons only replace the deterministic prototype ViewState.
