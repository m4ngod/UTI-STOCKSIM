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
    from stock_sim.services.run_persistence_query_service import RunPersistenceQueryService  # type: ignore
except Exception:  # noqa
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from services.run_persistence_query_service import RunPersistenceQueryService  # type: ignore


_READONLY = False
_SENT_RESUMED = False
_LAST_REPORT: Dict[str, Any] | None = None
_ACKED_INCONSISTENT_RUNS: set[str] = set()


class RecoveryService:
    @staticmethod
    def _collect_validation_reasons(rep: dict[str, Any] | None) -> list[str]:
        if not isinstance(rep, dict):
            return []
        val = rep.get("validation", {}) or {}
        mismatches = val.get("mismatches", {}) or {}
        coverage = bool(val.get("snapshot_event_coverage_available"))
        reasons: list[str] = []

        trade_gap = mismatches.get("trade_event_vs_trade_row_gap", {}) or {}
        if trade_gap.get("ok") is False:
            reasons.append("trade_event_trade_row_gap")

        order_gap = mismatches.get("order_event_vs_order_row_gap", {}) or {}
        if order_gap.get("ok") is False:
            reasons.append("order_event_order_row_gap")

        snapshot_gap = mismatches.get("snapshot_event_vs_snapshot_row_gap", {}) or {}
        if coverage and snapshot_gap.get("ok") is False:
            reasons.append("snapshot_event_snapshot_row_gap")

        snapshot_symbol = mismatches.get("snapshot_symbol_set_match", {}) or {}
        if coverage and snapshot_symbol.get("ok") is False:
            reasons.append("snapshot_symbol_set_mismatch")

        snapshot_sim_day = mismatches.get("snapshot_sim_day_set_match", {}) or {}
        if coverage and snapshot_sim_day.get("ok") is False:
            reasons.append("snapshot_sim_day_set_mismatch")

        if rep.get("ok") is False:
            reasons.append("run_report_not_ok")
        return sorted(set(reasons))

    def _build_report(self) -> Dict[str, Any]:
        s = SessionLocal()
        try:
            queries = RunPersistenceQueryService(s)
            rows = queries.load_recovery_rows()
            active_run_id = queries.get_active_run_id()
            order_rows = rows.order_rows
            trade_rows = rows.trade_rows
            ledger_rows = rows.ledger_rows
            event_rows = rows.event_rows

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
            inconsistent_run_reasons: dict[str, list[str]] = {}
            replay_validation: dict[str | None, dict] = {}
            run_ids = {rid for rid in per_run.keys() if rid is not None}
            run_ids.update(queries.collect_run_ids(rows))
            ordered_run_ids = sorted(run_ids, key=lambda rid: (0 if rid == active_run_id else 1, str(rid)))
            for run_id in ordered_run_ids:
                stats = per_run[run_id]
                severe = (stats["trades"] > stats["ledgers"] and stats["trades"] > 0) or (stats["filled_orders"] > stats["trades"])
                reasons: list[str] = []
                if stats["trades"] > stats["ledgers"] and stats["trades"] > 0:
                    reasons.append("trade_rows_exceed_ledgers")
                if stats["filled_orders"] > stats["trades"]:
                    reasons.append("filled_orders_exceed_trade_rows")
                try:
                    replay_validation[run_id] = replay_service.build_run_report(run_id)
                    try:
                        SimulationRunService(s).sync_from_run_report(run_id, replay_validation[run_id])
                    except Exception:
                        pass
                except Exception:
                    replay_validation[run_id] = {"run_id": run_id, "ok": False, "error": "replay_validation_failed"}
                    severe = True
                    reasons.append("replay_validation_failed")
                rep = replay_validation.get(run_id)
                if rep:
                    validation_reasons = self._collect_validation_reasons(rep)
                    if validation_reasons:
                        severe = True
                        reasons.extend(validation_reasons)
                    val = rep.get("validation", {})
                    bars = val.get("bars", {})
                    bars_1m = bars.get("1m", {})
                    bars_1h = bars.get("1h", {})
                    bars_1d = bars.get("1d", {})
                    if val.get("persisted", {}).get("snapshots", 0) > 0 and bars_1m.get("count", 0) == 0:
                        severe = True
                        reasons.append("snapshots_without_1m_bars")
                    if bars_1m.get("count", 0) > 0 and (bars_1h.get("count", 0) == 0 or bars_1d.get("count", 0) == 0):
                        warning_runs.append(run_id)
                if severe:
                    inconsistent_runs.append(run_id)
                    inconsistent_run_reasons[run_id] = sorted(set(reasons))

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
                    "active_run_id": active_run_id,
                    "inconsistent_runs": inconsistent_runs,
                    "inconsistent_run_reasons": inconsistent_run_reasons,
                    "warning_runs": sorted({r for r in warning_runs if r is not None}),
                    "replay_validation": replay_validation,
                },
            }
        finally:
            s.close()

    def recover(self) -> Dict[str, Any]:
        global _READONLY, _SENT_RESUMED, _LAST_REPORT
        report = self._build_report()
        inconsistent_runs = [str(run_id) for run_id in (report["checks"].get("inconsistent_runs") or [])]
        new_inconsistent_runs = [run_id for run_id in inconsistent_runs if run_id not in _ACKED_INCONSISTENT_RUNS]
        if new_inconsistent_runs:
            _ACKED_INCONSISTENT_RUNS.update(new_inconsistent_runs)
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
