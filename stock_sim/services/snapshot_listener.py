# python
"""Snapshot 落地监听器: 增强版本
 - 订阅 SNAPSHOT_UPDATED & TRADE 事件
 - 计算并持久化派生指标: change_pct, change_speed, volume_delta, turnover_delta, turnover_rate, spread, imbalance, trade_count_sec, vwap
 - 需要 instruments 表中 free_float_shares / lot_size（lot_size 通过 InstrumentService 已存）
"""
from __future__ import annotations
from datetime import datetime
from threading import RLock
from sqlalchemy.orm import Session
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # 新增: 模拟时钟

class SnapshotPersistenceListener:
    def __init__(self, session_factory=SessionLocal):
        self._sf = session_factory
        self._started = False
        # 前一秒缓存: symbol -> {ts, last, volume, turnover}
        self._prev: dict[str, dict] = {}
        # 交易计数缓存: (symbol, second_ts) -> count
        self._trade_counter: dict[tuple[str, datetime], int] = {}
        # 元数据缓存: symbol -> {free_float_shares, lot_size, prev_close}
        self._meta: dict[str, dict] = {}
        self._lock = RLock()

    # ---------------- Public ----------------
    def start(self):
        if self._started:
            return
        event_bus.subscribe(EventType.SNAPSHOT_UPDATED, self._on_snapshot, async_mode=False)
        event_bus.subscribe(EventType.TRADE, self._on_trade, async_mode=False)
        self._warm_meta()
        self._started = True

    # ---------------- Meta Cache ----------------
    def _warm_meta(self):
        try:
            sess: Session = self._sf()
            try:
                for inst in sess.query(Instrument).all():
                    self._meta[inst.symbol.upper()] = {
                        "free_float_shares": inst.free_float_shares or inst.total_shares,
                        "lot_size": inst.lot_size or 1,
                        "prev_close": inst.initial_price or inst.initial_price  # 先用 initial_price 兜底
                    }
            finally:
                sess.close()
        except Exception:
            pass

    def _ensure_meta(self, symbol: str):
        up = symbol.upper()
        if up in self._meta:
            return
        try:
            sess: Session = self._sf(); inst = sess.get(Instrument, up)
            if inst:
                self._meta[up] = {
                    "free_float_shares": inst.free_float_shares or inst.total_shares,
                    "lot_size": inst.lot_size or 1,
                    "prev_close": inst.initial_price or inst.initial_price
                }
            sess.close()
        except Exception:
            pass

    # ---------------- Trade Event ----------------
    def _on_trade(self, topic: str, payload: dict):
        tr = payload.get("trade") if isinstance(payload, dict) else None
        if not tr:
            return
        sym = tr.get("symbol")
        if not sym:
            return
        second = self._second_ts(tr.get("ts"))
        if not second:
            second = datetime.utcnow().replace(microsecond=0)
        key = (sym.upper(), second)
        with self._lock:
            self._trade_counter[key] = self._trade_counter.get(key, 0) + 1

    # ---------------- Snapshot Event ----------------
    def _on_snapshot(self, topic: str, payload: dict):
        snap = payload.get("snapshot") if isinstance(payload, dict) else None
        symbol = (payload.get("symbol") or (snap or {}).get("symbol")) if payload else None
        if not symbol:
            return
        symbol_u = symbol.upper()
        last = (snap or {}).get("last")
        volume = (snap or {}).get("vol")
        turnover = (snap or {}).get("turnover")
        bid1 = (snap or {}).get("bid1")
        ask1 = (snap or {}).get("ask1")
        bid1_qty = (snap or {}).get("bid1_qty")
        ask1_qty = (snap or {}).get("ask1_qty")
        now = datetime.utcnow().replace(microsecond=0)
        # 计算派生
        with self._lock:
            self._ensure_meta(symbol_u)
            meta = self._meta.get(symbol_u, {})
            prev_info = self._prev.get(symbol_u)
            prev_close = meta.get("prev_close")
            prev_last = prev_info.get("last") if prev_info else None
            prev_volume = prev_info.get("volume") if prev_info else None
            prev_turnover = prev_info.get("turnover") if prev_info else None
            volume_delta = (volume - prev_volume) if (volume is not None and prev_volume is not None) else None
            turnover_delta = (turnover - prev_turnover) if (turnover is not None and prev_turnover is not None) else None
            change_pct = None
            if prev_close and last is not None and prev_close != 0:
                change_pct = (last - prev_close) / prev_close * 100
            change_speed = None
            if prev_last and last is not None and prev_last != 0:
                change_speed = (last - prev_last) / prev_last * 100
            spread = (ask1 - bid1) if (ask1 is not None and bid1 is not None) else None
            imb = None
            if bid1_qty or ask1_qty:
                bq = bid1_qty or 0; aq = ask1_qty or 0; denom = bq + aq
                imb = ((bq - aq) / denom) if denom > 0 else None
            free_float = meta.get("free_float_shares")
            turnover_rate = None
            if free_float and volume is not None and free_float > 0:
                # volume 假设为“股”或“份”数量；若是手需乘以 lot_size
                lot_size = meta.get("lot_size", 1) or 1
                turnover_rate = (volume * 1.0) / free_float  # 若 volume 为手可改 (volume*lot_size)/free_float
            # trade count
            key = (symbol_u, now)
            trade_count_sec = self._trade_counter.pop(key, 0)
            # vwap
            vwap = (turnover / volume) if (turnover and volume) else None
            # 写库
            sess: Session = self._sf()
            try:
                row = (sess.query(Snapshot1s)
                        .filter(Snapshot1s.symbol == symbol_u, Snapshot1s.ts == now)
                        .one_or_none())
                sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
                if row is None:
                    row = Snapshot1s(symbol=symbol_u, ts=now,
                                     last_price=last, bid1=bid1, ask1=ask1,
                                     bid1_qty=bid1_qty, ask1_qty=ask1_qty,
                                     volume=volume, turnover=turnover,
                                     prev_close=prev_close, change_pct=change_pct,
                                     change_speed=change_speed, volume_delta=volume_delta,
                                     turnover_delta=turnover_delta, turnover_rate=turnover_rate,
                                     spread=spread, imbalance=imb, trade_count_sec=trade_count_sec,
                                     vwap=vwap,
                                     sim_day=sim_day if sim_day else 0,
                                     sim_dt=sim_dt)
                    sess.add(row)
                else:
                    # 更新已有
                    if last is not None: row.last_price = last
                    if bid1 is not None: row.bid1 = bid1
                    if ask1 is not None: row.ask1 = ask1
                    if bid1_qty is not None: row.bid1_qty = bid1_qty
                    if ask1_qty is not None: row.ask1_qty = ask1_qty
                    if volume is not None: row.volume = volume
                    if turnover is not None: row.turnover = turnover
                    row.prev_close = prev_close if prev_close is not None else row.prev_close
                    row.change_pct = change_pct if change_pct is not None else row.change_pct
                    row.change_speed = change_speed if change_speed is not None else row.change_speed
                    row.volume_delta = volume_delta if volume_delta is not None else row.volume_delta
                    row.turnover_delta = turnover_delta if turnover_delta is not None else row.turnover_delta
                    row.turnover_rate = turnover_rate if turnover_rate is not None else row.turnover_rate
                    row.spread = spread if spread is not None else row.spread
                    row.imbalance = imb if imb is not None else row.imbalance
                    row.trade_count_sec = trade_count_sec if trade_count_sec is not None else row.trade_count_sec
                    row.vwap = vwap if vwap is not None else row.vwap
                    if sim_day and not getattr(row, 'sim_day', None):
                        row.sim_day = sim_day; row.sim_dt = sim_dt
                sess.commit()
            except Exception:
                sess.rollback()
            finally:
                sess.close()
            # 更新前值缓存
            self._prev[symbol_u] = {
                "ts": now,
                "last": last,
                "volume": volume,
                "turnover": turnover
            }

    # ---------------- Utils ----------------
    @staticmethod
    def _second_ts(iso_ts: str | None) -> datetime | None:
        if not iso_ts:
            return None
        try:
            # 支持标准 ISO (含微秒) -> 截断到秒
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            return dt.replace(microsecond=0, tzinfo=None)
        except Exception:
            return None

# 全局实例函数
listener_singleton: SnapshotPersistenceListener | None = None

def ensure_snapshot_listener_started():
    global listener_singleton
    if listener_singleton is None:
        listener_singleton = SnapshotPersistenceListener()
        listener_singleton.start()
    return listener_singleton
