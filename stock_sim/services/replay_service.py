from __future__ import annotations

import json
from collections import Counter
from typing import Callable, List, Dict, Any

try:
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.persistence.models_order import OrderORM  # type: ignore
    from stock_sim.persistence.models_trade import TradeORM  # type: ignore
    from stock_sim.persistence.models_ledger import Ledger  # type: ignore
    from stock_sim.persistence.models_snapshot import Snapshot1s  # type: ignore
    from stock_sim.persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore
except Exception:  # noqa
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from persistence.models_order import OrderORM  # type: ignore
    from persistence.models_trade import TradeORM  # type: ignore
    from persistence.models_ledger import Ledger  # type: ignore
    from persistence.models_snapshot import Snapshot1s  # type: ignore
    from persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore


class ReplayService:
    def load_events(
        self,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int | None = None,
        run_id: str | None = None,
        start_sim_day: int | None = None,
        end_sim_day: int | None = None,
        start_sim_dt: Any | None = None,
        end_sim_dt: Any | None = None,
    ) -> List[Dict[str, Any]]:
        s = SessionLocal()
        try:
            q = s.query(EventLog)
            if start_ts is not None:
                q = q.filter(EventLog.ts_ms >= start_ts)
            if end_ts is not None:
                q = q.filter(EventLog.ts_ms <= end_ts)
            if run_id is not None:
                q = q.filter(EventLog.run_id == run_id)
            if start_sim_day is not None:
                q = q.filter(EventLog.sim_day >= start_sim_day)
            if end_sim_day is not None:
                q = q.filter(EventLog.sim_day <= end_sim_day)
            if start_sim_dt is not None:
                q = q.filter(EventLog.sim_dt >= start_sim_dt)
            if end_sim_dt is not None:
                q = q.filter(EventLog.sim_dt <= end_sim_dt)
            q = q.order_by(EventLog.ts_ms.asc(), EventLog.id.asc())
            if limit is not None:
                q = q.limit(limit)
            rows = q.all()
            out: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    payload = json.loads(r.payload) if r.payload else {}
                except Exception:
                    payload = {"_raw": r.payload}
                out.append(
                    {
                        "id": r.id,
                        "ts_ms": r.ts_ms,
                        "type": r.type,
                        "symbol": r.symbol,
                        "run_id": getattr(r, "run_id", None),
                        "sim_day": getattr(r, "sim_day", None),
                        "sim_dt": getattr(r, "sim_dt", None),
                        "payload": payload,
                    }
                )
            return out
        finally:
            s.close()

    def replay(
        self,
        apply_fn: Callable[[Dict[str, Any]], None],
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int | None = None,
        run_id: str | None = None,
        start_sim_day: int | None = None,
        end_sim_day: int | None = None,
        start_sim_dt: Any | None = None,
        end_sim_dt: Any | None = None,
    ) -> int:
        events = self.load_events(
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            run_id=run_id,
            start_sim_day=start_sim_day,
            end_sim_day=end_sim_day,
            start_sim_dt=start_sim_dt,
            end_sim_dt=end_sim_dt,
        )
        for ev in events:
            try:
                apply_fn(ev)
            except Exception:
                pass
        return len(events)

    def dry_run_summary(
        self,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int | None = None,
        run_id: str | None = None,
        start_sim_day: int | None = None,
        end_sim_day: int | None = None,
        start_sim_dt: Any | None = None,
        end_sim_dt: Any | None = None,
    ) -> Dict[str, Any]:
        events = self.load_events(
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            run_id=run_id,
            start_sim_day=start_sim_day,
            end_sim_day=end_sim_day,
            start_sim_dt=start_sim_dt,
            end_sim_dt=end_sim_dt,
        )
        type_counts = Counter(ev["type"] for ev in events)
        symbols = sorted({ev["symbol"] for ev in events if ev.get("symbol")})
        sim_days = [ev["sim_day"] for ev in events if ev.get("sim_day") is not None]
        return {
            "mode": "dry-run",
            "event_count": len(events),
            "type_counts": dict(type_counts),
            "symbols": symbols,
            "run_id": run_id,
            "sim_day_range": None if not sim_days else [min(sim_days), max(sim_days)],
        }

    def validate_against_persisted_facts(self, run_id: str) -> Dict[str, Any]:
        s = SessionLocal()
        try:
            events = self.load_events(run_id=run_id)
            event_counts = Counter(ev["type"] for ev in events)
            snapshot_rows = s.query(Snapshot1s).filter(Snapshot1s.run_id == run_id).all()
            bar1m_rows = s.query(Bar1m).filter(Bar1m.run_id == run_id).all()
            bar1h_rows = s.query(Bar1h).filter(Bar1h.run_id == run_id).all()
            bar1d_rows = s.query(Bar1d).filter(Bar1d.run_id == run_id).all()
            persisted = {
                "orders": s.query(OrderORM).filter(OrderORM.run_id == run_id).count(),
                "trades": s.query(TradeORM).filter(TradeORM.run_id == run_id).count(),
                "ledgers": s.query(Ledger).filter(Ledger.run_id == run_id).count(),
                "snapshots": len(snapshot_rows),
                "bars_1m": len(bar1m_rows),
                "bars_1h": len(bar1h_rows),
                "bars_1d": len(bar1d_rows),
            }
            event_side = {
                "orders": event_counts.get("OrderAccepted", 0) + event_counts.get("OrderRejected", 0),
                "trades": event_counts.get("TradeEvent", 0) + event_counts.get("Trade", 0),
                "accounts": event_counts.get("AccountUpdated", 0),
                "snapshots": event_counts.get("SnapshotUpdated", 0),
                "bars_1m": 0,
                "bars_1h": 0,
                "bars_1d": 0,
            }
            snapshot_events = [ev for ev in events if ev.get("type") == "SnapshotUpdated"]
            event_snapshot_symbols = sorted({ev.get("symbol") for ev in snapshot_events if ev.get("symbol")})
            row_snapshot_symbols = sorted({getattr(r, "symbol", None) for r in snapshot_rows if getattr(r, "symbol", None)})
            event_snapshot_sim_days = sorted({ev.get("sim_day") for ev in snapshot_events if ev.get("sim_day") is not None})
            row_snapshot_sim_days = sorted({getattr(r, "sim_day", None) for r in snapshot_rows if getattr(r, "sim_day", None) is not None})
            snapshot_event_coverage_available = bool(snapshot_events)
            bar1m_symbols = sorted({getattr(r, "symbol", None) for r in bar1m_rows if getattr(r, "symbol", None)})
            bar1h_symbols = sorted({getattr(r, "symbol", None) for r in bar1h_rows if getattr(r, "symbol", None)})
            bar1d_symbols = sorted({getattr(r, "symbol", None) for r in bar1d_rows if getattr(r, "symbol", None)})
            bar1m_sim_days = sorted({getattr(r, "sim_day", None) for r in bar1m_rows if getattr(r, "sim_day", None) is not None})
            bar1h_sim_days = sorted({getattr(r, "sim_day", None) for r in bar1h_rows if getattr(r, "sim_day", None) is not None})
            bar1d_sim_days = sorted({getattr(r, "sim_day", None) for r in bar1d_rows if getattr(r, "sim_day", None) is not None})
            checks = {
                "trade_event_vs_trade_row_gap": abs(event_side["trades"] - persisted["trades"]),
                "order_event_vs_order_row_gap": abs(event_side["orders"] - persisted["orders"]),
                "snapshot_event_vs_snapshot_row_gap": abs(event_side["snapshots"] - persisted["snapshots"]),
                "snapshot_event_coverage_available": snapshot_event_coverage_available,
                "snapshot_symbol_set_match": (event_snapshot_symbols == row_snapshot_symbols) if snapshot_event_coverage_available else None,
                "snapshot_sim_day_set_match": (event_snapshot_sim_days == row_snapshot_sim_days) if snapshot_event_coverage_available else None,
            }
            return {
                "run_id": run_id,
                "persisted": persisted,
                "event_side": event_side,
                "snapshot_symbols": {
                    "event_side": event_snapshot_symbols,
                    "persisted": row_snapshot_symbols,
                },
                "snapshot_sim_days": {
                    "event_side": event_snapshot_sim_days,
                    "persisted": row_snapshot_sim_days,
                },
                "snapshot_event_coverage_available": snapshot_event_coverage_available,
                "bars": {
                    "1m": {"symbols": bar1m_symbols, "sim_days": bar1m_sim_days, "count": len(bar1m_rows)},
                    "1h": {"symbols": bar1h_symbols, "sim_days": bar1h_sim_days, "count": len(bar1h_rows)},
                    "1d": {"symbols": bar1d_symbols, "sim_days": bar1d_sim_days, "count": len(bar1d_rows)},
                },
                "checks": checks,
                "ok": (
                    checks["trade_event_vs_trade_row_gap"] == 0
                    and (checks["snapshot_symbol_set_match"] in (True, None))
                    and (checks["snapshot_sim_day_set_match"] in (True, None))
                ),
            }
        finally:
            s.close()

    def build_run_report(self, run_id: str) -> Dict[str, Any]:
        dry = self.dry_run_summary(run_id=run_id)
        validation = self.validate_against_persisted_facts(run_id)
        return {
            "run_id": run_id,
            "summary": dry,
            "validation": validation,
            "ok": bool(dry.get("event_count", 0) >= 0 and validation.get("ok")),
        }


replay_service = ReplayService()

__all__ = ["ReplayService", "replay_service"]
