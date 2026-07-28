# Strategy Diagnostics V1 + Frontend V2 Wave 1 contract

Status: integration contract for Issues #49–#52. This document is not a
release-certification claim; Issue #53 owns release certification.

## Boundary

The integration is in-process and read-only. Strategy Diagnostics V1 owns
campaign, run, evidence, persistence, provenance, and terminal truth.
Frontend V2 consumes that truth only through
`StrategyDiagnosticsV1ApplicationReadModel` version 1.0, whose values are
immutable typed DTOs. The QML layer consumes the two versioned Feature
Interfaces:

- `RunMonitoringFeature` version 1.2
- `EvidenceAndFindingsFeature` version 1.1

Those are the only active Feature Interfaces in Wave 1. Their public type
graphs must not expose dictionaries, `Mapping`, `Any`, ORM or database types,
Strategy Diagnostics domain objects, repositories, Qt objects, `EventBridge`,
or concurrency primitives.

## Identity and consistency

A selected journey is pinned by campaign ID and run ID, and—when sealed
evidence exists—by evidence-package and reproduction-manifest IDs. Run and
Evidence pages must show the exact durable identities returned by the
Application read model. A refresh may accept only a different semantic
`SourceRevisionToken` from the current connection generation; the token is an
opaque content identity, not an ordered revision. Duplicate tokens and events
from older generations are ignored.

The last reliable immutable state remains visible when a retryable partial,
stale, disconnected, or reconnecting read occurs. Structured errors carry a
stable code, message, and retryability. Terminal run outcomes are immutable
and disable diagnostic task commands. No state permits manual trading.

## Persistence tracer

The certification tracer starts a file-backed Formal Diagnostic Campaign
through public Application behavior, seals evidence, records durable
identities, disposes the original database engine, creates a new Application
and engine against the same files, and mounts the production Application
adapter through the two live Feature adapters into QML.

The tracer asserts the same identities after reopen, Run-to-Evidence
navigation, disconnect, a new connection generation, authoritative reread,
terminal presentation, remount, and clean close. It never substitutes a
dictionary producer, mocked Application, direct final-result database insert,
or direct QML property injection for the live path.

An independent test starts a real persisted Strategy Run and advances it from
running to completed through public Application methods while observing the
same Run Monitoring Feature seam.

## Accessibility and lifecycle

The real journey preserves keyboard-only navigation, Narrator names and
descriptions, focus restoration, synchronized chart narrative/table revision,
200% text scale, reduced motion, high contrast, disconnect/reconnect and
terminal announcements, remount behavior, and clean subscription disposal.

## Explicit exclusions

Wave 1 does not add manual trading, HTTP, REST, OpenAPI, IPC, a second process,
or a general-purpose façade. It does not remove legacy Widgets. It does not
expand Feature Interface versions or claim T08/T09/T10 or release
certification.
