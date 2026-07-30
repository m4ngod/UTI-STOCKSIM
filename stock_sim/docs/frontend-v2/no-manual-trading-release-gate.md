# Frontend V2 no-manual-trading release gate

Frontend V2 is a Strategy Diagnostics Laboratory. Manual trading is denied by default.

The active Wave 1 surface may read market, account, position, order, and fill
values only when they explain a diagnostic run, evidence, or finding. These
values are immutable diagnostic context. They are not navigation destinations,
editable forms, transaction controls, or generic runtime commands.

`Cancel diagnostic task` is a feature-specific lifecycle operation with a
`CancelDiagnosticTask` identity. It must route only to
`cancel_diagnostic_task`; it must never route to `cancel order` or another
transaction operation.

Every release must pass the automated gate covering:

- the exact public members of `RunMonitoringFeature` and
  `EvidenceAndFindingsFeature`;
- the QML Adapter Slot allowlist;
- the runtime QML object tree and its interactive accessible roles;
- Journey routes and keyboard shortcuts;
- telemetry event names;
- deterministic-fake and live Adapter surfaces and runtime gateway calls;
- immutable read-only diagnostic context;
- packaging and clean-room certification evidence.

The gate is a source-tree release command, because it audits source, policy,
tests, and package inputs that are intentionally absent from an installed
wheel. Run it from the locked checkout with:

```powershell
python -m stock_sim.release.no_manual_trading_gate `
  --project-root . `
  --source-commit <commit>
```

The command executes the live and deterministic-fake runtime negative suite
before reporting success. Packaging retains that exact report, and clean-room
certification re-runs the gate against the certification checkout and rejects
any field or source-digest mismatch.

The runtime subprocess ignores ambient pytest options and plugin injection.
Only the five required passing JUnit sentinels count as execution evidence;
collected, skipped, xfailed, failed, or missing cases fail closed.

Active Wave 1 source imports and the compiled QML Journey dependency graph
must not contain transaction-bearing backend services or persistence modules.
The audited Nuitka reports are checksummed into candidate evidence, then
checksum-verified and re-audited during clean-room certification.

Any manual order, cancel-order, replace-order, bulk-order, Buy/Sell, order-entry,
or universal dispatch capability fails the gate and blocks release even when
visual, performance, accessibility, and packaging checks otherwise pass.

Any future manual-trading request requires a separate product decision. It
cannot be introduced as a parity fix, migration fallback, shortcut, telemetry
command, technology requirement, or generic dispatch escape hatch.
