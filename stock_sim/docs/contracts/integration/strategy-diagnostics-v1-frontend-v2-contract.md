# Strategy Diagnostics V1 + Frontend V2 Wave 3 contract

Status: incremental source-level integration contract for Issues #77, #78, and #79 plus the
certified Wave 2 delivery in Issues #56–#66. This is not a Wave 3 installed
release-certification claim. Issue #88 owns Wave 3 installed offline release certification,
T08/T09/T10 evidence, packages, tag, and release assets.

## Versioned boundary

Strategy Diagnostics V1 owns Diagnostic Task, Formal Diagnostic Campaign,
Campaign node and attempt, Strategy Run, Diagnostic Evidence, persistence,
provenance, Reproduction Manifest, and terminal truth. `AppContext` is the only
composition root.

- `StrategyLibraryFeature` version 1.0
- `ScenarioLabFeature` version 1.0
- `DiagnosticTasksFeature` version 1.0
- `RunMonitoringFeature` version 1.2
- `EvidenceAndFindingsFeature` version 1.1

The Strategy inventory read boundary is the separate in-process
`StrategyDiagnosticsV1StrategyLibraryApplication` version 1.0. Its production
Adapter calls only public `DiagnosticsApplication.read_strategy_under_test_inventory`
and `DiagnosticsApplication.validate_formal_strategy_set` behavior. The
comparison and exact formal-set selection commands remain on
`StrategyLibraryFeature` 1.0.

The Scenario Lab read boundary is the separate in-process
`StrategyDiagnosticsV1ScenarioLabApplication` version 1.0. Its production
Adapter calls only public `DiagnosticsApplication.list_historical_segments`,
`read_diagnostic_campaign_case_inventory`, `transformation_catalog_view`, and
`preview_reference_market_path` behavior. It translates admitted Historical
Market Segments, content-addressed Reference Market Paths, the registered
Transformation Catalog, and Campaign Case projections into immutable typed
values. `CampaignCaseId` is the only Market Scenario identity; the Reference
Market Path content hash remains a distinct provenance identity. Bounded path
previews are integrity checked, and reconstructed 30-second paths are labeled
as reconstructed rather than recorded tick or order-book microstructure.

`ScenarioLabFeature` 1.0 freezes the complete snapshot, subscription, close,
Recipe Draft, validation, approval, materialization, retry, composition,
assumption-resolution, and formal-selection operation allowlist. Issue #79
activates only read capabilities. Recipe and scenario mutations return typed
unavailable results until Issues #80–#83 implement their owning slices; the
deterministic fake is never a production fallback.

The Diagnostic Tasks command boundary is the separate in-process
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

Comparison presents every declared dimension directly: exact identity/version,
source path and SHA-256, lineage, compatibility surface and manifest,
capabilities, candidate-data policy, versioned Guardrail thresholds, dependency
provenance, and diagnostic applicability. Selection binds the complete exact
backend reference set. Its durable bookmark contains those immutable references
and optional focus identity, never presentation copies; reopen rereads and
revalidates authority before publishing `CURRENT`. Missing identities publish
`UNAVAILABLE`; changed versions, manifests, Guardrails, or dependencies publish
`CONFLICT` and require explicit reselection. No score, ranking, or recommendation
is computed.

Issue #79 activates Scenario Lab read tracing. Search and filters operate only
over immutable typed `ScenarioLabViewState`. Historical Segment entries retain
exact segment, content, source snapshot, provenance, coverage, admission,
quality, and recommendation-tag facts. Reference Path entries retain content
identity, segment/source binding, seed, expander, source/runtime resolution,
reconstruction notice, tolerance, normalization, Market Rule Profile,
Transformation versions, time range, integrity, reproducibility, and bounded
preview. Market Scenario entries retain backend-created Campaign Case identity,
layer, comparison role, baseline relationship, Recipe/path/source/seed and
Transformation identities. Effective execution assumptions remain explicitly
`not_yet_resolved` until Issue #83; QML neither guesses nor synthesizes them.

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
Feature Adapter, and the production QML browse, comparison, exact selection,
durable-bookmark reopen, and focus-restoration route. Its inherited Wave 2
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

The Issue #79 source slice uses real public Historical Segment admission,
Scenario Recipe approval, Reference Path materialization, and Campaign Case
derivation, then traces those exact identities through the production Scenario
Lab Application Adapter, live Feature Adapter, and production QML route. The
path hash and Campaign Case identity are independently reasserted and never
substituted for one another.

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
Subscription disposal, idempotent close, comparison, exact formal selection,
selection idempotency, invalid selection, stale/conflict/unavailable bookmark
recovery, and terminal selection identity immutability.
Scenario Lab uses unchanged test bodies for loading/ready search state,
immutable segment/path/scenario/catalog values, bounded preview and
reconstruction honesty, source revision/generation, subscription disposal,
idempotent close, exact Campaign Case versus path identity, and typed
unavailable Recipe/materialization/composition capabilities. Structured
failure retains the last reliable immutable inventory as stale.

### Seam 3: installed offline black-box release

Issue #88 owns the Wave 3 installed offline black-box journey, hardware and
software rendering certification, clean-room installation, package checksums,
dependency manifests, retained raw evidence, release tag, and remote assets.
The source gate proves incremental preflight readiness but does not claim that
Wave 3 Seam 3 has passed. The inherited Wave 2 certification remains recorded
by Issue #66.

## Accessibility, safety, and performance

The current five-route journey preserves keyboard navigation, Narrator names and
descriptions, focus restoration, 200% text scale, reduced motion, high
contrast, background-task continuity, remount behavior, and clean subscription
disposal. The source gate also exercises the fixed hardware/software
performance projection with typed Diagnostic Task command and `TaskHandle`
observations.

## Explicit exclusions

Wave 3 does not add manual trading, HTTP, REST, OpenAPI, IPC, a second process,
WebEngine, or a general-purpose frontend façade. It does not remove legacy
Widgets. Issues #77 and #78 activate Strategy Library browse, explicit
comparison, exact formal selection, and authoritative bookmark recovery.
Issue #79 activates Scenario Lab read tracing; Recipe writes, approval,
materialization, scenario-set composition, and handoff remain owned by Issues
#80–#84. System Health and Wave 4 remain unimplemented. This contract does not claim Wave 3
T08/T09/T10 or release certification.
