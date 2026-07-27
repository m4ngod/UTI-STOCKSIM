"""Typed read-model Seam between Strategy Diagnostics V1 and Frontend V2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from .evidence_and_findings import (
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceCoverage,
)
from .run_monitoring import (
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringData,
    StrategyRunId,
)


@dataclass(frozen=True, slots=True)
class ApplicationReadModelVersion:
    """Major/minor compatibility identity for the in-process read Seam."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.major, int)
            or not isinstance(self.minor, int)
            or self.major < 0
            or self.minor < 0
        ):
            raise ValueError("Application read-model version must be non-negative")

    def accepts(self, provider: ApplicationReadModelVersion) -> bool:
        return self.major == provider.major and provider.minor >= self.minor


APPLICATION_READ_MODEL_INTERFACE_VERSION = ApplicationReadModelVersion(1, 0)


@dataclass(frozen=True, slots=True)
class V1JourneySelector:
    campaign_id: FormalDiagnosticCampaignId
    run_id: StrategyRunId
    evidence_package_id: DiagnosticEvidencePackageId | None = None
    manifest_id: ReproductionManifestId | None = None

    def __post_init__(self) -> None:
        expected = (
            ("campaign_id", self.campaign_id, FormalDiagnosticCampaignId),
            ("run_id", self.run_id, StrategyRunId),
            (
                "evidence_package_id",
                self.evidence_package_id,
                DiagnosticEvidencePackageId,
            ),
            ("manifest_id", self.manifest_id, ReproductionManifestId),
        )
        for name, value, value_type in expected:
            if value is not None and not isinstance(value, value_type):
                raise TypeError(f"{name} must be a {value_type.__name__}")


@dataclass(frozen=True, slots=True)
class ResolvedV1Journey:
    run_context: RunMonitoringContext
    evidence_context: EvidenceAndFindingsContext
    evidence_package_id: DiagnosticEvidencePackageId | None
    campaign_case_id: MarketScenarioId
    campaign_layer: EvidenceCoverage


@dataclass(frozen=True, slots=True)
class SourceRevisionToken:
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 64
            or any(character not in "0123456789abcdef" for character in self.value)
        ):
            raise ValueError("Source revision token must be a lowercase SHA-256")


class ApplicationReadAvailability(str, Enum):
    READY = "ready"
    PENDING = "pending"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class ApplicationReadErrorCode(str, Enum):
    EVIDENCE_PENDING = "diagnostic_evidence_pending"
    EVIDENCE_SELECTION_AMBIGUOUS = "diagnostic_evidence_selection_ambiguous"
    EVIDENCE_MAPPING_FAILED = "diagnostic_evidence_mapping_failed"
    CONTRACT_INCOMPATIBLE = "strategy_diagnostics_contract_incompatible"
    IDENTITY_MISMATCH = "strategy_diagnostics_identity_mismatch"
    INTEGRITY_FAILED = "strategy_diagnostics_integrity_failed"
    READ_FAILED = "strategy_diagnostics_read_failed"
    RUN_NOT_IN_CAMPAIGN = "strategy_diagnostics_run_not_in_campaign"
    SELECTION_NOT_FOUND = "strategy_diagnostics_selection_not_found"


@dataclass(frozen=True, slots=True)
class ApplicationReadError:
    code: ApplicationReadErrorCode
    message: str
    retryable: bool
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ApplicationReadErrorCode):
            raise TypeError("code must be an ApplicationReadErrorCode")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("Application read error message cannot be empty")


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ApplicationReadResult(Generic[T]):
    availability: ApplicationReadAvailability
    source_token: SourceRevisionToken | None
    source_observed_at: datetime | None
    value: T | None
    error: ApplicationReadError | None

    def __post_init__(self) -> None:
        if (
            self.source_observed_at is not None
            and self.source_observed_at.tzinfo is None
        ):
            raise ValueError("source_observed_at must be timezone-aware")
        if self.availability is ApplicationReadAvailability.READY:
            if self.value is None or self.error is not None:
                raise ValueError("A ready read requires a value and no error")
        elif self.availability in (
            ApplicationReadAvailability.NOT_FOUND,
            ApplicationReadAvailability.FAILED,
        ):
            if self.value is not None or self.error is None:
                raise ValueError(
                    "A failed or not-found read requires an error and no value"
                )
        elif self.error is None:
            raise ValueError("A pending or partial read requires a structured error")


@runtime_checkable
class StrategyDiagnosticsV1ApplicationReadModel(Protocol):
    @property
    def interface_version(self) -> ApplicationReadModelVersion: ...

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]: ...

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]: ...

    def read_evidence(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[EvidenceAndFindingsData]: ...


__all__ = [
    "APPLICATION_READ_MODEL_INTERFACE_VERSION",
    "ApplicationReadAvailability",
    "ApplicationReadError",
    "ApplicationReadErrorCode",
    "ApplicationReadModelVersion",
    "ApplicationReadResult",
    "ResolvedV1Journey",
    "SourceRevisionToken",
    "StrategyDiagnosticsV1ApplicationReadModel",
    "V1JourneySelector",
]
