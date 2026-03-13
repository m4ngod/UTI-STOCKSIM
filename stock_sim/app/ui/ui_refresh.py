# Lightweight UI Refresh/Bridge utilities
# - Keeps a reference to the main window so non-UI modules/adapters can open panels
# - Provides open_symbol_page(symbol) to spawn a dedicated K-line + L2 page per symbol
from __future__ import annotations
from typing import Any, Optional

_main_window: Optional[Any] = None


def register_main_window(mw: Any) -> None:
    global _main_window
    _main_window = mw


def get_main_window() -> Optional[Any]:
    return _main_window


def refresh_language_dependent_ui() -> None:  # minimal safe no-op
    # Future: update menu/panel titles according to current i18n
    try:
        mw = _main_window
        if mw is None:
            return
        # If tabs/menu exist, titles are usually evaluated on add; keep no-op for now
        return
    except Exception:
        return


def open_panel(name: str) -> Optional[Any]:
    mw = _main_window
    if mw is None:
        return None
    try:
        return mw.open_panel(name)
    except Exception:
        return None


def open_symbol_page(symbol: str, *, controller: Any | None = None, service: Any | None = None,
                      timeframe: str = "1d") -> Optional[Any]:
    """Open or create a dedicated per-symbol detail page.
    - Registers a dynamic panel with name f"symbol:{symbol}" if not already present
    - Uses SymbolDetailPanel + SymbolDetailPanelAdapter; preloads the given timeframe
    - Falls back gracefully if registry or UI is unavailable
    """
    name = f"symbol:{(symbol or '').strip()}"
    if not symbol:
        return None
    try:
        # Lazy imports to avoid hard dependency at import time
        from app.panels import list_panels, register_panel, get_panel  # type: ignore
        from app.panels.market.panel import SymbolDetailPanel  # type: ignore
        from app.ui.adapters.market_adapter import SymbolDetailPanelAdapter  # type: ignore
        from app.controllers.market_controller import MarketController  # type: ignore
        from app.services.market_data_service import MarketDataService  # type: ignore
    except Exception:
        # Registry or required classes not available
        return None

    # Ensure controller/service
    ctl = controller
    svc = service
    try:
        if ctl is None or svc is None:
            # Create fresh instances as a fallback
            svc = svc or MarketDataService()  # type: ignore[call-arg]
            ctl = ctl or MarketController(svc)  # type: ignore[call-arg]
    except Exception:
        return None

    # Register dynamic panel if not present yet
    try:
        exists = False
        try:
            for p in list_panels():
                if p.get("name") == name:
                    exists = True
                    break
        except Exception:
            exists = False
        if not exists:
            def _factory(_sym: str = symbol, _ctl: Any = ctl, _svc: Any = svc, _tf: str = timeframe):
                logic = SymbolDetailPanel(_ctl, _svc)
                # Preload symbol on designated timeframe (daily by default)
                try:
                    logic.load_symbol(_sym, _tf)  # type: ignore[arg-type]
                except Exception:
                    pass
                return SymbolDetailPanelAdapter().bind(logic)  # type: ignore
            # Human-friendly title like "AAPL Detail"
            title = f"{symbol} Detail"
            try:
                register_panel(name, _factory, title=title, meta={"symbol": symbol, "timeframe": timeframe})
            except Exception:
                # If already registered by a race, ignore
                pass
    except Exception:
        pass

    # Open via main window if available; otherwise just instantiate via registry
    mw = _main_window
    if mw is not None:
        try:
            return mw.open_panel(name)  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        return get_panel(name)
    except Exception:
        return None
