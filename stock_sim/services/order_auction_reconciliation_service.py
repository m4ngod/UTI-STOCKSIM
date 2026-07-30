from __future__ import annotations

from stock_sim.core.const import OrderStatus
from stock_sim.persistence.models_order import OrderORM
from stock_sim.services.engine_registry import engine_registry


class OrderAuctionReconciliationService:
    """Own auction leftover reconciliation outside the main order path."""

    def __init__(
        self,
        *,
        session,
        default_engine,
        cancellation_service,
        mem_order_updater,
    ) -> None:
        self._session = session
        self._default_engine = default_engine
        self._cancellation_service = cancellation_service
        self._mem_order_updater = mem_order_updater

    def reconcile_unmatched_auction_cancels(self) -> None:
        for engine in self._iter_engines():
            ids = getattr(engine, "auction_canceled_order_ids", None)
            if not ids:
                continue
            for order_id in list(ids):
                orm = self._session.get(OrderORM, order_id)
                if orm is None:
                    continue
                if orm.status != OrderStatus.CANCELED:
                    self._cancellation_service.cancel_persisted_order(
                        orm,
                        reason="AUCTION_UNMATCHED",
                        engine=engine,
                    )
                else:
                    self._mem_order_updater(order_id, orm, engine)
            try:
                engine.auction_canceled_order_ids = []
            except Exception:
                pass

    def _iter_engines(self):
        symbols = []
        try:
            symbols = engine_registry.symbols()
        except Exception:
            symbols = []
        engines = []
        for symbol in symbols:
            engine = engine_registry.get(symbol)
            if engine is not None:
                engines.append(engine)
        if self._default_engine is not None and self._default_engine not in engines:
            engines.append(self._default_engine)
        return engines


__all__ = ["OrderAuctionReconciliationService"]
