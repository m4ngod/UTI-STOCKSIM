# Strategy Diagnostics V1 + Frontend V2 Wave 3 contract

Status: incremental source-level integration contract for Issues #77–#84 plus the
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
`preview_reference_market_path` behavior plus the public Recipe authoring,
materialization, formal Scenario Set composition, execution-resolution, and
formal-selection commands owned by Issues #80–#83 and the typed handoff read
projections consumed by Issue #84. It translates admitted Historical
Market Segments, content-addressed Reference Market Paths, the registered
Transformation Catalog, and Campaign Case projections into immutable typed
values. `CampaignCaseId` is the only Market Scenario identity; the Reference
Market Path content hash remains a distinct provenance identity. Bounded path
previews are integrity checked, and reconstructed 30-second paths are labeled
as reconstructed rather than recorded tick or order-book microstructure.

`ScenarioLabFeature` 1.0 freezes the complete snapshot, subscription, close,
Recipe Draft, validation, approval, materialization, retry, composition,
assumption-resolution, and formal-selection operation allowlist. Issue #79
activates read capabilities; Issues #80–#83 activate each declared mutation
without changing the Interface version. Issue #84 activates the typed handoff
without adding a Scenario Lab command or changing the Interface version; the
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
Transformation identities.

Issue #83 activates Formal Campaign Scenario Set composition. A formal set has
exactly one untransformed Baseline, every bounded level from exactly one family
in each Isolated Sensitivity sweep, and declared multi-family Compound cases.
The backend collapses immutable Recipe history to the active approved version
of each Recipe lineage and compares isolated/compound semantic slots; retained
historical baseline or successor versions do not silently enlarge one declared
sweep, while a newly declared parameter level does.
Selective or incomplete composition is typed as `quick_experiment` and cannot
enter formal handoff. The backend resolves each exact Strategy Under Test and
Campaign Case target through the same production run-specification resolver,
publishing requested and effective conditions, typed override reasons, and the
first market node strictly later than Decision Time. Missing Decision Time stays
`not_yet_resolved`; incompatible Strategy, Guardrail, Recipe, path, Market Rule,
Transformation, or execution-policy bindings fail closed. A content-identified
`ScenarioSelectionContext` binds exact identities and hashes plus separate
source-generation, selection-revision, originating-view-revision, Scenario Set
projection-revision, and execution-resolution projection-revision facts.
Successor composition or resolution makes an older context stale. QML presents
these typed projections and never treats a Reproduction Manifest as editable or
predictive Scenario Lab input.

Issue #84 activates `DiagnosticSetupSelectionContext` as an immutable typed
navigation intent over two independent current selections. It combines the
exact `StrategySelectionContext` and `ScenarioSelectionContext`, verifies every
Strategy/Case execution target and projection revision, and converts them into
the unchanged `DiagnosticTaskConfiguration` accepted by
`DiagnosticTasksFeature` 1.0. The Journey Workspace displays the exact Strategy
selection, Scenario Set, execution resolution, selection/view revisions,
source generations, and configuration content identity before enabling create
or revise. It does not introduce a shared catalog/lab facade or duplicate
backend truth.

The handoff uses frozen typed input variants through the five existing
`DiagnosticTasksFeature` 1.0 operations: create, revise, validate, approve, and
start. It adds no Feature or Application operation. An AppContext-owned
`DiagnosticSetupSelectionCoordinator` supplies only the current immutable
typed setup for read-time reconciliation in the live and deterministic-fake
adapters. Only an explicit typed input variant carries that setup into command
content identity; legacy base commands retain their pre-Wave-3 identity and
idempotent replay behavior. The live adapter reconciles task reads through the
public backend `get_diagnostic_task` path; the coordinator never reads
persistence, acts as a Repository, or becomes a QML-facing Interface.

Persistence migration `0021_diagnostic_selection_dependency_invalidation`
atomically binds validation and approval to the exact upstream selection
content. Authority is rechecked on task read and before later commands. A
successor or unavailable upstream selection invalidates active validation and
approval, returns the task to Draft, preserves prior rows and an immutable
invalidation audit, and makes campaign start fail closed. Legacy callers that
do not supply the new typed navigation context retain Diagnostic Tasks 1.0
behavior.

Formal Set, execution-resolution, and selection projections persist separate
monotonic revisions in their immutable command results. Authoritative successor
ordering therefore does not depend on wall-clock uniqueness, command UUID sort
order, or a database-specific insertion-order feature.

## Identity, commands, and recovery

The journey preserves exact task, Campaign, node, attempt, run, Evidence
Package, and Reproduction Manifest identities. Commands use typed identities,
idempotency keys, expected revisions, and persistent `TaskHandle` values.
Approval binds the exact validated revision and, for Issue #84 handoffs, the
exact upstream dependency hash; a changed configuration or later upstream
authority drift invalidates the prior approval without deleting its history.
Retry creates a new attempt without replacing failed history.

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

The Issue #83 source slice composes complete and selective sets from the real
backend inventory, proves formal versus Quick Experiment eligibility, resolves
exact targets through the production resolver, selects only a fully resolved
formal context, and reopens the same file-backed Application to recover the
authoritative identities. The production QML route receives the exact current
Strategy Library selection through the root composition and exposes accessible
composition, resolution, and selection controls without a generic payload bus.

The Issue #84 source slice composes those two current formal selections into
the unchanged task configuration, creates and validates a real persisted task,
atomically binds approval to the exact dependency hash, then creates an
authoritative Scenario successor and proves task reread invalidates the old
approval and rejects campaign start. QML adapter tests prove unavailable
upstream selection disables handoff and that the accessible setup summary
contains every exact identity.

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
Recipe/materialization commands, complete versus Quick Experiment composition,
execution resolution and override reasons, `not_yet_resolved` exclusion,
formal selection, idempotency, source conflict, and stale successor contexts.
Structured failure retains the last reliable immutable inventory as stale.

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
Issues #79–#83 activate Scenario Lab read tracing, Recipe writes, approval,
materialization, scenario-set composition, and formal selection. Issue #84
activates the exact typed handoff into unchanged Diagnostic Tasks 1.0. System
Health and Wave 4 remain unimplemented. This contract does not claim Wave 3
T08/T09/T10 or release certification.
