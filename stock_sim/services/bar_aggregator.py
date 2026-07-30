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
        try:
            event_bus.subscribe(EventType.SIM_DAY, self._on_sim_day, async_mode=False)
        except Exception:
            pass
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
        touched_days: set[int] = set()
        for minute_start in self._completed_snapshot_minutes(latest_safe_minute):
            if minute_start in self._processed_minutes:
                continue
            touched_days.update(self._build_minute_bars(minute_start, refresh_day_bars=False))
            self._processed_minutes.add(minute_start)
            if minute_start.minute == 59:
                self._build_hour_bar(minute_start.replace(minute=0, second=0, microsecond=0))
        for sim_day in touched_days:
            self._build_day_bar_by_sim_day(sim_day)
        if len(self._processed_minutes) > 2000:
            cutoff = latest_safe_minute - timedelta(days=2)
            self._processed_minutes = {m for m in self._processed_minutes if m >= cutoff}

    def flush_all(self, *, run_ids: list[str] | None = None) -> dict[str, int]:
        """Build bars for every persisted snapshot minute, including the current minute."""
        run_scope = self._normalize_run_scope(run_ids)
        sess: Session = SessionLocal()
        try:
            query = sess.query(Snapshot1s.ts)
            if run_scope:
                query = query.filter(Snapshot1s.run_id.in_(run_scope))
            rows = query.order_by(Snapshot1s.ts.asc()).all()
            minutes = sorted(
                {
                    row[0].replace(second=0, microsecond=0)
                    for row in rows
                    if row and row[0] is not None
                }
            )
            before_count = self._bar_count(sess, run_scope)
        finally:
            sess.close()

        touched_days: set[int] = set()
        for minute_start in minutes:
            touched_days.update(
                self._build_minute_bars(
                    minute_start,
                    run_ids=run_scope,
                    refresh_day_bars=False,
                )
            )
            self._processed_minutes.add(minute_start)
            if minute_start.minute == 59:
                self._build_hour_bar(
                    minute_start.replace(minute=0, second=0, microsecond=0),
                    run_ids=run_scope,
                )
        for sim_day in touched_days:
            self._build_day_bar_by_sim_day(sim_day, run_ids=run_scope)

        sess = SessionLocal()
        try:
            after_count = self._bar_count(sess, run_scope)
        finally:
            sess.close()
        return {
            "processed_minute_count": len(minutes),
            "bar_1m_count": after_count,
            "bar_1m_delta": max(after_count - before_count, 0),
        }

    @staticmethod
    def _bar_count(sess: Session, run_scope: list[str]) -> int:
        query = sess.query(Bar1m)
        if run_scope:
            query = query.filter(Bar1m.run_id.in_(run_scope))
        return int(query.count())

    @staticmethod
    def _normalize_run_scope(run_ids: list[str] | None) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in (run_ids or []) if str(item).strip()))

    def _on_sim_day(self, _topic: str, payload: dict):
        try:
            day = int((payload or {}).get("sim_day", (payload or {}).get("sim_day_index", 0)) or 0)
        except Exception:
            return
        if day > 0:
            self._build_day_bar_by_sim_day(day - 1)
        self._build_day_bar_by_sim_day(day)

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

    def _build_minute_bars(
        self,
        minute_start: datetime,
        *,
        run_ids: list[str] | None = None,
        refresh_day_bars: bool = True,
    ) -> set[int]:
        minute_end = minute_start + timedelta(minutes=1)
        run_scope = self._normalize_run_scope(run_ids)
        sess: Session = SessionLocal()
        try:
            query = (
                sess.query(Snapshot1s)
                .filter(Snapshot1s.ts >= minute_start, Snapshot1s.ts < minute_end)
            )
            if run_scope:
                query = query.filter(Snapshot1s.run_id.in_(run_scope))
            snaps: List[Snapshot1s] = query.order_by(Snapshot1s.symbol.asc(), Snapshot1s.ts.asc()).all()
            if not snaps:
                return set()
            grouped: Dict[tuple[str, str | None], List[Snapshot1s]] = defaultdict(list)
            for snap in snaps:
                if snap.last_price is not None:
                    grouped[(str(snap.symbol), getattr(snap, "run_id", None))].append(snap)
            touched_days: set[int] = set()
            for (symbol, run_id), arr in grouped.items():
                sim_day = self._resolve_sim_day(arr)
                sim_dt = virtual_datetime(sim_day)
                touched_days.add(sim_day)
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
            if refresh_day_bars:
                for sim_day in touched_days:
                    self._build_day_bar_by_sim_day(sim_day, run_ids=run_scope)
            return touched_days
        except Exception:
            sess.rollback()
            return set()
        finally:
            sess.close()

    def _build_hour_bar(self, hour_start: datetime, *, run_ids: list[str] | None = None):
        hour_end = hour_start + timedelta(hours=1)
        run_scope = self._normalize_run_scope(run_ids)
        sess: Session = SessionLocal()
        try:
            query = (
                sess.query(Bar1m)
                .filter(Bar1m.ts >= hour_start, Bar1m.ts < hour_end)
            )
            if run_scope:
                query = query.filter(Bar1m.run_id.in_(run_scope))
            bars: List[Bar1m] = query.order_by(Bar1m.symbol.asc(), Bar1m.ts.asc()).all()
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

    def _build_day_bar_by_sim_day(self, sim_day: int, *, run_ids: list[str] | None = None):
        day = max(0, int(sim_day))
        run_scope = self._normalize_run_scope(run_ids)
        sess: Session = SessionLocal()
        try:
            bars_query = sess.query(Bar1m).filter(Bar1m.sim_day == day)
            if run_scope:
                bars_query = bars_query.filter(Bar1m.run_id.in_(run_scope))
            bars: List[Bar1m] = bars_query.order_by(Bar1m.symbol.asc(), Bar1m.ts.asc()).all()
            if bars:
                grouped: Dict[tuple[str, str | None], List[Bar1m]] = defaultdict(list)
                for bar in bars:
                    grouped[(str(bar.symbol), getattr(bar, "run_id", None))].append(bar)
                sim_dt = virtual_datetime(day)
                for (symbol, run_id), arr in grouped.items():
                    self._upsert_bar(
                        sess=sess,
                        model=Bar1d,
                        ts=sim_dt,
                        symbol=symbol,
                        run_id=run_id,
                        arr=arr,
                        timeframe="1d",
                        sim_day=day,
                        sim_dt=sim_dt,
                    )
                sess.commit()
                return

            snaps_query = sess.query(Snapshot1s).filter(Snapshot1s.sim_day == day)
            if run_scope:
                snaps_query = snaps_query.filter(Snapshot1s.run_id.in_(run_scope))
            snaps: List[Snapshot1s] = snaps_query.order_by(Snapshot1s.symbol.asc(), Snapshot1s.ts.asc()).all()
            if not snaps:
                return
            grouped_snaps: Dict[tuple[str, str | None], List[Snapshot1s]] = defaultdict(list)
            for snap in snaps:
                if snap.last_price is not None:
                    grouped_snaps[(str(snap.symbol), getattr(snap, "run_id", None))].append(snap)
            sim_dt = virtual_datetime(day)
            for (symbol, run_id), arr in grouped_snaps.items():
                self._upsert_bar(
                    sess=sess,
                    model=Bar1d,
                    ts=sim_dt,
                    symbol=symbol,
                    run_id=run_id,
                    arr=arr,
                    timeframe="1d",
                    sim_day=day,
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
        is_snapshot_series = hasattr(arr[0], "last_price")
        price_attr = "last_price" if is_snapshot_series else "close"
        open_attr = "last_price" if is_snapshot_series else "open"
        close_attr = "last_price" if is_snapshot_series else "close"
        open_p = float(getattr(arr[0], open_attr, 0.0) or 0.0)
        close_p = float(getattr(arr[-1], close_attr, 0.0) or 0.0)
        high_p: float | None = None
        low_p: float | None = None
        volume = 0.0
        turnover = 0.0
        for item in arr:
            price = float(getattr(item, price_attr, 0.0) or 0.0)
            if price > 0:
                high_p = price if high_p is None else max(high_p, price)
                low_p = price if low_p is None else min(low_p, price)
            if not is_snapshot_series:
                volume += float(getattr(item, "volume", 0.0) or 0.0)
                turnover += float(getattr(item, "turnover", 0.0) or 0.0)
        if high_p is None or low_p is None:
            return None
        if is_snapshot_series:
            first_volume = float(getattr(arr[0], "volume", 0.0) or 0.0)
            last_volume = float(getattr(arr[-1], "volume", 0.0) or 0.0)
            first_turnover = float(getattr(arr[0], "turnover", 0.0) or 0.0)
            last_turnover = float(getattr(arr[-1], "turnover", 0.0) or 0.0)
            volume = max(last_volume - first_volume, 0.0)
            turnover = max(last_turnover - first_turnover, 0.0)
        return {
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": int(volume),
            "turnover": float(turnover),
        }

    @staticmethod
    def _resolve_sim_day(arr: List[Snapshot1s] | List[Bar1m]) -> int:
        days = [
            int(getattr(item, "sim_day", 0) or 0)
            for item in arr
            if getattr(item, "sim_day", None) is not None
        ]
        if days:
            return max(days)
        return int(current_sim_day() or 0)


_bar_aggregator_singleton: BarAggregator | None = None


def ensure_bar_aggregator_started() -> BarAggregator:
    global _bar_aggregator_singleton
    if _bar_aggregator_singleton is None:
        _bar_aggregator_singleton = BarAggregator()
        _bar_aggregator_singleton.start()
    return _bar_aggregator_singleton
