from __future__ import annotations
"""
Self-test: simulate double-click on Market panel watchlist and verify detail updates.

Writes PASS/FAIL to logs/selftest_market_dblclick.txt for visibility.
"""
import sys
import traceback
import os

# Put repo root on sys.path when executed directly
if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if root not in sys.path:
        sys.path.append(root)

from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController
from app.panels.market.panel import MarketPanel as MarketLogic
from app.ui.adapters.market_adapter import MarketPanelAdapter

RESULT_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)),
                           'logs', 'selftest_market_dblclick.txt')

def write_result(text: str) -> None:
    try:
        os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
        with open(RESULT_PATH, 'w', encoding='utf-8') as f:
            f.write(text)
    except Exception:
        pass

def run() -> None:
    svc = MarketDataService()  # uses synthetic fetcher
    ctl = MarketController(svc)
    logic = MarketLogic(ctl, svc)

    # Prepare watchlist
    sym = "SYMTEST"
    logic.add_symbol(sym)

    # Bind adapter
    adapter = MarketPanelAdapter().bind(logic)

    # Simulate double-click by invoking handler (trimmed input also tested)
    adapter._handle_select(f"  {sym}  ")  # type: ignore[attr-defined]

    # Retrieve detail view from logic and assert selection loaded
    dv = logic.detail_view()
    if not isinstance(dv, dict):
        raise AssertionError("detail_view() did not return a dict")
    sel = dv.get("symbol")
    series = dv.get("series")

    # Basic assertions: symbol set and series loaded with OHLC arrays
    if sel != sym:
        raise AssertionError(f"Selected symbol mismatch: got {sel!r}, expected {sym!r}")
    if not series or not isinstance(series, dict):
        raise AssertionError("Series missing in detail view")
    for k in ("ts", "open", "high", "low", "close"):
        if k not in series or not isinstance(series[k], list) or len(series[k]) == 0:
            raise AssertionError(f"Series field {k!r} missing or empty")

    write_result("PASS: Market dblclick -> detail view updated and series loaded.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        msg = f"FAIL: {e}\n{traceback.format_exc()}"
        write_result(msg)
        sys.exit(1)
    sys.exit(0)
