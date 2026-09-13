"""Immutable exact-assets extension 1.0; no backend or Qt types cross this seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol

from .capabilities import FeatureExtensionDescriptor
from .run_monitoring import Completeness, Freshness, SourceGenerationId, SourceKind, Subscription, ViewPhase
from .strategy_library_application import StrategyLibraryEntry


class ExactAssetKind(str, Enum):
    LEGACY_STRATEGY = "legacy_strategy"


@dataclass(frozen=True, slots=True)
class ExactStrategyAsset:
    kind: ExactAssetKind
    lineage_id: str
    version_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ExactAssetQuery:
    operation_id: str
    target: ExactStrategyAsset
    expected_revision: str
    frozen_input_hash: str
    operation: str = "query_exact_strategy_asset"
    operation_version: str = "1.0"

    @classmethod
    def freeze(cls, *, operation_id: str, target: ExactStrategyAsset, expected_revision: str) -> ExactAssetQuery:
        # The versioned wire format is checked against the authoritative backend
        # independently; the Interface does not import an application domain type.
        payload = {"schema": "exact-asset-query/1.0", "operation": "query_exact_strategy_asset",
                   "operation_version": "1.0", "target": asdict(target), "expected_revision": expected_revision}
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return cls(operation_id, target, expected_revision, hashlib.sha256(content.encode("utf-8")).hexdigest())


class AssetQueryDisposition(str, Enum):
    COMPLETED = "completed"
    REJECTED = "rejected"


class AssetQueryReasonCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    OPERATION_ID_CONFLICT = "operation_id_conflict"
    OPERATION_NOT_IMPLEMENTED = "operation_not_implemented"
    INPUT_HASH_MISMATCH = "input_hash_mismatch"
    STALE_REVISION = "stale_revision"
    ASSET_NOT_FOUND = "asset_not_found"
    ASSET_CONTENT_MISMATCH = "asset_content_mismatch"
    STALE_SOURCE_GENERATION = "stale_source_generation"
    SOURCE_UNAVAILABLE = "source_unavailable"


@dataclass(frozen=True, slots=True)
class AssetQueryReason:
    code: AssetQueryReasonCode
    message: str
    semantic_target: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class ExactAssetQueryResult:
    request: ExactAssetQuery
    disposition: AssetQueryDisposition
    source_revision: str | None
    asset: StrategyLibraryEntry | None
    reason: AssetQueryReason | None = None


@dataclass(frozen=True, slots=True)
class StrategyAssetSummary:
    reference: ExactStrategyAsset
    display_name: str


@dataclass(frozen=True, slots=True)
class StrategyAssetQueryState:
    revision: int
    source_generation: SourceGenerationId
    source_kind: SourceKind
    source_revision: str | None
    phase: ViewPhase
    freshness: Freshness
    completeness: Completeness
    assets: tuple[StrategyAssetSummary, ...] = ()
    request: ExactAssetQuery | None = None
    result: ExactAssetQueryResult | None = None
    error: AssetQueryReason | None = None
    retained_content: ExactAssetQueryResult | None = None
    content_freshness: Freshness = Freshness.AWAITING_FIRST_STATE


class StrategyAssetQueriesFeature(Protocol):
    @property
    def extension_descriptor(self) -> FeatureExtensionDescriptor: ...

    def snapshot(self) -> StrategyAssetQueryState: ...
    def subscribe(self, observer: Callable[[StrategyAssetQueryState], None]) -> Subscription: ...
    def refresh(self) -> StrategyAssetQueryState: ...
    def query_exact_asset(self, request: ExactAssetQuery, expected_source_generation: SourceGenerationId) -> StrategyAssetQueryState: ...
    def close(self) -> None: ...
