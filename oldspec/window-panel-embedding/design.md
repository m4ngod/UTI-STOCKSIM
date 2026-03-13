# Design Document

## Overview
Introduce visible embedding of preloaded panels into MainWindow. Provide a central QWidget with QVBoxLayout in GUI mode. Each panel may expose either widget() -> QWidget or mount(parent_layout) to supply visible content. If absent, a fallback QLabel placeholder is inserted. Headless mode remains unaffected.

## Steering Document Alignment
### Technical Standards (tech.md)
- Single Responsibility: MainWindow only manages container + embedding; panels manage their own UI.
- Thread Safety: GUI operations limited to main thread; headless path avoids Qt calls.
- Metrics: Non-intrusive optional counters.
### Project Structure (structure.md)
- Place new helper in app/ui or app/panels/shared if needed; minimal changes to app/main.py.
- No cross-layer leakage (services/controllers untouched).

## Code Reuse Analysis
Reuse existing panel registry: get_panel(name), list_panels(). Do not alter panel registration API. Placeholder panels reused; we augment their visibility via fallback widget creation.
### Existing Components to Leverage
- panels.__init__ / registry: source of panel factories.
- run_frontend preload list.
### Integration Points
- main.run_frontend: after instantiating MainWindow before show().
- Panel objects: optional widget()/mount() reflection.

## Architecture
Add central widget creation inside MainWindow.__init__ when QApplication available. Embedding pipeline:
open_panel(name) -> get_panel -> if GUI mode: _mount_panel(name, instance)
_mount_panel checks existing mapping, resolves widget, or creates fallback QLabel.
### Modular Design Principles
- Separate mounting logic into private helper methods.
- No new global state; MainWindow holds per-instance maps.
```mermaid
graph TD
  R[Registry] -->|get_panel| P[PanelInstance]
  P -->|widget()/mount()| M[Mount Helper]
  M --> L[QVBoxLayout]
  Main[MainWindow] --> M
```

## Components and Interfaces
### MainWindow (updated)
Purpose: Container + layout + panel mounting.
Interfaces:
- open_panel(name)
- list_available()
Internal additions:
- _ensure_central_layout()
- _mount_panel(name, inst)
Dependencies: QtWidgets (GUI mode), registry API.
Reuses: existing preload logic.
### HeadlessMainWindow (unchanged)
Purpose: Non-GUI placeholder with identical public API but no Qt.
### Panel Contract (convention, not base class)
- Optional def widget(self) -> QWidget
- Optional def mount(self, parent_layout: QLayout) -> QWidget|None
Fallback: QLabel(f"{name} panel (placeholder)").

## Data Models
No new persistent models. Runtime structures:
- self._panel_widgets: Dict[str, QWidget]

## Error Handling
### Error Scenarios
1. Panel factory raises exception.
   - Handling: catch, metrics.inc('panel_mount_failure'), skip.
   - User Impact: Panel absent; others load.
2. mount() throws.
   - Handling: log (optional), fallback placeholder.
   - Impact: Placeholder shows panel name.

## Testing Strategy
### Unit Testing
- Test _ensure_central_layout idempotency.
- Test open_panel widget detection (mock panel with widget()).
- Test fallback creation when no widget/mount.
### Integration Testing
- GUI skipped in CI if PySide6 unavailable; simulate by monkeypatching QApplication and dummy QWidget.
- Headless path regression: existing tests unaffected.
### End-to-End Testing
- Start GUI in headless-friendly environment (if possible) or simulate by forcing headless=False with dummy Qt stubs; assert open_panel populates mapping.

