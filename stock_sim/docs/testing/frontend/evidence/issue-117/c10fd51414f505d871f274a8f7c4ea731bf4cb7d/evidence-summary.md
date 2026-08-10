# Issue #117 retained Widgets order-independence evidence

This supplemental record is bound to implementation commit
`c10fd51414f505d871f274a8f7c4ea731bf4cb7d`, based on merged baseline
`c4aca230a843bc41891f0e64882501b2f413a41e`.

It closes a source-seam gap discovered while preparing issue #118. It does
not claim any #118 installed-Windows, offline, hardware-renderer,
software-renderer, performance, or release gate.

## Root cause and correction

`AccountPanelAdapter` previously selected its Qt or headless widget classes at
module import time. A headless test that imported the module before a
`QApplication` permanently cached `_HeadlessAccountWidget`. The later retained
Widgets rollback stage then handed that object to a real `QStackedWidget`,
which rejected it.

The adapter now resolves the current Qt lifecycle when `_create_widget()` is
called. Dedicated headless classes remain available for headless use, while an
adapter created after `QApplication` exists lazily loads and consistently uses
the real Qt widget, table-item, layout, label, combo-box, and timer types.

## Red-to-green evidence

- Baseline minimal regression: `1 failed in 6.45s`; the subprocess imported
  `account_adapter`, then created `QApplication`, but received
  `_HeadlessAccountWidget`.
- Baseline original polluted order: `1 failed, 1 passed in 158.04s`; the
  candidate to retained Widgets to candidate drill failed at
  `QStackedWidget.addWidget`.
- Fixed minimal regression: `1 passed in 3.19s`.
- Fixed original polluted order: `2 passed in 133.18s`.

## Regression evidence

- `2 passed in 155.51s`: complete issue #117 fresh initialization and copied
  formal Wave 3 data migration/rollback integration file. This covers
  deterministic and idempotent migration, exact durable identity graph,
  candidate to retained Widgets to candidate recovery, and clean exits.
- `43 passed in 349.51s`: frontend V2 packaging contract, including retained
  Widgets artifact/source, release manifest, dependency-lock and SHA-256
  contracts.
- `10 passed in 5.42s`: Account adapter, panel registry, main-window layout,
  and no-manual-trading runtime safety tests.
- Python compilation and `git diff --check` passed.

## Scope and release boundary

No ledger qualification or reset rule changed. No persistence schema,
bookmark, release manifest, artifact checksum, System Health remediation,
manual-trading capability, WebEngine capability, route inventory, route,
panel, or Widgets shell was changed or deleted. `legacy_route_count` remains
8 and no legacy deletion is authorized.

The installed clean-Windows, hardware/software renderer, offline Windows,
performance, remote artifact, formal release, and real 14-consecutive-day
gates remain unverified. Issue #118 must rerun its complete source gate from a
revision containing this fix before it can make any certification claim.
