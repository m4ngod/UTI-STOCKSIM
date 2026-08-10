# Issue #117 retained Widgets adapter lifecycle evidence

This supplemental record is bound to implementation commit
`ce94f61c46600596bca7c04fedeaa5da7a2e4a18`, based on merged #117 follow-up
baseline `1827763971a342fd3e9e94cd6cddd61a94535267`.

It closes the remaining source-seam process-order gaps discovered when issue
#118 reran the complete source gate. It does not claim any #118 installed
Windows, offline, hardware/software renderer, performance certification,
remote artifact, or release gate.

## Root cause and correction

Market, Agents, and Orders selected fake or real Qt classes when their modules
were imported. A prior headless test could therefore permanently bind fake
`QWidget` types before the retained Widgets rollback stage created a real
`QApplication`.

Each affected adapter now resolves a consistent type bundle when its widget
tree is created. Market applies the same bundle to its root, symbol detail,
order-book, dialog, and dynamically constructed chart widget. Agents applies
one bundle to its root, controls, table items, status styling, insights
container, and batch dialog. Orders applies one bundle to its root, filter
controls, table, and table items. Headless behavior remains available when no
Qt application exists.

Clock, Leaderboard, Arena, and Diagnostics were audited and do not use the
same fake-class-at-import plus real-lifecycle-at-creation mismatch.

## Red-to-green evidence

- Market minimal reproduction: `1 failed in 1.85s` with the module fake
  `QWidget`; fixed test `1 passed in 1.33s`, asserting the root, symbol detail,
  and chart are real PySide6 widgets after a headless import.
- The first complete source gate after the Market repair passed its first five
  groups, then failed at Agents after `151 passed` in the sixth group.
- The combined Agents/Orders lifecycle test first failed at Agents, then
  advanced to an Orders `_HeadlessRoot` failure after the Agents fix, and
  finally passed in `1.03s` after both fixes.

## Focused and rollback evidence

- `19 passed in 4.20s`: complete Market adapter focus, including chart,
  snapshot bridge, create dialog, detail navigation, and no-trade-button
  behavior.
- `49 passed in 27.32s`: Agents/Orders adapter, creation, wiring, dedup, and
  no-manual-trading runtime/release safety focus.
- `5 passed in 118.50s`: Account, Market, Agents, and Orders were imported and
  exercised headlessly before the candidate to retained Widgets to candidate
  rollback drill.
- `2 passed in 115.78s`: complete Wave 4 fresh initialization and copied Wave
  3 migration/rollback file, including deterministic/idempotent migration,
  exact durable identity recovery, and clean exits.
- Python compilation and `git diff --check` passed.

## Complete source gate

The unmodified
`stock_sim.release.strategy_diagnostics_v1_frontend_v2_gate` completed in
1488.2 seconds with every runner group at exit 0:

- six-feature-conformance: `310 passed, 17 deselected`
- persisted-application-qml-tracer: `64 passed`
- strategy-diagnostics-v1-regression: `389 passed, 1 deselected`
- strategy-diagnostics-v1-lazy-import-isolation: `1 passed`
- frontend-v2-contract: `228 passed, 30 deselected`
- frontend-v2-integration-e2e-accessibility: `153 passed, 5 deselected`
- frontend-v2-unit: `299 passed, 1 skipped`
- frontend-v2-event-bridge: `6 passed`
- frontend-v2-safety: `29 passed, 1 deselected`
- frontend-v2-performance-packaging-contract: `212 passed, 3 deselected`

## Scope and release boundary

No persistence schema, bookmark, ledger qualification/reset rule, release
manifest, artifact checksum, System Health remediation, trading capability,
WebEngine capability, route inventory, route, panel, or Widgets shell was
deleted or changed. `legacy_route_count` remains 8 and no legacy deletion is
authorized.

This source-gate evidence must not be treated as #118 installed-Windows,
offline, renderer, performance, remote artifact, or formal release evidence.
Issue #118 must restart its own work from a master revision containing this
fix and execute those gates independently.
