"""App-layer market data service."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set
from datetime import date, datetime, timezone
import math
import threading
import time

import numpy as np

from app.runtime_gateway import RuntimeGateway
from observability.metrics import metrics
from .bars_cache import BarsCache, BarDict, BarsSeries, Timeframe


Fetcher = Callable[[str, Timeframe, int], List[BarDict]]

_TIMEFRAME_MS: Dict[Timeframe, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "60m": 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

_TRADING_DAY_SLOTS: Dict[Timeframe, int] = {
    "1m": 240,
    "5m": 48,
    "15m": 16,
    "60m": 4,
    "1d": 1,
}


class MarketDataService:
    def __init__(
        self,
        bars_cache: Optional[BarsCache] = None,
        *,
        fetcher: Optional[Fetcher] = None,
        default_limit: int = 500,
        enable_runtime_holdings: bool = False,
        allow_synthetic_fallback: bool = True,
        runtime_gateway: RuntimeGateway | None = None,
    ):
        self._cache = bars_cache or BarsCache()
        self._fetcher: Fetcher = fetcher or _synthetic_fetcher
        self._series_placeholder = fetcher is None
        self._allow_synthetic_fallback = bool(allow_synthetic_fallback)
        self._enable_runtime_holdings = enable_runtime_holdings
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._subscribed: Set[str] = set()
        self._default_limit = default_limit
        self._lock = threading.RLock()
        self._runtime_symbols: Set[str] = set()
        self._realtime_bars: Dict[tuple[str, Timeframe, int], BarDict] = {}
        self._symbol_meta: Dict[str, Dict[str, float]] = {}
        self._series_path_meta: Dict[tuple[str, Timeframe], Dict[str, object]] = {}

    def ensure_symbol(self, symbol: str):
        with self._lock:
            if symbol in self._subscribed:
                return False
            self._subscribed.add(symbol)
            metrics.inc("market_subscribe")
            return True

    def load_initial(self, symbol: str, timeframe: Timeframe, *, limit: Optional[int] = None) -> BarsSeries:
        lim = limit or self._default_limit
        start_ms = time.perf_counter()
        requested_scope = self._requested_history_scope()
        runtime_rows = self._runtime_fetch_bars(symbol, timeframe, lim)
        bars, runtime_meta = self._extract_runtime_bars(runtime_rows)
        if bars:
            self._record_series_path_meta(
                symbol,
                timeframe,
                source="runtime-persisted-bars",
                authoritative=True,
                runtime_backed=True,
                refresh="runtime-query-load",
                history_scope_requested=requested_scope,
                history_scope_resolved=str(runtime_meta.get("history_scope_resolved") or "unscoped"),
            )
        else:
            bars = self._runtime_fetch_trade_bars(symbol, timeframe, lim)
            if bars:
                self._record_series_path_meta(
                    symbol,
                    timeframe,
                    source="runtime-trade-log-bars",
                    authoritative=True,
                    runtime_backed=True,
                    refresh="runtime-query-trade-bars",
                    history_scope_requested=requested_scope,
                    history_scope_resolved="runtime-trade-log",
                )
        if not bars:
            if self._allow_synthetic_fallback:
                bars = self._fetcher(symbol, timeframe, lim)
                if bars:
                    is_default_synthetic = bool(self._series_placeholder)
                    self._record_series_path_meta(
                        symbol,
                        timeframe,
                        source="default-synthetic-fetcher" if is_default_synthetic else "fetcher",
                        authoritative=False,
                        runtime_backed=False,
                        refresh="synthetic-fallback" if is_default_synthetic else "fetcher-load",
                        history_scope_requested=requested_scope,
                        history_scope_resolved="synthetic-fallback" if is_default_synthetic else "fetcher",
                    )
            else:
                self._record_series_path_meta(
                    symbol,
                    timeframe,
                    source="runtime-empty",
                    authoritative=False,
                    runtime_backed=True,
                    refresh="runtime-query-load",
                    history_scope_requested=requested_scope,
                    history_scope_resolved="none",
                )
        if not bars:
            raise RuntimeError("failed to load initial bars")
        self._cache.upsert(symbol, timeframe, bars)
        series = self._cache.get(symbol, timeframe)
        metrics.add_timing("market_load_initial_ms", (time.perf_counter() - start_ms) * 1000)
        if series is None:
            raise RuntimeError("failed to load initial bars")
        return series

    def append_realtime(self, symbol: str, timeframe: Timeframe, bar: dict[str, object]) -> None:
        self._cache.upsert(symbol, timeframe, [bar])  # type: ignore[arg-type]
        metrics.inc("market_realtime_bar")

    def register_symbol_meta(
        self,
        symbol: str,
        *,
        reference_price: float | None = None,
        price_step: float | None = None,
        limit_pct: float = 0.10,
    ) -> None:
        sym = (symbol or "").strip().upper()
        if not sym:
            return
        with self._lock:
            meta = dict(self._symbol_meta.get(sym) or {})
            if reference_price is not None and reference_price > 0:
                meta["reference_price"] = float(reference_price)
            if price_step is not None and price_step > 0:
                meta["price_step"] = float(price_step)
            meta["limit_pct"] = float(limit_pct)
            self._symbol_meta[sym] = meta

    def record_runtime_trade(self, symbol: str, *, price: float, qty: int, ts_ms: Optional[int] = None) -> None:
        sym = (symbol or "").strip().upper()
        if not sym or price <= 0 or qty <= 0:
            return
        event_ts = int(ts_ms if ts_ms is not None else time.time() * 1000)
        requested_scope = self._requested_history_scope()
        with self._lock:
            if sym not in self._runtime_symbols:
                self._cache.clear_symbol(sym)
                self._runtime_symbols.add(sym)
            meta = dict(self._symbol_meta.get(sym) or {})
            meta.setdefault("reference_price", float(price))
            meta.setdefault("price_step", 0.01)
            meta.setdefault("limit_pct", 0.10)
            self._symbol_meta[sym] = meta
            for timeframe in ("1m", "5m", "15m", "60m", "1d"):
                bucket_ts = self._runtime_trade_bucket_start_ms(event_ts, timeframe)
                key = (sym, timeframe, bucket_ts)
                bar = self._realtime_bars.get(key)
                if bar is None:
                    bar = {
                        "ts": bucket_ts,
                        "open": float(price),
                        "high": float(price),
                        "low": float(price),
                        "close": float(price),
                        "volume": float(qty),
                    }
                else:
                    bar = {
                        "ts": bucket_ts,
                        "open": float(bar["open"]),
                        "high": float(max(float(bar["high"]), price)),
                        "low": float(min(float(bar["low"]), price)),
                        "close": float(price),
                        "volume": float(bar.get("volume", 0.0)) + float(qty),
                    }
                self._realtime_bars[key] = bar
                self.append_realtime(sym, timeframe, bar)
                self._record_series_path_meta(
                    sym,
                    timeframe,
                    source="runtime-trade-cache",
                    authoritative=True,
                    runtime_backed=True,
                    refresh="trade-event-append",
                    history_scope_requested=requested_scope,
                    history_scope_resolved="runtime-trade-cache",
                )
        metrics.inc("market_runtime_trade_bar")

    def record_runtime_bar_update(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        sym = str(payload.get("symbol") or "").strip().upper()
        timeframe = self._normalize_timeframe(str(payload.get("timeframe") or ""))
        raw_bar = payload.get("bar") or {}
        if not sym or timeframe is None or not isinstance(raw_bar, dict):
            return
        try:
            open_p = float(raw_bar.get("open") or 0.0)
            high_p = float(raw_bar.get("high") or 0.0)
            low_p = float(raw_bar.get("low") or 0.0)
            close_p = float(raw_bar.get("close") or 0.0)
            volume = float(raw_bar.get("volume") or 0.0)
        except Exception:
            return
        if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
            return
        ts = self._bar_event_ts_ms(raw_bar.get("ts"), timeframe, payload.get("sim_day"))
        bar: BarDict = {
            "ts": ts,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
        }
        requested_scope = self._requested_history_scope()
        with self._lock:
            if sym not in self._runtime_symbols:
                self._cache.clear_symbol(sym)
                self._runtime_symbols.add(sym)
            meta = dict(self._symbol_meta.get(sym) or {})
            meta.setdefault("reference_price", open_p)
            meta.setdefault("price_step", 0.01)
            meta.setdefault("limit_pct", 0.10)
            self._symbol_meta[sym] = meta
            self._realtime_bars[(sym, timeframe, ts)] = bar
            self.append_realtime(sym, timeframe, bar)
            self._record_series_path_meta(
                sym,
                timeframe,
                source="runtime-persisted-bars",
                authoritative=True,
                runtime_backed=True,
                refresh="bar-event-append",
                history_scope_requested=requested_scope,
                history_scope_resolved="active-run" if payload.get("run_id") else "runtime-bar-event",
            )
        metrics.inc("market_runtime_bar_update")

    def get_closes(self, symbol: str, timeframe: Timeframe) -> Optional[np.ndarray]:
        return self._cache.get_close(symbol, timeframe)

    def get_ohlcv(self, symbol: str, timeframe: Timeframe) -> Optional[BarsSeries]:
        return self._cache.get(symbol, timeframe)

    def request_detail(self, symbol: str, timeframe: Timeframe, *, ensure_loaded: bool = True, limit: Optional[int] = None) -> Dict[str, object]:
        series = self._cache.get(symbol, timeframe)
        if series is None and ensure_loaded:
            try:
                series = self.load_initial(symbol, timeframe, limit=limit)
            except Exception:
                series = None
        stale = self._cache.is_stale(symbol, timeframe)
        series_meta = self._describe_series_path(symbol, timeframe, series)
        series_status = self._resolve_series_status(series, stale=stale, path_meta=series_meta)
        detail_series_meta = {
            "source": str(series_meta.get("source") or "unknown"),
            "authoritative": bool(series_meta.get("authoritative", False)),
            "status": series_status,
            "refresh": str(series_meta.get("refresh") or "unknown"),
            "placeholder": bool(series_meta.get("source") == "default-synthetic-fetcher"),
            "origin": str(series_meta.get("source") or "unknown"),
            "runtime_backed": bool(series_meta.get("runtime_backed", False)),
            "history_scope_requested": str(series_meta.get("history_scope_requested") or self._requested_history_scope()),
            "history_scope_resolved": str(series_meta.get("history_scope_resolved") or "none"),
        }
        return {
            "series": series,
            "is_stale": stale,
            "symbol": symbol,
            "timeframe": timeframe,
            "chart_meta": self._build_chart_meta(symbol, timeframe, series, series_meta),
            "series_meta": detail_series_meta,
            "series_placeholder": bool(detail_series_meta["placeholder"]),
            "series_origin": str(detail_series_meta["origin"]),
            "series_authoritative": bool(detail_series_meta["authoritative"]),
            "series_runtime_backed": bool(detail_series_meta["runtime_backed"]),
            "series_history_scope_requested": str(detail_series_meta["history_scope_requested"]),
            "series_history_scope_resolved": str(detail_series_meta["history_scope_resolved"]),
            "series_refresh": str(detail_series_meta["refresh"]),
            "series_status": series_status,
        }

    def subscribed_symbols(self) -> List[str]:
        with self._lock:
            return list(self._subscribed)

    def get_retail_holdings(self, symbol: str, limit: int = 8) -> Dict[str, object] | None:
        if not self._enable_runtime_holdings:
            return None
        return self._runtime_gateway.get_retail_holdings(symbol, limit=limit)

    def get_holdings_detail(self, symbol: str, limit: int = 8) -> Dict[str, object]:
        holdings = None
        holdings_meta: Dict[str, object] = {
            "source": "placeholder",
            "authoritative": False,
            "status": "placeholder",
            "refresh": "helper-fetch",
        }
        try:
            try:
                holdings = self.get_retail_holdings(symbol, limit=limit)
            except TypeError:
                holdings = self.get_retail_holdings(symbol)
            if isinstance(holdings, dict):
                holdings_meta = {
                    "source": str(holdings.get("source") or "runtime-position-book"),
                    "authoritative": bool(holdings.get("authoritative", False)),
                    "status": "available",
                    "refresh": "runtime-query",
                }
        except Exception:
            holdings = None
            holdings_meta = {
                "source": "runtime-position-book",
                "authoritative": False,
                "status": "error",
                "refresh": "runtime-query",
            }

        if holdings is None:
            holdings = {
                "labels": [],
                "pct": [],
                "placeholder": True,
                "note": "non-authoritative holdings placeholder",
            }

        return {
            "holdings": holdings,
            "holdings_meta": holdings_meta,
        }

    def get_recent_trades(self, symbol: str, limit: int = 20) -> List[Dict[str, object]]:
        try:
            return self._runtime_gateway.get_recent_trades(symbol, limit=limit)  # type: ignore[return-value]
        except TypeError:
            return self._runtime_gateway.get_recent_trades(symbol)  # type: ignore[return-value]

    def get_trades_detail(self, symbol: str, limit: int = 20) -> Dict[str, object]:
        trades: List[Dict[str, object]] = []
        trades_meta: Dict[str, object] = {
            "source": "runtime-trade-log",
            "authoritative": True,
            "status": "empty",
            "refresh": "runtime-query",
        }
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {
                "trades": trades,
                "trades_meta": trades_meta,
            }
        try:
            trades = [
                self._normalize_trade_row(row)
                for row in self.get_recent_trades(sym, limit=limit)
                if isinstance(row, dict)
            ]
            trades = [row for row in trades if row]
            trades_meta["status"] = "available" if trades else "empty"
        except Exception:
            trades = []
            trades_meta = {
                "source": "runtime-trade-log",
                "authoritative": False,
                "status": "error",
                "refresh": "runtime-query",
            }
        return {
            "trades": trades,
            "trades_meta": trades_meta,
        }

    @staticmethod
    def _bucket_start_ms(ts_ms: int, timeframe: Timeframe) -> int:
        interval = _TIMEFRAME_MS[timeframe]
        return int(ts_ms // interval) * interval

    def _runtime_trade_bucket_start_ms(self, ts_ms: int, timeframe: Timeframe) -> int:
        if timeframe == "1d":
            try:
                sim_day = int(self._runtime_gateway.get_current_sim_day() or 0)
            except Exception:
                sim_day = 0
            return max(sim_day, 0) * _TIMEFRAME_MS["1d"]
        return self._bucket_start_ms(ts_ms, timeframe)

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> Timeframe | None:
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "60m": "60m",
            "1h": "60m",
            "1d": "1d",
        }
        value = mapping.get(str(timeframe or "").strip().lower())
        return value  # type: ignore[return-value]

    @staticmethod
    def _bar_event_ts_ms(raw_ts: object, timeframe: Timeframe, raw_sim_day: object = None) -> int:
        if timeframe == "1d":
            try:
                sim_day = int(raw_sim_day)  # type: ignore[arg-type]
            except Exception:
                sim_day = None
            if sim_day is not None:
                return max(sim_day, 0) * _TIMEFRAME_MS["1d"]
        if isinstance(raw_ts, (int, float)):
            ts_num = int(raw_ts)
            return ts_num if ts_num >= 10_000_000_000 else ts_num * 1000
        if isinstance(raw_ts, str) and raw_ts.strip():
            text = raw_ts.strip()
            try:
                ts_num = int(text)
                return ts_num if ts_num >= 10_000_000_000 else ts_num * 1000
            except Exception:
                pass
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if timeframe == "1d" and dt.year <= 1:
                    return max((dt.date() - date(1, 1, 1)).days, 0) * _TIMEFRAME_MS["1d"]
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                pass
        return int(time.time() * 1000)

    def _runtime_fetch_bars(self, symbol: str, timeframe: Timeframe, limit: int) -> List[BarDict]:
        return self._runtime_gateway.get_bars(symbol, timeframe, limit=limit)  # type: ignore[return-value]

    def _runtime_fetch_trade_bars(self, symbol: str, timeframe: Timeframe, limit: int) -> List[BarDict]:
        try:
            trade_lookup_limit = min(max(int(limit) * 8, 200), 1_000)
            trade_rows = self.get_recent_trades(symbol, limit=trade_lookup_limit)
        except Exception:
            return []
        trades: List[Dict[str, object]] = []
        for row in trade_rows:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_trade_row(row)
            if not normalized:
                continue
            try:
                ts = int(normalized.get("ts") or 0)
                price = float(normalized.get("price") or 0.0)
                qty = int(normalized.get("qty") or 0)
            except Exception:
                continue
            if ts <= 0 or price <= 0 or qty <= 0:
                continue
            trades.append({"ts": ts, "price": price, "qty": qty})
        if not trades:
            return []
        trades.sort(key=lambda item: int(item["ts"]))
        grouped: Dict[int, BarDict] = {}
        for trade in trades:
            bucket_ts = self._bucket_start_ms(int(trade["ts"]), timeframe)
            price = float(trade["price"])
            qty = int(trade["qty"])
            bar = grouped.get(bucket_ts)
            if bar is None:
                grouped[bucket_ts] = {
                    "ts": bucket_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": float(qty),
                }
            else:
                bar["high"] = float(max(float(bar["high"]), price))
                bar["low"] = float(min(float(bar["low"]), price))
                bar["close"] = price
                bar["volume"] = float(bar.get("volume", 0.0)) + float(qty)
        bars = [grouped[key] for key in sorted(grouped)]
        return bars[-max(int(limit), 1):]

    def _normalize_trade_row(self, row: Dict[str, Any]) -> Dict[str, object]:
        ts_raw = row.get("ts")
        ts_ms: int | None
        try:
            ts_ms = int(ts_raw) if ts_raw is not None else None
        except Exception:
            ts_ms = None
        return {
            "trade_id": str(row.get("trade_id") or ""),
            "symbol": str(row.get("symbol") or ""),
            "price": float(row.get("price") or 0.0),
            "qty": int(row.get("qty") or row.get("quantity") or 0),
            "ts": ts_ms,
            "buy_account_id": str(row.get("buy_account_id") or ""),
            "sell_account_id": str(row.get("sell_account_id") or ""),
            "buy_order_id": str(row.get("buy_order_id") or ""),
            "sell_order_id": str(row.get("sell_order_id") or ""),
            "source": "runtime-trade-log",
        }

    def _build_chart_meta(
        self,
        symbol: str,
        timeframe: Timeframe,
        series: Optional[BarsSeries],
        series_meta: Dict[str, object],
    ) -> Dict[str, float | int | str | None]:
        sym = (symbol or "").strip().upper()
        with self._lock:
            meta = dict(self._symbol_meta.get(sym) or {})
        reference_price = float(meta.get("reference_price") or 0.0)
        if reference_price <= 0 and series is not None and len(series.close):
            try:
                reference_price = float(series.open[0] or series.close[0])
            except Exception:
                reference_price = 0.0
        if reference_price <= 0 and series is not None and len(series.close):
            try:
                reference_price = float(series.close[-1])
            except Exception:
                reference_price = 0.0
        price_step = float(meta.get("price_step") or 0.01)
        limit_pct = float(meta.get("limit_pct") or 0.10)
        limit_down = None
        limit_up = None
        if reference_price > 0:
            limit_down = round(max(price_step, reference_price * (1.0 - limit_pct)), 6)
            limit_up = round(max(limit_down + price_step, reference_price * (1.0 + limit_pct)), 6)
        history_high = None
        if series is not None and len(series.high):
            try:
                history_high = float(np.max(series.high))
            except Exception:
                history_high = None
        active_run_id = None
        try:
            active_run_id = self._runtime_gateway.get_current_run_id()
        except Exception:
            active_run_id = None
        requested_scope = str(series_meta.get("history_scope_requested") or self._requested_history_scope())
        resolved_scope = str(series_meta.get("history_scope_resolved") or "none")
        return {
            "reference_price": reference_price or None,
            "price_step": price_step,
            "limit_pct": limit_pct,
            "limit_down": limit_down,
            "limit_up": limit_up,
            "day_slots": _TRADING_DAY_SLOTS[timeframe],
            "interval_ms": _TIMEFRAME_MS[timeframe],
            "current_sim_day": int(self._runtime_gateway.get_current_sim_day()),
            "history_high": history_high,
            "active_run_id": active_run_id,
            "history_scope": resolved_scope,
            "history_scope_requested": requested_scope,
            "history_scope_resolved": resolved_scope,
            "series_source": str(series_meta.get("source") or "unknown"),
            "series_authoritative": bool(series_meta.get("authoritative", False)),
        }

    def _requested_history_scope(self) -> str:
        try:
            run_id = self._runtime_gateway.get_current_run_id()
        except Exception:
            run_id = None
        return "active-run" if run_id else "unscoped"

    def _record_series_path_meta(self, symbol: str, timeframe: Timeframe, **meta: object) -> None:
        sym = (symbol or "").strip().upper()
        if not sym:
            return
        with self._lock:
            self._series_path_meta[(sym, timeframe)] = dict(meta)

    def _extract_runtime_bars(self, rows: List[BarDict]) -> tuple[List[BarDict], Dict[str, object]]:
        requested_scope = self._requested_history_scope()
        if not rows:
            return [], {
                "history_scope_requested": requested_scope,
                "history_scope_resolved": "none",
            }
        first = rows[0] if isinstance(rows[0], dict) else {}
        resolved_scope = "unscoped"
        if isinstance(first, dict):
            resolved_scope = str(first.get("_history_scope") or first.get("history_scope") or resolved_scope)
        cleaned: List[BarDict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cleaned.append(
                {
                    "ts": row["ts"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row.get("volume", 0.0),
                }
            )
        return cleaned, {
            "history_scope_requested": requested_scope,
            "history_scope_resolved": resolved_scope,
        }

    def _describe_series_path(
        self,
        symbol: str,
        timeframe: Timeframe,
        series: Optional[BarsSeries],
    ) -> Dict[str, object]:
        sym = (symbol or "").strip().upper()
        with self._lock:
            stored = dict(self._series_path_meta.get((sym, timeframe)) or {})
        if stored:
            return stored
        if sym in self._runtime_symbols:
            return {
                "source": "runtime-trade-cache",
                "authoritative": True,
                "runtime_backed": True,
                "refresh": "trade-event-append",
                "history_scope_requested": self._requested_history_scope(),
                "history_scope_resolved": "runtime-trade-cache",
            }
        if series is None and not self._allow_synthetic_fallback:
            return {
                "source": "runtime-empty",
                "authoritative": False,
                "runtime_backed": True,
                "refresh": "runtime-query-load",
                "history_scope_requested": self._requested_history_scope(),
                "history_scope_resolved": "none",
            }
        if series is not None and self._allow_synthetic_fallback and self._series_placeholder:
            return {
                "source": "default-synthetic-fetcher",
                "authoritative": False,
                "runtime_backed": False,
                "refresh": "synthetic-fallback",
                "history_scope_requested": self._requested_history_scope(),
                "history_scope_resolved": "synthetic-fallback",
            }
        return {
            "source": "fetcher",
            "authoritative": False,
            "runtime_backed": False,
            "refresh": "fetcher-load",
            "history_scope_requested": self._requested_history_scope(),
            "history_scope_resolved": "fetcher" if series is not None else "none",
        }

    @staticmethod
    def _resolve_series_status(
        series: Optional[BarsSeries],
        *,
        stale: bool,
        path_meta: Dict[str, object],
    ) -> str:
        if series is None:
            return "missing"
        if str(path_meta.get("source") or "") == "default-synthetic-fetcher":
            return "placeholder"
        if stale:
            return "stale"
        return "available"


def _synthetic_fetcher(symbol: str, timeframe: Timeframe, limit: int) -> List[BarDict]:
    interval = _TIMEFRAME_MS[timeframe]
    now = int(time.time() * 1000)
    start = now - (limit - 1) * interval
    h = abs(hash(symbol)) % 10_000
    rng = np.random.default_rng(h)
    base = 50 + (h % 300) / 10.0
    bars: List[BarDict] = []
    price = base
    for i in range(limit):
        ts = start + i * interval
        wave = math.sin(i / 20.0) * 0.5
        noise = rng.normal(0, 0.2)
        price = max(0.5, price + wave + noise)
        high = price + abs(rng.normal(0, 0.3))
        low = max(0.1, price - abs(rng.normal(0, 0.3)))
        open_ = price + rng.normal(0, 0.15)
        close = price + rng.normal(0, 0.15)
        vol = max(1.0, abs(rng.normal(100, 20)))
        bars.append(
            {
                "ts": ts,
                "open": float(open_),
                "high": float(max(open_, high, close)),
                "low": float(min(open_, low, close)),
                "close": float(close),
                "volume": float(vol),
            }
        )
    return bars


__all__ = [
    "MarketDataService",
    "_synthetic_fetcher",
]
