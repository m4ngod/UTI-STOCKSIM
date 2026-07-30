from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.market import register_market_panel
import time


def _build_market_panel():
    reset_registry()
    register_builtin_panels()
    svc = MarketDataService()
    ctl = MarketController(svc)
    register_market_panel(ctl, svc)
    panel = get_panel('market')
    return panel, ctl, svc


def _snapshot(symbol: str, last: float):
    now = int(time.time() * 1000)
    return {
        'symbol': symbol,
        'last': last,
        'bid_levels': [(last - 0.1, 10)],
        'ask_levels': [(last + 0.1, 10)],
        'volume': 1000,
        'turnover': last * 1000,
        'ts': now,
        'snapshot_id': f'snap-{symbol}-{now}',
    }


def test_market_panel_add_and_view():
    panel, ctl, _ = _build_market_panel()
    panel.add_symbol('AAA')
    panel.add_symbol('BBB')
    # 合并快照
    ctl.merge_batch([
        _snapshot('AAA', 10.5),
        _snapshot('BBB', 8.2),
    ])
    view = panel.get_view()
    symbols = view['watchlist']['symbols']
    assert 'AAA' in symbols and 'BBB' in symbols
    items = view['watchlist']['snapshots']['items']
    # 两条数据
    assert len(items) == 2
    # 确保字段存在
    assert {'symbol','last','volume','snapshot_id'} <= items[0].keys()


def test_market_panel_filter_and_pagination():
    panel, ctl, _ = _build_market_panel()
    for s, p in [('AAA', 10.0), ('AAB', 11.0), ('AAC', 9.5)]:
        panel.add_symbol(s)
        ctl.merge_batch([_snapshot(s, p)])
    panel.set_filter('aa')  # 全部匹配 (不区分大小写)
    panel.set_page(1, 2)
    v1 = panel.get_view()
    assert v1['watchlist']['snapshots']['page_size'] == 2
    assert v1['watchlist']['snapshots']['total'] == 3
    # 第二页
    panel.set_page(2, 2)
    v2 = panel.get_view()
    assert v2['watchlist']['snapshots']['page'] == 2
    assert len(v2['watchlist']['snapshots']['items']) == 1


def test_market_panel_sort_and_detail():
    panel, ctl, svc = _build_market_panel()
    panel.add_symbol('ZZZ')
    panel.add_symbol('AAA')
    ctl.merge_batch([
        _snapshot('ZZZ', 5.0),
        _snapshot('AAA', 12.0),
    ])
    panel.set_sort('last')
    view = panel.get_view()
    items = view['watchlist']['snapshots']['items']
    # 按 last 降序, 第一条应是 AAA
    assert items[0]['symbol'] == 'AAA'
    # 选中 AAA 查看详情
    panel.select_symbol('AAA')
    detail = panel.detail_view()
    assert detail['symbol'] == 'AAA'
    assert detail['series'] is not None
    assert len(detail['series']['close']) > 0
    # snapshot 字段包含 symbol
    assert detail['snapshot'] is None or detail['snapshot']['symbol'] == 'AAA'


def test_market_panel_get_view_uses_lightweight_selected_symbol():
    panel, _, svc = _build_market_panel()
    panel.add_symbol('AAA')
    panel.select_symbol('AAA')

    def _fail_detail_fetch(*_args, **_kwargs):
        raise AssertionError("get_view should not build the full detail view")

    svc.get_trades_detail = _fail_detail_fetch  # type: ignore[method-assign]
    svc.get_holdings_detail = _fail_detail_fetch  # type: ignore[method-assign]

    view = panel.get_view()

    assert view["selected"] == "AAA"


class _InstrumentGateway:
    def list_instruments(self, *, active_only=True):
        assert active_only is True
        return [
            {
                "symbol": "PST1",
                "name": "Persisted 1",
                "initial_price": 12.34,
                "tick_size": 0.01,
                "is_active": True,
                "ipo_opened": True,
            }
        ]


def test_market_panel_loads_persisted_instruments_into_watchlist_and_snapshots():
    svc = MarketDataService(allow_synthetic_fallback=False, runtime_gateway=_InstrumentGateway())
    ctl = MarketController(svc, runtime_gateway=_InstrumentGateway())
    panel = __import__("app.panels.market.panel", fromlist=["MarketPanel"]).MarketPanel(ctl, svc)

    loaded = panel.load_persisted_instruments()
    view = panel.get_view()
    items = view["watchlist"]["snapshots"]["items"]

    assert loaded == ["PST1"]
    assert view["watchlist"]["symbols"] == ["PST1"]
    assert items[0]["symbol"] == "PST1"
    assert items[0]["last"] == 12.34

