from __future__ import annotations
import time
from typing import List, Dict

from app.services.market_data_service import MarketDataService, Timeframe
from app.services.market_data_service import Fetcher
from app.controllers.market_controller import MarketController
from app.panels.market.panel import MarketPanel

# --------------- Deterministic Small Bars Fetcher -----------------
# 返回固定 30 根 1m K 线, close 为线性递增, 便于指标计算且可预期

def _deterministic_fetcher(symbol: str, timeframe: Timeframe, limit: int) -> List[Dict[str, float]]:  # noqa: D401
    # 忽略 limit, 固定 30 根
    n = 30
    now_ms = int(time.time() * 1000)
    interval = 60_000  # 1m
    start = now_ms - (n - 1) * interval
    bars: List[Dict[str, float]] = []
    base = 100.0
    for i in range(n):
        ts = start + i * interval
        close = base + i * 0.5
        open_ = close - 0.2
        high = close + 0.3
        low = close - 0.4
        vol = 100 + i
        bars.append({
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        })
    return bars

# --------------- Test -----------------

def test_indicator_future_resolves_and_updates_detail_view_model():
    svc = MarketDataService(fetcher=_deterministic_fetcher, default_limit=30)
    ctl = MarketController(svc)
    panel = MarketPanel(ctl, svc)

    symbol = "TESTX"
    panel.select_symbol(symbol, timeframe="1m")

    # 轮询 detail view 直到指标出现或超时
    deadline = time.time() + 5.0  # 最长等待 5s (通常 <0.2s)
    indicators = {}
    while time.time() < deadline:
        view = panel.detail_view()
        indicators = view.get("indicators", {})
        # 预期出现: ma20 与 macd (macd 是 dict)
        if "ma20" in indicators and "macd" in indicators:
            macd_val = indicators["macd"]
            if isinstance(macd_val, dict) and all(k in macd_val for k in ("macd", "signal", "hist")):
                break
        time.sleep(0.05)

    assert indicators, "detail view 未包含 indicators (超时)"  # 成功条件: 存在 indicators key
    assert "ma20" in indicators, "缺少 ma20 指标"
    assert "macd" in indicators, "缺少 macd 指标"
    assert isinstance(indicators["macd"], dict), "macd 指标应为字典"
    assert set(indicators["macd"].keys()) == {"macd", "signal", "hist"}
    # 长度校验: 应与 bars 数量相等 (30)
    ma_series = indicators["ma20"]
    assert isinstance(ma_series, list)
    assert len(ma_series) == 30
    macd_series = indicators["macd"]["macd"]
    assert isinstance(macd_series, list)
    assert len(macd_series) == 30

