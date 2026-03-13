# python
"""多标的撮合与IPO/快照节流测试 (基础快速自检)
运行方式: pytest -q tests/test_multi_symbol_match.py
说明:
 - 使用真实服务层(SessionLocal)依赖外部配置的数据库, 若需要纯内存请在 settings / engine 层扩展 sqlite 支持��
 - 仅做核心逻辑断言: 不同 symbol 簿隔离、成交不交叉、IPO 自动开盘、快照节流(粗略)。
"""
from time import sleep
import time
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce, Phase, EventType
from stock_sim.services.order_service import OrderService
from stock_sim.infra.event_bus import event_bus  # 新��: 事件总线
from stock_sim.services.ipo_service import maybe_auto_open_ipo  # 新增
from stock_sim.settings import settings  # 新增: 动态调整 IPO 时间窗口


def _collect_events(kinds: set[str], bucket: list, duration: float = 0.2):
    def handler(evt):
        bucket.append((evt.get('event_type'), evt))
    # 简化：event_bus 当前接口 publish(EventType, payload) 直接 payload 无 event_type；此处按 subscribe(patch) 模拟
    # 订阅
    subs = []
    for k in kinds:
        def _wrap(payload, _k=k):
            bucket.append((_k, payload))
        event_bus.subscribe(getattr(EventType, k), _wrap, async_mode=False)
        subs.append((k, _wrap))
    sleep(duration)
    # 解除订阅(若 event_bus 提供 unsubscribe 可使用；否则忽略)
    return bucket


def test_multi_symbol_separation():
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    # 加速 IPO 窗口 (测试环境缩短)
    settings.IPO_CALL_AUCTION_SECONDS = 0.05
    settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS = 0.01
    # 创建两个普通标的 (直接进入连续竞价)
    inst_srv.create(symbol='AAA', name='AAA', tick_size=0.01, lot_size=100, min_qty=100,
                    total_shares=1_000_000, free_float_shares=500_000, initial_price=10.0, ipo_opened=True)
    inst_srv.create(symbol='BBB', name='BBB', tick_size=0.01, lot_size=100, min_qty=100,
                    total_shares=2_000_000, free_float_shares=1_000_000, initial_price=20.0, ipo_opened=True)
    # IPO 标的 (集合竞价阶段)
    inst_srv.create(symbol='IPOX', name='IPOX', tick_size=0.01, lot_size=100, min_qty=100,
                    total_shares=1_000_000, free_float_shares=300_000, initial_price=15.0, ipo_opened=False)
    # 直接构造引擎 — 使用 AAA 对象
    stock0 = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    eng = MatchingEngine('AAA', stock0)
    osrv = OrderService(s, eng, instrument_service=inst_srv)
    # AAA 连续竞价立即成交
    buy1 = Order(symbol='AAA', side=OrderSide.BUY, price=10.00, quantity=100, account_id='ACC1')
    sell1 = Order(symbol='AAA', side=OrderSide.SELL, price=10.00, quantity=100, account_id='ACC2')
    osrv.place_order(buy1); osrv.place_order(sell1)
    assert buy1.filled == 100 and sell1.filled == 100
    # BBB 买单挂入簿 (无对手不成交)
    buy_bbb = Order(symbol='BBB', side=OrderSide.BUY, price=19.50, quantity=200, account_id='ACC3')
    osrv.place_order(buy_bbb)
    assert buy_bbb.filled == 0
    # 簿隔离
    book_aaa = eng.get_book('AAA'); book_bbb = eng.get_book('BBB')
    assert book_aaa.snapshot.volume > 0
    assert book_bbb.snapshot.volume == 0
    # IPOX 集合竞价：放入买/卖单
    buy_ipo1 = Order(symbol='IPOX', side=OrderSide.BUY, price=16.0, quantity=100_000, account_id='ACC4')
    buy_ipo2 = Order(symbol='IPOX', side=OrderSide.BUY, price=15.5, quantity=100_000, account_id='ACC5')
    sell_ipo = Order(symbol='IPOX', side=OrderSide.SELL, price=15.0, quantity=120_000, account_id='ACC_ISSUER')
    osrv.place_order(buy_ipo1); osrv.place_order(buy_ipo2); osrv.place_order(sell_ipo)
    # 强制缩短 IPO 集合竞价结束时间
    ipo_book = eng.get_book('IPOX')
    eng._ipo_end_ts = time.time() - 0.001  # 立即到期
    # 第一次调用: 进入清算缓冲
    maybe_auto_open_ipo(eng, ipo_book)
    assert ipo_book.phase is Phase.CALL_AUCTION and getattr(eng, '_ipo_cleared', False)
    # 等待缓冲结束
    sleep(settings.IPO_AUCTION_SETTLE_BUFFER_SECONDS + 0.02)
    # 第二次调用: 完成切换
    maybe_auto_open_ipo(eng, ipo_book)
    assert ipo_book.phase is Phase.CONTINUOUS
    # 校验成交：卖单数量 120k，买单需求 200k，按最大撮合量与定价策略应 >=0
    exec_vol = sum(t.quantity for t in ipo_book.trades)
    assert exec_vol > 0, 'IPOX 应产生实际集合竞价成交'
    # 卖单应被全部撮合或剩余部分取消
    assert not (sell_ipo.is_active and sell_ipo.remaining > 0), '未成交卖单应被取消'
    # 未成交买单应进入连续簿 (若有剩余)
    remaining_buy = (buy_ipo1.remaining + buy_ipo2.remaining) > 0
    if remaining_buy:
        # 确认挂在 bids
        bids_all = [o for arr in ipo_book.bids.values() for o in arr]
        assert any(o.order_id in (buy_ipo1.order_id, buy_ipo2.order_id) for o in bids_all)
    # 节流检查
    start_vol = book_bbb.snapshot.volume
    for i in range(7):
        o = Order(symbol='BBB', side=OrderSide.SELL, price=25.0, quantity=100, account_id=f'ACC_S{i}')
        osrv.place_order(o)
    assert book_bbb.snapshot.volume == start_vol
    s.close()


