"""Read-only System Health Feature Interface 1.0 contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    Subscription,
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
class SystemHealthContext:
    """The read-only 1.0 context; diagnostic identity graph is deferred."""


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
    diagnostic_queue: DiagnosticQueueHealthComponent
    diagnostic_cache: DiagnosticCacheHealthComponent
    error: SystemHealthError | None

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
        if not isinstance(self.diagnostic_cache, DiagnosticCacheHealthComponent):
            raise TypeError("diagnostic_cache must be typed")
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
    "SystemHealthContext",
    "SystemHealthError",
    "SystemHealthErrorCode",
    "SystemHealthFeature",
    "SystemHealthObserver",
    "SystemHealthPresentationState",
    "SystemHealthRecoveryExpectation",
    "SystemHealthSource",
    "SystemHealthViewState",
    "VersionHealthComponent",
]
