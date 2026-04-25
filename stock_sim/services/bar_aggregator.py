# python
"""Aggregate persisted snapshots into 1m/1h/1d bars."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Type

from sqlalchemy.orm import Session

from stock_sim.core.const import EventType
from stock_sim.infra.event_bus import event_bus
from stock_sim.persistence.models_bars import Bar1d, Bar1h, Bar1m
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime


class BarAggregator:
    def __init__(
        self,
        *,
        poll_interval: float = 1.0,
        delay_sec: int = 2,
        backfill_lookback_minutes: int = 240,
        max_backfill_minutes: int = 60,
    ):
        self.poll_interval = poll_interval
        self.delay_sec = delay_sec
        self.backfill_lookback_minutes = max(1, int(backfill_lookback_minutes))
        self.max_backfill_minutes = max(1, int(max_backfill_minutes))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._processed_minutes: set[datetime] = set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="BarAggregator", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            try:
                self._aggregate_pending_minutes()
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def _aggregate_pending_minutes(self):
        now = datetime.utcnow()
        target_end = now - timedelta(seconds=self.delay_sec)
        latest_safe_minute = target_end.replace(second=0, microsecond=0) - timedelta(minutes=1)
        if latest_safe_minute < datetime(1970, 1, 1):
            return
        for minute_start in self._completed_snapshot_minutes(latest_safe_minute):
            if minute_start in self._processed_minutes:
                continue
            self._build_minute_bars(minute_start)
            self._processed_minutes.add(minute_start)
            if minute_start.minute == 59:
                self._build_hour_bar(minute_start.replace(minute=0, second=0, microsecond=0))
                if minute_start.hour == 23:
                    self._build_day_bar(minute_start.date())
        if len(self._processed_minutes) > 2000:
            cutoff = latest_safe_minute - timedelta(days=2)
            self._processed_minutes = {m for m in self._processed_minutes if m >= cutoff}

    def _completed_snapshot_minutes(self, latest_safe_minute: datetime) -> list[datetime]:
        lower_bound = latest_safe_minute - timedelta(minutes=self.backfill_lookback_minutes)
        upper_bound = latest_safe_minute + timedelta(minutes=1)
        sess: Session = SessionLocal()
        try:
            rows = (
                sess.query(Snapshot1s.ts)
                .filter(Snapshot1s.ts >= lower_bound, Snapshot1s.ts < upper_bound)
                .order_by(Snapshot1s.ts.asc())
                .all()
            )
        finally:
            sess.close()
        minutes = sorted(
            {
                row[0].replace(second=0, microsecond=0)
                for row in rows
                if row and row[0] is not None and row[0].replace(second=0, microsecond=0) <= latest_safe_minute
            }
        )
        return minutes[-self.max_backfill_minutes :]

    def _build_minute_bars(self, minute_start: datetime):
        minute_end = minute_start + timedelta(minutes=1)
        sess: Session = SessionLocal()
        try:
            snaps: List[Snapshot1s] = (
                sess.query(Snapshot1s)
                .filter(Snapshot1s.ts >= minute_start, Snapshot1s.ts < minute_end)
                .order_by(Snapshot1s.symbol.asc(), Snapshot1s.ts.asc())
                .all()
            )
            if not snaps:
                return
            grouped: Dict[tuple[str, str | None], List[Snapshot1s]] = defaultdict(list)
            for snap in snaps:
                if snap.last_price is not None:
                    grouped[(str(snap.symbol), getattr(snap, "run_id", None))].append(snap)
            sim_day = current_sim_day()
            sim_dt = virtual_datetime(sim_day)
            for (symbol, run_id), arr in grouped.items():
                self._upsert_bar(
                    sess=sess,
                    model=Bar1m,
                    ts=minute_start,
                    symbol=symbol,
                    run_id=run_id,
                    arr=arr,
                    timeframe="1m",
                    sim_day=sim_day,
                    sim_dt=sim_dt,
                )
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

    def _build_hour_bar(self, hour_start: datetime):
        hour_end = hour_start + timedelta(hours=1)
        sess: Session = SessionLocal()
        try:
            bars: List[Bar1m] = (
                sess.query(Bar1m)
                .filter(Bar1m.ts >= hour_start, Bar1m.ts < hour_end)
                .order_by(Bar1m.symbol.asc(), Bar1m.ts.asc())
                .all()
            )
            if not bars:
                return
            grouped: Dict[tuple[str, str | None], List[Bar1m]] = defaultdict(list)
            for bar in bars:
                grouped[(str(bar.symbol), getattr(bar, "run_id", None))].append(bar)
            sim_day = current_sim_day()
            sim_dt = virtual_datetime(sim_day)
            for (symbol, run_id), arr in grouped.items():
                self._upsert_bar(
                    sess=sess,
                    model=Bar1h,
                    ts=hour_start,
                    symbol=symbol,
                    run_id=run_id,
                    arr=arr,
                    timeframe="1h",
                    sim_day=sim_day,
                    sim_dt=sim_dt,
                )
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

    def _build_day_bar(self, day_value: date):
        day_start = datetime(day_value.year, day_value.month, day_value.day)
        day_end = day_start + timedelta(days=1)
        sess: Session = SessionLocal()
        try:
            bars: List[Bar1m] = (
                sess.query(Bar1m)
                .filter(Bar1m.ts >= day_start, Bar1m.ts < day_end)
                .order_by(Bar1m.symbol.asc(), Bar1m.ts.asc())
                .all()
            )
            if not bars:
                return
            grouped: Dict[tuple[str, str | None], List[Bar1m]] = defaultdict(list)
            for bar in bars:
                grouped[(str(bar.symbol), getattr(bar, "run_id", None))].append(bar)
            sim_day = current_sim_day()
            sim_dt = virtual_datetime(sim_day)
            for (symbol, run_id), arr in grouped.items():
                self._upsert_bar(
                    sess=sess,
                    model=Bar1d,
                    ts=day_start,
                    symbol=symbol,
                    run_id=run_id,
                    arr=arr,
                    timeframe="1d",
                    sim_day=sim_day,
                    sim_dt=sim_dt,
                )
            sess.commit()
        except Exception:
            sess.rollback()
        finally:
            sess.close()

    def _upsert_bar(
        self,
        *,
        sess: Session,
        model: Type[Bar1m] | Type[Bar1h] | Type[Bar1d],
        ts: datetime,
        symbol: str,
        run_id: str | None,
        arr: List[Snapshot1s] | List[Bar1m],
        timeframe: str,
        sim_day: int,
        sim_dt: datetime,
    ):
        resolved_run_id = run_id or next((getattr(item, "run_id", None) for item in arr if getattr(item, "run_id", None)), None)
        query = sess.query(model).filter(model.symbol == symbol, model.ts == ts)
        if resolved_run_id is None:
            query = query.filter(model.run_id.is_(None))
        else:
            query = query.filter(model.run_id == resolved_run_id)
        existing = query.one_or_none()
        ohlcv = self._aggregate_ohlcv(arr)
        if ohlcv is None:
            return
        if existing is None:
            existing = model(
                ts=ts,
                symbol=symbol,
                run_id=resolved_run_id,
                open=ohlcv["open"],
                high=ohlcv["high"],
                low=ohlcv["low"],
                close=ohlcv["close"],
                volume=ohlcv["volume"],
                turnover=ohlcv["turnover"],
                sim_day=sim_day if sim_day else 0,
                sim_dt=sim_dt,
            )
            sess.add(existing)
        else:
            existing.run_id = resolved_run_id or getattr(existing, "run_id", None)
            existing.open = ohlcv["open"]
            existing.high = ohlcv["high"]
            existing.low = ohlcv["low"]
            existing.close = ohlcv["close"]
            existing.volume = ohlcv["volume"]
            existing.turnover = ohlcv["turnover"]
            if sim_day and not getattr(existing, "sim_day", None):
                existing.sim_day = sim_day
                existing.sim_dt = sim_dt
        event_bus.publish(
            EventType.BAR_UPDATED,
            {
                "symbol": symbol,
                "run_id": resolved_run_id,
                "timeframe": timeframe,
                "sim_day": sim_day,
                "sim_dt": sim_dt.isoformat() if sim_dt else None,
                "bar": {
                    "ts": ts.isoformat(),
                    "open": ohlcv["open"],
                    "high": ohlcv["high"],
                    "low": ohlcv["low"],
                    "close": ohlcv["close"],
                    "volume": ohlcv["volume"],
                    "turnover": ohlcv["turnover"],
                },
            },
        )

    @staticmethod
    def _aggregate_ohlcv(arr: List[Snapshot1s] | List[Bar1m]) -> dict | None:
        if not arr:
            return None
        open_p = float(getattr(arr[0], "last_price", getattr(arr[0], "open", 0.0)) or 0.0)
        close_p = float(getattr(arr[-1], "last_price", getattr(arr[-1], "close", 0.0)) or 0.0)
        prices = [float(getattr(item, "last_price", getattr(item, "close", 0.0)) or 0.0) for item in arr]
        prices = [p for p in prices if p > 0]
        if not prices:
            return None
        high_p = max(prices)
        low_p = min(prices)
        first_volume = float(getattr(arr[0], "volume", 0.0) or 0.0)
        last_volume = float(getattr(arr[-1], "volume", 0.0) or 0.0)
        first_turnover = float(getattr(arr[0], "turnover", 0.0) or 0.0)
        last_turnover = float(getattr(arr[-1], "turnover", 0.0) or 0.0)
        if hasattr(arr[0], "last_price"):
            volume = max(last_volume - first_volume, 0.0)
            turnover = max(last_turnover - first_turnover, 0.0)
        else:
            volume = sum(float(getattr(item, "volume", 0.0) or 0.0) for item in arr)
            turnover = sum(float(getattr(item, "turnover", 0.0) or 0.0) for item in arr)
        return {
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": int(volume),
            "turnover": float(turnover),
        }


_bar_aggregator_singleton: BarAggregator | None = None


def ensure_bar_aggregator_started() -> BarAggregator:
    global _bar_aggregator_singleton
    if _bar_aggregator_singleton is None:
        _bar_aggregator_singleton = BarAggregator()
        _bar_aggregator_singleton.start()
    return _bar_aggregator_singleton
