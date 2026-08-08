"""Typed in-process Application Interface for Strategy Library 1.0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ._diagnostics_application_access import (
    shared_diagnostics_application_access_gate,
)
from .diagnostics_application_ownership import (
    DiagnosticsApplicationIdentity,
    diagnostics_application_identity,
)
from .diagnostic_tasks_application import GuardrailProfileId
from .run_monitoring import StrategyUnderTestId
from .strategy_diagnostics_v1_read_model import SourceRevisionToken

if TYPE_CHECKING:
    from strategy_diagnostics.application import DiagnosticsApplication
    from strategy_diagnostics.strategy_inventory import (
        StrategyUnderTestInventory,
        StrategyUnderTestInventoryEntry,
    )


@dataclass(frozen=True, slots=True)
class StrategyLibraryApplicationVersion:
    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION = (
    StrategyLibraryApplicationVersion(major=1, minor=0)
)


class StrategyAvailability(str, Enum):
    FORMAL_CAMPAIGN_READY = "formal_campaign_ready"
    UNAVAILABLE = "unavailable"
    OUTDATED = "outdated"
    INCOMPATIBLE = "incompatible"
    MISSING_DEPENDENCY = "missing_dependency"


class StrategyAvailabilityReasonCode(str, Enum):
    FORMAL_CAMPAIGN_READY = "formal_campaign_ready"
    APPLICATION_NOT_READY = "application_not_ready"
    SOURCE_BINDING_MISSING = "source_binding_missing"
    SOURCE_CONTENT_MISMATCH = "source_content_mismatch"
    PACKAGED_SOURCE_MISSING = "packaged_source_missing"
    COMPATIBILITY_SURFACE_OUTDATED = "compatibility_surface_outdated"
    COMPATIBILITY_MANIFEST_MISMATCH = "compatibility_manifest_mismatch"
    CANDIDATE_DATA_POLICY_INCOMPATIBLE = (
        "candidate_data_policy_incompatible"
    )
    GUARDRAIL_PROFILE_MISSING = "guardrail_profile_missing"
    GUARDRAIL_PROFILE_MISMATCH = "guardrail_profile_mismatch"
    REQUIRED_DEPENDENCY_MISSING = "required_dependency_missing"
    FORMAL_SELECTION_NOT_YET_AVAILABLE = (
        "formal_strategy_selection_not_yet_available"
    )
    FORMAL_STRATEGY_SET_INVALID = "formal_strategy_set_invalid"
    INVENTORY_SOURCE_CONFLICT = "inventory_source_conflict"


@dataclass(frozen=True, slots=True)
class StrategyAvailabilityReason:
    code: StrategyAvailabilityReasonCode
    summary: str
    corrective_guidance: str


@dataclass(frozen=True, slots=True)
class StrategyDisplayMetadata:
    display_name: str
    summary: str


@dataclass(frozen=True, slots=True)
class StrategySourceIdentity:
    module: str
    source_relative_path: str
    packaged_relative_path: str
    content_sha256: str
    lineage: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyCompatibilityManifest:
    surface_version: str
    content_hash: str
    lifecycle_callbacks: tuple[str, ...]
    scheduled_callbacks: tuple[str, ...]
    scheduling_calls: tuple[str, ...]
    context_fields: tuple[str, ...]
    portfolio_fields: tuple[str, ...]
    market_data_calls: tuple[str, ...]
    history_units: tuple[str, ...]
    configuration_calls: tuple[str, ...]
    trading_calls: tuple[str, ...]
    logging_calls: tuple[str, ...]

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return (
            self.lifecycle_callbacks
            + self.scheduled_callbacks
            + self.scheduling_calls
            + self.context_fields
            + self.portfolio_fields
            + self.market_data_calls
            + self.history_units
            + self.configuration_calls
            + self.trading_calls
            + self.logging_calls
        )


@dataclass(frozen=True, slots=True)
class StrategyGuardrailThreshold:
    metric_name: str
    operator: str
    value: str


@dataclass(frozen=True, slots=True)
class StrategyGuardrailProfile:
    strategy_id: StrategyUnderTestId
    strategy_version: str
    profile_id: GuardrailProfileId
    profile_version: str
    thresholds: tuple[StrategyGuardrailThreshold, ...]


class StrategyDependencyKind(str, Enum):
    RETAINED_SOURCE = "retained_source"
    PACKAGED_SOURCE = "packaged_source"
    COMPATIBILITY_MANIFEST = "compatibility_manifest"
    PTRADE_SURFACE = "ptrade_surface"
    CANDIDATE_DATA_POLICY = "candidate_data_policy"
    GUARDRAIL_PROFILE = "guardrail_profile"


@dataclass(frozen=True, slots=True)
class StrategyDependencyIdentity:
    kind: StrategyDependencyKind
    identity: str
    version: str
    content_hash: str
    available: bool
    compatible: bool


@dataclass(frozen=True, slots=True)
class StrategyLibraryEntry:
    strategy_id: StrategyUnderTestId
    strategy_version: str
    entity_revision: int
    display: StrategyDisplayMetadata
    source: StrategySourceIdentity
    compatibility: StrategyCompatibilityManifest
    candidate_data_policy: str
    guardrail_profile: StrategyGuardrailProfile | None
    dependencies: tuple[StrategyDependencyIdentity, ...]
    required_for_v1_formal_campaign: bool
    formal_campaign_eligible: bool
    availability: StrategyAvailability
    availability_reasons: tuple[StrategyAvailabilityReason, ...]


@dataclass(frozen=True, slots=True)
class StrategyLibraryInventory:
    entries: tuple[StrategyLibraryEntry, ...]
    formal_campaign_required_strategy_count: int
    persistence_migration_revision: str


class StrategyLibraryApplicationAvailability(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILED = "failed"


class StrategyLibraryApplicationErrorCode(str, Enum):
    INVENTORY_READ_FAILED = "strategy_library_inventory_read_failed"
    APPLICATION_NOT_READY = "strategy_library_application_not_ready"


@dataclass(frozen=True, slots=True)
class StrategyLibraryApplicationError:
    code: StrategyLibraryApplicationErrorCode
    message: str
    retryable: bool
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyLibraryApplicationInventoryResult:
    availability: StrategyLibraryApplicationAvailability
    inventory: StrategyLibraryInventory | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: StrategyLibraryApplicationError | None


@dataclass(frozen=True, slots=True)
class FormalStrategySelectionReference:
    strategy_id: StrategyUnderTestId
    strategy_version: str
    manifest_content_hash: str
    guardrail_profile_id: GuardrailProfileId
    guardrail_profile_version: str
    dependency_identities: tuple[StrategyDependencyIdentity, ...]


@dataclass(frozen=True, slots=True)
class ValidateFormalStrategySet:
    selections: tuple[FormalStrategySelectionReference, ...]
    expected_source_revision: SourceRevisionToken


class FormalStrategySetValidationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    SOURCE_CONFLICT = "source_conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FormalStrategySetValidation:
    state: FormalStrategySetValidationState
    selections: tuple[FormalStrategySelectionReference, ...]
    source_revision: SourceRevisionToken
    reasons: tuple[StrategyAvailabilityReason, ...]


@runtime_checkable
class StrategyDiagnosticsV1StrategyLibraryApplication(Protocol):
    @property
    def interface_version(self) -> StrategyLibraryApplicationVersion: ...

    def read_inventory(self) -> StrategyLibraryApplicationInventoryResult: ...

    def validate_formal_strategy_set(
        self,
        command: ValidateFormalStrategySet,
    ) -> FormalStrategySetValidation: ...


class LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter:
    """Translate only public DiagnosticsApplication inventory behavior."""

    def __init__(self, application: DiagnosticsApplication) -> None:
        self._application = application
        self._application_access_gate = (
            shared_diagnostics_application_access_gate(application)
        )

    @property
    def interface_version(self) -> StrategyLibraryApplicationVersion:
        return STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION

    @property
    def application_identity(self) -> DiagnosticsApplicationIdentity:
        return diagnostics_application_identity(self._application)

    def read_inventory(self) -> StrategyLibraryApplicationInventoryResult:
        observed_at = datetime.now(timezone.utc)
        try:
            with self._application_access_gate:
                inventory = self._application.read_strategy_under_test_inventory()
        except RuntimeError:
            return _failed_inventory_result(
                observed_at=observed_at,
                code=(
                    StrategyLibraryApplicationErrorCode.APPLICATION_NOT_READY
                ),
                message="Strategy Diagnostics is not ready.",
                retryable=True,
            )
        except (KeyError, OSError, TypeError, UnicodeError, ValueError):
            return _failed_inventory_result(
                observed_at=observed_at,
                code=(
                    StrategyLibraryApplicationErrorCode.INVENTORY_READ_FAILED
                ),
                message="The authoritative Strategy inventory is unavailable.",
                retryable=False,
            )
        mapped = _map_inventory(inventory)
        availability = (
            StrategyLibraryApplicationAvailability.EMPTY
            if not mapped.entries
            else StrategyLibraryApplicationAvailability.READY
            if all(
                item.availability is StrategyAvailability.FORMAL_CAMPAIGN_READY
                for item in mapped.entries
            )
            else StrategyLibraryApplicationAvailability.PARTIAL
        )
        return StrategyLibraryApplicationInventoryResult(
            availability=availability,
            inventory=mapped,
            source_token=SourceRevisionToken(inventory.content_hash),
            observed_at=datetime.now(timezone.utc),
            error=None,
        )

    def validate_formal_strategy_set(
        self,
        command: ValidateFormalStrategySet,
    ) -> FormalStrategySetValidation:
        from strategy_diagnostics import (
            FormalStrategySelectionCandidate,
            FormalStrategySetValidationState as BackendValidationState,
            StrategyInventoryDependency,
            StrategyInventoryDependencyKind,
        )

        try:
            candidates = tuple(
                FormalStrategySelectionCandidate(
                    strategy_id=item.strategy_id.value,
                    strategy_version=item.strategy_version,
                    manifest_content_hash=item.manifest_content_hash,
                    guardrail_profile_id=item.guardrail_profile_id.value,
                    guardrail_profile_version=item.guardrail_profile_version,
                    dependencies=tuple(
                        StrategyInventoryDependency(
                            kind=StrategyInventoryDependencyKind(
                                dependency.kind.value
                            ),
                            identity=dependency.identity,
                            version=dependency.version,
                            content_hash=dependency.content_hash,
                            available=dependency.available,
                            compatible=dependency.compatible,
                        )
                        for dependency in item.dependency_identities
                    ),
                )
                for item in command.selections
            )
            with self._application_access_gate:
                validation = self._application.validate_formal_strategy_set(
                    candidates=candidates,
                    expected_inventory_content_hash=(
                        command.expected_source_revision.value
                    ),
                )
        except RuntimeError:
            return _unavailable_validation(command.expected_source_revision)
        except (KeyError, OSError, TypeError, UnicodeError, ValueError):
            return _unavailable_validation(command.expected_source_revision)
        state = FormalStrategySetValidationState(validation.state.value)
        assert isinstance(validation.state, BackendValidationState)
        return FormalStrategySetValidation(
            state=state,
            selections=tuple(
                _selection_reference_from_entry(item)
                for item in validation.entries
            ),
            source_revision=SourceRevisionToken(
                validation.inventory_content_hash
            ),
            reasons=tuple(
                StrategyAvailabilityReason(
                    code=StrategyAvailabilityReasonCode(reason.code.value),
                    summary=reason.summary,
                    corrective_guidance=reason.corrective_guidance,
                )
                for reason in validation.reasons
            ),
        )


def _unavailable_validation(
    source_revision: SourceRevisionToken,
) -> FormalStrategySetValidation:
    return FormalStrategySetValidation(
        state=FormalStrategySetValidationState.UNAVAILABLE,
        selections=(),
        source_revision=source_revision,
        reasons=(
            StrategyAvailabilityReason(
                code=StrategyAvailabilityReasonCode.APPLICATION_NOT_READY,
                summary="The authoritative Strategy inventory is unavailable.",
                corrective_guidance="Reconnect and reread before selecting.",
            ),
        ),
    )


def _selection_reference_from_entry(
    item: StrategyUnderTestInventoryEntry,
) -> FormalStrategySelectionReference:
    mapped = _map_entry(item)
    profile = mapped.guardrail_profile
    if profile is None:
        raise ValueError("Validated Strategy is missing a Guardrail profile")
    return FormalStrategySelectionReference(
        strategy_id=mapped.strategy_id,
        strategy_version=mapped.strategy_version,
        manifest_content_hash=mapped.compatibility.content_hash,
        guardrail_profile_id=profile.profile_id,
        guardrail_profile_version=profile.profile_version,
        dependency_identities=mapped.dependencies,
    )


def _failed_inventory_result(
    *,
    observed_at: datetime,
    code: StrategyLibraryApplicationErrorCode,
    message: str,
    retryable: bool,
) -> StrategyLibraryApplicationInventoryResult:
    return StrategyLibraryApplicationInventoryResult(
        availability=StrategyLibraryApplicationAvailability.FAILED,
        inventory=None,
        source_token=None,
        observed_at=observed_at,
        error=StrategyLibraryApplicationError(
            code=code,
            message=message,
            retryable=retryable,
        ),
    )


def _map_inventory(inventory: StrategyUnderTestInventory) -> StrategyLibraryInventory:
    return StrategyLibraryInventory(
        entries=tuple(_map_entry(item) for item in inventory.entries),
        formal_campaign_required_strategy_count=(
            inventory.formal_campaign_required_strategy_count
        ),
        persistence_migration_revision=inventory.persistence_migration_revision,
    )


def _map_entry(item: StrategyUnderTestInventoryEntry) -> StrategyLibraryEntry:
    return StrategyLibraryEntry(
        strategy_id=StrategyUnderTestId(item.strategy_id),
        strategy_version=item.strategy_version,
        entity_revision=item.entity_revision,
        display=StrategyDisplayMetadata(
            display_name=item.display.display_name,
            summary=item.display.summary,
        ),
        source=StrategySourceIdentity(
            module=item.source.module,
            source_relative_path=item.source.source_relative_path,
            packaged_relative_path=item.source.packaged_relative_path,
            content_sha256=item.source.content_sha256,
            lineage=item.source.lineage,
        ),
        compatibility=StrategyCompatibilityManifest(
            surface_version=item.compatibility.surface_version,
            content_hash=item.compatibility.content_hash,
            lifecycle_callbacks=item.compatibility.lifecycle_callbacks,
            scheduled_callbacks=item.compatibility.scheduled_callbacks,
            scheduling_calls=item.compatibility.scheduling_calls,
            context_fields=item.compatibility.context_fields,
            portfolio_fields=item.compatibility.portfolio_fields,
            market_data_calls=item.compatibility.market_data_calls,
            history_units=item.compatibility.history_units,
            configuration_calls=item.compatibility.configuration_calls,
            trading_calls=item.compatibility.trading_calls,
            logging_calls=item.compatibility.logging_calls,
        ),
        candidate_data_policy=item.candidate_data_policy,
        guardrail_profile=(
            None
            if item.guardrail_profile is None
            else StrategyGuardrailProfile(
                strategy_id=StrategyUnderTestId(
                    item.guardrail_profile.strategy_id
                ),
                strategy_version=item.guardrail_profile.strategy_version,
                profile_id=GuardrailProfileId(
                    item.guardrail_profile.profile_id
                ),
                profile_version=item.guardrail_profile.profile_version,
                thresholds=tuple(
                    StrategyGuardrailThreshold(
                        metric_name=threshold.metric_name,
                        operator=threshold.operator,
                        value=str(threshold.value),
                    )
                    for threshold in item.guardrail_profile.thresholds
                ),
            )
        ),
        dependencies=tuple(
            StrategyDependencyIdentity(
                kind=StrategyDependencyKind(dependency.kind.value),
                identity=dependency.identity,
                version=dependency.version,
                content_hash=dependency.content_hash,
                available=dependency.available,
                compatible=dependency.compatible,
            )
            for dependency in item.dependencies
        ),
        required_for_v1_formal_campaign=(
            item.required_for_v1_formal_campaign
        ),
        formal_campaign_eligible=item.formal_campaign_eligible,
        availability=StrategyAvailability(item.availability.value),
        availability_reasons=tuple(
            StrategyAvailabilityReason(
                code=StrategyAvailabilityReasonCode(reason.code.value),
                summary=reason.summary,
                corrective_guidance=reason.corrective_guidance,
            )
            for reason in item.availability_reasons
        ),
    )


__all__ = [
    "STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION",
    "FormalStrategySelectionReference",
    "FormalStrategySetValidation",
    "FormalStrategySetValidationState",
    "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
    "StrategyAvailability",
    "StrategyAvailabilityReason",
    "StrategyAvailabilityReasonCode",
    "StrategyCompatibilityManifest",
    "StrategyDependencyIdentity",
    "StrategyDependencyKind",
    "StrategyDiagnosticsV1StrategyLibraryApplication",
    "StrategyDisplayMetadata",
    "StrategyGuardrailProfile",
    "StrategyGuardrailThreshold",
    "StrategyLibraryApplicationAvailability",
    "StrategyLibraryApplicationError",
    "StrategyLibraryApplicationErrorCode",
    "StrategyLibraryApplicationInventoryResult",
    "StrategyLibraryApplicationVersion",
    "StrategyLibraryEntry",
    "StrategyLibraryInventory",
    "StrategySourceIdentity",
    "ValidateFormalStrategySet",
]
