from __future__ import annotations

from typing import Any, Dict
from collections import defaultdict

try:
    from stock_sim.services.replay_service import replay_service  # type: ignore
    from stock_sim.services.simulation_run_service import SimulationRunService  # type: ignore
except Exception:  # noqa
    from services.replay_service import replay_service  # type: ignore
    from services.simulation_run_service import SimulationRunService  # type: ignore

try:
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.persistence.models_order import OrderORM  # type: ignore
    from stock_sim.persistence.models_trade import TradeORM  # type: ignore
    from stock_sim.persistence.models_ledger import Ledger  # type: ignore
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_snapshot import Snapshot1s  # type: ignore
    from stock_sim.persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore
except Exception:  # noqa
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from persistence.models_order import OrderORM  # type: ignore
    from persistence.models_trade import TradeORM  # type: ignore
    from persistence.models_ledger import Ledger  # type: ignore
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_snapshot import Snapshot1s  # type: ignore
    from persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore


_READONLY = False
_SENT_RESUMED = False
_LAST_REPORT: Dict[str, Any] | None = None


class RecoveryService:
    def _build_report(self) -> Dict[str, Any]:
        s = SessionLocal()
        try:
            order_rows = s.query(OrderORM).all()
            trade_rows = s.query(TradeORM).all()
            ledger_rows = s.query(Ledger).all()
            event_rows = s.query(EventLog).all()

            orders = len(order_rows)
            open_orders = sum(1 for r in order_rows if str(r.status).endswith("NEW") or str(r.status).endswith("PARTIAL"))
            filled_orders = sum(1 for r in order_rows if str(r.status).endswith("FILLED"))
            trades = len(trade_rows)
            ledgers = len(ledger_rows)
            events = len(event_rows)

            per_run = defaultdict(lambda: {"filled_orders": 0, "trades": 0, "ledgers": 0})
            for r in order_rows:
                rid = getattr(r, "run_id", None)
                if str(r.status).endswith("FILLED"):
                    per_run[rid]["filled_orders"] += 1
            for r in trade_rows:
                per_run[getattr(r, "run_id", None)]["trades"] += 1
            for r in ledger_rows:
                per_run[getattr(r, "run_id", None)]["ledgers"] += 1

            inconsistent_runs = []
            warning_runs = []
            replay_validation: dict[str | None, dict] = {}
            run_ids = {rid for rid in per_run.keys() if rid is not None}
            run_ids.update({getattr(r, 'run_id', None) for r in event_rows if getattr(r, 'run_id', None) is not None})
            run_ids.update({getattr(r, 'run_id', None) for r in trade_rows if getattr(r, 'run_id', None) is not None})
            run_ids.update({getattr(r, 'run_id', None) for r in ledger_rows if getattr(r, 'run_id', None) is not None})
            run_ids.update({getattr(r, 'run_id', None) for r in order_rows if getattr(r, 'run_id', None) is not None})
            run_ids.update({r[0] for r in s.query(Snapshot1s.run_id).filter(Snapshot1s.run_id.isnot(None)).distinct().all()})
            run_ids.update({r[0] for r in s.query(Bar1m.run_id).filter(Bar1m.run_id.isnot(None)).distinct().all()})
            run_ids.update({r[0] for r in s.query(Bar1h.run_id).filter(Bar1h.run_id.isnot(None)).distinct().all()})
            run_ids.update({r[0] for r in s.query(Bar1d.run_id).filter(Bar1d.run_id.isnot(None)).distinct().all()})
            for run_id in sorted(run_ids):
                stats = per_run[run_id]
                severe = (stats["trades"] > stats["ledgers"] and stats["trades"] > 0) or (stats["filled_orders"] > stats["trades"])
                try:
                    replay_validation[run_id] = replay_service.build_run_report(run_id)
                    try:
                        SimulationRunService(s).sync_from_run_report(run_id, replay_validation[run_id])
                    except Exception:
                        pass
                except Exception:
                    replay_validation[run_id] = {"run_id": run_id, "ok": False, "error": "replay_validation_failed"}
                rep = replay_validation.get(run_id)
                if rep:
                    val = rep.get("validation", {})
                    bars = val.get("bars", {})
                    bars_1m = bars.get("1m", {})
                    bars_1h = bars.get("1h", {})
                    bars_1d = bars.get("1d", {})
                    if val.get("persisted", {}).get("snapshots", 0) > 0 and bars_1m.get("count", 0) == 0:
                        severe = True
                    if bars_1m.get("count", 0) > 0 and (bars_1h.get("count", 0) == 0 or bars_1d.get("count", 0) == 0):
                        warning_runs.append(run_id)
                if severe:
                    inconsistent_runs.append(run_id)

            try:
                s.commit()
            except Exception:
                s.rollback()
            return {
                "status": "ok",
                "readonly": False,
                "restored_entities": orders + trades + ledgers,
                "counts": {
                    "orders": orders,
                    "open_orders": open_orders,
                    "filled_orders": filled_orders,
                    "trades": trades,
                    "ledgers": ledgers,
                    "event_log": events,
                },
                "checks": {
                    "trade_without_ledger_possible": trades > ledgers and trades > 0,
                    "filled_order_without_trade_possible": filled_orders > trades,
                    "event_log_available": events > 0,
                    "inconsistent_runs": inconsistent_runs,
                    "warning_runs": sorted({r for r in warning_runs if r is not None}),
                    "replay_validation": replay_validation,
                },
            }
        finally:
            s.close()

    def recover(self) -> Dict[str, Any]:
        global _READONLY, _SENT_RESUMED, _LAST_REPORT
        report = self._build_report()
        inconsistent = bool(report["checks"].get("inconsistent_runs"))
        if inconsistent:
            _READONLY = True
            report["status"] = "degraded"
            report["readonly"] = True
            report["reason"] = "TRADE_LEDGER_MISMATCH"
            try:
                event_bus.publish(EventType.RECOVERY_FAILED, report)
            except Exception:
                pass
            _LAST_REPORT = report
            return report

        _READONLY = False
        try:
            event_bus.publish(EventType.RECOVERY_RESUMED, report)
            _SENT_RESUMED = True
        except Exception:
            pass
        _LAST_REPORT = report
        return report

    def last_report(self) -> Dict[str, Any] | None:
        return _LAST_REPORT


def is_readonly() -> bool:
    return _READONLY


def mark_failed(reason: str = "unknown"):
    global _READONLY, _LAST_REPORT
    if _READONLY:
        return
    _READONLY = True
    payload = {"reason": reason, "status": "degraded", "readonly": True}
    _LAST_REPORT = payload
    try:
        event_bus.publish(EventType.RECOVERY_FAILED, payload)
    except Exception:
        pass


def mark_resumed_if_needed():
    global _SENT_RESUMED, _LAST_REPORT
    if _READONLY:
        return
    if _SENT_RESUMED:
        return
    payload = {"status": "ok", "lazy": True, "readonly": False}
    _LAST_REPORT = payload
    try:
        event_bus.publish(EventType.RECOVERY_RESUMED, payload)
        _SENT_RESUMED = True
    except Exception:
        pass


recovery_service = RecoveryService()

__all__ = [
    "RecoveryService",
    "recovery_service",
    "is_readonly",
    "mark_resumed_if_needed",
    "mark_failed",
]
