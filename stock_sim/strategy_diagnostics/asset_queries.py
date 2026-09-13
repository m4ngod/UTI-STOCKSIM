"""Application-owned exact queries for retained legacy Strategy assets.

The query journal stores immutable read receipts only. It does not introduce an
asset repository, synthesize Factor/Combination versions, or alter old inventory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import Enum
from threading import RLock

from .strategy_inventory import StrategyUnderTestInventory, StrategyUnderTestInventoryEntry


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class ExactAssetKind(str, Enum):
    LEGACY_STRATEGY = "legacy_strategy"


@dataclass(frozen=True, slots=True)
class ExactStrategyAsset:
    kind: ExactAssetKind
    lineage_id: str
    version_id: str
    content_hash: str

    @classmethod
    def from_entry(cls, entry: StrategyUnderTestInventoryEntry) -> ExactStrategyAsset:
        # Readiness, display labels and entity revision are mutable observations,
        # not immutable strategy content. Material dependency identities are pinned.
        content_hash = _hash({
            "schema": "legacy-strategy-asset/1.0",
            "strategy_id": entry.strategy_id,
            "strategy_version": entry.strategy_version,
            "source": asdict(entry.source),
            "compatibility": asdict(entry.compatibility),
            "candidate_data_policy": entry.candidate_data_policy,
            "guardrail_profile": (
                None if entry.guardrail_profile is None
                else entry.guardrail_profile.to_dict()
            ),
            "dependencies": sorted(
                (item.kind.value, item.identity, item.version, item.content_hash)
                for item in entry.dependencies
            ),
        })
        return cls(ExactAssetKind.LEGACY_STRATEGY, entry.strategy_id,
                   entry.strategy_version, content_hash)


@dataclass(frozen=True, slots=True)
class ExactAssetQuery:
    operation_id: str
    target: ExactStrategyAsset
    expected_revision: str
    frozen_input_hash: str
    operation: str = "query_exact_strategy_asset"
    operation_version: str = "1.0"

    @classmethod
    def freeze(
        cls, *, operation_id: str, target: ExactStrategyAsset, expected_revision: str,
    ) -> ExactAssetQuery:
        request = cls(operation_id, target, expected_revision, "")
        return cls(operation_id, target, expected_revision, request.input_hash())

    def input_hash(self) -> str:
        return _hash({
            "schema": "exact-asset-query/1.0",
            "operation": self.operation,
            "operation_version": self.operation_version,
            "target": asdict(self.target),
            "expected_revision": self.expected_revision,
        })


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
    asset: StrategyUnderTestInventoryEntry | None
    reason: AssetQueryReason | None = None


class ExactStrategyQueries:
    """One journal per owning DiagnosticsApplication; identical IDs replay receipts."""

    def __init__(self, read_inventory: Callable[[], StrategyUnderTestInventory]) -> None:
        self._read_inventory = read_inventory
        self._receipts: dict[str, ExactAssetQueryResult] = {}
        self._lock = RLock()

    def query(self, request: ExactAssetQuery) -> ExactAssetQueryResult:
        with self._lock:
            malformed_field = self._malformed_field(request)
            if malformed_field is not None:
                return self._reject(request, AssetQueryReasonCode.INVALID_REQUEST,
                                    "读取请求的字段类型、精确身份或摘要格式无效。", malformed_field)
            existing = self._receipts.get(request.operation_id)
            if existing is not None:
                if existing.request == request:
                    return existing
                return self._reject(request, AssetQueryReasonCode.OPERATION_ID_CONFLICT,
                                    "该操作 ID 已绑定其他输入；请重新读取并使用新的操作 ID。",
                                    "operation_id")
            result = self._execute(request)
            self._receipts[request.operation_id] = result
            return result

    @staticmethod
    def _malformed_field(request: ExactAssetQuery) -> str | None:
        def text(value: object) -> bool:
            return isinstance(value, str) and bool(value.strip())

        def digest(value: object) -> bool:
            return (isinstance(value, str) and len(value) == 64
                    and all(character in "0123456789abcdef" for character in value))

        if not text(request.operation_id):
            return "operation_id"
        if not isinstance(request.target, ExactStrategyAsset):
            return "target"
        if request.target.kind is not ExactAssetKind.LEGACY_STRATEGY:
            return "target/kind"
        for name in ("lineage_id", "version_id"):
            if not text(getattr(request.target, name)):
                return "target/" + name
        if not digest(request.target.content_hash):
            return "target/content_hash"
        if not digest(request.expected_revision):
            return "expected_revision"
        if not digest(request.frozen_input_hash):
            return "frozen_input_hash"
        return None

    def _execute(self, request: ExactAssetQuery) -> ExactAssetQueryResult:
        if (request.operation, request.operation_version) != ("query_exact_strategy_asset", "1.0"):
            return self._reject(request, AssetQueryReasonCode.OPERATION_NOT_IMPLEMENTED,
                                "该操作或操作版本尚未实现。", "operation")
        if request.frozen_input_hash != request.input_hash():
            return self._reject(request, AssetQueryReasonCode.INPUT_HASH_MISMATCH,
                                "冻结输入已改变；请重新确认精确目标。", "frozen_input_hash")
        try:
            inventory = self._read_inventory()
        except Exception:  # noqa: BLE001 - typed, sanitized application-source boundary
            return self._reject(request, AssetQueryReasonCode.SOURCE_UNAVAILABLE,
                                "来源暂不可读；恢复后可使用新的操作 ID 显式重试。",
                                "source", retryable=True)
        if inventory.content_hash != request.expected_revision:
            return self._reject(request, AssetQueryReasonCode.STALE_REVISION,
                                "资产目录已改变；请重新读取，不会自动替换版本。",
                                "expected_revision", inventory.content_hash)
        asset = next((
            entry for entry in inventory.entries
            if (entry.strategy_id, entry.strategy_version)
            == (request.target.lineage_id, request.target.version_id)
        ), None)
        if asset is None:
            return self._reject(request, AssetQueryReasonCode.ASSET_NOT_FOUND,
                                "找不到该精确资产版本；未使用最新版本替代。",
                                "target/version_id", inventory.content_hash)
        if ExactStrategyAsset.from_entry(asset) != request.target:
            return self._reject(request, AssetQueryReasonCode.ASSET_CONTENT_MISMATCH,
                                "资产内容或物质依赖与固定引用不一致。",
                                "target/content_hash", inventory.content_hash)
        return ExactAssetQueryResult(request, AssetQueryDisposition.COMPLETED,
                                     inventory.content_hash, asset)

    @staticmethod
    def _reject(
        request: ExactAssetQuery, code: AssetQueryReasonCode, message: str,
        semantic_target: str, source_revision: str | None = None, *, retryable: bool = False,
    ) -> ExactAssetQueryResult:
        return ExactAssetQueryResult(
            request, AssetQueryDisposition.REJECTED, source_revision, None,
            AssetQueryReason(code, message, semantic_target, retryable),
        )
