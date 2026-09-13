"""Explicit compatibility descriptions; availability means implemented, not ready.

This catalog does not dispatch commands. Existing typed snapshots still decide
whether an implemented operation is allowed for the current source and context.
The legacy interface shapes and their semantics remain unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .versioning import (
    ACTIVE_FEATURE_INTERFACES,
    FeatureInterfaceDescriptor,
    FeatureInterfaceVersion,
    FeatureModuleName,
)


class CapabilityRestrictionCode(str, Enum):
    INTERFACE_NOT_IMPLEMENTED = "interface_not_implemented"
    OPERATION_NOT_IMPLEMENTED = "operation_not_implemented"


@dataclass(frozen=True, slots=True)
class CapabilityRestriction:
    code: CapabilityRestrictionCode
    message: str
    semantic_target: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class FeatureOperationDescriptor:
    name: str
    version: FeatureInterfaceVersion


@dataclass(frozen=True, slots=True)
class FeatureExtensionDescriptor:
    feature: FeatureModuleName
    name: str
    version: FeatureInterfaceVersion
    schemas: tuple[str, ...]
    operations: tuple[FeatureOperationDescriptor, ...]
    composition_entrypoint: str


@dataclass(frozen=True, slots=True)
class ExtensionCapability:
    feature: FeatureModuleName
    extension: str
    version: FeatureInterfaceVersion
    operation: str
    available: bool
    reason: CapabilityRestriction | None


@dataclass(frozen=True, slots=True)
class FeatureCapability:
    descriptor: FeatureInterfaceDescriptor
    operations: tuple[FeatureOperationDescriptor, ...]


@dataclass(frozen=True, slots=True)
class OperationCapability:
    descriptor: FeatureInterfaceDescriptor
    operation: str
    available: bool
    reason: CapabilityRestriction | None


@dataclass(frozen=True, slots=True)
class FeatureCapabilityCatalog:
    schema_version: FeatureInterfaceVersion
    features: tuple[FeatureCapability, ...]
    extensions: tuple[FeatureExtensionDescriptor, ...] = ()

    def negotiate_extension(self, feature: FeatureModuleName, extension: str,
                            version: FeatureInterfaceVersion, operation: str) -> ExtensionCapability:
        match = next((item for item in self.extensions
                      if (item.feature, item.name, item.version) == (feature, extension, version)), None)
        target = f"{feature.value}/{extension}/{version.render()}/{operation}"
        if match is None:
            reason = CapabilityRestriction(CapabilityRestrictionCode.INTERFACE_NOT_IMPLEMENTED,
                                           "该兼容扩展或扩展版本尚未实现。", target)
        elif any(item.name == operation for item in match.operations):
            return ExtensionCapability(feature, extension, version, operation, True, None)
        else:
            reason = CapabilityRestriction(CapabilityRestrictionCode.OPERATION_NOT_IMPLEMENTED,
                                           "该操作未包含在兼容扩展中。", target)
        return ExtensionCapability(feature, extension, version, operation, False, reason)

    def negotiate(
        self,
        feature: FeatureModuleName,
        version: FeatureInterfaceVersion,
        operation: str,
    ) -> OperationCapability:
        requested = FeatureInterfaceDescriptor(feature, version)
        matched = next(
            (item for item in self.features if item.descriptor == requested), None
        )
        if matched is None:
            reason = CapabilityRestriction(
                CapabilityRestrictionCode.INTERFACE_NOT_IMPLEMENTED,
                f"尚未实现 {feature.value} {version.render()}；保留旧版本只读或既有操作能力。",
                f"{feature.value}/{version.render()}/{operation}",
            )
        elif any(item.name == operation for item in matched.operations):
            return OperationCapability(requested, operation, True, None)
        else:
            reason = CapabilityRestriction(
                CapabilityRestrictionCode.OPERATION_NOT_IMPLEMENTED,
                f"{feature.value} {version.render()} 尚未实现操作 {operation}。",
                f"{feature.value}/{version.render()}/{operation}",
            )
        return OperationCapability(requested, operation, False, reason)


class _VersionedFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...


# Operation versions inherit their frozen legacy Feature version. Listing a
# method here must never turn a legacy operation into a V2.1 semantic claim.
_LEGACY_OPERATIONS: dict[FeatureModuleName, tuple[str, ...]] = {
    FeatureModuleName.STRATEGY_LIBRARY: (
        "snapshot", "subscribe", "compare_strategies",
        "select_formal_strategy_set", "close",
    ),
    FeatureModuleName.SCENARIO_LAB: (
        "snapshot", "subscribe", "create_recipe_draft", "author_recipe_with_ai",
        "revise_recipe_draft", "validate_recipe_draft", "approve_recipe",
        "materialize_reference_path", "retry_materialization",
        "compose_scenario_set", "resolve_execution_assumptions",
        "select_formal_scenario_set", "close",
    ),
    FeatureModuleName.DIAGNOSTIC_TASKS: (
        "snapshot", "subscribe", "create_diagnostic_task", "revise_configuration",
        "validate_configuration", "approve_configuration",
        "start_formal_diagnostic_campaign", "pause_diagnostic_target",
        "resume_diagnostic_target", "cancel_diagnostic_target",
        "retry_failed_campaign_node", "close",
    ),
    FeatureModuleName.RUN_MONITORING: (
        "snapshot", "subscribe", "pause_diagnostic_task",
        "resume_diagnostic_task", "cancel_diagnostic_task", "close",
    ),
    FeatureModuleName.EVIDENCE_AND_FINDINGS: ("snapshot", "subscribe", "close"),
    FeatureModuleName.SYSTEM_HEALTH: ("snapshot", "subscribe", "close"),
}


def describe_feature_capabilities(
    providers: tuple[tuple[FeatureModuleName, _VersionedFeature], ...],
    extensions: tuple[FeatureExtensionDescriptor, ...] = (),
) -> FeatureCapabilityCatalog:
    """Describe only the explicitly registered contract on the composed provider."""
    features = []
    for name, provider in providers:
        descriptor = FeatureInterfaceDescriptor(name, provider.interface_version)
        if descriptor not in ACTIVE_FEATURE_INTERFACES:
            continue
        features.append(FeatureCapability(
            descriptor,
            tuple(
                FeatureOperationDescriptor(operation, descriptor.version)
                for operation in _LEGACY_OPERATIONS[name]
                if callable(getattr(provider, operation, None))
            ),
        ))
    return FeatureCapabilityCatalog(FeatureInterfaceVersion(1, 0), tuple(features), extensions)
