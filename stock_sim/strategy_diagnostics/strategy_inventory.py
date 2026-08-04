"""Authoritative Strategy Under Test inventory owned by the backend."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .diagnostic_evidence import StrategyGuardrailProfile
from .formal_strategy_sources import FORMAL_STRATEGY_SOURCE_BINDINGS
from .ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTRADE_SURFACE_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTradeCompatibilityManifest,
    ptrade_manifest_for,
)


class StrategyInventoryAvailability(str, Enum):
    FORMAL_CAMPAIGN_READY = "formal_campaign_ready"
    UNAVAILABLE = "unavailable"
    OUTDATED = "outdated"
    INCOMPATIBLE = "incompatible"
    MISSING_DEPENDENCY = "missing_dependency"


class StrategyInventoryReasonCode(str, Enum):
    FORMAL_CAMPAIGN_READY = "formal_campaign_ready"
    SOURCE_BINDING_MISSING = "source_binding_missing"
    SOURCE_CONTENT_MISMATCH = "source_content_mismatch"
    COMPATIBILITY_SURFACE_OUTDATED = "compatibility_surface_outdated"
    GUARDRAIL_PROFILE_MISSING = "guardrail_profile_missing"
    GUARDRAIL_PROFILE_MISMATCH = "guardrail_profile_mismatch"
    FORMAL_STRATEGY_SET_INVALID = "formal_strategy_set_invalid"
    INVENTORY_SOURCE_CONFLICT = "inventory_source_conflict"


@dataclass(frozen=True, slots=True)
class StrategyInventoryReason:
    code: StrategyInventoryReasonCode
    summary: str
    corrective_guidance: str


@dataclass(frozen=True, slots=True)
class StrategyInventoryDisplay:
    display_name: str
    summary: str


@dataclass(frozen=True, slots=True)
class StrategyInventorySource:
    module: str
    source_relative_path: str
    packaged_relative_path: str
    content_sha256: str
    lineage: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyInventoryCompatibility:
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


class StrategyInventoryDependencyKind(str, Enum):
    RETAINED_SOURCE = "retained_source"
    PACKAGED_SOURCE = "packaged_source"
    COMPATIBILITY_MANIFEST = "compatibility_manifest"
    PTRADE_SURFACE = "ptrade_surface"
    CANDIDATE_DATA_POLICY = "candidate_data_policy"
    GUARDRAIL_PROFILE = "guardrail_profile"


@dataclass(frozen=True, slots=True)
class StrategyInventoryDependency:
    kind: StrategyInventoryDependencyKind
    identity: str
    version: str
    content_hash: str
    available: bool
    compatible: bool


@dataclass(frozen=True, slots=True)
class StrategyUnderTestInventoryEntry:
    strategy_id: str
    strategy_version: str
    entity_revision: int
    display: StrategyInventoryDisplay
    source: StrategyInventorySource
    compatibility: StrategyInventoryCompatibility
    candidate_data_policy: str
    guardrail_profile: StrategyGuardrailProfile | None
    dependencies: tuple[StrategyInventoryDependency, ...]
    required_for_v1_formal_campaign: bool
    formal_campaign_eligible: bool
    availability: StrategyInventoryAvailability
    availability_reasons: tuple[StrategyInventoryReason, ...]


@dataclass(frozen=True, slots=True)
class StrategyUnderTestInventory:
    entries: tuple[StrategyUnderTestInventoryEntry, ...]
    formal_campaign_required_strategy_count: int
    persistence_migration_revision: str

    @property
    def content_hash(self) -> str:
        return _content_hash(_inventory_content_payload(self))


@dataclass(frozen=True, slots=True)
class FormalStrategySelectionCandidate:
    strategy_id: str
    strategy_version: str
    manifest_content_hash: str
    guardrail_profile_id: str
    guardrail_profile_version: str
    dependencies: tuple[StrategyInventoryDependency, ...]


class FormalStrategySetValidationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    SOURCE_CONFLICT = "source_conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FormalStrategySetValidation:
    state: FormalStrategySetValidationState
    entries: tuple[StrategyUnderTestInventoryEntry, ...]
    inventory_content_hash: str
    reasons: tuple[StrategyInventoryReason, ...]


_FORMAL_STRATEGIES = (
    (
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
        "QuentX Live Minute Scenario-native",
        "Live-minute representative for point-in-time Scenario diagnostics.",
    ),
    (
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
        "QuentX 5.2.3 Scenario-native",
        "QuentX 5.2.3 representative adapted to the formal Scenario data world.",
    ),
)


def build_strategy_under_test_inventory(
    *,
    guardrail_profiles: tuple[StrategyGuardrailProfile, ...],
    persistence_migration_revision: str,
) -> StrategyUnderTestInventory:
    """Audit only the backend-declared V1 formal strategy registrations."""

    profiles = {
        (profile.strategy_id, profile.strategy_version): profile
        for profile in guardrail_profiles
    }
    entries = tuple(
        _inventory_entry(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            display_name=display_name,
            summary=summary,
            profile=profiles.get((strategy_id, strategy_version)),
        )
        for strategy_id, strategy_version, display_name, summary in _FORMAL_STRATEGIES
    )
    return StrategyUnderTestInventory(
        entries=entries,
        formal_campaign_required_strategy_count=len(_FORMAL_STRATEGIES),
        persistence_migration_revision=persistence_migration_revision,
    )


def validate_formal_strategy_set(
    *,
    inventory: StrategyUnderTestInventory,
    candidates: tuple[FormalStrategySelectionCandidate, ...],
    expected_inventory_content_hash: str,
) -> FormalStrategySetValidation:
    """Validate an exact formal set against current backend-owned facts."""

    current_hash = inventory.content_hash
    if expected_inventory_content_hash != current_hash:
        return FormalStrategySetValidation(
            state=FormalStrategySetValidationState.SOURCE_CONFLICT,
            entries=(),
            inventory_content_hash=current_hash,
            reasons=(
                StrategyInventoryReason(
                    code=StrategyInventoryReasonCode.INVENTORY_SOURCE_CONFLICT,
                    summary="The Strategy inventory revision changed.",
                    corrective_guidance=(
                        "Reread the authoritative inventory before selecting."
                    ),
                ),
            ),
        )
    required = tuple(
        entry
        for entry in inventory.entries
        if entry.required_for_v1_formal_campaign
    )
    candidate_ids = tuple(item.strategy_id for item in candidates)
    required_ids = tuple(item.strategy_id for item in required)
    if (
        len(candidates) != inventory.formal_campaign_required_strategy_count
        or len(candidate_ids) != len(set(candidate_ids))
        or set(candidate_ids) != set(required_ids)
    ):
        return _invalid_formal_set(
            inventory,
            "Select every backend-declared V1 Strategy exactly once.",
        )
    indexed = {item.strategy_id: item for item in candidates}
    for entry in required:
        candidate = indexed[entry.strategy_id]
        profile = entry.guardrail_profile
        if (
            not entry.formal_campaign_eligible
            or entry.availability
            is not StrategyInventoryAvailability.FORMAL_CAMPAIGN_READY
            or any(
                not dependency.available or not dependency.compatible
                for dependency in entry.dependencies
            )
        ):
            return FormalStrategySetValidation(
                state=FormalStrategySetValidationState.UNAVAILABLE,
                entries=(),
                inventory_content_hash=current_hash,
                reasons=entry.availability_reasons,
            )
        if (
            candidate.strategy_version != entry.strategy_version
            or candidate.manifest_content_hash
            != entry.compatibility.content_hash
        ):
            return _invalid_formal_set(
                inventory,
                "A selected Strategy version or compatibility manifest changed.",
            )
        if (
            profile is None
            or candidate.guardrail_profile_id != profile.profile_id
            or candidate.guardrail_profile_version != profile.profile_version
        ):
            return FormalStrategySetValidation(
                state=FormalStrategySetValidationState.INVALID,
                entries=(),
                inventory_content_hash=current_hash,
                reasons=(
                    StrategyInventoryReason(
                        code=(
                            StrategyInventoryReasonCode.GUARDRAIL_PROFILE_MISMATCH
                        ),
                        summary=(
                            "The selected Guardrail profile does not match its "
                            "Strategy version."
                        ),
                        corrective_guidance=(
                            "Use the versioned Guardrail profile declared by the "
                            "current authoritative inventory."
                        ),
                    ),
                ),
            )
        if candidate.dependencies != entry.dependencies:
            return _invalid_formal_set(
                inventory,
                "A selected Strategy dependency identity changed.",
            )
    return FormalStrategySetValidation(
        state=FormalStrategySetValidationState.VALID,
        entries=required,
        inventory_content_hash=current_hash,
        reasons=(),
    )


def _invalid_formal_set(
    inventory: StrategyUnderTestInventory,
    summary: str,
) -> FormalStrategySetValidation:
    return FormalStrategySetValidation(
        state=FormalStrategySetValidationState.INVALID,
        entries=(),
        inventory_content_hash=inventory.content_hash,
        reasons=(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.FORMAL_STRATEGY_SET_INVALID,
                summary=summary,
                corrective_guidance=(
                    "Reread and select the exact backend-declared formal set."
                ),
            ),
        ),
    )


def _inventory_entry(
    *,
    strategy_id: str,
    strategy_version: str,
    display_name: str,
    summary: str,
    profile: StrategyGuardrailProfile | None,
) -> StrategyUnderTestInventoryEntry:
    manifest = ptrade_manifest_for(strategy_id, strategy_version)
    binding = FORMAL_STRATEGY_SOURCE_BINDINGS.get(manifest.strategy_module)
    source_hash = _declared_source_hash(manifest)
    reasons: list[StrategyInventoryReason] = []
    availability = StrategyInventoryAvailability.FORMAL_CAMPAIGN_READY
    if binding is None:
        availability = StrategyInventoryAvailability.MISSING_DEPENDENCY
        reasons.append(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.SOURCE_BINDING_MISSING,
                summary="The retained formal source binding is missing.",
                corrective_guidance=(
                    "Restore the backend-declared source binding before selection."
                ),
            )
        )
    elif source_hash != binding.normalized_sha256:
        availability = StrategyInventoryAvailability.INCOMPATIBLE
        reasons.append(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.SOURCE_CONTENT_MISMATCH,
                summary="The registered formal source content does not match.",
                corrective_guidance=(
                    "Publish a reviewed strategy version with a matching source hash."
                ),
            )
        )
    if manifest.surface_version != PTRADE_SURFACE_VERSION:
        availability = StrategyInventoryAvailability.OUTDATED
        reasons.append(
            StrategyInventoryReason(
                code=(
                    StrategyInventoryReasonCode.COMPATIBILITY_SURFACE_OUTDATED
                ),
                summary="The strategy targets an inactive PTrade surface.",
                corrective_guidance=(
                    "Use a strategy version declared for the active PTrade surface."
                ),
            )
        )
    if profile is None:
        availability = StrategyInventoryAvailability.MISSING_DEPENDENCY
        reasons.append(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.GUARDRAIL_PROFILE_MISSING,
                summary="The matching Strategy Guardrail Profile is missing.",
                corrective_guidance=(
                    "Restore one matching versioned Guardrail Profile."
                ),
            )
        )
    elif (
        profile.strategy_id != strategy_id
        or profile.strategy_version != strategy_version
    ):
        availability = StrategyInventoryAvailability.INCOMPATIBLE
        reasons.append(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.GUARDRAIL_PROFILE_MISMATCH,
                summary="The Strategy Guardrail Profile does not match this version.",
                corrective_guidance=(
                    "Choose a Guardrail Profile bound to this exact strategy version."
                ),
            )
        )
    if not reasons:
        reasons.append(
            StrategyInventoryReason(
                code=StrategyInventoryReasonCode.FORMAL_CAMPAIGN_READY,
                summary="All formal Strategy dependencies are current.",
                corrective_guidance="No corrective action is required.",
            )
        )
    source = StrategyInventorySource(
        module=manifest.strategy_module,
        source_relative_path=(
            "" if binding is None else binding.source_relative_path
        ),
        packaged_relative_path=(
            "" if binding is None else binding.packaged_relative_path
        ),
        content_sha256=(
            source_hash
            or ("" if binding is None else binding.normalized_sha256)
        ),
        lineage=manifest.strategy_lineage,
    )
    compatible = availability is StrategyInventoryAvailability.FORMAL_CAMPAIGN_READY
    dependencies = _dependencies(
        manifest=manifest,
        source=source,
        profile=profile,
        binding_present=binding is not None,
        source_matches=(
            binding is not None and source_hash == binding.normalized_sha256
        ),
        profile_compatible=(
            profile is not None
            and profile.strategy_id == strategy_id
            and profile.strategy_version == strategy_version
        ),
    )
    return StrategyUnderTestInventoryEntry(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        entity_revision=1,
        display=StrategyInventoryDisplay(display_name, summary),
        source=source,
        compatibility=_compatibility(manifest),
        candidate_data_policy=manifest.candidate_data_policy,
        guardrail_profile=profile,
        dependencies=dependencies,
        required_for_v1_formal_campaign=True,
        formal_campaign_eligible=compatible,
        availability=availability,
        availability_reasons=tuple(reasons),
    )


def _declared_source_hash(manifest: PTradeCompatibilityManifest) -> str:
    binding = FORMAL_STRATEGY_SOURCE_BINDINGS.get(manifest.strategy_module)
    if binding is None:
        return ""
    project_root = Path(__file__).resolve().parent.parent
    try:
        source = (project_root / binding.source_relative_path).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError):
        return ""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _compatibility(
    manifest: PTradeCompatibilityManifest,
) -> StrategyInventoryCompatibility:
    return StrategyInventoryCompatibility(
        surface_version=manifest.surface_version,
        content_hash=manifest.content_hash,
        lifecycle_callbacks=manifest.lifecycle_callbacks,
        scheduled_callbacks=manifest.scheduled_callbacks,
        scheduling_calls=manifest.scheduling_calls,
        context_fields=manifest.context_fields,
        portfolio_fields=manifest.portfolio_fields,
        market_data_calls=manifest.market_data_calls,
        history_units=manifest.history_units,
        configuration_calls=manifest.configuration_calls,
        trading_calls=manifest.trading_calls,
        logging_calls=manifest.logging_calls,
    )


def _dependencies(
    *,
    manifest: PTradeCompatibilityManifest,
    source: StrategyInventorySource,
    profile: StrategyGuardrailProfile | None,
    binding_present: bool,
    source_matches: bool,
    profile_compatible: bool,
) -> tuple[StrategyInventoryDependency, ...]:
    source_available = binding_present and bool(source.content_sha256)
    return (
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.RETAINED_SOURCE,
            source.source_relative_path,
            "1",
            source.content_sha256,
            source_available,
            source_matches,
        ),
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.PACKAGED_SOURCE,
            source.packaged_relative_path,
            "1",
            source.content_sha256,
            binding_present,
            source_matches,
        ),
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.COMPATIBILITY_MANIFEST,
            f"{manifest.strategy_id}@{manifest.strategy_version}",
            manifest.strategy_version,
            manifest.content_hash,
            True,
            manifest.surface_version == PTRADE_SURFACE_VERSION,
        ),
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.PTRADE_SURFACE,
            PTRADE_SURFACE_VERSION,
            PTRADE_SURFACE_VERSION,
            hashlib.sha256(PTRADE_SURFACE_VERSION.encode("utf-8")).hexdigest(),
            True,
            manifest.surface_version == PTRADE_SURFACE_VERSION,
        ),
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.CANDIDATE_DATA_POLICY,
            manifest.candidate_data_policy,
            "1",
            hashlib.sha256(
                manifest.candidate_data_policy.encode("utf-8")
            ).hexdigest(),
            bool(manifest.candidate_data_policy),
            bool(manifest.candidate_data_policy),
        ),
        StrategyInventoryDependency(
            StrategyInventoryDependencyKind.GUARDRAIL_PROFILE,
            "" if profile is None else profile.profile_id,
            "" if profile is None else profile.profile_version,
            "" if profile is None else _content_hash(profile.to_dict()),
            profile is not None and bool(profile.thresholds),
            profile_compatible,
        ),
    )


def _inventory_content_payload(
    inventory: StrategyUnderTestInventory,
) -> dict[str, object]:
    return {
        "formal_campaign_required_strategy_count": (
            inventory.formal_campaign_required_strategy_count
        ),
        "persistence_migration_revision": inventory.persistence_migration_revision,
        "entries": [
            {
                "strategy_id": item.strategy_id,
                "strategy_version": item.strategy_version,
                "entity_revision": item.entity_revision,
                "display": {
                    "display_name": item.display.display_name,
                    "summary": item.display.summary,
                },
                "source": {
                    "module": item.source.module,
                    "source_relative_path": item.source.source_relative_path,
                    "packaged_relative_path": item.source.packaged_relative_path,
                    "content_sha256": item.source.content_sha256,
                    "lineage": item.source.lineage,
                },
                "compatibility": {
                    "surface_version": item.compatibility.surface_version,
                    "content_hash": item.compatibility.content_hash,
                    "lifecycle_callbacks": item.compatibility.lifecycle_callbacks,
                    "scheduled_callbacks": item.compatibility.scheduled_callbacks,
                    "scheduling_calls": item.compatibility.scheduling_calls,
                    "context_fields": item.compatibility.context_fields,
                    "portfolio_fields": item.compatibility.portfolio_fields,
                    "market_data_calls": item.compatibility.market_data_calls,
                    "history_units": item.compatibility.history_units,
                    "configuration_calls": item.compatibility.configuration_calls,
                    "trading_calls": item.compatibility.trading_calls,
                    "logging_calls": item.compatibility.logging_calls,
                },
                "candidate_data_policy": item.candidate_data_policy,
                "guardrail_profile": (
                    None
                    if item.guardrail_profile is None
                    else item.guardrail_profile.to_dict()
                ),
                "dependencies": [
                    {
                        "kind": dependency.kind.value,
                        "identity": dependency.identity,
                        "version": dependency.version,
                        "content_hash": dependency.content_hash,
                        "available": dependency.available,
                        "compatible": dependency.compatible,
                    }
                    for dependency in item.dependencies
                ],
                "required_for_v1_formal_campaign": (
                    item.required_for_v1_formal_campaign
                ),
                "formal_campaign_eligible": item.formal_campaign_eligible,
                "availability": item.availability.value,
                "availability_reasons": [
                    {
                        "code": reason.code.value,
                        "summary": reason.summary,
                        "corrective_guidance": reason.corrective_guidance,
                    }
                    for reason in item.availability_reasons
                ],
            }
            for item in inventory.entries
        ],
    }


def _content_hash(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FormalStrategySelectionCandidate",
    "FormalStrategySetValidation",
    "FormalStrategySetValidationState",
    "StrategyInventoryAvailability",
    "StrategyInventoryCompatibility",
    "StrategyInventoryDependency",
    "StrategyInventoryDependencyKind",
    "StrategyInventoryDisplay",
    "StrategyInventoryReason",
    "StrategyInventoryReasonCode",
    "StrategyInventorySource",
    "StrategyUnderTestInventory",
    "StrategyUnderTestInventoryEntry",
    "build_strategy_under_test_inventory",
    "validate_formal_strategy_set",
]
