from __future__ import annotations

from stock_sim.observability.metrics import metrics

try:
    from stock_sim.services.borrow_fee_scheduler import borrow_fee_scheduler  # type: ignore
except Exception:
    from services.borrow_fee_scheduler import borrow_fee_scheduler  # type: ignore


class OrderMaintenanceService:
    """Own day-boundary runtime maintenance related to the order path."""

    def __init__(self, *, session, risk) -> None:
        self._session = session
        self._risk = risk

    def daily_reset(self) -> bool:
        try:
            self._risk.storage.reset_day()
        except Exception:
            pass

        try:
            from stock_sim.persistence.models_position import Position  # type: ignore
        except Exception:
            from persistence.models_position import Position  # type: ignore

        try:
            positions = self._session.query(Position).all()
            self._risk.reset_day_tplus(positions)
        except Exception:
            pass

        try:
            count, total_fee = borrow_fee_scheduler.run(self._session)
            if count:
                metrics.inc("borrow_fee_accrual_batches")
        except Exception:
            metrics.inc("borrow_fee_accrual_errors")
        return True


__all__ = ["OrderMaintenanceService"]
