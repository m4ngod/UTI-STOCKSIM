"""Read-only System Health Feature Interface 1.0 contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from typing import Protocol, TypeAlias, TypeVar, runtime_checkable

from .diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    DiagnosticTaskConfigurationContentId,
)
from .evidence_and_findings import (
    DiagnosticEvidencePackageId,
    FindingId,
    SensitivityBreakpointId,
)
from .run_monitoring import (
    Completeness,
    DiagnosticTaskId,
    FormalDiagnosticCampaignId,
    Freshness,
    ReproductionManifestId,
    SourceGenerationId,
    SourceKind,
    StrategyRunId,
    Subscription,
    TaskHandleId,
    ViewPhase,
)
from .versioning import FeatureInterfaceDescriptor, FeatureInterfaceVersion


class RuntimeHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    UNKNOWN = "unknown"


class SystemHealthComponentIdentity(str, Enum):
    APPLICATION_RUNTIME = "application_runtime"
    DIAGNOSTIC_PERSISTENCE = "diagnostic_persistence"
    VERSION_COMPATIBILITY = "version_compatibility"


# Retain the Issue #108 public name as a compatibility alias while the
# component identity set grows from Runtime-only to the complete 1.0 slice.
RuntimeHealthComponentIdentity = SystemHealthComponentIdentity


class HealthCompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class PersistenceAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class PersistenceReopenVerification(str, Enum):
    VERIFIED = "verified"
    NOT_YET_VERIFIED = "not_yet_verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SystemHealthAffectedScope(str, Enum):
    APPLICATION_RUNTIME = "application_runtime"
    DIAGNOSTIC_PERSISTENCE = "diagnostic_persistence"
    VERSION_COMPATIBILITY = "version_compatibility"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"
    REPRODUCTION_MANIFEST = "reproduction_manifest"


class SystemHealthRecoveryExpectation(str, Enum):
    AUTOMATIC_RETRY = "automatic_retry"
    SOURCE_RECONNECTION = "source_reconnection"
    INITIALIZATION_REQUIRED = "initialization_required"
    COMPATIBLE_BUILD_REQUIRED = "compatible_build_required"
    COMPATIBLE_ARTIFACT_REQUIRED = "compatible_artifact_required"
    RELEASE_REPAIR_REQUIRED = "release_repair_required"
    NONE = "none"


class RuntimeHealthRecoveryPhase(str, Enum):
    IDLE = "idle"
    DISCONNECTED = "disconnected"
    REREADING = "rereading"
    RECOVERED = "recovered"
    FAILED = "failed"


class DiagnosticDataSourceComponentIdentity(str, Enum):
    ADMITTED_HISTORICAL_MARKET_DATA = "admitted_historical_market_data"


class DiagnosticDataSourceHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"


class DiagnosticDataSourceConnectionState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    UNAVAILABLE = "unavailable"


class DiagnosticDataSourceFallbackState(str, Enum):
    PRIMARY = "primary"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"


class DiagnosticDataSourceRecoveryPhase(str, Enum):
    IDLE = "idle"
    DISCONNECTED = "disconnected"
    FALLBACK = "fallback"
    RECONNECTING = "reconnecting"
    REREADING = "rereading"
    RECOVERED = "recovered"
    FAILED_RECOVERY = "failed_recovery"


class DiagnosticDataSourceScope(str, Enum):
    SCENARIO_INPUTS = "scenario_inputs"
    DIAGNOSTIC_EVIDENCE_INTERPRETATION = "diagnostic_evidence_interpretation"


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceIdentity:
    public_id: str
    provider: str
    dataset: str
    version: str

    def __post_init__(self) -> None:
        prefix = "admitted-source-"
        if not isinstance(self.public_id, str) or not self.public_id.startswith(
            prefix
        ):
            raise ValueError("Data Source public identity must be opaque")
        opaque_suffix = self.public_id[len(prefix) :]
        if not 16 <= len(opaque_suffix) <= 64 or any(
            character not in "0123456789abcdef" for character in opaque_suffix
        ):
            raise ValueError("Data Source public identity must be opaque")
        for label, value in (
            ("provider", self.provider),
            ("dataset", self.dataset),
            ("version", self.version),
        ):
            _require_safe_source_label(value, label)


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceRevision:
    value: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, int)
            or isinstance(self.value, bool)
            or self.value < 1
        ):
            raise ValueError("Data Source revision must be positive")


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceObservation:
    identity: DiagnosticDataSourceIdentity
    revision: DiagnosticDataSourceRevision
    generation: SourceGenerationId
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DiagnosticDataSourceIdentity):
            raise TypeError("identity must be a Data Source identity")
        if not isinstance(self.revision, DiagnosticDataSourceRevision):
            raise TypeError("revision must be a Data Source revision")
        if not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")
        _require_aware(self.observed_at, "Data Source observation time")


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceHealthComponent:
    identity: DiagnosticDataSourceComponentIdentity
    classification: DiagnosticDataSourceHealthClassification
    connection: DiagnosticDataSourceConnectionState
    fallback: DiagnosticDataSourceFallbackState
    accepted_revision: DiagnosticDataSourceRevision | None
    accepted_generation: SourceGenerationId | None
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    last_reliable_observation: DiagnosticDataSourceObservation | None
    affected_scope: tuple[DiagnosticDataSourceScope, ...]
    recovery_phase: DiagnosticDataSourceRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DiagnosticDataSourceComponentIdentity):
            raise TypeError("identity must be a Data Source component identity")
        if not isinstance(
            self.classification,
            DiagnosticDataSourceHealthClassification,
        ):
            raise TypeError("classification must be a Data Source classification")
        if not isinstance(self.connection, DiagnosticDataSourceConnectionState):
            raise TypeError("connection must be a Data Source connection state")
        if not isinstance(self.fallback, DiagnosticDataSourceFallbackState):
            raise TypeError("fallback must be a Data Source fallback state")
        if self.accepted_revision is not None and not isinstance(
            self.accepted_revision,
            DiagnosticDataSourceRevision,
        ):
            raise TypeError("accepted_revision must be a Data Source revision")
        if self.accepted_generation is not None and not isinstance(
            self.accepted_generation,
            SourceGenerationId,
        ):
            raise TypeError("accepted_generation must be a SourceGenerationId")
        if (self.accepted_revision is None) is not (
            self.accepted_generation is None
        ):
            raise ValueError("accepted revision and generation must be jointly present")
        if not isinstance(self.freshness, Freshness):
            raise TypeError("freshness must be a Freshness")
        if not isinstance(self.recovery_phase, DiagnosticDataSourceRecoveryPhase):
            raise TypeError("recovery_phase must be a Data Source recovery phase")
        _require_aware(self.observed_at, "Data Source Health observation time")
        _require_freshness_window(
            self.age,
            self.freshness_threshold,
            "Data Source Health",
        )
        _require_typed_scope(
            self.affected_scope,
            DiagnosticDataSourceScope,
            "Data Source",
        )
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("Data Source error must be a SystemHealthError")
        if self.last_reliable_observation is not None:
            if not isinstance(
                self.last_reliable_observation,
                DiagnosticDataSourceObservation,
            ):
                raise TypeError("last reliable observation must be typed")
            if self.accepted_revision != self.last_reliable_observation.revision:
                raise ValueError("accepted revision must match last reliable state")
            if self.accepted_generation != self.last_reliable_observation.generation:
                raise ValueError("accepted generation must match last reliable state")
        elif self.accepted_revision is not None:
            raise ValueError("accepted state requires a last reliable observation")
        if (
            self.classification
            is DiagnosticDataSourceHealthClassification.UNAVAILABLE
            and self.last_reliable_observation is not None
        ):
            raise ValueError("unavailable Data Source Health cannot be reliable")
        if self.classification is DiagnosticDataSourceHealthClassification.HEALTHY:
            if (
                self.connection is not DiagnosticDataSourceConnectionState.CONNECTED
                or self.last_reliable_observation is None
                or self.freshness is not Freshness.FRESH
                or self.error is not None
            ):
                raise ValueError("healthy Data Source Health is contradictory")
        if self.classification is DiagnosticDataSourceHealthClassification.STALE:
            if (
                self.last_reliable_observation is None
                or self.freshness is not Freshness.STALE
            ):
                raise ValueError("stale Data Source Health requires stale history")
        if (
            self.classification is DiagnosticDataSourceHealthClassification.RECOVERING
            and (
                self.connection is not DiagnosticDataSourceConnectionState.RECONNECTING
                or self.last_reliable_observation is None
            )
        ):
            raise ValueError("recovering Data Source Health is contradictory")
        if self.recovery_phase is DiagnosticDataSourceRecoveryPhase.DISCONNECTED:
            if self.connection is not DiagnosticDataSourceConnectionState.DISCONNECTED:
                raise ValueError("disconnected recovery requires disconnection")
        if self.recovery_phase in {
            DiagnosticDataSourceRecoveryPhase.FALLBACK,
            DiagnosticDataSourceRecoveryPhase.RECONNECTING,
            DiagnosticDataSourceRecoveryPhase.REREADING,
            DiagnosticDataSourceRecoveryPhase.FAILED_RECOVERY,
        } and self.connection is not DiagnosticDataSourceConnectionState.RECONNECTING:
            raise ValueError("active recovery requires a reconnecting source")
        if self.recovery_phase is DiagnosticDataSourceRecoveryPhase.RECOVERED:
            if (
                self.connection is not DiagnosticDataSourceConnectionState.CONNECTED
                or self.last_reliable_observation is None
            ):
                raise ValueError("recovered Data Source Health requires reliable state")
        _require_safe_diagnostic_text(
            self.explanation,
            "Data Source Health explanation",
        )


class DiagnosticQueueHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


class DiagnosticQueueConsumerAvailability(str, Enum):
    AVAILABLE = "available"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class DiagnosticQueueBlockageReason(str, Enum):
    NONE = "none"
    PAUSED_DIAGNOSTIC_WORK = "paused_diagnostic_work"
    RECOVERY_REQUIRED = "recovery_required"
    SOURCE_UNAVAILABLE = "source_unavailable"
    UNKNOWN = "unknown"


class DiagnosticQueueScope(str, Enum):
    DIAGNOSTIC_TASK = "diagnostic_task"
    FORMAL_DIAGNOSTIC_CAMPAIGN = "formal_diagnostic_campaign"
    CAMPAIGN_NODES = "campaign_nodes"


class DiagnosticQueueRecoveryPhase(str, Enum):
    IDLE = "idle"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    FAILED_RECOVERY = "failed_recovery"


class DiagnosticCacheHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    FALLBACK = "fallback"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


class DiagnosticCacheFallbackState(str, Enum):
    PRIMARY = "primary"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class DiagnosticCacheLastRefreshResult(str, Enum):
    NOT_OBSERVED = "not_observed"
    SUCCEEDED = "succeeded"
    FALLBACK_SUCCEEDED = "fallback_succeeded"
    FAILED = "failed"


class DiagnosticCacheCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class DiagnosticCacheScope(str, Enum):
    REFERENCE_MARKET_PATHS = "reference_market_paths"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"


class DiagnosticCacheRecoveryPhase(str, Enum):
    IDLE = "idle"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    FAILED_RECOVERY = "failed_recovery"


class SystemHealthPresentationState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    UNKNOWN = "unknown"


class SystemHealthErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "runtime_health_no_authoritative_observation"
    OBSERVATION_FAILED = "runtime_health_observation_failed"
    SOURCE_DISCONNECTED = "runtime_health_source_disconnected"
    AUTHORITATIVE_REREAD_FAILED = "runtime_health_authoritative_reread_failed"
    DATA_SOURCE_UNAVAILABLE = "diagnostic_data_source_unavailable"
    DATA_SOURCE_DISCONNECTED = "diagnostic_data_source_disconnected"
    DATA_SOURCE_REREAD_FAILED = "diagnostic_data_source_reread_failed"
    DIAGNOSTIC_QUEUE_NO_AUTHORITATIVE_OBSERVATION = (
        "diagnostic_queue_no_authoritative_observation"
    )
    DIAGNOSTIC_QUEUE_READ_FAILED = "diagnostic_queue_read_failed"
    DIAGNOSTIC_CACHE_NO_AUTHORITATIVE_OBSERVATION = (
        "diagnostic_cache_no_authoritative_observation"
    )
    DIAGNOSTIC_CACHE_READ_FAILED = "diagnostic_cache_read_failed"
    PERSISTENCE_NOT_INITIALIZED = "persistence_health_not_initialized"
    PERSISTENCE_UNAVAILABLE = "persistence_health_unavailable"
    PERSISTENCE_SCHEMA_INCOMPATIBLE = "persistence_schema_incompatible"
    VERSION_FACTS_UNAVAILABLE = "version_health_facts_unavailable"
    DEPENDENCY_LOCK_UNAVAILABLE = "dependency_lock_unavailable"
    RELEASE_BINDING_UNAVAILABLE = "release_binding_unavailable"
    RELEASE_BINDING_INCOMPATIBLE = "release_binding_incompatible"
    REPRODUCTION_MANIFEST_INCOMPATIBLE = "reproduction_manifest_incompatible"
    REPRODUCTION_MANIFEST_UNAVAILABLE = "reproduction_manifest_unavailable"


@dataclass(frozen=True, slots=True)
class SystemHealthError:
    code: SystemHealthErrorCode
    explanation: str
    retryable: bool
    affected_scope: SystemHealthAffectedScope = (
        SystemHealthAffectedScope.APPLICATION_RUNTIME
    )
    recovery_expectation: SystemHealthRecoveryExpectation = (
        SystemHealthRecoveryExpectation.AUTOMATIC_RETRY
    )
    correlation_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, SystemHealthErrorCode):
            raise TypeError("code must be a SystemHealthErrorCode")
        _require_safe_diagnostic_text(
            self.explanation,
            "System Health explanation",
        )
        if not isinstance(self.affected_scope, SystemHealthAffectedScope):
            raise TypeError("affected_scope must be typed")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a bool")
        if not isinstance(self.recovery_expectation, SystemHealthRecoveryExpectation):
            raise TypeError("recovery_expectation must be typed")
        if self.correlation_identity is not None:
            _require_safe_correlation_identity(
                self.correlation_identity,
                "System Health correlation identity",
            )


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    identity: SystemHealthComponentIdentity
    classification: RuntimeHealthClassification
    revision: int
    observed_at: datetime
    last_successful_observation_at: datetime | None
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SystemHealthComponentIdentity):
            raise TypeError("identity must be a SystemHealthComponentIdentity")
        if self.identity is not SystemHealthComponentIdentity.APPLICATION_RUNTIME:
            raise ValueError("Runtime Health requires the runtime identity")
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Runtime Health revision must be positive")
        _require_aware(self.observed_at, "Runtime Health observation time")
        if self.last_successful_observation_at is not None:
            _require_aware(
                self.last_successful_observation_at,
                "Runtime Health last successful observation time",
            )
        _require_safe_diagnostic_text(
            self.explanation,
            "Runtime Health explanation",
        )


@dataclass(frozen=True, slots=True)
class PersistenceHealthComponent:
    identity: SystemHealthComponentIdentity
    classification: RuntimeHealthClassification
    revision: int
    observed_at: datetime
    last_successful_observation_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    availability: PersistenceAvailability
    schema_compatibility: HealthCompatibilityState
    schema_head: str | None
    supported_schema_head: str
    last_successful_durable_read_at: datetime | None
    last_successful_durable_write_at: datetime | None
    reopen_verification: PersistenceReopenVerification
    affected_scope: SystemHealthAffectedScope
    recovery_phase: RuntimeHealthRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if self.identity is not SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE:
            raise ValueError("Persistence Health requires the persistence identity")
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Persistence Health revision must be positive")
        _require_aware(self.observed_at, "Persistence Health observation time")
        for label, value in (
            ("Persistence Health last observation", self.last_successful_observation_at),
            ("durable read observation", self.last_successful_durable_read_at),
            ("durable write observation", self.last_successful_durable_write_at),
        ):
            if value is not None:
                _require_aware(value, label)
        if not isinstance(self.freshness, Freshness):
            raise TypeError("freshness must be a Freshness")
        if self.age < timedelta(0):
            raise ValueError("Persistence Health age cannot be negative")
        if self.freshness_threshold <= timedelta(0):
            raise ValueError("Persistence Health threshold must be positive")
        if not isinstance(self.availability, PersistenceAvailability):
            raise TypeError("availability must be a PersistenceAvailability")
        if not isinstance(self.schema_compatibility, HealthCompatibilityState):
            raise TypeError("schema_compatibility must be typed")
        if self.schema_head is not None:
            _require_safe_identity(self.schema_head, "schema head")
        _require_safe_identity(self.supported_schema_head, "supported schema head")
        if not isinstance(self.reopen_verification, PersistenceReopenVerification):
            raise TypeError("reopen_verification must be typed")
        if self.affected_scope is not SystemHealthAffectedScope.DIAGNOSTIC_PERSISTENCE:
            raise ValueError("Persistence Health affected scope must be persistence")
        if not isinstance(self.recovery_phase, RuntimeHealthRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_diagnostic_text(
            self.explanation,
            "Persistence Health explanation",
        )
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


@dataclass(frozen=True, slots=True)
class VersionHealthComponent:
    identity: SystemHealthComponentIdentity
    classification: RuntimeHealthClassification
    revision: int
    observed_at: datetime
    last_successful_observation_at: datetime | None
    product_build: str
    feature_interfaces: tuple[FeatureInterfaceDescriptor, ...]
    dependency_lock_identity: str | None
    release_manifest_compatibility: HealthCompatibilityState
    runner_version: str
    schema_version: str
    evidence_format_version: str
    manifest_format_version: str
    reproduction_manifest_compatibility: HealthCompatibilityState
    affected_scope: SystemHealthAffectedScope
    recovery_phase: RuntimeHealthRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if self.identity is not SystemHealthComponentIdentity.VERSION_COMPATIBILITY:
            raise ValueError("Version Health requires the version identity")
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Version Health revision must be positive")
        _require_aware(self.observed_at, "Version Health observation time")
        if self.last_successful_observation_at is not None:
            _require_aware(
                self.last_successful_observation_at,
                "Version Health last observation",
            )
        for label, value in (
            ("product build", self.product_build),
            ("runner version", self.runner_version),
            ("schema version", self.schema_version),
            ("evidence format version", self.evidence_format_version),
            ("manifest format version", self.manifest_format_version),
        ):
            _require_safe_identity(value, label)
        if not isinstance(self.feature_interfaces, tuple) or not all(
            isinstance(item, FeatureInterfaceDescriptor)
            for item in self.feature_interfaces
        ):
            raise TypeError("feature_interfaces must be an immutable typed tuple")
        digest = self.dependency_lock_identity
        if digest is not None and (
            not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or len(digest) != 71
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            raise ValueError("dependency lock identity must be a SHA-256 identity")
        if not isinstance(
            self.release_manifest_compatibility,
            HealthCompatibilityState,
        ):
            raise TypeError("release manifest compatibility must be typed")
        if not isinstance(
            self.reproduction_manifest_compatibility,
            HealthCompatibilityState,
        ):
            raise TypeError("manifest compatibility must be typed")
        if self.affected_scope is not SystemHealthAffectedScope.VERSION_COMPATIBILITY:
            raise ValueError("Version Health affected scope must be version compatibility")
        if not isinstance(self.recovery_phase, RuntimeHealthRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_diagnostic_text(
            self.explanation,
            "Version Health explanation",
        )
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


SystemHealthComponent = (
    RuntimeHealthComponent | PersistenceHealthComponent | VersionHealthComponent
)


@dataclass(frozen=True, slots=True)
class DiagnosticQueueHealthComponent:
    classification: DiagnosticQueueHealthClassification
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    pending_count: int
    running_count: int
    blocked_count: int
    oldest_pending_age: timedelta | None
    consumer_availability: DiagnosticQueueConsumerAvailability
    blockage_reason: DiagnosticQueueBlockageReason
    affected_scope: tuple[DiagnosticQueueScope, ...]
    recovery_phase: DiagnosticQueueRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.classification, DiagnosticQueueHealthClassification):
            raise TypeError("classification must be a DiagnosticQueueHealthClassification")
        _require_component_revision(self.revision, "Diagnostic Queue Health")
        _require_aware(self.observed_at, "Diagnostic Queue Health observation time")
        _require_freshness_window(
            self.age,
            self.freshness_threshold,
            "Diagnostic Queue Health",
        )
        for value, label in (
            (self.pending_count, "pending count"),
            (self.running_count, "running count"),
            (self.blocked_count, "blocked count"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Diagnostic Queue Health {label} must be non-negative")
        if self.oldest_pending_age is not None and self.oldest_pending_age < timedelta(0):
            raise ValueError("Diagnostic Queue Health oldest pending age cannot be negative")
        if not isinstance(self.consumer_availability, DiagnosticQueueConsumerAvailability):
            raise TypeError("consumer_availability must be typed")
        if not isinstance(self.blockage_reason, DiagnosticQueueBlockageReason):
            raise TypeError("blockage_reason must be typed")
        _require_typed_scope(self.affected_scope, DiagnosticQueueScope, "Diagnostic Queue")
        if not isinstance(self.recovery_phase, DiagnosticQueueRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_text(self.explanation, "Diagnostic Queue Health explanation")
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheHealthComponent:
    classification: DiagnosticCacheHealthClassification
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    generation: SourceGenerationId | None
    fallback: DiagnosticCacheFallbackState
    last_refresh_result: DiagnosticCacheLastRefreshResult
    compatibility: DiagnosticCacheCompatibility
    affected_scope: tuple[DiagnosticCacheScope, ...]
    recovery_phase: DiagnosticCacheRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.classification, DiagnosticCacheHealthClassification):
            raise TypeError("classification must be a DiagnosticCacheHealthClassification")
        _require_component_revision(self.revision, "Diagnostic Cache Health")
        _require_aware(self.observed_at, "Diagnostic Cache Health observation time")
        _require_freshness_window(
            self.age,
            self.freshness_threshold,
            "Diagnostic Cache Health",
        )
        if self.generation is not None and not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")
        if not isinstance(self.fallback, DiagnosticCacheFallbackState):
            raise TypeError("fallback must be typed")
        if not isinstance(self.last_refresh_result, DiagnosticCacheLastRefreshResult):
            raise TypeError("last_refresh_result must be typed")
        if not isinstance(self.compatibility, DiagnosticCacheCompatibility):
            raise TypeError("compatibility must be typed")
        _require_typed_scope(self.affected_scope, DiagnosticCacheScope, "Diagnostic Cache")
        if not isinstance(self.recovery_phase, DiagnosticCacheRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_text(self.explanation, "Diagnostic Cache Health explanation")
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


@dataclass(frozen=True, slots=True)
class SystemHealthSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceKind):
            raise TypeError("kind must be a SourceKind")
        _require_safe_text(self.identity, "System Health source identity")
        if not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")


@dataclass(frozen=True, slots=True)
class SystemHealthDiagnosticContextVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.major, int)
            or isinstance(self.major, bool)
            or not isinstance(self.minor, int)
            or isinstance(self.minor, bool)
            or self.major < 0
            or self.minor < 0
        ):
            raise ValueError("System Health diagnostic context version is invalid")


SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION = SystemHealthDiagnosticContextVersion(1, 0)


class SystemHealthContextResolution(str, Enum):
    NO_CURRENT_TASK = "no_current_task"
    EXACT_MATCH = "exact_match"
    MISSING = "missing"
    SUPERSEDED = "superseded"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    COMPLETED = "completed"


class SystemHealthOverallClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"
    CONTEXT_MISSING = "context_missing"
    CONTEXT_SUPERSEDED = "context_superseded"
    CONTEXT_INCOMPATIBLE = "context_incompatible"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    DIAGNOSTIC_FAILED = "diagnostic_failed"
    DIAGNOSTIC_COMPLETED = "diagnostic_completed"


class SystemHealthImpactComponentIdentity(str, Enum):
    APPLICATION_RUNTIME = "application_runtime"
    DIAGNOSTIC_DATA_SOURCE = "diagnostic_data_source"
    DIAGNOSTIC_QUEUE = "diagnostic_queue"
    DIAGNOSTIC_CACHE = "diagnostic_cache"
    DIAGNOSTIC_PERSISTENCE = "diagnostic_persistence"
    VERSION_COMPATIBILITY = "version_compatibility"


class SystemHealthComponentImpactClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class SystemHealthDiagnosticScope(str, Enum):
    DIAGNOSTIC_TASK = "diagnostic_task"
    TASK_HANDLE = "task_handle"
    FORMAL_CAMPAIGN = "formal_diagnostic_campaign"
    STRATEGY_RUN = "strategy_run"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"
    DIAGNOSTIC_FINDING = "diagnostic_finding"
    SENSITIVITY_BREAKPOINT = "sensitivity_breakpoint"
    REPRODUCTION_MANIFEST = "reproduction_manifest"


@dataclass(frozen=True, slots=True)
class SystemHealthDiagnosticContext:
    """Exact immutable correlation graph requested by the System Health surface."""

    task_id: DiagnosticTaskId
    task_revision: int
    configuration_content_id: DiagnosticTaskConfigurationContentId
    version: SystemHealthDiagnosticContextVersion = (
        SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION
    )
    task_handle_id: TaskHandleId | None = None
    campaign_id: FormalDiagnosticCampaignId | None = None
    campaign_revision: int | None = None
    run_id: StrategyRunId | None = None
    evidence_package_id: DiagnosticEvidencePackageId | None = None
    finding_id: FindingId | None = None
    sensitivity_breakpoint_id: SensitivityBreakpointId | None = None
    reproduction_manifest_id: ReproductionManifestId | None = None
    approved_recipe_version_ids: tuple[ApprovedScenarioRecipeVersionId, ...] = ()
    evidence_format_version: str | None = None
    manifest_format_version: str | None = None

    def __post_init__(self) -> None:
        expected = (
            ("task_id", self.task_id, DiagnosticTaskId),
            (
                "configuration_content_id",
                self.configuration_content_id,
                DiagnosticTaskConfigurationContentId,
            ),
            ("version", self.version, SystemHealthDiagnosticContextVersion),
            ("task_handle_id", self.task_handle_id, TaskHandleId),
            ("campaign_id", self.campaign_id, FormalDiagnosticCampaignId),
            ("run_id", self.run_id, StrategyRunId),
            (
                "evidence_package_id",
                self.evidence_package_id,
                DiagnosticEvidencePackageId,
            ),
            ("finding_id", self.finding_id, FindingId),
            (
                "sensitivity_breakpoint_id",
                self.sensitivity_breakpoint_id,
                SensitivityBreakpointId,
            ),
            (
                "reproduction_manifest_id",
                self.reproduction_manifest_id,
                ReproductionManifestId,
            ),
        )
        for name, value, value_type in expected:
            if value is not None and not isinstance(value, value_type):
                raise TypeError(f"{name} must be a {value_type.__name__}")
        if (
            not isinstance(self.task_revision, int)
            or isinstance(self.task_revision, bool)
            or self.task_revision < 1
        ):
            raise ValueError("task_revision must be positive")
        if (self.campaign_id is None) != (self.campaign_revision is None):
            raise ValueError(
                "campaign_id and campaign_revision must be provided together"
            )
        if self.campaign_revision is not None and (
            not isinstance(self.campaign_revision, int)
            or isinstance(self.campaign_revision, bool)
            or self.campaign_revision < 1
        ):
            raise ValueError("campaign_revision must be positive")
        if self.run_id is not None and self.campaign_id is None:
            raise ValueError("run_id requires campaign_id")
        if self.evidence_package_id is not None and self.run_id is None:
            raise ValueError("evidence_package_id requires run_id")
        if self.reproduction_manifest_id is not None and self.run_id is None:
            raise ValueError("reproduction_manifest_id requires run_id")
        if self.finding_id is not None and self.evidence_package_id is None:
            raise ValueError("finding_id requires evidence_package_id")
        if self.sensitivity_breakpoint_id is not None and self.finding_id is None:
            raise ValueError("sensitivity_breakpoint_id requires finding_id")
        if not isinstance(self.approved_recipe_version_ids, tuple) or any(
            not isinstance(item, ApprovedScenarioRecipeVersionId)
            for item in self.approved_recipe_version_ids
        ):
            raise TypeError(
                "approved_recipe_version_ids must be an immutable typed tuple"
            )
        if len(set(self.approved_recipe_version_ids)) != len(
            self.approved_recipe_version_ids
        ):
            raise ValueError("approved_recipe_version_ids must be unique")
        identities: list[tuple[str, str]] = [
            ("task_id", self.task_id.value),
            ("configuration_content_id", self.configuration_content_id.value),
        ]
        for label, item in (
            ("task_handle_id", self.task_handle_id),
            ("campaign_id", self.campaign_id),
            ("run_id", self.run_id),
            ("evidence_package_id", self.evidence_package_id),
            ("finding_id", self.finding_id),
            ("sensitivity_breakpoint_id", self.sensitivity_breakpoint_id),
            ("reproduction_manifest_id", self.reproduction_manifest_id),
        ):
            if item is not None:
                identities.append((label, item.value))
        for identity_label, identity_value in identities:
            _require_safe_diagnostic_identity(
                identity_value,
                f"diagnostic context {identity_label}",
            )
        for recipe_version_id in self.approved_recipe_version_ids:
            _require_safe_diagnostic_identity(
                recipe_version_id.value,
                "diagnostic context approved_recipe_version_id",
            )
        for format_label, format_value in (
            ("evidence_format_version", self.evidence_format_version),
            ("manifest_format_version", self.manifest_format_version),
        ):
            if format_value is not None:
                _require_safe_diagnostic_identity(
                    format_value,
                    f"diagnostic context {format_label}",
                )


@dataclass(frozen=True, slots=True)
class SystemHealthDiagnosticContextState:
    resolution: SystemHealthContextResolution
    requested: SystemHealthDiagnosticContext | None
    observed_task_revision: int | None
    observed_campaign_revision: int | None
    terminal: bool
    source_revision: str | None
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, SystemHealthContextResolution):
            raise TypeError("resolution must be a SystemHealthContextResolution")
        if self.requested is not None and not isinstance(
            self.requested,
            SystemHealthDiagnosticContext,
        ):
            raise TypeError("requested must be a SystemHealthDiagnosticContext")
        if (
            self.resolution is SystemHealthContextResolution.NO_CURRENT_TASK
        ) != (self.requested is None):
            if not (
                self.resolution is SystemHealthContextResolution.INCOMPATIBLE
                and self.requested is None
            ):
                raise ValueError("no-current-task must be represented explicitly")
        for label, value in (
            ("observed_task_revision", self.observed_task_revision),
            ("observed_campaign_revision", self.observed_campaign_revision),
        ):
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ValueError(f"{label} must be positive")
        expected_terminal = self.resolution in {
            SystemHealthContextResolution.FAILED,
            SystemHealthContextResolution.COMPLETED,
        }
        if not isinstance(self.terminal, bool) or self.terminal is not expected_terminal:
            raise ValueError("terminal must match failed/completed diagnostic state")
        if self.source_revision is not None:
            if (
                not isinstance(self.source_revision, str)
                or len(self.source_revision) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in self.source_revision
                )
            ):
                raise ValueError("source_revision must be a lowercase SHA-256")
        _require_safe_diagnostic_text(
            self.explanation,
            "System Health diagnostic context explanation",
        )


@dataclass(frozen=True, slots=True)
class SystemHealthComponentImpact:
    component: SystemHealthImpactComponentIdentity
    classification: SystemHealthComponentImpactClassification
    affected_scope: tuple[SystemHealthDiagnosticScope, ...]
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.component, SystemHealthImpactComponentIdentity):
            raise TypeError("component must be a SystemHealthImpactComponentIdentity")
        if not isinstance(
            self.classification,
            SystemHealthComponentImpactClassification,
        ):
            raise TypeError("classification must be a typed component impact")
        if not isinstance(self.affected_scope, tuple) or any(
            not isinstance(item, SystemHealthDiagnosticScope)
            for item in self.affected_scope
        ):
            raise TypeError("affected_scope must be an immutable typed tuple")
        if len(set(self.affected_scope)) != len(self.affected_scope):
            raise ValueError("affected_scope must be unique")
        _require_component_revision(self.revision, "component impact")


def _default_no_current_diagnostic_context() -> SystemHealthDiagnosticContextState:
    return SystemHealthDiagnosticContextState(
        resolution=SystemHealthContextResolution.NO_CURRENT_TASK,
        requested=None,
        observed_task_revision=None,
        observed_campaign_revision=None,
        terminal=False,
        source_revision=None,
        explanation="No current Diagnostic Task is selected.",
    )


@dataclass(frozen=True, slots=True)
class SystemHealthContext:
    """Optional typed diagnostic selection; ``None`` is no-current-task."""

    version: SystemHealthDiagnosticContextVersion = (
        SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION
    )
    diagnostic: SystemHealthDiagnosticContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.version, SystemHealthDiagnosticContextVersion):
            raise TypeError("version must be a SystemHealthDiagnosticContextVersion")
        if self.diagnostic is not None and not isinstance(
            self.diagnostic,
            SystemHealthDiagnosticContext,
        ):
            raise TypeError("diagnostic must be a SystemHealthDiagnosticContext")


_DIAGNOSTIC_CONTEXT_WIRE_KEYS = frozenset(
    {
        "version",
        "task_id",
        "task_revision",
        "configuration_content_id",
        "task_handle_id",
        "campaign_id",
        "campaign_revision",
        "run_id",
        "evidence_package_id",
        "finding_id",
        "sensitivity_breakpoint_id",
        "reproduction_manifest_id",
        "approved_recipe_version_ids",
        "evidence_format_version",
        "manifest_format_version",
    }
)

_DiagnosticIdentity: TypeAlias = (
    TaskHandleId
    | FormalDiagnosticCampaignId
    | StrategyRunId
    | DiagnosticEvidencePackageId
    | FindingId
    | SensitivityBreakpointId
    | ReproductionManifestId
)
_DiagnosticIdentityT = TypeVar(
    "_DiagnosticIdentityT",
    TaskHandleId,
    FormalDiagnosticCampaignId,
    StrategyRunId,
    DiagnosticEvidencePackageId,
    FindingId,
    SensitivityBreakpointId,
    ReproductionManifestId,
)


def encode_system_health_diagnostic_context(
    context: SystemHealthDiagnosticContext,
) -> str:
    if not isinstance(context, SystemHealthDiagnosticContext):
        raise TypeError("context must be a SystemHealthDiagnosticContext")

    def optional_value(value: _DiagnosticIdentity | None) -> str | None:
        return None if value is None else value.value

    payload = {
        "version": {"major": context.version.major, "minor": context.version.minor},
        "task_id": context.task_id.value,
        "task_revision": context.task_revision,
        "configuration_content_id": context.configuration_content_id.value,
        "task_handle_id": optional_value(context.task_handle_id),
        "campaign_id": optional_value(context.campaign_id),
        "campaign_revision": context.campaign_revision,
        "run_id": optional_value(context.run_id),
        "evidence_package_id": optional_value(context.evidence_package_id),
        "finding_id": optional_value(context.finding_id),
        "sensitivity_breakpoint_id": optional_value(
            context.sensitivity_breakpoint_id
        ),
        "reproduction_manifest_id": optional_value(
            context.reproduction_manifest_id
        ),
        "approved_recipe_version_ids": [
            item.value for item in context.approved_recipe_version_ids
        ],
        "evidence_format_version": context.evidence_format_version,
        "manifest_format_version": context.manifest_format_version,
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def decode_system_health_diagnostic_context(
    payload: str,
) -> SystemHealthDiagnosticContext:
    if not isinstance(payload, str) or not payload or len(payload) > 8192:
        raise ValueError("diagnostic context payload must be bounded JSON text")
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("diagnostic context payload must be valid JSON") from exc
    if not isinstance(raw, dict) or frozenset(raw) != _DIAGNOSTIC_CONTEXT_WIRE_KEYS:
        raise ValueError("diagnostic context payload has an invalid schema")
    version = raw["version"]
    if not isinstance(version, dict) or frozenset(version) != {"major", "minor"}:
        raise ValueError("diagnostic context version has an invalid schema")
    typed_version = SystemHealthDiagnosticContextVersion(
        major=version["major"],
        minor=version["minor"],
    )
    if typed_version != SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION:
        raise ValueError("diagnostic context version is incompatible")

    def required_text(name: str) -> str:
        value = raw[name]
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text")
        return value

    def optional_identity(
        name: str,
        value_type: type[_DiagnosticIdentityT],
    ) -> _DiagnosticIdentityT | None:
        value = raw[name]
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text or null")
        return value_type(value)

    recipe_versions = raw["approved_recipe_version_ids"]
    if not isinstance(recipe_versions, list) or any(
        not isinstance(item, str) for item in recipe_versions
    ):
        raise TypeError("approved_recipe_version_ids must be a JSON array of text")
    for name in ("evidence_format_version", "manifest_format_version"):
        if raw[name] is not None and not isinstance(raw[name], str):
            raise TypeError(f"{name} must be text or null")
    return SystemHealthDiagnosticContext(
        task_id=DiagnosticTaskId(required_text("task_id")),
        task_revision=raw["task_revision"],
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            required_text("configuration_content_id")
        ),
        version=typed_version,
        task_handle_id=optional_identity("task_handle_id", TaskHandleId),
        campaign_id=optional_identity("campaign_id", FormalDiagnosticCampaignId),
        campaign_revision=raw["campaign_revision"],
        run_id=optional_identity("run_id", StrategyRunId),
        evidence_package_id=optional_identity(
            "evidence_package_id", DiagnosticEvidencePackageId
        ),
        finding_id=optional_identity("finding_id", FindingId),
        sensitivity_breakpoint_id=optional_identity(
            "sensitivity_breakpoint_id", SensitivityBreakpointId
        ),
        reproduction_manifest_id=optional_identity(
            "reproduction_manifest_id", ReproductionManifestId
        ),
        approved_recipe_version_ids=tuple(
            ApprovedScenarioRecipeVersionId(item) for item in recipe_versions
        ),
        evidence_format_version=raw["evidence_format_version"],
        manifest_format_version=raw["manifest_format_version"],
    )


@dataclass(frozen=True, slots=True)
class SystemHealthViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    last_reliable_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: SystemHealthSource
    context: SystemHealthContext
    phase: ViewPhase
    presentation: SystemHealthPresentationState
    completeness: Completeness
    components: tuple[SystemHealthComponent, ...]
    last_reliable_payload: tuple[SystemHealthComponent, ...] | None
    recovery_phase: RuntimeHealthRecoveryPhase
    diagnostic_data_source: DiagnosticDataSourceHealthComponent
    diagnostic_queue: DiagnosticQueueHealthComponent
    diagnostic_cache: DiagnosticCacheHealthComponent
    error: SystemHealthError | None
    diagnostic_context: SystemHealthDiagnosticContextState = field(
        default_factory=_default_no_current_diagnostic_context
    )
    overall_classification: SystemHealthOverallClassification = (
        SystemHealthOverallClassification.UNKNOWN
    )
    component_impacts: tuple[SystemHealthComponentImpact, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("System Health view revision must be positive")
        _require_aware(self.observed_at, "System Health observation time")
        if self.last_reliable_at is not None:
            _require_aware(self.last_reliable_at, "last reliable time")
        if self.age < timedelta(0):
            raise ValueError("System Health age cannot be negative")
        if self.freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        if not isinstance(self.components, tuple):
            raise TypeError("System Health components must be an immutable tuple")
        component_types = (
            RuntimeHealthComponent,
            PersistenceHealthComponent,
            VersionHealthComponent,
        )
        if not all(isinstance(component, component_types) for component in self.components):
            raise TypeError("System Health components must be typed")
        if len(self.components) > 3:
            raise ValueError("System Health exposes three finite components")
        identities = tuple(component.identity for component in self.components)
        if len(set(identities)) != len(identities):
            raise ValueError("System Health component identities must be unique")
        expected_order = (
            SystemHealthComponentIdentity.APPLICATION_RUNTIME,
            SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE,
            SystemHealthComponentIdentity.VERSION_COMPATIBILITY,
        )
        if identities != tuple(item for item in expected_order if item in identities):
            raise ValueError("System Health components must use the finite order")
        if self.last_reliable_payload is not None and not isinstance(
            self.last_reliable_payload,
            tuple,
        ):
            raise TypeError("last reliable payload must be an immutable tuple")
        if self.last_reliable_payload is not None:
            if len(self.last_reliable_payload) > 3 or not all(
                isinstance(component, component_types)
                for component in self.last_reliable_payload
            ):
                raise TypeError("last reliable payload must contain typed components")
            payload_identities = tuple(
                component.identity for component in self.last_reliable_payload
            )
            if payload_identities != tuple(
                item for item in expected_order if item in payload_identities
            ):
                raise ValueError("last reliable payload must use the finite order")
        if not isinstance(self.diagnostic_queue, DiagnosticQueueHealthComponent):
            raise TypeError("diagnostic_queue must be typed")
        if not isinstance(
            self.diagnostic_data_source,
            DiagnosticDataSourceHealthComponent,
        ):
            raise TypeError("diagnostic_data_source must be typed")
        if not isinstance(self.diagnostic_cache, DiagnosticCacheHealthComponent):
            raise TypeError("diagnostic_cache must be typed")
        if not isinstance(
            self.diagnostic_context,
            SystemHealthDiagnosticContextState,
        ):
            raise TypeError("diagnostic_context must be typed")
        if not isinstance(
            self.overall_classification,
            SystemHealthOverallClassification,
        ):
            raise TypeError("overall_classification must be typed")
        if not isinstance(self.component_impacts, tuple) or any(
            not isinstance(item, SystemHealthComponentImpact)
            for item in self.component_impacts
        ):
            raise TypeError("component_impacts must be an immutable typed tuple")
        if self.component_impacts:
            if tuple(item.component for item in self.component_impacts) != tuple(
                SystemHealthImpactComponentIdentity
            ):
                raise ValueError("component_impacts must use the finite component order")
            if any(item.revision != self.revision for item in self.component_impacts):
                raise ValueError(
                    "component impact revisions must compose the System Health revision"
                )
        if (
            self.diagnostic_queue.revision != self.revision
            or self.diagnostic_cache.revision != self.revision
        ):
            raise ValueError(
                "Queue and Cache component revisions must compose the System Health revision"
            )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty")
    if len(value) > 512:
        raise ValueError(f"{label} must be bounded")


def _require_component_revision(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} revision must be positive")


def _require_freshness_window(age: timedelta, threshold: timedelta, label: str) -> None:
    if age < timedelta(0):
        raise ValueError(f"{label} age cannot be negative")
    if threshold <= timedelta(0):
        raise ValueError(f"{label} freshness threshold must be positive")


def _require_typed_scope(
    value: tuple[object, ...],
    enum_type: type[Enum],
    label: str,
) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{label} affected scope must be an immutable tuple")
    if not value or any(not isinstance(item, enum_type) for item in value):
        raise ValueError(f"{label} affected scope must be finite and typed")


def _require_safe_identity(value: str, label: str) -> None:
    _require_safe_text(value, label)
    lowered = value.casefold()
    if (
        "\\" in value
        or "://" in lowered
        or "\n" in value
        or "\r" in value
        or any(marker in lowered for marker in ("token=", "password=", "secret="))
    ):
        raise ValueError(f"{label} must be a safe redacted identity")


def _require_safe_diagnostic_identity(value: str, label: str) -> None:
    _require_safe_identity(value, label)
    lowered = value.casefold()
    if (
        not value.isascii()
        or "/" in value
        or any(
            not (character.isalnum() or character in "-_.:")
            for character in value
        )
        or any(
            marker in lowered
            for marker in (
                "sqlite",
                "authorization",
                "bearer",
                "api_key",
                "apikey",
                "credential",
                "cookie",
                "password",
                "secret",
                "token",
            )
        )
    ):
        raise ValueError(f"{label} must be a safe redacted identity")


def _require_safe_correlation_identity(value: str, label: str) -> None:
    _require_safe_text(value, label)
    lowered = value.casefold()
    if (
        not value.isascii()
        or not value[0].isalnum()
        or "-" not in value
        or any(
            not (character.isalnum() or character == "-")
            for character in value
        )
        or any(
            marker in lowered
            for marker in (
                "select",
                "insert",
                "update",
                "delete",
                "sqlite",
                "table",
                "token",
                "password",
                "secret",
            )
        )
    ):
        raise ValueError(f"{label} must be an opaque redacted identity")


def _require_safe_diagnostic_text(value: str, label: str) -> None:
    _require_safe_text(value, label)
    lowered = value.casefold()
    if (
        "\\" in value
        or "://" in lowered
        or ":/" in lowered
        or any(
            marker in lowered
            for marker in (
                "traceback",
                "select ",
                "insert ",
                "update ",
                "delete from ",
                "token=",
                "password=",
                "secret=",
                ".sqlite",
                ".sqlite3",
                ".db",
            )
        )
    ):
        raise ValueError(f"{label} must be a safe redacted explanation")


def _require_safe_source_label(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 96:
        raise ValueError(f"Data Source {label} must be a safe public label")
    if label == "provider" and value == "BaoStock":
        return
    prefix = label.title() + " "
    if not value.startswith(prefix):
        raise ValueError(f"Data Source {label} must be opaque")
    suffix = value[len(prefix) :]
    if len(suffix) != 8 or any(
        character not in "0123456789abcdef" for character in suffix
    ):
        raise ValueError(f"Data Source {label} must be opaque")


SystemHealthObserver = Callable[[SystemHealthViewState], None]


@runtime_checkable
class SystemHealthFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(
        self,
        context: "SystemHealthContext",
    ) -> "SystemHealthViewState": ...

    def subscribe(
        self,
        context: "SystemHealthContext",
        observer: SystemHealthObserver,
    ) -> Subscription: ...

    def close(self) -> None: ...


__all__ = [
    "DiagnosticDataSourceComponentIdentity",
    "DiagnosticDataSourceConnectionState",
    "DiagnosticDataSourceFallbackState",
    "DiagnosticDataSourceHealthClassification",
    "DiagnosticDataSourceHealthComponent",
    "DiagnosticDataSourceIdentity",
    "DiagnosticDataSourceObservation",
    "DiagnosticDataSourceRecoveryPhase",
    "DiagnosticDataSourceRevision",
    "DiagnosticDataSourceScope",
    "DiagnosticCacheCompatibility",
    "DiagnosticCacheFallbackState",
    "DiagnosticCacheHealthClassification",
    "DiagnosticCacheHealthComponent",
    "DiagnosticCacheLastRefreshResult",
    "DiagnosticCacheRecoveryPhase",
    "DiagnosticCacheScope",
    "DiagnosticQueueBlockageReason",
    "DiagnosticQueueConsumerAvailability",
    "DiagnosticQueueHealthClassification",
    "DiagnosticQueueHealthComponent",
    "DiagnosticQueueRecoveryPhase",
    "DiagnosticQueueScope",
    "HealthCompatibilityState",
    "PersistenceAvailability",
    "PersistenceHealthComponent",
    "PersistenceReopenVerification",
    "RuntimeHealthClassification",
    "RuntimeHealthComponent",
    "RuntimeHealthComponentIdentity",
    "RuntimeHealthRecoveryPhase",
    "SystemHealthAffectedScope",
    "SystemHealthComponentIdentity",
    "SystemHealthComponent",
    "SystemHealthComponentImpact",
    "SystemHealthComponentImpactClassification",
    "SystemHealthContext",
    "SystemHealthContextResolution",
    "SYSTEM_HEALTH_DIAGNOSTIC_CONTEXT_VERSION",
    "SystemHealthDiagnosticContext",
    "SystemHealthDiagnosticContextState",
    "SystemHealthDiagnosticContextVersion",
    "SystemHealthDiagnosticScope",
    "SystemHealthError",
    "SystemHealthErrorCode",
    "SystemHealthFeature",
    "SystemHealthObserver",
    "SystemHealthPresentationState",
    "SystemHealthRecoveryExpectation",
    "SystemHealthImpactComponentIdentity",
    "SystemHealthOverallClassification",
    "SystemHealthSource",
    "SystemHealthViewState",
    "VersionHealthComponent",
    "decode_system_health_diagnostic_context",
    "encode_system_health_diagnostic_context",
]
