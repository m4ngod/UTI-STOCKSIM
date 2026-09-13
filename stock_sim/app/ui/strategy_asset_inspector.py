"""Qt projection for the explicit exact-assets Feature extension."""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot

from app.features.capabilities import FeatureCapabilityCatalog
from app.features.run_monitoring import Freshness, Subscription, ViewPhase
from app.features.strategy_asset_contract import (
    StrategyAssetQueriesFeature, StrategyAssetQueryState, ExactAssetQuery, ExactStrategyAsset,
)
from app.features.versioning import FeatureInterfaceVersion, FeatureModuleName


class StrategyAssetInspectorQtAdapter(QObject):
    stateChanged = Signal()
    delivery = Signal(int, object)

    def __init__(self, feature: StrategyAssetQueriesFeature | None,
                 catalog: FeatureCapabilityCatalog | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._feature = feature
        self._catalog = catalog
        self._state = None if feature is None else feature.snapshot()
        self._selected: ExactStrategyAsset | None = None
        self._subscription: Subscription | None = None
        self._mount = 0
        self._active = False
        self._closed = False
        self.delivery.connect(self._accept, Qt.ConnectionType.QueuedConnection)

    @Slot(bool)
    def setActive(self, active: bool) -> None:  # noqa: N802
        if self._closed or self._active == active:
            return
        self._active = active
        self._mount += 1
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
        if active and self._feature is not None:
            self._state = self._feature.snapshot()
            mount = self._mount
            self._subscription = self._feature.subscribe(lambda state: self.delivery.emit(mount, state))
            if self._state.freshness is Freshness.AWAITING_FIRST_STATE:
                self.refresh()
        self.stateChanged.emit()

    @Slot(int, object)
    def _accept(self, mount: int, state: StrategyAssetQueryState) -> None:
        if self._closed or not self._active or mount != self._mount:
            return
        if self._state is not None and (state.revision <= self._state.revision
                or state.source_generation.value < self._state.source_generation.value):
            return
        self._state = state
        self.stateChanged.emit()

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def available(self) -> bool:
        return self._feature is not None

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def busy(self) -> bool:
        return self._state is not None and self._state.phase is ViewPhase.LOADING

    @Property("QVariantList", notify=stateChanged)  # type: ignore[arg-type]
    def assets(self) -> list[dict[str, str]]:
        if self._state is None:
            return []
        return [{"label": f"{item.display_name} · {item.reference.version_id}",
                 "key": self._key(item.reference)} for item in self._state.assets]

    @Property(int, notify=stateChanged)  # type: ignore[arg-type]
    def selectedIndex(self) -> int:  # noqa: N802
        if self._state is not None:
            for index, item in enumerate(self._state.assets):
                if item.reference == self._selected:
                    return index
        return -1

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canQuery(self) -> bool:  # noqa: N802
        return bool(self.available and self._active and not self._closed and not self.busy
                and self._state is not None and self._state.source_revision is not None
                and any(item.reference == self._selected for item in self._state.assets)
                and self._state.freshness is Freshness.FRESH)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        state = self._state
        if state is None:
            return "当前未提供精确资产查询能力；旧策略库仍可使用。"
        source = "本地演示数据" if state.source_kind.value == "deterministic_fake" else "真实应用数据"
        if self.busy:
            return f"正在读取 · {source}"
        if state.error is not None:
            return f"读取受限 · {state.error.message}"
        if not state.assets:
            return f"没有可读取的旧策略资产 · {source}"
        if state.result is not None and state.result.request.target == self._selected:
            return ("精确版本已核验" if state.content_freshness is Freshness.FRESH else "保留历史读取记录 · 内容已标陈旧") + f" · {source}"
        return f"{len(state.assets)} 个精确版本 · {source}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def limitationText(self) -> str:  # noqa: N802
        if self._catalog is None:
            return "当前未提供新组合创作能力；不会自动转换旧策略。"
        capability = self._catalog.negotiate(FeatureModuleName.STRATEGY_LIBRARY,
                                              FeatureInterfaceVersion(2, 0), "save_combination")
        return "" if capability.available else "当前仅读取旧策略版本，不会自动生成因子或组合。新组合创作尚不可用。"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def resultText(self) -> str:  # noqa: N802
        state = self._state
        if self._selected is None:
            return "选择一个精确版本，再读取其固定内容与依赖。"
        heading = f"{self._selected.lineage_id} @ {self._selected.version_id}"
        retained = None if state is None else state.retained_content
        if retained is not None and retained.request.target == self._selected:
            assert state is not None
            result = retained
            stale = "保留的已验证内容 · 当前读取尚未重新确认\n" if state.content_freshness is not Freshness.FRESH else ""
            assert result.asset is not None
            return (f"{heading}\n{stale}{self._selected.kind.value} · 只读历史身份\n"
                    f"内容 SHA-256\n{self._selected.content_hash}\n"
                    f"冻结输入 SHA-256\n{result.request.frozen_input_hash}\n"
                    f"固定源 revision\n{result.source_revision}\n"
                    f"读取记录 ID · {result.request.operation_id}\n"
                    f"物质依赖 · {len(result.asset.dependencies)} 项")
        if state is None or state.request is None or state.request.target != self._selected:
            return heading + "\n尚未读取所选版本。"
        if state.result is None:
            return heading + "\n正在等待该精确目标的读取结果。"
        return heading + "\n未显示资产内容；请根据限制原因重新读取。"

    @Slot(str)
    def selectKey(self, key: str) -> None:  # noqa: N802
        self._selected = next((item.reference for item in self._state.assets
                               if self._key(item.reference) == key), None) if self._state else None
        self.stateChanged.emit()

    @Slot()
    def refresh(self) -> None:
        if self._feature is not None and self._active and not self._closed:
            self._accept(self._mount, self._feature.refresh())

    @Slot()
    def querySelected(self) -> None:  # noqa: N802
        if not self.canQuery or self._feature is None or self._state is None:
            return
        assert self._selected is not None and self._state.source_revision is not None
        request = ExactAssetQuery.freeze(operation_id=uuid4().hex, target=self._selected,
                                        expected_revision=self._state.source_revision)
        self._accept(self._mount, self._feature.query_exact_asset(request, self._state.source_generation))

    def close(self) -> None:
        self.setActive(False)
        self._closed = True

    @staticmethod
    def _key(reference: ExactStrategyAsset) -> str:
        return "|".join((reference.kind.value, reference.lineage_id, reference.version_id, reference.content_hash))
