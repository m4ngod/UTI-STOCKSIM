# python
"""Bar Aggregator
将 snapshots_1s 聚合为 1m / 1h / 1d Bars 并发布 BAR_UPDATED 事件。
策略(简化 MVP):
  - 后台线程每秒检查是否有新的完整分钟 (now - delay)
  - 对上一完整分钟做一次聚合(按 symbol 扫描)
  - minute 聚合: open/high/low/close 取快照 last_price 序列；volume = max(volume)-min(volume)
  - turnover 同上差值；若 volume/turnover 为 None 则置 0
  - 生成 1m bar 后若 minute_start.minute == 59 => 聚合该小时 (60 根 1m bar)
  - 若同时 hour == 23 且 minute == 59 => 聚合当日 (所有当日 1m)
  - 聚合完成后发布 EventType.BAR_UPDATED 事件 (timeframe: '1m'/'1h'/'1d')
幂等: 再次运行同一窗口会尝试 upsert (若存在则跳过)。
"""
from __future__ import annotations
import threading, time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List
from sqlalchemy.orm import Session
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_bars import Bar1m, Bar1h, Bar1d
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # 新增: 模拟时钟

class BarAggregator:
    def __init__(self, *, poll_interval: float = 1.0, delay_sec: int = 2):
        self.poll_interval = poll_interval
        self.delay_sec = delay_sec  # 等待 N 秒避免秒尾写入尚未完成
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._processed_minutes: set[datetime] = set()  # 已聚合的 minute 起始 UTC 时间

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="BarAggregator", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # ---------------- Loop ----------------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._aggregate_pending_minutes()
            except Exception:
                pass
            time.sleep(self.poll_interval)

    # ---------------- Core Aggregation ----------------
    def _aggregate_pending_minutes(self):
        now = datetime.utcnow()
        # 已完成的上一分钟 (考虑 delay)
        target_end = now - timedelta(seconds=self.delay_sec)
        minute_start = target_end.replace(second=0, microsecond=0)
        # 不处理当前尚未完整的一分钟
        if minute_start >= now.replace(second=0, microsecond=0):
            return
        if minute_start in self._processed_minutes:
            return
        self._build_minute_bars(minute_start)
        self._processed_minutes.add(minute_start)
        # 触发小时/日聚合
        if minute_start.minute == 59:
            self._build_hour_bar(minute_start.replace(minute=0, second=0, microsecond=0))
            if minute_start.hour == 23:
                self._build_day_bar(minute_start.date())
        # 裁剪已处理集合（保留最近 1440）
        if len(self._processed_minutes) > 2000:
            cutoff = minute_start - timedelta(days=2)
            self._processed_minutes = {m for m in self._processed_minutes if m >= cutoff}

    def _build_minute_bars(self, minute_start: datetime):
        minute_end = minute_start + timedelta(minutes=1)
        sess: Session = SessionLocal()
        try:
            snaps: List[Snapshot1s] = (sess.query(Snapshot1s)
                                       .filter(Snapshot1s.ts >= minute_start, Snapshot1s.ts < minute_end)
                                       .order_by(Snapshot1s.symbol.asc(), Snapshot1s.ts.asc())
                                       .all())
            if not snaps:
                return
            sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
            # ...existing code 分组...
            grouped: Dict[str, List[Snapshot1s]] = defaultdict(list)
            for s in snaps:
                if s.last_price is not None:
                    grouped[s.symbol].append(s)
            for symbol, arr in grouped.items():
                # ...existing code...
                exists = (sess.query(Bar1m).filter(Bar1m.symbol==symbol, Bar1m.ts==minute_start).one_or_none())
                if exists:
                    # 若历史 bar 未打 sim_day 补齐
                    if sim_day and not getattr(exists, 'sim_day', None):
                        exists.sim_day = sim_day; exists.sim_dt = sim_dt
                    continue
                # ...existing code 价格计算...
                bar = Bar1m(ts=minute_start, symbol=symbol,
                            open=open_p, high=high_p, low=low_p, close=close_p,
                            volume=vol, turnover=turnover,
                            sim_day=sim_day if sim_day else 0, sim_dt=sim_dt)
                sess.add(bar)
                sess.flush()
                event_bus.publish(EventType.BAR_UPDATED, {
                    "symbol": symbol,
                    "timeframe": "1m",
                    "bar": {
                        "ts": minute_start.isoformat(),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol,
                        "turnover": turnover,
                    }
                })
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

    def _build_hour_bar(self, hour_start: datetime):
        hour_end = hour_start + timedelta(hours=1)
        sess: Session = SessionLocal()
        try:
            bars: List[Bar1m] = (sess.query(Bar1m)
                                  .filter(Bar1m.ts >= hour_start, Bar1m.ts < hour_end)
                                  .order_by(Bar1m.symbol.asc(), Bar1m.ts.asc())
                                  .all())
            if not bars:
                return
            sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
            # ...existing code 分组...
            grouped: Dict[str, List[Bar1m]] = defaultdict(list)
            for b in bars:
                grouped[b.symbol].append(b)
            for symbol, arr in grouped.items():
                exists = (sess.query(Bar1h)
                          .filter(Bar1h.symbol==symbol, Bar1h.ts==hour_start).one_or_none())
                if exists:
                    if sim_day and not getattr(exists, 'sim_day', None):
                        exists.sim_day = sim_day; exists.sim_dt = sim_dt
                    continue
                # ...existing code 计算...
                hb = Bar1h(ts=hour_start, symbol=symbol,
                           open=open_p, high=high_p, low=low_p, close=close_p,
                           volume=vol, turnover=turnover,
                           sim_day=sim_day if sim_day else 0, sim_dt=sim_dt)
                sess.add(hb)
                sess.flush()
                event_bus.publish(EventType.BAR_UPDATED, {
                    "symbol": symbol,
                    "timeframe": "1h",
                    "bar": {
                        "ts": hour_start.isoformat(),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol,
                        "turnover": turnover,
                    }
                })
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

    def _build_day_bar(self, day_date):
        day_start = datetime(day_date.year, day_date.month, day_date.day)
        day_end = day_start + timedelta(days=1)
        sess: Session = SessionLocal()
        try:
            bars: List[Bar1m] = (sess.query(Bar1m)
                                  .filter(Bar1m.ts >= day_start, Bar1m.ts < day_end)
                                  .order_by(Bar1m.symbol.asc(), Bar1m.ts.asc())
                                  .all())
            if not bars:
                return
            sim_day = current_sim_day(); sim_dt = virtual_datetime(sim_day)
            grouped: Dict[str, List[Bar1m]] = defaultdict(list)
            for b in bars:
                grouped[b.symbol].append(b)
            for symbol, arr in grouped.items():
                exists = (sess.query(Bar1d)
                          .filter(Bar1d.symbol==symbol, Bar1d.ts==day_start).one_or_none())
                if exists:
                    if sim_day and not getattr(exists, 'sim_day', None):
                        exists.sim_day = sim_day; exists.sim_dt = sim_dt
                    continue
                # ...existing code 计算...
                db = Bar1d(ts=day_start, symbol=symbol,
                           open=open_p, high=high_p, low=low_p, close=close_p,
                           volume=vol, turnover=turnover,
                           sim_day=sim_day if sim_day else 0, sim_dt=sim_dt)
                sess.add(db)
                sess.flush()
                event_bus.publish(EventType.BAR_UPDATED, {
                    "symbol": symbol,
                    "timeframe": "1d",
                    "bar": {
                        "ts": day_start.isoformat(),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol,
                        "turnover": turnover,
                    }
                })
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

# --------- 全局便捷函数 ---------
_bar_aggregator_singleton: BarAggregator | None = None

def ensure_bar_aggregator_started() -> BarAggregator:
    global _bar_aggregator_singleton
    if _bar_aggregator_singleton is None:
        _bar_aggregator_singleton = BarAggregator()
        _bar_aggregator_singleton.start()
    return _bar_aggregator_singleton
