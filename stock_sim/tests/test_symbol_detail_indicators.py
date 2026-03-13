import time
import numpy as np
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService

# ---- Stubs ----
class _StubController:
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):  # noqa: D401
        return {"items": [], "total": 0, "page": 1}
    def get_snapshot(self, symbol: str):  # noqa: D401
        return None

class _StubMarketDataService(MarketDataService):
    pass


def test_symbol_detail_indicators_ma_macd():
    svc = _StubMarketDataService()
    panel = MarketPanel(_StubController(), svc)
    symbol = "TEST"
    panel.select_symbol(symbol, timeframe="1m")
    # 轮询获取 detail_view 直到指标出现
    deadline = time.perf_counter() + 2.0
    ma_arr = None
    macd_obj = None
    while time.perf_counter() < deadline:
        view = panel.detail_view()
        ind = view.get("indicators", {})
        ma_arr = ind.get("ma20")
        macd_obj = ind.get("macd")
        if isinstance(ma_arr, list) and macd_obj and isinstance(macd_obj.get("macd"), list):
            break
        time.sleep(0.02)
    assert isinstance(ma_arr, list) and len(ma_arr) > 0
    assert isinstance(macd_obj, dict) and all(isinstance(macd_obj[k], list) for k in ["macd", "signal", "hist"])
    # 长度一致
    l = len(ma_arr)
    assert len(macd_obj["macd"]) == l
    assert len(macd_obj["signal"]) == l
    assert len(macd_obj["hist"]) == l

