import time
from app.controllers import AccountController, MarketController
from app.services.account_service import AccountService
from app.services.market_data_service import MarketDataService
from infra.event_bus import event_bus
from app.event_bridge import FRONTEND_SNAPSHOT_BATCH_TOPIC
from app.core_dto.snapshot import SnapshotDTO


def test_account_controller_pagination_and_filter():
    svc = AccountService()
    ctl = AccountController(svc)
    acc = ctl.load_account('ACC1')
    # 基本断言
    assert acc.account_id == 'ACC1'
    # 不带过滤
    page1 = ctl.get_positions(page=1, page_size=2)
    assert page1['page'] == 1 and page1['page_size'] == 2
    assert len(page1['items']) <= 2
    total = page1['total']
    # 第二页
    page2 = ctl.get_positions(page=2, page_size=2)
    assert page2['page'] == 2
    # 过滤 (用第一个持仓 symbol 前缀)
    if acc.positions:
        prefix = acc.positions[0].symbol[:3].lower()
        filt = ctl.get_positions(symbol_filter=prefix)
        assert filt['total'] >= 1
    # 越界页
    out_page = ctl.get_positions(page=999, page_size=10)
    assert out_page['items'] == []


def test_market_controller_merge_and_list_and_filter():
    msvc = MarketDataService()
    mctl = MarketController(msvc)
    # 模拟 EventBridge 批次
    base_ts = int(time.time() * 1000)
    batch = [
        {
            'symbol': 'AAA', 'last': 10.0, 'bid_levels': [(10.0, 1)], 'ask_levels': [(10.1, 2)],
            'volume': 100, 'turnover': 1000.0, 'ts': base_ts, 'snapshot_id': 's1'
        },
        {
            'symbol': 'BBB', 'last': 20.0, 'bid_levels': [(20.0, 1)], 'ask_levels': [(20.1, 2)],
            'volume': 100, 'turnover': 1000.0, 'ts': base_ts+1, 'snapshot_id': 's2'
        },
        # 更新 AAA
        {
            'symbol': 'AAA', 'last': 11.5, 'bid_levels': [(11.5, 1)], 'ask_levels': [(11.6, 2)],
            'volume': 120, 'turnover': 1100.0, 'ts': base_ts+2, 'snapshot_id': 's3'
        },
    ]
    mctl.merge_batch(batch)
    snap_aaa = mctl.get_snapshot('AAA')
    assert snap_aaa and snap_aaa.last == 11.5
    # 列表 + 排序
    lst = mctl.list_snapshots(sort_by='last')
    assert lst['total'] == 2
    assert lst['items'][0].last >= lst['items'][1].last
    # 过滤
    filt = mctl.list_snapshots(symbol_filter='bb')
    assert filt['total'] == 1 and filt['items'][0].symbol == 'BBB'


def test_market_controller_indicator_request_ma():
    msvc = MarketDataService()
    mctl = MarketController(msvc)
    # 先加载 symbol bars 以确保有数据
    msvc.load_initial('AAA', '1m')
    results = []

    def cb(res, meta):
        results.append((res, meta))

    fut = mctl.request_indicator(symbol='AAA', timeframe='1m', name='ma', window=5, callback=cb)
    # 等待执行
    deadline = time.time() + 2
    while time.time() < deadline and not results:
        # poll 回调
        from app.indicators.executor import indicator_executor
        indicator_executor.poll_callbacks()
        time.sleep(0.01)
    assert results, 'indicator callback not invoked'
    res, meta = results[0]
    assert meta['name'] == 'ma'
    assert meta['params']['window'] == 5
    # 结果长度应与 closes 一致或 >= window (ma 实现通常输出同长度)
    assert hasattr(res, 'shape') and res.shape[0] > 0

