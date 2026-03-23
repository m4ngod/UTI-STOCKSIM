from __future__ import annotations

from typing import Any, Dict

try:
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.persistence.models_order import OrderORM  # type: ignore
    from stock_sim.persistence.models_trade import TradeORM  # type: ignore
    from stock_sim.persistence.models_ledger import Ledger  # type: ignore
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
except Exception:  # noqa
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from persistence.models_order import OrderORM  # type: ignore
    from persistence.models_trade import TradeORM  # type: ignore
    from persistence.models_ledger import Ledger  # type: ignore
    from persistence.models_event_log import EventLog  # type: ignore


_READONLY = False
_SENT_RESUMED = False
_LAST_REPORT: Dict[str, Any] | None = None


class RecoveryService:
    def _build_report(self) -> Dict[str, Any]:
        s = SessionLocal()
        try:
            orders = s.query(OrderORM).count()
            open_orders = s.query(OrderORM).filter(OrderORM.status.in_(["NEW", "PARTIAL"])) .count()
            filled_orders = s.query(OrderORM).filter(OrderORM.status == "FILLED").count()
            trades = s.query(TradeORM).count()
            ledgers = s.query(Ledger).count()
            events = s.query(EventLog).count()
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
                },
            }
        finally:
            s.close()

    def recover(self) -> Dict[str, Any]:
        global _READONLY, _SENT_RESUMED, _LAST_REPORT
        report = self._build_report()
        inconsistent = bool(
            report["checks"]["trade_without_ledger_possible"]
            or report["checks"]["filled_order_without_trade_possible"]
        )
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
