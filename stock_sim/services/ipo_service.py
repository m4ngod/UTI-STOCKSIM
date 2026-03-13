# python
"""IPO 自动开盘服务 (两阶段模型)

maybe_auto_open_ipo(engine, book):
  使用两次调用完成拍卖:
    1) 结束时间到达后首次调用 -> 计算 auction_price 与可执行撮合量, 生成临时 trades 缓冲, 设置 _ipo_cleared=True 与 _ipo_settle_end_ts= now + buffer, 更新 snapshot(open/last/close) (不发布成交), 返回 False。
    2) 缓冲时间到期后再次调用 -> 发布缓冲 trades, 取消未成交卖单, 未成交买单转入连续簿, 切换 phase=CONTINUOUS, 返回 True。

测试期望: 第一次调用后仍处于 CALL_AUCTION 且 engine._ipo_cleared=True。
"""
from __future__ import annotations
from typing import List
from stock_sim.core.const import Phase, OrderSide, EventType
from stock_sim.core.trade import Trade
from stock_sim.infra.event_bus import event_bus
from stock_sim.settings import settings

# 价格选择: 最大撮合量 -> 最小不平衡 -> 距离 initial_price 最近 -> 价格本身序

def _compute_auction_price(buys: list, sells: list, initial_price: float | None) -> tuple[float, int]:
    ip = float(initial_price or 0.0)
    prices = sorted({*(b.price for b in buys), *(s.price for s in sells)})
    if not prices:
        return ip, 0
    candidates = []  # (exec, imbalance, dist_to_ip, price, buy_vol, sell_vol)
    for p in prices:
        buy_vol = sum(o.remaining for o in buys if o.price >= p)
        sell_vol = sum(o.remaining for o in sells if o.price <= p)
        exec_v = min(buy_vol, sell_vol)
        if exec_v <= 0:
            continue
        imbalance = abs(buy_vol - sell_vol)
        dist = abs(p - ip) if ip > 0 else 0.0
        candidates.append((exec_v, imbalance, dist, p, buy_vol, sell_vol))
    if not candidates:
        # 没有可撮合量 -> 使用最接近初始价或最后一个价格
        return (ip if ip > 0 else prices[-1], 0)
    candidates.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    best = candidates[0]
    return best[3], best[0]


def maybe_auto_open_ipo(engine, book) -> bool:
    try:
        import time as _t
        if book.phase is not Phase.CALL_AUCTION:
            return False
        if book.has_continuous_started:
            return True
        # 初始化结束时间
        end_ts = getattr(engine, '_ipo_end_ts', None)
        if end_ts is None:
            engine._ipo_end_ts = _t.time() + float(getattr(settings, 'IPO_CALL_AUCTION_SECONDS', 3.75))
            return False
        now = _t.time()
        if now < engine._ipo_end_ts:
            return False  # 仍在收集阶段
        # 第一次清算
        if not getattr(engine, '_ipo_cleared', False):
            orders_all = list(getattr(book.call_auction, '_orders', []))
            buys = [o for o in orders_all if o.side is OrderSide.BUY and o.is_active and o.remaining > 0]
            sells = [o for o in orders_all if o.side is OrderSide.SELL and o.is_active and o.remaining > 0]
            initial_price = float((book.instrument_meta or {}).get('initial_price') or 0.0)
            auction_price, exec_plan = _compute_auction_price(buys, sells, initial_price)
            trades: List[Trade] = []
            if exec_plan > 0:
                # 价格时间优先分配
                buys_sorted = sorted(buys, key=lambda x: (-x.price, x.ts_created))
                sells_sorted = sorted(sells, key=lambda x: (x.price, x.ts_created))
                remain = exec_plan
                from stock_sim.core.trade import Trade as TradeCls
                bi = si = 0
                while remain > 0 and bi < len(buys_sorted) and si < len(sells_sorted):
                    b = buys_sorted[bi]; s = sells_sorted[si]
                    if b.price < auction_price or s.price > auction_price:
                        if b.price < auction_price: bi += 1; continue
                        if s.price > auction_price: si += 1; continue
                    qty = min(b.remaining, s.remaining, remain)
                    if qty <= 0:
                        if b.remaining <= 0: bi += 1
                        if s.remaining <= 0: si += 1
                        continue
                    b.fill(qty, auction_price)
                    s.fill(qty, auction_price)
                    trades.append(TradeCls(symbol=book.symbol, price=auction_price, quantity=qty,
                                           buy_order_id=b.order_id, sell_order_id=s.order_id,
                                           buy_account_id=b.account_id or '', sell_account_id=s.account_id or ''))
                    remain -= qty
                    if b.remaining <= 0: bi += 1
                    if s.remaining <= 0: si += 1
            # 缓冲登记
            engine._ipo_cleared = True
            engine._ipo_auction_price = auction_price
            engine._ipo_trades_buffer = trades
            engine._ipo_settle_end_ts = now + float(getattr(settings, 'IPO_AUCTION_SETTLE_BUFFER_SECONDS', 0.25))
            # 预先写入 snapshot 拟开盘价
            if auction_price > 0:
                snap = book.snapshot
                snap.open_price = snap.last_price = snap.close_price = auction_price
            return False
        # 第二阶段: 等待缓冲
        settle_end = getattr(engine, '_ipo_settle_end_ts', None)
        if settle_end and now < settle_end:
            return False
        # 切换
        auction_price = getattr(engine, '_ipo_auction_price', 0.0)
        trades = getattr(engine, '_ipo_trades_buffer', []) or []
        for tr in trades:
            event_bus.publish(EventType.TRADE, {"trade": tr.to_dict(), "phase": "CALL_AUCTION"})
        if trades:
            try: book.trades.extend(trades)
            except Exception: pass
        event_bus.publish(EventType.IPO_OPENED, {
            'symbol': book.symbol,
            'open_price': auction_price,
            'executed_volume': sum(t.quantity for t in trades),
            'total_orders': len(getattr(book.call_auction, '_orders', [])),
            'cleared': True
        })
        # 取消未成交卖单, 保留未成交买单进入簿
        orders_all = list(getattr(book.call_auction, '_orders', []))
        for o in orders_all:
            if o.side is OrderSide.SELL and o.remaining > 0 and o.is_active:
                o.cancel('AUCTION_NOT_FILLED')
        for o in orders_all:
            if o.side is OrderSide.BUY and o.is_active and o.remaining > 0:
                engine._add_to_book(o, book)
        book.phase = Phase.CONTINUOUS
        book.has_continuous_started = True
        book.instrument_meta['ipo_opened'] = True
        engine._conditional_refresh_snapshot(book, force=True)
        # 清理缓冲
        for attr in ('_ipo_trades_buffer','_ipo_settle_end_ts'):
            if hasattr(engine, attr):
                try: delattr(engine, attr)
                except Exception: pass
        return True
    except Exception:
        return False
