# Strategy Diagnostics V1 + Frontend V2 Wave 2 contract

Status: source-level integration contract for Issues #56–#65. This is not an
installed release-certification claim.
Issue #66 owns installed offline release certification, T08/T09/T10 evidence,
packages, tag, and release assets.

## Versioned boundary

Strategy Diagnostics V1 owns Diagnostic Task, Formal Diagnostic Campaign,
Campaign node and attempt, Strategy Run, Diagnostic Evidence, persistence,
provenance, Reproduction Manifest, and terminal truth. `AppContext` is the only
composition root.

- `DiagnosticTasksFeature` version 1.0
- `RunMonitoringFeature` version 1.2
- `EvidenceAndFindingsFeature` version 1.1

The command boundary is the separate in-process
`StrategyDiagnosticsV1DiagnosticTasksApplication` version 1.0. The existing
read boundary remains `StrategyDiagnosticsV1ApplicationReadModel` version 1.0.
QML receives only internal Qt projections of the Feature Interfaces.

The transitive public Interface type graph is immutable and typed. It excludes
`dict`, `Mapping`, `Any`, mutable collections, backend domain and persistence
objects, Repository and database types, artifact stores, `RuntimeGateway`,
`EventBridge`, Qt objects, threads, futures, locks, and other concurrency
primitives.

## Identity, commands, and recovery

The journey preserves exact task, Campaign, node, attempt, run, Evidence
Package, and Reproduction Manifest identities. Commands use typed identities,
idempotency keys, expected revisions, and persistent `TaskHandle` values.
Approval binds the exact validated revision; a changed configuration invalidates
the prior approval. Retry creates a new attempt without replacing failed
history.

Disconnect, reconnect, route leave/remount, and Application reopen trigger an
authoritative reread. Older connection generations and late callbacks are
quarantined. The last reliable immutable state remains visible through
retryable partial, stale, disconnected, and reconnecting reads. Terminal
history is monotonic. No state permits manual trading.

## Acceptance seams

### Seam 1: real persisted product tracer

The source-bound tracer suite creates, validates, approves, and starts a
Diagnostic Task through public `DiagnosticsApplication` behavior and the live
`StrategyDiagnosticsV1DiagnosticTasksApplication` adapter. It mounts the
production QML route through all three live Feature adapters, observes the
persistent `TaskHandle`, follows Run Monitoring into Evidence & Findings,
disconnects and reconnects, disposes the database engine, creates a fresh
Application and engine against the same files, and verifies exact durable
identities and terminal history.

The primary production-QML path is joined by exact real live/file-backed
targets for authoritative input rejection and correction, exact-revision
approval, command identity and idempotency recovery, lifecycle and failed-node
retry, terminal non-regression, order-cancel isolation, connection generation
quarantine, disposal, and no-late-callback behavior. The source gate binds
these targets by file and test name so the suite cannot silently lose a
required edge.

It never substitutes a fake, dictionary producer, Repository read, mocked
Application, direct final-result database insert, or QML property injection for
the production path.

### Seam 2: unchanged-body live/fake conformance

One adapter-independent conformance body verifies immutable typed
`ViewState`, commands, results, `TaskHandle`, subscription, freshness,
revision, last reliable state, structured errors, command identity,
idempotency, expected revision, disconnect/reconnect, old-generation
quarantine, terminal monotonicity, disposal, and idempotent close for both live
and deterministic fake adapters.

### Seam 3: installed offline black-box release

Issue #66 owns the installed offline black-box journey, hardware and software
rendering certification, clean-room installation, package checksums,
dependency manifests, retained raw evidence, release tag, and remote assets.
The #65 source gate proves preflight readiness but does not claim that Seam 3
has passed.

## Accessibility, safety, and performance

The three-route journey preserves keyboard navigation, Narrator names and
descriptions, focus restoration, 200% text scale, reduced motion, high
contrast, background-task continuity, remount behavior, and clean subscription
disposal. The source gate also exercises the fixed hardware/software
performance projection with typed Diagnostic Task command and `TaskHandle`
observations.

## Explicit exclusions

Wave 2 does not add manual trading, HTTP, REST, OpenAPI, IPC, a second process,
WebEngine, or a general-purpose frontend façade. It does not remove legacy
Widgets. Strategy Library, Scenario Lab, System Health, and Waves 3–4 remain
unimplemented. This contract does not claim T08/T09/T10 or release
certification.
