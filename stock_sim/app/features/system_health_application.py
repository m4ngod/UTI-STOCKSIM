"""Feature-specific System Health Application Interface 1.0."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ._diagnostics_application_access import (
    shared_diagnostics_application_access_gate,
)
from .diagnostics_application_ownership import (
    DiagnosticsApplicationIdentity,
    diagnostics_application_identity,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .system_health import (
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheLastRefreshResult,
    DiagnosticCacheScope,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticQueueScope,
    DiagnosticDataSourceIdentity,
    DiagnosticDataSourceScope,
    RuntimeHealthClassification,
    HealthCompatibilityState,
    PersistenceAvailability,
    PersistenceReopenVerification,
)
from .versioning import ACTIVE_FEATURE_INTERFACES, FeatureInterfaceDescriptor

from strategy_diagnostics.diagnostic_evidence import (
    DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
)
from strategy_diagnostics.persistence import (
    DIAGNOSTIC_SCHEMA_REVISION,
    DiagnosticPersistenceAvailability,
    DiagnosticPersistenceCompatibility,
    DiagnosticPersistenceReopenState,
)
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION
from strategy_diagnostics.versioning import STRATEGY_DIAGNOSTICS_RUNNER_VERSION
from stock_sim import __version__ as STOCK_SIM_VERSION

if TYPE_CHECKING:
    from strategy_diagnostics.application import DiagnosticsApplication


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationVersion:
    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION = RuntimeHealthApplicationVersion(
    major=1,
    minor=0,
)


class RuntimeHealthApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class RuntimeHealthApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "runtime_health_no_authoritative_observation"
    READ_FAILED = "runtime_health_read_failed"
    PERSISTENCE_NOT_INITIALIZED = "persistence_health_not_initialized"
    PERSISTENCE_READ_FAILED = "persistence_health_read_failed"
    PERSISTENCE_SCHEMA_INCOMPATIBLE = "persistence_schema_incompatible"
    VERSION_READ_FAILED = "version_health_read_failed"
    DEPENDENCY_LOCK_UNAVAILABLE = "dependency_lock_unavailable"
    RELEASE_MANIFEST_UNAVAILABLE = "release_manifest_unavailable"
    RELEASE_MANIFEST_INCOMPATIBLE = "release_manifest_incompatible"
    MANIFEST_INCOMPATIBLE = "reproduction_manifest_incompatible"
    MANIFEST_UNAVAILABLE = "reproduction_manifest_unavailable"


class DiagnosticQueueApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class DiagnosticQueueApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "diagnostic_queue_no_authoritative_observation"
    READ_FAILED = "diagnostic_queue_read_failed"


class DiagnosticCacheApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class DiagnosticCacheApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "diagnostic_cache_no_authoritative_observation"
    READ_FAILED = "diagnostic_cache_read_failed"


class DiagnosticDataSourceApplicationAvailability(str, Enum):
    READY = "ready"
    NO_ADMITTED_SOURCE = "no_admitted_source"
    FAILED = "failed"


class DiagnosticDataSourceApplicationErrorCode(str, Enum):
    NO_ADMITTED_SOURCE = "diagnostic_data_source_no_admitted_source"
    READ_FAILED = "diagnostic_data_source_read_failed"


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceApplicationError:
    code: DiagnosticDataSourceApplicationErrorCode
    explanation: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticDataSourceApplicationErrorCode):
            raise TypeError("code must be a Data Source application error code")
        _require_safe_text(self.explanation, "Diagnostic Data Source error")


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceApplicationObservation:
    identity: DiagnosticDataSourceIdentity
    observed_at: datetime
    affected_scope: tuple[DiagnosticDataSourceScope, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, DiagnosticDataSourceIdentity):
            raise TypeError("identity must be a Data Source identity")
        _require_aware(self.observed_at)
        if (
            not isinstance(self.affected_scope, tuple)
            or not self.affected_scope
            or not all(
                isinstance(item, DiagnosticDataSourceScope)
                for item in self.affected_scope
            )
        ):
            raise TypeError("affected_scope must be immutable and typed")


@dataclass(frozen=True, slots=True)
class DiagnosticDataSourceApplicationResult:
    availability: DiagnosticDataSourceApplicationAvailability
    observation: DiagnosticDataSourceApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticDataSourceApplicationError | None

    def __post_init__(self) -> None:
        _validate_application_result(
            self.availability,
            DiagnosticDataSourceApplicationAvailability.READY,
            self.observation,
            self.source_token,
            self.error,
            "Diagnostic Data Source",
        )
        _require_aware(self.observed_at)


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationError:
    code: RuntimeHealthApplicationErrorCode
    explanation: str
    retryable: bool
    correlation_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, RuntimeHealthApplicationErrorCode):
            raise TypeError("code must be a RuntimeHealthApplicationErrorCode")
        if not self.explanation.strip() or len(self.explanation) > 512:
            raise ValueError("Runtime Health error explanation must be bounded")


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationObservation:
    classification: RuntimeHealthClassification
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        _require_aware(self.observed_at)
        if not self.explanation.strip() or len(self.explanation) > 512:
            raise ValueError("Runtime Health explanation must be bounded")


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationResult:
    availability: RuntimeHealthApplicationAvailability
    observation: RuntimeHealthApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: RuntimeHealthApplicationError | None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, RuntimeHealthApplicationAvailability):
            raise TypeError(
                "availability must be a RuntimeHealthApplicationAvailability"
            )
        _require_aware(self.observed_at)
        if self.availability is RuntimeHealthApplicationAvailability.READY:
            if self.observation is None or self.source_token is None:
                raise ValueError("Ready Runtime Health requires an observation")
            if self.error is not None:
                raise ValueError("Ready Runtime Health cannot carry an error")
        elif self.observation is not None:
            raise ValueError("Unavailable Runtime Health cannot carry an observation")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationError:
    code: DiagnosticQueueApplicationErrorCode
    explanation: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticQueueApplicationErrorCode):
            raise TypeError("code must be a DiagnosticQueueApplicationErrorCode")
        _require_safe_text(self.explanation, "Diagnostic Queue error")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationObservation:
    pending_count: int
    running_count: int
    blocked_count: int
    oldest_pending_at: datetime | None
    consumer_availability: DiagnosticQueueConsumerAvailability
    blockage_reason: DiagnosticQueueBlockageReason
    affected_scope: tuple[DiagnosticQueueScope, ...]
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        for count in (self.pending_count, self.running_count, self.blocked_count):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("Diagnostic Queue counts must be non-negative")
        if self.oldest_pending_at is not None:
            _require_aware(self.oldest_pending_at)
        if not isinstance(self.consumer_availability, DiagnosticQueueConsumerAvailability):
            raise TypeError("consumer availability must be typed")
        if not isinstance(self.blockage_reason, DiagnosticQueueBlockageReason):
            raise TypeError("blockage reason must be typed")
        if not self.affected_scope or any(
            not isinstance(item, DiagnosticQueueScope)
            for item in self.affected_scope
        ):
            raise ValueError("affected scope must be finite and typed")
        _require_aware(self.observed_at)
        _require_safe_text(self.explanation, "Diagnostic Queue explanation")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationResult:
    availability: DiagnosticQueueApplicationAvailability
    observation: DiagnosticQueueApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticQueueApplicationError | None

    def __post_init__(self) -> None:
        _validate_application_result(
            self.availability,
            DiagnosticQueueApplicationAvailability.READY,
            self.observation,
            self.source_token,
            self.error,
            "Diagnostic Queue",
        )
        _require_aware(self.observed_at)


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationError:
    code: DiagnosticCacheApplicationErrorCode
    explanation: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticCacheApplicationErrorCode):
            raise TypeError("code must be a DiagnosticCacheApplicationErrorCode")
        _require_safe_text(self.explanation, "Diagnostic Cache error")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationObservation:
    generation: int | None
    fallback: DiagnosticCacheFallbackState
    last_refresh_result: DiagnosticCacheLastRefreshResult
    compatibility: DiagnosticCacheCompatibility
    affected_scope: tuple[DiagnosticCacheScope, ...]
    last_refresh_at: datetime
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.generation is not None and self.generation < 1:
            raise ValueError("Diagnostic Cache generation must be positive")
        if not isinstance(self.fallback, DiagnosticCacheFallbackState):
            raise TypeError("fallback must be typed")
        if not isinstance(self.last_refresh_result, DiagnosticCacheLastRefreshResult):
            raise TypeError("last refresh result must be typed")
        if not isinstance(self.compatibility, DiagnosticCacheCompatibility):
            raise TypeError("compatibility must be typed")
        if not self.affected_scope or any(
            not isinstance(item, DiagnosticCacheScope)
            for item in self.affected_scope
        ):
            raise ValueError("affected scope must be finite and typed")
        _require_aware(self.last_refresh_at)
        _require_aware(self.observed_at)
        _require_safe_text(self.explanation, "Diagnostic Cache explanation")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationResult:
    availability: DiagnosticCacheApplicationAvailability
    observation: DiagnosticCacheApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticCacheApplicationError | None

    def __post_init__(self) -> None:
        _validate_application_result(
            self.availability,
            DiagnosticCacheApplicationAvailability.READY,
            self.observation,
            self.source_token,
            self.error,
            "Diagnostic Cache",
        )
        _require_aware(self.observed_at)


@dataclass(frozen=True, slots=True)
class PersistenceHealthApplicationObservation:
    availability: PersistenceAvailability
    schema_compatibility: HealthCompatibilityState
    schema_head: str | None
    supported_schema_head: str
    last_successful_durable_read_at: datetime | None
    last_successful_durable_write_at: datetime | None
    reopen_verification: PersistenceReopenVerification
    observed_at: datetime
    error: RuntimeHealthApplicationError | None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, PersistenceAvailability):
            raise TypeError("availability must be a PersistenceAvailability")
        if not isinstance(self.schema_compatibility, HealthCompatibilityState):
            raise TypeError("schema_compatibility must be typed")
        _require_aware(self.observed_at)
        for value in (
            self.last_successful_durable_read_at,
            self.last_successful_durable_write_at,
        ):
            if value is not None:
                _require_aware(value)
        if not isinstance(self.reopen_verification, PersistenceReopenVerification):
            raise TypeError("reopen_verification must be typed")


@dataclass(frozen=True, slots=True)
class VersionHealthApplicationObservation:
    product_build: str
    feature_interfaces: tuple[FeatureInterfaceDescriptor, ...]
    dependency_lock_identity: str | None
    release_manifest_compatibility: HealthCompatibilityState
    runner_version: str
    schema_version: str
    evidence_format_version: str
    manifest_format_version: str
    reproduction_manifest_compatibility: HealthCompatibilityState
    observed_at: datetime
    error: RuntimeHealthApplicationError | None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at)
        if not isinstance(self.feature_interfaces, tuple) or not all(
            isinstance(item, FeatureInterfaceDescriptor)
            for item in self.feature_interfaces
        ):
            raise TypeError("feature_interfaces must be an immutable typed tuple")
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


@runtime_checkable
class StrategyDiagnosticsV1SystemHealthApplication(Protocol):
    @property
    def interface_version(self) -> RuntimeHealthApplicationVersion: ...

    def read_runtime_health(self) -> RuntimeHealthApplicationResult: ...

    def read_diagnostic_data_source_health(
        self,
    ) -> DiagnosticDataSourceApplicationResult: ...

    def read_diagnostic_queue_health(
        self,
    ) -> DiagnosticQueueApplicationResult: ...

    def read_diagnostic_cache_health(
        self,
    ) -> DiagnosticCacheApplicationResult: ...

    def read_persistence_health(
        self,
    ) -> PersistenceHealthApplicationObservation: ...

    def read_version_health(self) -> VersionHealthApplicationObservation: ...


class LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter:
    """Translate the real DiagnosticsApplication lifecycle to safe typed health."""

    def __init__(
        self,
        application: DiagnosticsApplication,
        *,
        clock: Callable[[], datetime] | None = None,
        current_manifest_format_provider: Callable[[], str | None] | None = None,
        release_manifest_provider: (
            Callable[[], Mapping[str, object] | None] | None
        ) = None,
        dependency_lock_path: Path | None = None,
        product_build: str | None = None,
    ) -> None:
        self._application = application
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._application_access_gate = (
            shared_diagnostics_application_access_gate(application)
        )
        self._current_manifest_format_provider = (
            current_manifest_format_provider
            or (lambda: _selected_reproduction_manifest_format(application))
        )
        self._release_manifest_provider = (
            release_manifest_provider or _selected_release_manifest
        )
        self._dependency_lock_path = dependency_lock_path or (
            Path(__file__).resolve().parents[2]
            / "stock_sim"
            / "release"
            / "frontend_v2_toolchain.lock.json"
        )
        self._product_build = product_build or _installed_product_build()

    @property
    def interface_version(self) -> RuntimeHealthApplicationVersion:
        return RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION

    @property
    def application_identity(self) -> DiagnosticsApplicationIdentity:
        return diagnostics_application_identity(self._application)

    def read_runtime_health(self) -> RuntimeHealthApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                state = self._application.status()
        except RuntimeError:
            return _application_failure(
                observed_at=observed_at,
                availability=(
                    RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    RuntimeHealthApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Runtime Health observation is available."
                ),
                retryable=True,
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _application_failure(
                observed_at=observed_at,
                availability=RuntimeHealthApplicationAvailability.FAILED,
                code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Runtime Health read failed safely.",
                retryable=True,
            )

        normalized = str(state.status).strip().casefold()
        classification = (
            RuntimeHealthClassification.HEALTHY
            if normalized == "ready"
            else RuntimeHealthClassification.DEGRADED
            if normalized == "degraded"
            else RuntimeHealthClassification.UNAVAILABLE
        )
        explanation = (
            "Diagnostics runtime is ready."
            if classification is RuntimeHealthClassification.HEALTHY
            else "Diagnostics runtime reports degraded availability."
            if classification is RuntimeHealthClassification.DEGRADED
            else "Diagnostics runtime is unavailable."
        )
        token = hashlib.sha256(
            f"runtime-health|{normalized}|{state.workspace}".encode("utf-8")
        ).hexdigest()
        return RuntimeHealthApplicationResult(
            availability=RuntimeHealthApplicationAvailability.READY,
            observation=RuntimeHealthApplicationObservation(
                classification=classification,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(token),
            observed_at=observed_at,
            error=None,
        )

    def read_diagnostic_data_source_health(
        self,
    ) -> DiagnosticDataSourceApplicationResult:
        read_at = self._clock()
        _require_aware(read_at)
        try:
            with self._application_access_gate:
                segments = tuple(self._application.list_historical_segments())
        except RuntimeError:
            return _data_source_application_failure(
                observed_at=read_at,
                availability=(
                    DiagnosticDataSourceApplicationAvailability.NO_ADMITTED_SOURCE
                ),
                code=DiagnosticDataSourceApplicationErrorCode.NO_ADMITTED_SOURCE,
                explanation="No admitted diagnostic data source is available.",
            )
        except Exception:  # noqa: BLE001 - redact backend failures at the seam
            return _data_source_application_failure(
                observed_at=read_at,
                availability=DiagnosticDataSourceApplicationAvailability.FAILED,
                code=DiagnosticDataSourceApplicationErrorCode.READ_FAILED,
                explanation=(
                    "The authoritative diagnostic data-source read failed safely."
                ),
            )
        if not segments:
            return _data_source_application_failure(
                observed_at=read_at,
                availability=(
                    DiagnosticDataSourceApplicationAvailability.NO_ADMITTED_SOURCE
                ),
                code=DiagnosticDataSourceApplicationErrorCode.NO_ADMITTED_SOURCE,
                explanation="No admitted diagnostic data source is available.",
            )
        try:
            provenance = max(
                (segment.source_provenance for segment in segments),
                key=lambda item: item.observed_at,
            )
            token = hashlib.sha256(
                "|".join(
                    sorted(
                        f"{segment.segment_id}:{segment.content_hash}:"
                        f"{segment.source_snapshot_id}"
                        for segment in segments
                    )
                ).encode("utf-8")
            ).hexdigest()
            identity = DiagnosticDataSourceIdentity(
                public_id=f"admitted-source-{token[:16]}",
                provider=_safe_provider_label(provenance.provider),
                dataset=_opaque_source_label("Dataset", provenance.dataset),
                version=_opaque_source_label("Version", provenance.version),
            )
            return DiagnosticDataSourceApplicationResult(
                availability=DiagnosticDataSourceApplicationAvailability.READY,
                observation=DiagnosticDataSourceApplicationObservation(
                    identity=identity,
                    observed_at=provenance.observed_at,
                    affected_scope=(
                        DiagnosticDataSourceScope.SCENARIO_INPUTS,
                        DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
                    ),
                ),
                source_token=SourceRevisionToken(token),
                observed_at=read_at,
                error=None,
            )
        except Exception:  # noqa: BLE001 - redact malformed source metadata
            return _data_source_application_failure(
                observed_at=read_at,
                availability=DiagnosticDataSourceApplicationAvailability.FAILED,
                code=DiagnosticDataSourceApplicationErrorCode.READ_FAILED,
                explanation=(
                    "The authoritative diagnostic data-source read failed safely."
                ),
            )

    def read_diagnostic_queue_health(self) -> DiagnosticQueueApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                summary = self._application.diagnostic_task_queue_health()
        except RuntimeError:
            return _queue_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticQueueApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticQueueApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Queue observation is available."
                ),
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _queue_application_failure(
                observed_at=observed_at,
                availability=DiagnosticQueueApplicationAvailability.FAILED,
                code=DiagnosticQueueApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Diagnostic Queue read failed safely.",
            )

        pending_count = summary.pending_count
        running_count = summary.running_count
        blocked_count = summary.blocked_count
        if blocked_count:
            consumer_availability = DiagnosticQueueConsumerAvailability.BLOCKED
            blockage_reason = DiagnosticQueueBlockageReason.PAUSED_DIAGNOSTIC_WORK
            explanation = "Diagnostic work is paused at a supported lifecycle boundary."
        elif pending_count and not running_count:
            consumer_availability = DiagnosticQueueConsumerAvailability.UNKNOWN
            blockage_reason = DiagnosticQueueBlockageReason.RECOVERY_REQUIRED
            explanation = "Diagnostic work is queued and awaiting a consumer observation."
        else:
            consumer_availability = DiagnosticQueueConsumerAvailability.AVAILABLE
            blockage_reason = DiagnosticQueueBlockageReason.NONE
            explanation = (
                "The Diagnostic Queue is empty and available."
                if not (pending_count or running_count or blocked_count)
                else "Diagnostic work is being consumed without a reported blockage."
            )
        scope_by_kind = {
            "diagnostic_task": DiagnosticQueueScope.DIAGNOSTIC_TASK,
            "formal_diagnostic_campaign": (
                DiagnosticQueueScope.FORMAL_DIAGNOSTIC_CAMPAIGN
            ),
            "campaign_node": DiagnosticQueueScope.CAMPAIGN_NODES,
        }
        affected_scope = tuple(
            scope_by_kind[item.value]
            for item in summary.affected_target_kinds
        )
        token_content = (
            "diagnostic-queue",
            summary.revision,
            pending_count,
            running_count,
            blocked_count,
            consumer_availability.value,
            blockage_reason.value,
            (
                None
                if summary.oldest_pending_at is None
                else summary.oldest_pending_at.isoformat()
            ),
            tuple(item.value for item in affected_scope),
        )
        return DiagnosticQueueApplicationResult(
            availability=DiagnosticQueueApplicationAvailability.READY,
            observation=DiagnosticQueueApplicationObservation(
                pending_count=pending_count,
                running_count=running_count,
                blocked_count=blocked_count,
                oldest_pending_at=summary.oldest_pending_at,
                consumer_availability=consumer_availability,
                blockage_reason=blockage_reason,
                affected_scope=affected_scope,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(token_content).encode("utf-8")).hexdigest()
            ),
            observed_at=observed_at,
            error=None,
        )

    def read_diagnostic_cache_health(self) -> DiagnosticCacheApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                snapshot = self._application.diagnostic_cache_health()
        except RuntimeError:
            return _cache_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticCacheApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Cache observation is available."
                ),
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _cache_application_failure(
                observed_at=observed_at,
                availability=DiagnosticCacheApplicationAvailability.FAILED,
                code=DiagnosticCacheApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Diagnostic Cache read failed safely.",
            )
        if snapshot is None or snapshot.observed_at is None:
            return _cache_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticCacheApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Cache observation is available."
                ),
            )
        fallback = DiagnosticCacheFallbackState(snapshot.fallback.value)
        refresh_result = DiagnosticCacheLastRefreshResult(
            snapshot.last_refresh_result.value
        )
        compatibility = DiagnosticCacheCompatibility(snapshot.compatibility.value)
        explanation = _cache_explanation(
            fallback=fallback,
            refresh_result=refresh_result,
            compatibility=compatibility,
        )
        token_content = (
            "diagnostic-cache",
            snapshot.generation,
            snapshot.observed_at.isoformat(),
            fallback.value,
            refresh_result.value,
            compatibility.value,
            snapshot.affected_artifact_count,
        )
        return DiagnosticCacheApplicationResult(
            availability=DiagnosticCacheApplicationAvailability.READY,
            observation=DiagnosticCacheApplicationObservation(
                generation=(
                    None if snapshot.generation < 1 else snapshot.generation
                ),
                fallback=fallback,
                last_refresh_result=refresh_result,
                compatibility=compatibility,
                affected_scope=(
                    DiagnosticCacheScope.REFERENCE_MARKET_PATHS,
                    DiagnosticCacheScope.DIAGNOSTIC_EVIDENCE,
                ),
                last_refresh_at=snapshot.observed_at,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(token_content).encode("utf-8")).hexdigest()
            ),
            observed_at=observed_at,
            error=None,
        )

    def read_persistence_health(
        self,
    ) -> PersistenceHealthApplicationObservation:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                result = self._application.read_diagnostic_persistence_health()
        except RuntimeError:
            return _persistence_application_failure(
                observed_at=observed_at,
                availability=PersistenceAvailability.UNKNOWN,
                code=RuntimeHealthApplicationErrorCode.PERSISTENCE_NOT_INITIALIZED,
                explanation=(
                    "No authoritative Diagnostic Persistence observation is available."
                ),
                retryable=True,
            )
        except Exception:  # noqa: BLE001 - discard raw persistence failure details
            return _persistence_application_failure(
                observed_at=observed_at,
                availability=PersistenceAvailability.UNAVAILABLE,
                code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                explanation="Diagnostic Persistence is unavailable.",
                retryable=True,
            )

        availability = {
            DiagnosticPersistenceAvailability.AVAILABLE: (
                PersistenceAvailability.AVAILABLE
            ),
            DiagnosticPersistenceAvailability.UNAVAILABLE: (
                PersistenceAvailability.UNAVAILABLE
            ),
            DiagnosticPersistenceAvailability.NOT_INITIALIZED: (
                PersistenceAvailability.UNKNOWN
            ),
        }[result.availability]
        compatibility = {
            DiagnosticPersistenceCompatibility.COMPATIBLE: (
                HealthCompatibilityState.COMPATIBLE
            ),
            DiagnosticPersistenceCompatibility.INCOMPATIBLE: (
                HealthCompatibilityState.INCOMPATIBLE
            ),
            DiagnosticPersistenceCompatibility.UNKNOWN: (
                HealthCompatibilityState.UNKNOWN
            ),
        }[result.compatibility]
        reopen = {
            DiagnosticPersistenceReopenState.VERIFIED: (
                PersistenceReopenVerification.VERIFIED
            ),
            DiagnosticPersistenceReopenState.NOT_YET_VERIFIED: (
                PersistenceReopenVerification.NOT_YET_VERIFIED
            ),
            DiagnosticPersistenceReopenState.FAILED: (
                PersistenceReopenVerification.FAILED
            ),
            DiagnosticPersistenceReopenState.UNKNOWN: (
                PersistenceReopenVerification.UNKNOWN
            ),
        }[result.reopen_state]
        error = None
        if compatibility is HealthCompatibilityState.INCOMPATIBLE:
            error = RuntimeHealthApplicationError(
                code=(
                    RuntimeHealthApplicationErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
                ),
                explanation=(
                    "Diagnostic Persistence schema is incompatible with this build."
                ),
                retryable=False,
            )
        elif availability is PersistenceAvailability.UNAVAILABLE:
            error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                explanation="Diagnostic Persistence is unavailable.",
                retryable=True,
            )
        elif availability is PersistenceAvailability.UNKNOWN:
            error = RuntimeHealthApplicationError(
                code=(
                    RuntimeHealthApplicationErrorCode.PERSISTENCE_NOT_INITIALIZED
                ),
                explanation=(
                    "No authoritative Diagnostic Persistence observation is available."
                ),
                retryable=True,
            )
        return PersistenceHealthApplicationObservation(
            availability=availability,
            schema_compatibility=compatibility,
            schema_head=result.schema_head,
            supported_schema_head=result.supported_schema_head,
            last_successful_durable_read_at=(
                result.last_successful_durable_read_at
            ),
            last_successful_durable_write_at=(
                result.last_successful_durable_write_at
            ),
            reopen_verification=reopen,
            observed_at=observed_at,
            error=error,
        )

    def read_version_health(self) -> VersionHealthApplicationObservation:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            lock_bytes = self._dependency_lock_path.read_bytes()
            lock_identity = "sha256:" + hashlib.sha256(lock_bytes).hexdigest()
            lock_payload = json.loads(lock_bytes)
            if not isinstance(lock_payload, dict):
                raise ValueError("dependency lock must be an object")
        except Exception:  # noqa: BLE001 - discard path and filesystem details
            return _version_application_failure(
                observed_at=observed_at,
                product_build=self._product_build,
                code=RuntimeHealthApplicationErrorCode.DEPENDENCY_LOCK_UNAVAILABLE,
                explanation="The dependency-lock identity is unavailable.",
                retryable=False,
            )
        try:
            with self._application_access_gate:
                release_manifest = self._release_manifest_provider()
                current_manifest_format = self._current_manifest_format_provider()
        except Exception:  # noqa: BLE001 - discard fixture/provider details
            return _version_application_failure(
                observed_at=observed_at,
                product_build=self._product_build,
                dependency_lock_identity=lock_identity,
                code=RuntimeHealthApplicationErrorCode.VERSION_READ_FAILED,
                explanation="Version compatibility facts are unavailable.",
                retryable=True,
            )
        if release_manifest is None:
            release_compatibility = HealthCompatibilityState.UNKNOWN
            release_error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_UNAVAILABLE,
                explanation="No authoritative release binding is available.",
                retryable=False,
            )
        elif (
            release_manifest.get("schema_version") != 1
            or release_manifest.get("toolchain_lock") != lock_payload
        ):
            release_compatibility = HealthCompatibilityState.INCOMPATIBLE
            release_error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_INCOMPATIBLE,
                explanation=(
                    "The release binding is incompatible with the dependency lock."
                ),
                retryable=False,
            )
        else:
            release_compatibility = HealthCompatibilityState.COMPATIBLE
            release_error = None
        if current_manifest_format is None:
            compatibility = HealthCompatibilityState.UNKNOWN
            manifest_error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.MANIFEST_UNAVAILABLE,
                explanation=(
                    "No current Reproduction Manifest compatibility fact is available."
                ),
                retryable=True,
            )
        elif current_manifest_format == REPRODUCTION_MANIFEST_SCHEMA_VERSION:
            compatibility = HealthCompatibilityState.COMPATIBLE
            manifest_error = None
        else:
            compatibility = HealthCompatibilityState.INCOMPATIBLE
            manifest_error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE,
                explanation=(
                    "The current Reproduction Manifest format is incompatible."
                ),
                retryable=False,
            )
        error = (
            manifest_error
            if compatibility is HealthCompatibilityState.INCOMPATIBLE
            else release_error
            if release_compatibility is HealthCompatibilityState.INCOMPATIBLE
            else manifest_error or release_error
        )
        return VersionHealthApplicationObservation(
            product_build=self._product_build,
            feature_interfaces=ACTIVE_FEATURE_INTERFACES,
            dependency_lock_identity=lock_identity,
            release_manifest_compatibility=release_compatibility,
            runner_version=STRATEGY_DIAGNOSTICS_RUNNER_VERSION,
            schema_version=DIAGNOSTIC_SCHEMA_REVISION,
            evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
            manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
            reproduction_manifest_compatibility=compatibility,
            observed_at=observed_at,
            error=error,
        )


def _application_failure(
    *,
    observed_at: datetime,
    availability: RuntimeHealthApplicationAvailability,
    code: RuntimeHealthApplicationErrorCode,
    explanation: str,
    retryable: bool,
) -> RuntimeHealthApplicationResult:
    return RuntimeHealthApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=RuntimeHealthApplicationError(
            code=code,
            explanation=explanation,
            retryable=retryable,
        ),
    )


def _queue_application_failure(
    *,
    observed_at: datetime,
    availability: DiagnosticQueueApplicationAvailability,
    code: DiagnosticQueueApplicationErrorCode,
    explanation: str,
) -> DiagnosticQueueApplicationResult:
    return DiagnosticQueueApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=DiagnosticQueueApplicationError(
            code=code,
            explanation=explanation,
            retryable=True,
        ),
    )


def _data_source_application_failure(
    *,
    observed_at: datetime,
    availability: DiagnosticDataSourceApplicationAvailability,
    code: DiagnosticDataSourceApplicationErrorCode,
    explanation: str,
) -> DiagnosticDataSourceApplicationResult:
    return DiagnosticDataSourceApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=DiagnosticDataSourceApplicationError(
            code=code,
            explanation=explanation,
            retryable=True,
        ),
    )


def _persistence_application_failure(
    *,
    observed_at: datetime,
    availability: PersistenceAvailability,
    code: RuntimeHealthApplicationErrorCode,
    explanation: str,
    retryable: bool,
) -> PersistenceHealthApplicationObservation:
    return PersistenceHealthApplicationObservation(
        availability=availability,
        schema_compatibility=HealthCompatibilityState.UNKNOWN,
        schema_head=None,
        supported_schema_head=DIAGNOSTIC_SCHEMA_REVISION,
        last_successful_durable_read_at=None,
        last_successful_durable_write_at=None,
        reopen_verification=PersistenceReopenVerification.UNKNOWN,
        observed_at=observed_at,
        error=RuntimeHealthApplicationError(
            code=code,
            explanation=explanation,
            retryable=retryable,
        ),
    )


def _cache_application_failure(
    *,
    observed_at: datetime,
    availability: DiagnosticCacheApplicationAvailability,
    code: DiagnosticCacheApplicationErrorCode,
    explanation: str,
) -> DiagnosticCacheApplicationResult:
    return DiagnosticCacheApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=DiagnosticCacheApplicationError(
            code=code,
            explanation=explanation,
            retryable=True,
        ),
    )


def _version_application_failure(
    *,
    observed_at: datetime,
    product_build: str,
    code: RuntimeHealthApplicationErrorCode,
    explanation: str,
    retryable: bool,
    dependency_lock_identity: str | None = None,
) -> VersionHealthApplicationObservation:
    return VersionHealthApplicationObservation(
        product_build=product_build,
        feature_interfaces=ACTIVE_FEATURE_INTERFACES,
        dependency_lock_identity=dependency_lock_identity,
        release_manifest_compatibility=HealthCompatibilityState.UNKNOWN,
        runner_version=STRATEGY_DIAGNOSTICS_RUNNER_VERSION,
        schema_version=DIAGNOSTIC_SCHEMA_REVISION,
        evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
        reproduction_manifest_compatibility=HealthCompatibilityState.UNKNOWN,
        observed_at=observed_at,
        error=RuntimeHealthApplicationError(
            code=code,
            explanation=explanation,
            retryable=retryable,
        ),
    )


def _cache_explanation(
    *,
    fallback: DiagnosticCacheFallbackState,
    refresh_result: DiagnosticCacheLastRefreshResult,
    compatibility: DiagnosticCacheCompatibility,
) -> str:
    if compatibility is DiagnosticCacheCompatibility.INCOMPATIBLE:
        return "The Diagnostic Cache observation is incompatible."
    if fallback is DiagnosticCacheFallbackState.ACTIVE:
        return "The Diagnostic Cache is serving a verified fallback."
    if refresh_result is DiagnosticCacheLastRefreshResult.FAILED:
        return "The Diagnostic Cache refresh failed safely."
    return "The Diagnostic Cache refresh completed successfully."


def _validate_application_result(
    availability: Enum,
    ready: Enum,
    observation: object | None,
    source_token: SourceRevisionToken | None,
    error: object | None,
    label: str,
) -> None:
    if availability is ready:
        if observation is None or source_token is None:
            raise ValueError(f"Ready {label} requires an observation")
        if error is not None:
            raise ValueError(f"Ready {label} cannot carry an error")
    elif observation is not None or source_token is not None or error is None:
        raise ValueError(f"Unavailable {label} must carry only a typed error")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{label} explanation must be bounded")


def _safe_provider_label(value: str) -> str:
    if value.strip().casefold() == "baostock":
        return "BaoStock"
    return _opaque_source_label("Provider", value)


def _opaque_source_label(prefix: str, value: str) -> str:
    digest = hashlib.sha256(
        f"diagnostic-source-label|{prefix}|{value}".encode("utf-8")
    ).hexdigest()
    return f"{prefix} {digest[:8]}"


def _installed_product_build() -> str:
    return f"stock-sim/{STOCK_SIM_VERSION}"


def _selected_reproduction_manifest_format(
    application: DiagnosticsApplication,
) -> str | None:
    evidence_package_id = os.environ.get(
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID",
        "",
    ).strip()
    manifest_id = os.environ.get(
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
        "",
    ).strip()
    if not evidence_package_id or not manifest_id:
        return None
    value = application.read_reproduction_manifest_format_identity(
        evidence_package_id,
        manifest_id,
    )
    return value if isinstance(value, str) else None


def _selected_release_manifest() -> Mapping[str, object] | None:
    manifest_path = os.environ.get(
        "STOCKSIM_FRONTEND_V2_RELEASE_MANIFEST_PATH",
        "",
    ).strip()
    if not manifest_path:
        return None
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime Health observation time must be timezone-aware")


__all__ = [
    "RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION",
    "DiagnosticCacheApplicationAvailability",
    "DiagnosticCacheApplicationError",
    "DiagnosticCacheApplicationErrorCode",
    "DiagnosticCacheApplicationObservation",
    "DiagnosticCacheApplicationResult",
    "DiagnosticDataSourceApplicationAvailability",
    "DiagnosticDataSourceApplicationError",
    "DiagnosticDataSourceApplicationErrorCode",
    "DiagnosticDataSourceApplicationObservation",
    "DiagnosticDataSourceApplicationResult",
    "DiagnosticQueueApplicationAvailability",
    "DiagnosticQueueApplicationError",
    "DiagnosticQueueApplicationErrorCode",
    "DiagnosticQueueApplicationObservation",
    "DiagnosticQueueApplicationResult",
    "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
    "PersistenceHealthApplicationObservation",
    "RuntimeHealthApplicationAvailability",
    "RuntimeHealthApplicationError",
    "RuntimeHealthApplicationErrorCode",
    "RuntimeHealthApplicationObservation",
    "RuntimeHealthApplicationResult",
    "RuntimeHealthApplicationVersion",
    "StrategyDiagnosticsV1SystemHealthApplication",
    "VersionHealthApplicationObservation",
]
