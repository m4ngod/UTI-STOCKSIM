import time
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService
from app.core_dto.trade import TradeDTO

class _StubController:
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):  # noqa: D401
        return {"items": [], "total": 0, "page": 1}
    def get_snapshot(self, symbol: str):  # noqa: D401
        return None

def test_symbol_detail_trades_ring_buffer():
    svc = MarketDataService()
    panel = MarketPanel(_StubController(), svc)
    panel.select_symbol('T1', timeframe='1m')
    # 等待指标异步首批完成 (非必须, 只确保 get_view 结构稳定)
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if panel.detail_view().get('indicators'):
            break
        time.sleep(0.01)
    # 添加两条当前 symbol 逐笔 + 一条其它 symbol (应被忽略)
    panel.add_trade(TradeDTO(symbol='T1', price=1.1, qty=10, side='buy', ts=1))
    panel.add_trade({'symbol':'T1','price':1.2,'qty':5,'side':'sell','ts':2})
    panel.add_trade({'symbol':'OTHER','price':9.9,'qty':3,'side':'buy','ts':3})
    view = panel.detail_view()
    trades = view.get('trades')
    assert isinstance(trades, list)
    assert len(trades) == 2
    # 字段存在
    for t in trades:
        assert set(['symbol','price','qty','side','ts']).issubset(t.keys())
    # get_view 再次调用不应改变长度 (纯读取)
    view2 = panel.detail_view()
    assert len(view2.get('trades')) == 2

