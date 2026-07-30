from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from stock_sim.persistence.models_bars import Bar1d, Bar1h, Bar1m
from stock_sim.persistence.models_event_log import EventLog
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_trade import TradeORM


@dataclass
class RunFactRows:
    snapshot_rows: list[Any]
    bar1m_rows: list[Any]
    bar1h_rows: list[Any]
    bar1d_rows: list[Any]
    persisted: dict[str, int]


@dataclass
class RecoveryRows:
    order_rows: list[Any]
    trade_rows: list[Any]
    ledger_rows: list[Any]
    event_rows: list[Any]


class RunPersistenceQueryService:
    """Shared persisted-fact queries for replay/recovery/reporting."""

    def __init__(self, session: Session):
        self.s = session

    def load_run_fact_rows(self, run_id: str) -> RunFactRows:
        snapshot_rows = self.s.query(Snapshot1s).filter(Snapshot1s.run_id == run_id).all()
        bar1m_rows = self.s.query(Bar1m).filter(Bar1m.run_id == run_id).all()
        bar1h_rows = self.s.query(Bar1h).filter(Bar1h.run_id == run_id).all()
        bar1d_rows = self.s.query(Bar1d).filter(Bar1d.run_id == run_id).all()
        persisted = {
            "orders": self.s.query(OrderORM).filter(OrderORM.run_id == run_id).count(),
            "trades": self.s.query(TradeORM).filter(TradeORM.run_id == run_id).count(),
            "ledgers": self.s.query(Ledger).filter(Ledger.run_id == run_id).count(),
            "snapshots": len(snapshot_rows),
            "bars_1m": len(bar1m_rows),
            "bars_1h": len(bar1h_rows),
            "bars_1d": len(bar1d_rows),
        }
        return RunFactRows(
            snapshot_rows=snapshot_rows,
            bar1m_rows=bar1m_rows,
            bar1h_rows=bar1h_rows,
            bar1d_rows=bar1d_rows,
            persisted=persisted,
        )

    def load_recovery_rows(self) -> RecoveryRows:
        return RecoveryRows(
            order_rows=self.s.query(OrderORM).all(),
            trade_rows=self.s.query(TradeORM).all(),
            ledger_rows=self.s.query(Ledger).all(),
            event_rows=self.s.query(EventLog).all(),
        )

    def collect_run_ids(self, recovery_rows: RecoveryRows) -> set[str]:
        run_ids = {
            getattr(row, "run_id", None)
            for row in (
                list(recovery_rows.order_rows)
                + list(recovery_rows.trade_rows)
                + list(recovery_rows.ledger_rows)
                + list(recovery_rows.event_rows)
            )
            if getattr(row, "run_id", None) is not None
        }
        run_ids.update({row[0] for row in self.s.query(Snapshot1s.run_id).filter(Snapshot1s.run_id.isnot(None)).distinct().all()})
        run_ids.update({row[0] for row in self.s.query(Bar1m.run_id).filter(Bar1m.run_id.isnot(None)).distinct().all()})
        run_ids.update({row[0] for row in self.s.query(Bar1h.run_id).filter(Bar1h.run_id.isnot(None)).distinct().all()})
        run_ids.update({row[0] for row in self.s.query(Bar1d.run_id).filter(Bar1d.run_id.isnot(None)).distinct().all()})
        return {str(run_id) for run_id in run_ids if run_id is not None}

    def get_active_run_id(self) -> str | None:
        row = (
            self.s.query(SimulationRun)
            .filter(SimulationRun.status.in_(("running", "starting", "created", "recovered")))
            .order_by(
                SimulationRun.updated_at.desc(),
                SimulationRun.started_at.desc(),
                SimulationRun.created_at.desc(),
            )
            .first()
        )
        if row is None or getattr(row, "run_id", None) is None:
            return None
        return str(row.run_id)
