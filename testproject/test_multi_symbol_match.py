"""多标的撮合与IPO/快照节流测试 (基础快速自检)
运行方式: pytest -q tests/test_multi_symbol_match.py
说明:
 - 现使用真实 MySQL (已移除内存 sqlite conftest)；测试启动时主动建表/补列。
 - 仅做核心逻辑断言: 不同 symbol 簿隔离、成交不交叉、IPO 自动开盘、快照节流(粗略)。
"""
# --- 新增: 启动时初始化数据库结构 & 兼容新增列 ---
from stock_sim.persistence.models_init import init_models
from stock_sim.persistence.models_imports import engine
from sqlalchemy import inspect, text

init_models()  # 创建缺失表 + 通用列迁移

# 额外: 补齐 positions.borrowed_qty (create_all 不会自动加已有表缺列)
try:
    insp = inspect(engine)
    if 'positions' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('positions')}
        if 'borrowed_qty' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE positions ADD COLUMN borrowed_qty INT NOT NULL DEFAULT 0"))
except Exception as _e:  # 忽略以免影响测试主体
    pass
# --- 以上新增结束 ---

from time import sleep
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, OrderType, TimeInForce, Phase, EventType
from stock_sim.services.order_service import OrderService
from stock_sim.infra.event_bus import event_bus  # 新��: 事件总线
from stock_sim.persistence.models_position import Position  # 新增: 预置持仓


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
    # 创建两个普通标的 & 一个 IPO 标的
    inst_srv.create(symbol='AAA', name='AAA', tick_size=0.01, lot_size=100, min_qty=100, total_shares=1_000_000, free_float_shares=500_000, initial_price=10.0)
    inst_srv.create(symbol='BBB', name='BBB', tick_size=0.01, lot_size=100, min_qty=100, total_shares=2_000_000, free_float_shares=1_000_000, initial_price=20.0)
    inst_srv.create(symbol='IPOX', name='IPOX', tick_size=0.01, lot_size=100, min_qty=100, total_shares=1_000_000, free_float_shares=300_000, initial_price=15.0)
    # 直接构造引擎(多标的) — 使用 AAA 对象
    stock0 = create_instrument('AAA', tick_size=0.01, lot_size=100, min_qty=100, initial_price=10.0)
    eng = MatchingEngine('AAA', stock0)
    # 先测试集合竞价: 不立即开盘, 先把买卖单放入 CALL_AUCTION 阶段
    # OrderService 绑定多标的引擎
    osrv = OrderService(s, eng, instrument_service=inst_srv)

    # 事件诊断订阅 (拒单/接受/取消)
    def _evt_reject(topic, payload):
        o = payload.get('order', {})
        print('[EVT REJECT]', 'reason=', payload.get('reason'), 'symbol=', o.get('symbol'), 'side=', o.get('side'), 'qty=', o.get('qty'), 'price=', o.get('price'))
    def _evt_accept(topic, payload):
        o = payload.get('order', {})
        print('[EVT ACCEPT]', 'symbol=', o.get('symbol'), 'side=', o.get('side'), 'qty=', o.get('qty'), 'price=', o.get('price'), 'phase=', payload.get('phase'))
    def _evt_cancel(topic, payload):
        print('[EVT CANCEL]', payload)
    event_bus.subscribe('OrderRejected', _evt_reject, async_mode=False)
    event_bus.subscribe('OrderAccepted', _evt_accept, async_mode=False)
    event_bus.subscribe('OrderCanceled', _evt_cancel, async_mode=False)

    # 预置卖方持仓, 避免风险引擎/冻结拒绝裸卖导致集合竞价无法撮合
    acc2 = osrv.accounts.get_or_create('ACC2')
    pos_acc2 = next((p for p in acc2.positions if p.symbol == 'AAA'), None)
    if not pos_acc2:
        pos_acc2 = Position(account_id='ACC2', symbol='AAA', quantity=100, frozen_qty=0, avg_price=10.0)
        acc2.positions.append(pos_acc2)  # 关键: 加入关系, 使 RiskEngine 可见
        s.flush()
    # 初始化日初基准 (T+1 可卖额度) —— 否则 RiskEngine 视为日初0
    osrv.daily_reset()

    # 下 AAA 簿双向订单 (集合竞价阶段仅入��不成交)
    buy1 = Order(symbol='AAA', side=OrderSide.BUY, price=10.00, quantity=100, account_id='ACC1')
    sell1 = Order(symbol='AAA', side=OrderSide.SELL, price=10.00, quantity=100, account_id='ACC2')
    osrv.place_order(buy1)
    # 诊断: 第1笔后查看竞价队列
    bookA = eng.get_book('AAA')
    print('[DEBUG AAA after buy] phase=', bookA.phase, 'orders=', [(o.order_id, o.side.name, o.price, o.filled, o.status.name) for o in bookA.call_auction._orders])
    osrv.place_order(sell1)
    print('[DEBUG AAA after sell] phase=', bookA.phase, 'orders=', [(o.order_id, o.side.name, o.price, o.filled, o.status.name) for o in bookA.call_auction._orders])
    # 运行集合竞价并开盘 -> 产生撮合
    eng.run_call_auction_and_open('AAA')
    print('[DEBUG AAA after open] phase=', bookA.phase, 'trades=', [(t.price, t.quantity, t.buy_order_id, t.sell_order_id) for t in bookA.trades], 'buy1=', (buy1.filled, buy1.status.name), 'sell1=', (sell1.filled, sell1.status.name))
    assert buy1.filled == 100 and sell1.filled == 100

    # 下 BBB 买单（暂时不成交）前先挂一个极高价卖单，阻断 IPO 自动开盘(需要有卖单存在)
    acc_bbb_seller = osrv.accounts.get_or_create('ACC_BBB_SELL')
    pos_bbb = next((p for p in acc_bbb_seller.positions if p.symbol == 'BBB'), None)
    if not pos_bbb:
        pos_bbb = Position(account_id='ACC_BBB_SELL', symbol='BBB', quantity=100, frozen_qty=0, avg_price=20.0)
        acc_bbb_seller.positions.append(pos_bbb)
        s.flush()
        osrv.daily_reset()  # 记录日初, 便于 T+1 卖出校验
    dummy_sell_bbb = Order(symbol='BBB', side=OrderSide.SELL, price=999.0, quantity=100, account_id='ACC_BBB_SELL')
    osrv.place_order(dummy_sell_bbb)

    buy_bbb = Order(symbol='BBB', side=OrderSide.BUY, price=19.50, quantity=200, account_id='ACC3')
    osrv.place_order(buy_bbb)
    assert buy_bbb.filled == 0

    # 验证簿隔离: AAA 有成交, BBB snapshot 不应携带 AAA 成交 volume
    book_aaa = eng.get_book('AAA')
    book_bbb = eng.get_book('BBB')
    assert book_aaa.snapshot.volume > 0
    assert book_bbb.snapshot.volume == 0

    # IPOX: 仅买单集合竞价 -> 触发自动 IPO 开盘 (通过 ipo_service)
    buy_ipo1 = Order(symbol='IPOX', side=OrderSide.BUY, price=16.0, quantity=40_000, account_id='ACC4')  # 缩量避免集中度超限
    buy_ipo2 = Order(symbol='IPOX', side=OrderSide.BUY, price=15.5, quantity=40_000, account_id='ACC5')  # 缩量避免集中度超限
    osrv.place_order(buy_ipo1)
    osrv.place_order(buy_ipo2)
    # 手动���行集合竞价开盘 (若外部未自动触发) — 再调用一次，���会影响已开盘
    eng.run_call_auction_and_open('IPOX')
    book_ipo = eng.get_book('IPOX')
    assert book_ipo.phase is Phase.CONTINUOUS
    assert book_ipo.snapshot.last_price == 15.0 or book_ipo.snapshot.last_price == book_ipo.snapshot.open_price
    assert book_ipo.trades, 'IPOX 应产生虚��发行成交'

    # 节流: 连续提交多笔不成交订单，观察刷新次数不过度增长（这里仅做存在性断言）
    start_vol = book_bbb.snapshot.volume
    for i in range(7):
        o = Order(symbol='BBB', side=OrderSide.SELL, price=25.0, quantity=100, account_id=f'ACC_S{i}')
        osrv.place_order(o)
    # 没有成交, volume 不变
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

    # 事件诊断订阅 (节流用例)
    def _evt_reject2(topic, payload):
        o = payload.get('order', {})
        print('[EVT2 REJECT]', 'reason=', payload.get('reason'), 'symbol=', o.get('symbol'), 'side=', o.get('side'), 'qty=', o.get('qty'), 'price=', o.get('price'))
    def _evt_accept2(topic, payload):
        o = payload.get('order', {})
        print('[EVT2 ACCEPT]', 'symbol=', o.get('symbol'), 'side=', o.get('side'), 'qty=', o.get('qty'), 'price=', o.get('price'), 'phase=', payload.get('phase'))
    event_bus.subscribe('OrderRejected', _evt_reject2, async_mode=False)
    event_bus.subscribe('OrderAccepted', _evt_accept2, async_mode=False)

    # 为所��将要下卖单的账户预置充足持仓，避免被视为裸卖而被风控拒绝
    for i in range(10):
        acc_id = f'TH_S{i}'
        acc = osrv.accounts.get_or_create(acc_id)
        if not any(p.symbol == sym for p in acc.positions):
            pos = Position(account_id=acc_id, symbol=sym, quantity=1000, frozen_qty=0, avg_price=8.0)
            acc.positions.append(pos)  # 确保关系建立
    s.flush()
    # 重置日初 (记录各账户当���持仓为 day_start 以通过 T+1 校验)
    osrv.daily_reset()

    snap_events: list = []
    def on_snap(topic, payload):  # 修正: event_bus 回调需要 (topic, payload)
        if payload.get('symbol') == sym:
            snap_events.append(payload)
    event_bus.subscribe(EventType.SNAPSHOT_UPDATED, on_snap, async_mode=False)

    # 进入连续竞价
    engine.run_call_auction_and_open(sym)
    # 清���开盘强制刷新产生的首次 SNAPSHOT_UPDATED 事件, 之后开始节流计数
    snap_events.clear()

    # 前4笔被动挂单(无成交) -> 0 次刷新
    for i in range(4):
        o = Order(symbol=sym, side=OrderSide.SELL, price=9.0 + i, quantity=10, account_id=f'TH_S{i}')
        osrv.place_order(o)
        b = engine.get_book(sym)
        print(f'[DEBUG THRO sell {i}] ops={b.ops_since_snapshot} snap_events={len(snap_events)} asks_levels={len(b.asks)} bids_levels={len(b.bids)}')

    # 第5笔触发第��次节流刷新
    o = Order(symbol=sym, side=OrderSide.SELL, price=9.4, quantity=10, account_id='TH_S4')
    osrv.place_order(o)
    b = engine.get_book(sym)
    print(f'[DEBUG THRO sell 4] ops={b.ops_since_snapshot} snap_events={len(snap_events)} asks_levels={len(b.asks)} bids_levels={len(b.bids)}')

    # 再挂 4 笔 (第6~9) 仍 1 次
    for i in range(5,9):
        o = Order(symbol=sym, side=OrderSide.SELL, price=9.0 + i, quantity=10, account_id=f'TH_S{i}')
        osrv.place_order(o)
        b = engine.get_book(sym)
        print(f'[DEBUG THRO sell {i}] ops={b.ops_since_snapshot} snap_events={len(snap_events)} asks_levels={len(b.asks)} bids_levels={len(b.bids)}')

    # 第10笔 -> 第2次刷新
    o = Order(symbol=sym, side=OrderSide.SELL, price=9.9, quantity=10, account_id='TH_S9')
    osrv.place_order(o)
    b = engine.get_book(sym)
    print(f'[DEBUG THRO sell 9] ops={b.ops_since_snapshot} snap_events={len(snap_events)} asks_levels={len(b.asks)} bids_levels={len(b.bids)}')

    # 下买单吃掉最优卖单 -> 有成交 => 强制刷新 (第3次)
    best_ask_price = min(p for p in [ord.price for arr in engine.get_book(sym).asks.values() for ord in arr])
    osrv.place_order(Order(symbol=sym, side=OrderSide.BUY, price=best_ask_price, quantity=10, account_id='TH_B_TRADE'))
    b = engine.get_book(sym)
    print(f'[DEBUG THRO trade buy] ops={b.ops_since_snapshot} snap_events={len(snap_events)} volume={b.snapshot.volume} best_ask={b.snapshot.best_ask_price} best_bid={b.snapshot.best_bid_price}')
    assert len(snap_events) == 3, f"成交应触发强制刷新 (第3次) 实际 {len(snap_events)}"
    s.close()
