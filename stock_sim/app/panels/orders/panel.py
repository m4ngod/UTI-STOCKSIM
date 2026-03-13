from __future__ import annotations
"""OrdersPanel (R1/R4/R5)

Headless-safe logic-only panel to collect and filter order-related lines:
- Supports three event types: Trade, OrderRejected, OrderCanceled
- Maintains a bounded deque (default capacity=1000) of normalized lines
- Provides symbol substring filter and type filter
- Thread-safe with a simple RLock

Normalization target keys per line:
  { ts:int(ms), type:str in {Trade, OrderRejected, OrderCanceled},
    order_id:Optional[str], symbol:Optional[str], side:Optional[str],
    price:Optional[float], qty:Optional[int], status:Optional[str], reason:Optional[str],
    account_id: Optional[str] }

No Qt imports; no event_bus wiring here.
"""
from typing import Any, Dict, Optional, Set
from threading import RLock
from collections import deque
import time
from datetime import datetime

__all__ = ["OrdersPanel"]


class OrdersPanel:
    def __init__(self, capacity: int = 1000) -> None:
        self._lock = RLock()
        self._capacity = max(1, int(capacity))
        self._lines: deque[Dict[str, Any]] = deque(maxlen=self._capacity)
        self._symbol_filter: Optional[str] = None  # lower-case substring
        self._type_filter: Optional[Set[str]] = None  # e.g., {"Trade", "OrderRejected"}
        self._account_filter: Optional[str] = None  # 新增: account_id 过滤

    # ---------------- Public API ----------------
    def add_line(self, payload: Dict[str, Any]) -> None:
        """Add a line from various payload shapes; normalize then append.
        Accepts payloads in two flavors:
          - Already normalized dict containing required keys (type, ts, ...)
          - Raw event payloads from services/order_service:
            * Trade: {"trade": {...}}
            * OrderRejected: {"order": {...}, "reason": str}
            * OrderCanceled: {"order_id": str, "reason": str}
        Unknown/extra fields are ignored. Missing normalized fields are set to None.
        """
        line = self._normalize(payload)
        if line is None:
            return
        with self._lock:
            self._lines.append(line)

    def set_symbol_filter(self, symbol_substring: Optional[str]) -> None:
        with self._lock:
            self._symbol_filter = symbol_substring.lower() if symbol_substring else None

    def set_type_filter(self, types: Optional[Set[str]]) -> None:
        with self._lock:
            self._type_filter = set(types) if types else None

    def set_account_filter(self, account_id: Optional[str]) -> None:
        with self._lock:
            self._account_filter = account_id or None

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def set_capacity(self, capacity: int) -> None:
        cap = max(1, int(capacity))
        with self._lock:
            if cap == self._capacity:
                return
            # rebuild deque preserving the newest items up to new capacity
            items = list(self._lines)
            if len(items) > cap:
                items = items[-cap:]
            self._capacity = cap
            self._lines = deque(items, maxlen=self._capacity)

    def get_view(self) -> Dict[str, Any]:
        """Return a snapshot view.
        Items are ordered from oldest -> newest (append order). UI may reverse if desired.
        Applies current filters.
        """
        with self._lock:
            sym_filter = self._symbol_filter
            type_filter = self._type_filter
            acct_filter = self._account_filter
            items = list(self._lines)
        if sym_filter:
            items = [ln for ln in items if isinstance(ln.get("symbol"), str) and sym_filter in ln["symbol"].lower()]
        if type_filter:
            items = [ln for ln in items if ln.get("type") in type_filter]
        if acct_filter:
            items = [ln for ln in items if ln.get("account_id") == acct_filter]
        return {
            "items": [dict(ln) for ln in items],
            "capacity": self._capacity,
            "filters": {
                "symbol": sym_filter,
                "types": sorted(type_filter) if type_filter else None,
                "account_id": acct_filter,
            },
            "total": len(items),
        }

    # ---------------- Internals ----------------
    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _iso_to_ms(s: str) -> Optional[int]:
        try:
            # Accept YYYY-MM-DDTHH:MM:SS[.ffffff][+offset]
            # Use fromisoformat; if timezone-aware, timestamp() handles it
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    @staticmethod
    def _normalize_type(t: Any) -> Optional[str]:
        if not t:
            return None
        if isinstance(t, str):
            # Accept case-insensitive
            t_up = t.strip()
            # Keep canonical case
            candidates = {"Trade", "OrderRejected", "OrderCanceled"}
            if t_up in candidates:
                return t_up
            t_cap = t_up.capitalize()
            if t_cap in candidates:
                return t_cap
            # Common lowercase keys
            mapping = {"trade": "Trade", "orderrejected": "OrderRejected", "ordercanceled": "OrderCanceled"}
            key = t_up.replace("_", "").replace("-", "").lower()
            return mapping.get(key)
        return None

    def _normalize(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Fast-path: already normalized
        if isinstance(payload.get("type"), str) and {
            "ts", "type"
        }.issubset(payload.keys()):
            # Ensure required keys exist; fill defaults
            return {
                "ts": self._coerce_ts(payload.get("ts")),
                "type": self._normalize_type(payload.get("type")) or "Trade",
                "order_id": payload.get("order_id"),
                "symbol": payload.get("symbol"),
                "side": self._safe_lower(payload.get("side")),
                "price": self._safe_float(payload.get("price")),
                "qty": self._safe_int(payload.get("qty")),
                "status": payload.get("status"),
                "reason": payload.get("reason"),
                "account_id": payload.get("account_id"),
            }

        # Trade event: {"trade": {...}}
        if isinstance(payload.get("trade"), dict):
            tr = payload["trade"]
            ts = self._coerce_ts(tr.get("ts") or payload.get("ts")) or self._now_ms()
            # Try several possible keys for qty and side
            qty = self._safe_int(tr.get("qty") if "qty" in tr else tr.get("quantity"))
            side = self._safe_lower(tr.get("side"))
            symbol = tr.get("symbol")
            price = self._safe_float(tr.get("price"))
            order_id = tr.get("order_id") or tr.get("buy_order_id") or tr.get("sell_order_id")
            account_id = tr.get("account_id") or payload.get("account_id")
            return {
                "ts": ts,
                "type": "Trade",
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "price": price,
                "qty": qty,
                "status": "TRADE",
                "reason": None,
                "account_id": account_id,
            }

        # OrderRejected: {"order": {...}, "reason": str}
        if isinstance(payload.get("order"), dict) and "reason" in payload:
            od = payload["order"]
            ts = self._coerce_ts(payload.get("ts"))
            if ts is None:
                ts = self._try_order_ts(od) or self._now_ms()
            qty = self._safe_int(od.get("qty") if "qty" in od else od.get("quantity"))
            return {
                "ts": ts,
                "type": "OrderRejected",
                "order_id": od.get("order_id"),
                "symbol": od.get("symbol"),
                "side": self._safe_lower(od.get("side")),
                "price": self._safe_float(od.get("price")),
                "qty": qty,
                "status": od.get("status") or "REJECTED",
                "reason": payload.get("reason"),
                "account_id": od.get("account_id") or payload.get("account_id"),
            }

        # OrderCanceled: {"order_id": str, "reason": str}
        if isinstance(payload.get("order_id"), str) and "reason" in payload:
            ts = self._coerce_ts(payload.get("ts")) or self._now_ms()
            return {
                "ts": ts,
                "type": "OrderCanceled",
                "order_id": payload.get("order_id"),
                "symbol": payload.get("symbol"),
                "side": self._safe_lower(payload.get("side")),
                "price": self._safe_float(payload.get("price")),
                "qty": self._safe_int(payload.get("qty")),
                "status": payload.get("status") or "CANCELED",
                "reason": payload.get("reason"),
                "account_id": payload.get("account_id"),
            }

        # If cannot determine, skip
        return None

    @staticmethod
    def _coerce_ts(v: Any) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, int):
            # Heuristic: treat < 1e11 as seconds
            return v if v >= 10_000_000_000 else v * 1000
        if isinstance(v, float):
            return int(v * 1000) if v < 10_000_000_000 else int(v)
        if isinstance(v, str):
            # try int first
            try:
                iv = int(v)
                return iv if iv >= 10_000_000_000 else iv * 1000
            except Exception:
                pass
            ms = OrdersPanel._iso_to_ms(v)
            return ms
        return None

    @staticmethod
    def _safe_lower(v: Any) -> Optional[str]:
        if isinstance(v, str):
            return v.lower()
        return None

    @staticmethod
    def _safe_int(v: Any) -> Optional[int]:
        try:
            if v is None:
                return None
            iv = int(v)
            return iv
        except Exception:
            return None

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            fv = float(v)
            return fv
        except Exception:
            return None

    @staticmethod
    def _try_order_ts(od: Dict[str, Any]) -> Optional[int]:
        # Prefer ts_last then ts_created, typical isoformat strings
        for k in ("ts_last", "ts_created"):
            v = od.get(k)
            if isinstance(v, str):
                ms = OrdersPanel._iso_to_ms(v)
                if ms is not None:
                    return ms
        return None