def test_snapshot_throttle():
    s = SessionLocal()
    inst_srv = InstrumentService(s)
    sym = 'THRO'
    inst_srv.create(symbol=sym, name=sym, tick_size=0.01, lot_size=10, min_qty=10,
                    total_shares=100_000, free_float_shares=50_000, initial_price=8.0)
    engine = MatchingEngine(sym, create_instrument(sym, tick_size=0.01, lot_size=10, min_qty=10, initial_price=8.0))
    osrv = OrderService(s, engine, instrument_service=inst_srv)

    snap_events: list = []
    def on_snap(payload):
        if payload.get('symbol') == sym:
            snap_events.append(payload)
    event_bus.subscribe(EventType.SNAPSHOT_UPDATED, on_snap, async_mode=False)

    # 进入连续竞价
    engine.run_call_auction_and_open(sym)

    # 前4笔被动挂单(无成交) -> 0 次刷新
    for i in range(4):
        osrv.place_order(Order(symbol=sym, side=OrderSide.SELL, price=9.0 + i, quantity=10, account_id=f'TH_S{i}'))
    assert len(snap_events) == 0, f"前4笔不应刷新 实际 {len(snap_events)}"

    # 第5笔触发第一次节流刷新
    osrv.place_order(Order(symbol=sym, side=OrderSide.SELL, price=9.4, quantity=10, account_id='TH_S4'))
    assert len(snap_events) == 1, f"第5笔应刷新1次 实际 {len(snap_events)}"

    # 再挂 4 笔 (第6~9) 仍 1 次
    for i in range(5,9):
        osrv.place_order(Order(symbol=sym, side=OrderSide.SELL, price=9.0 + i, quantity=10, account_id=f'TH_S{i}'))
    assert len(snap_events) == 1, f"至第9笔仍应仅1次 实际 {len(snap_events)}"

    # 第10笔 -> 第2次刷新
    osrv.place_order(Order(symbol=sym, side=OrderSide.SELL, price=9.9, quantity=10, account_id='TH_S9'))
    assert len(snap_events) == 2, f"第10笔应触发第2次刷新 实际 {len(snap_events)}"

    # 下买单吃掉最优卖单 -> 有成交 => 强制刷新 (第3次)
    best_ask_price = min(p for p in [ord.price for arr in engine.get_book(sym).asks.values() for ord in arr])
    osrv.place_order(Order(symbol=sym, side=OrderSide.BUY, price=best_ask_price, quantity=10, account_id='TH_B_TRADE'))
    assert len(snap_events) == 3, f"成交应触发强制刷新 (第3次) 实际 {len(snap_events)}"
    s.close()
