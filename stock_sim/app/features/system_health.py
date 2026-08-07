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
from .versioning import FeatureInterfaceVersion


class RuntimeHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RuntimeHealthComponentIdentity(str, Enum):
    APPLICATION_RUNTIME = "application_runtime"


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
    accepted_generation: SourceGenerationId
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
        if not isinstance(self.accepted_generation, SourceGenerationId):
            raise TypeError("accepted_generation must be a SourceGenerationId")
        if not isinstance(self.freshness, Freshness):
            raise TypeError("freshness must be a Freshness")
        if not isinstance(self.recovery_phase, DiagnosticDataSourceRecoveryPhase):
            raise TypeError("recovery_phase must be a Data Source recovery phase")
        _require_aware(self.observed_at, "Data Source Health observation time")
        if self.age < timedelta(0):
            raise ValueError("Data Source Health age cannot be negative")
        if self.freshness_threshold <= timedelta(0):
            raise ValueError("Data Source Health threshold must be positive")
        if not isinstance(self.affected_scope, tuple):
            raise TypeError("Data Source affected scope must be immutable")
        if not all(
            isinstance(item, DiagnosticDataSourceScope)
            for item in self.affected_scope
        ):
            raise TypeError("Data Source affected scope must be typed")
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
        _require_safe_text(self.explanation, "Data Source Health explanation")


class SystemHealthPresentationState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class SystemHealthErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "runtime_health_no_authoritative_observation"
    OBSERVATION_FAILED = "runtime_health_observation_failed"
    SOURCE_DISCONNECTED = "runtime_health_source_disconnected"
    AUTHORITATIVE_REREAD_FAILED = "runtime_health_authoritative_reread_failed"
    DATA_SOURCE_UNAVAILABLE = "diagnostic_data_source_unavailable"
    DATA_SOURCE_DISCONNECTED = "diagnostic_data_source_disconnected"
    DATA_SOURCE_REREAD_FAILED = "diagnostic_data_source_reread_failed"


@dataclass(frozen=True, slots=True)
class SystemHealthError:
    code: SystemHealthErrorCode
    explanation: str
    retryable: bool
    correlation_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, SystemHealthErrorCode):
            raise TypeError("code must be a SystemHealthErrorCode")
        _require_safe_text(self.explanation, "System Health explanation")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a bool")
        if self.correlation_identity is not None:
            _require_safe_text(
                self.correlation_identity,
                "System Health correlation identity",
            )


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    identity: RuntimeHealthComponentIdentity
    classification: RuntimeHealthClassification
    revision: int
    observed_at: datetime
    last_successful_observation_at: datetime | None
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RuntimeHealthComponentIdentity):
            raise TypeError("identity must be a RuntimeHealthComponentIdentity")
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
        _require_safe_text(self.explanation, "Runtime Health explanation")


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
    """The Runtime-only 1.0 context; contextual identity is deferred."""


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
    components: tuple[RuntimeHealthComponent, ...]
    diagnostic_data_source: DiagnosticDataSourceHealthComponent
    last_reliable_payload: RuntimeHealthComponent | None
    recovery_phase: RuntimeHealthRecoveryPhase
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
        if len(self.components) > 1:
            raise ValueError("System Health 1.0 exposes only Runtime Health")
        if self.components and self.components[0].identity is not (
            RuntimeHealthComponentIdentity.APPLICATION_RUNTIME
        ):
            raise ValueError("System Health 1.0 exposes only Runtime Health")
        if not isinstance(
            self.diagnostic_data_source,
            DiagnosticDataSourceHealthComponent,
        ):
            raise TypeError("System Health requires typed Data Source Health")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty")
    if len(value) > 512:
        raise ValueError(f"{label} must be bounded")


def _require_safe_source_label(value: str, label: str) -> None:
    _require_safe_text(value, f"Data Source {label}")
    normalized = value.casefold()
    forbidden = (
        "://",
        "\\",
        "/",
        "token",
        "cookie",
        "secret",
        "credential",
        "password",
        "connection string",
    )
    if any(marker in normalized for marker in forbidden):
        raise ValueError(f"Data Source {label} is not safe for presentation")


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
    "RuntimeHealthClassification",
    "RuntimeHealthComponent",
    "RuntimeHealthComponentIdentity",
    "RuntimeHealthRecoveryPhase",
    "SystemHealthContext",
    "SystemHealthError",
    "SystemHealthErrorCode",
    "SystemHealthFeature",
    "SystemHealthObserver",
    "SystemHealthPresentationState",
    "SystemHealthSource",
    "SystemHealthViewState",
]
