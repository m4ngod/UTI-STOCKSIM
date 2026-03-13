# python
"""IPO Poller
定期轮询所有引擎的 CALL_AUCTION 标的, 主动调用 maybe_auto_open_ipo 以:
 1. 触发 [TRACE IPO.*] 调试输出 (避免必须靠新订单驱动)
 2. 在超时后自动开盘 (force_timeout 分支)

启用:
  - 环境变量 DEBUG_IPO_POLL=1 (默认开启, 可设为0关闭)
  - 轮询间隔: DEBUG_IPO_POLL_INTERVAL (秒, 默认 1.0)
  - 自动开启 IPO TRACE: set_trace_ipo(True) (仅在 DEBUG_TRACE_IPO 未预设且 DEBUG_IPO_POLL_AUTO_TRACE=1 时)

调用 ensure_ipo_poller_started() 即可后台运行。
"""
from __future__ import annotations
import os, threading, time
from FE.engine_registry import engine_registry
from stock_sim.core.const import Phase
from stock_sim.services.ipo_service import maybe_auto_open_ipo, set_trace_ipo
from stock_sim.core.const import OrderSide

_poll_thread: threading.Thread | None = None
_stop_evt: threading.Event | None = None
_started = False

def _should_run():
    return os.environ.get('DEBUG_IPO_POLL', '1') not in ('0','false','False')

def _interval():
    try:
        return float(os.environ.get('DEBUG_IPO_POLL_INTERVAL','1'))
    except Exception:
        return 1.0

def _loop():
    itv = _interval()
    verbose = os.environ.get('DEBUG_IPO_POLL_VERBOSE','0') not in ('0','false','False')
    while _stop_evt and not _stop_evt.is_set():
        try:
            for sym in list(engine_registry.symbols()):
                eng = engine_registry.get(sym)
                if not eng:
                    continue
                try:
                    book = eng.get_book(sym)
                except Exception:
                    continue
                if verbose:
                    try:
                        orders_all = list(getattr(book.call_auction, '_orders', [])) if book.call_auction else []
                        buys = sum(1 for o in orders_all if o.side is OrderSide.BUY)
                        sells = sum(1 for o in orders_all if o.side is OrderSide.SELL)
                        #print(f"[IPO_STATUS] sym={sym} phase={book.phase.name} has_cont={book.has_continuous_started} orders={len(orders_all)} buys={buys} sells={sells} meta={{k:book.instrument_meta.get(k) for k in ('free_float_shares','total_shares','initial_price','ipo_opened','has_ever_continuous')}}", flush=True)
                    except Exception:
                        pass
                if book.phase is Phase.CALL_AUCTION:
                    # 主动尝试一次 (内部会根据条件打印 TRACE IPO.*)
                    maybe_auto_open_ipo(eng, book)
        except Exception:
            pass
        time.sleep(_interval())

def ensure_ipo_poller_started():
    global _poll_thread, _stop_evt, _started
    if _started:
        return True
    if not _should_run():
        return False
    # 自动开启 IPO trace (可关闭)
    if os.environ.get('DEBUG_IPO_POLL_AUTO_TRACE','1') not in ('0','false','False') and os.environ.get('DEBUG_TRACE_IPO') != '1':
        set_trace_ipo(True)
    _stop_evt = threading.Event()
    _poll_thread = threading.Thread(target=_loop, name='IPO-Poller', daemon=True)
    _poll_thread.start()
    _started = True
    return True

def stop_ipo_poller():
    global _poll_thread, _stop_evt, _started
    if not _started:
        return
    if _stop_evt:
        _stop_evt.set()
    if _poll_thread:
        _poll_thread.join(timeout=1)
    _started = False
