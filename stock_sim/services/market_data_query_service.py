# python
"""MarketDataQueryService
提供统一的快照/分时/特征读取接口 (Step 6)。

方法:
  get_last_tick(symbol)
  get_ticks(symbol, start_ts, end_ts)
  get_intraday_line(symbol) -> [(ts, last, volume_delta, turnover_delta, change_pct, turnover_rate)]
  get_realtime_features(symbol, lookback_n=60, feature_cols=None) -> list[dict]
  build_feature_vector(symbol, lookback_n=60, feature_cols=None) -> list[float]
  persist_feature_vector(symbol, vector, label=None)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Iterable, Sequence
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, asc, and_
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_feature_buffer import FeatureBuffer

_DEFAULT_FEATURE_COLS = [
    "last_price", "change_pct", "change_speed", "volume_delta", "turnover_delta",
    "turnover_rate", "spread", "imbalance", "trade_count_sec", "vwap"
]

@dataclass
class TickDTO:
    ts: datetime
    last: float | None
    volume: int | None
    turnover: float | None
    change_pct: float | None
    change_speed: float | None
    volume_delta: int | None
    turnover_delta: float | None
    turnover_rate: float | None
    spread: float | None
    imbalance: float | None
    trade_count_sec: int | None
    vwap: float | None

class MarketDataQueryService:
    def __init__(self, session: Session | None = None):
        self._external_session = session

    # ------------- session helper -------------
    def _session(self):
        return self._external_session or SessionLocal()

    # ------------- basic queries -------------
    def get_last_tick(self, symbol: str) -> TickDTO | None:
        sym = symbol.upper()
        sess = self._session()
        close_after = False if self._external_session else True
        try:
            row = (sess.query(Snapshot1s)
                   .filter(Snapshot1s.symbol == sym)
                   .order_by(desc(Snapshot1s.ts))
                   .limit(1).one_or_none())
            if not row:
                return None
            return self._row_to_dto(row)
        finally:
            if close_after:
                sess.close()

    def get_ticks(self, symbol: str, start_ts: datetime, end_ts: datetime) -> List[TickDTO]:
        sym = symbol.upper()
        sess = self._session(); close_after = False if self._external_session else True
        try:
            q = (sess.query(Snapshot1s)
                 .filter(Snapshot1s.symbol == sym,
                         Snapshot1s.ts >= start_ts,
                         Snapshot1s.ts <= end_ts)
                 .order_by(asc(Snapshot1s.ts)))
            return [self._row_to_dto(r) for r in q.all()]
        finally:
            if close_after:
                sess.close()

    def get_intraday_line(self, symbol: str, minutes: int | None = None) -> List[tuple]:
        """返回分时线: [(ts,last,volume_delta,turnover_delta,change_pct,turnover_rate)]
        minutes: 限制近 N 分钟 (可选)。若 None 取当日 00:00(UTC) 至今。"""
        now = datetime.utcnow()
        if minutes is not None:
            start_ts = now - timedelta(minutes=minutes)
        else:
            start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ticks = self.get_ticks(symbol, start_ts, now)
        out = []
        for t in ticks:
            out.append((t.ts, t.last, t.volume_delta, t.turnover_delta, t.change_pct, t.turnover_rate))
        return out

    # ------------- feature building -------------
    def get_realtime_features(self, symbol: str, lookback_n: int = 60, feature_cols: Sequence[str] | None = None) -> List[dict]:
        cols = list(feature_cols) if feature_cols else _DEFAULT_FEATURE_COLS
        sym = symbol.upper()
        sess = self._session(); close_after = False if self._external_session else True
        try:
            rows = (sess.query(Snapshot1s)
                    .filter(Snapshot1s.symbol == sym)
                    .order_by(desc(Snapshot1s.ts))
                    .limit(lookback_n)
                    .all())
            rows = list(reversed(rows))  # 按时间正序
            features: List[dict] = []
            for r in rows:
                rec = {"ts": r.ts}
                for c in cols:
                    rec[c] = getattr(r, c if c != 'last_price' else 'last_price', None)
                features.append(rec)
            return features
        finally:
            if close_after:
                sess.close()

    def build_feature_vector(self, symbol: str, lookback_n: int = 60, feature_cols: Sequence[str] | None = None) -> List[float]:
        feats = self.get_realtime_features(symbol, lookback_n=lookback_n, feature_cols=feature_cols)
        cols = list(feature_cols) if feature_cols else _DEFAULT_FEATURE_COLS
        vec: List[float] = []
        for row in feats:
            for c in cols:
                v = row.get(c)
                # 缺失填 0
                if v is None:
                    v = 0.0
                vec.append(float(v))
        return vec

    # ------------- persistence -------------
    def persist_feature_vector(self, symbol: str, vector: List[float], label: float | None = None):
        sess = self._session(); close_after = False if self._external_session else True
        try:
            fb = FeatureBuffer(symbol=symbol.upper(), features=','.join(f"{x:.6f}" for x in vector), label=label)
            sess.add(fb)
            sess.commit()
            return fb.id
        except Exception:
            sess.rollback(); raise
        finally:
            if close_after:
                sess.close()

    # ------------- util -------------
    @staticmethod
    def _row_to_dto(r: Snapshot1s) -> TickDTO:
        return TickDTO(
            ts=r.ts,
            last=r.last_price,
            volume=r.volume,
            turnover=r.turnover,
            change_pct=r.change_pct,
            change_speed=r.change_speed,
            volume_delta=r.volume_delta,
            turnover_delta=r.turnover_delta,
            turnover_rate=r.turnover_rate,
            spread=r.spread,
            imbalance=r.imbalance,
            trade_count_sec=r.trade_count_sec,
            vwap=r.vwap,
        )

