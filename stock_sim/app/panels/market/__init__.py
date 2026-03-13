from __future__ import annotations
from app.panels import replace_panel
from app.controllers.market_controller import MarketController
from app.services.market_data_service import MarketDataService

__all__ = ["MarketPanel", "SymbolDetailPanel", "register_market_panel"]

# 延迟导入: 避免在单测早期导入链路尚未准备好时失败
try:  # pragma: no cover
    from .panel import MarketPanel, SymbolDetailPanel  # type: ignore
except Exception:  # noqa: BLE001
    MarketPanel = None  # type: ignore
    SymbolDetailPanel = None  # type: ignore

def register_market_panel(controller: MarketController, service: MarketDataService):
    from .panel import MarketPanel as _MP  # 局部确保可用
    replace_panel("market", lambda: _MP(controller, service), title="Market", meta={"i18n_key": "panel.market"})
