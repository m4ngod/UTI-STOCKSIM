# Strategy Diagnostics V1 + Frontend V2 Wave 3 contract

Status: incremental source-level integration contract for Issue #77 plus the
certified Wave 2 delivery in Issues #56–#66. This is not a Wave 3 installed
release-certification claim. Issue #88 owns Wave 3 installed offline release certification,
T08/T09/T10 evidence, packages, tag, and release assets.

## Versioned boundary

Strategy Diagnostics V1 owns Diagnostic Task, Formal Diagnostic Campaign,
Campaign node and attempt, Strategy Run, Diagnostic Evidence, persistence,
provenance, Reproduction Manifest, and terminal truth. `AppContext` is the only
composition root.

- `StrategyLibraryFeature` version 1.0
- `DiagnosticTasksFeature` version 1.0
- `RunMonitoringFeature` version 1.2
- `EvidenceAndFindingsFeature` version 1.1

The Strategy inventory read boundary is the separate in-process
`StrategyDiagnosticsV1StrategyLibraryApplication` version 1.0. Its production
Adapter calls only public `DiagnosticsApplication.read_strategy_under_test_inventory`
behavior. The command boundary is the separate in-process
`StrategyDiagnosticsV1DiagnosticTasksApplication` version 1.0. The existing
read boundary remains `StrategyDiagnosticsV1ApplicationReadModel` version 1.0.
QML receives only internal Qt projections of the Feature Interfaces.

The transitive public Interface type graph is immutable and typed. It excludes
`dict`, `Mapping`, `Any`, mutable collections, backend domain and persistence
objects, Repository and database types, artifact stores, `RuntimeGateway`,
`EventBridge`, Qt objects, threads, futures, locks, and other concurrency
primitives.

The authoritative Strategy Library contains exactly the two backend-declared
Scenario-native Strategies Under Test. It presents exact strategy/version,
retained source and content lineage, PTrade surface and manifest identity,
declared capabilities, candidate-data policy, matching versioned Guardrail
Profile, dependency identities, eligibility, and typed availability reasons.
The internal reference strategy is excluded. Search and availability filters
operate over typed immutable ViewState; no frontend layer enumerates files,
packages, modules, entry points, or registry internals.

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

The source-bound tracer suite begins with a real public backend Strategy
inventory, the production Strategy Library Application Adapter, the live
Feature Adapter, and the production QML browse route. Its inherited Wave 2
path then creates, validates, approves, and starts a
Diagnostic Task through public `DiagnosticsApplication` behavior and the live
`StrategyDiagnosticsV1DiagnosticTasksApplication` adapter. It mounts the
production QML route through the inherited three live Feature adapters, observes the
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
Strategy Library uses unchanged test bodies for browse/search/filter state,
typed availability, first-read failure, last-reliable retention, duplicate and
lower revision quarantine, connection generation, old-generation invalidation,
Subscription disposal, and idempotent close.

### Seam 3: installed offline black-box release

Issue #88 owns the Wave 3 installed offline black-box journey, hardware and
software rendering certification, clean-room installation, package checksums,
dependency manifests, retained raw evidence, release tag, and remote assets.
The source gate proves incremental preflight readiness but does not claim that
Wave 3 Seam 3 has passed. The inherited Wave 2 certification remains recorded
by Issue #66.

## Accessibility, safety, and performance

The current four-route journey preserves keyboard navigation, Narrator names and
descriptions, focus restoration, 200% text scale, reduced motion, high
contrast, background-task continuity, remount behavior, and clean subscription
disposal. The source gate also exercises the fixed hardware/software
performance projection with typed Diagnostic Task command and `TaskHandle`
observations.

## Explicit exclusions

Wave 3 does not add manual trading, HTTP, REST, OpenAPI, IPC, a second process,
WebEngine, or a general-purpose frontend façade. It does not remove legacy
Widgets. Issue #77 activates browse-only Strategy Library; comparison and
formal selection remain capability-gated for #78. Scenario Lab, System Health,
and Wave 4 remain unimplemented. This contract does not claim Wave 3
T08/T09/T10 or release certification.
