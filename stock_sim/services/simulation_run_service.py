from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

try:
    from stock_sim.persistence.models_simulation_run import SimulationRun  # type: ignore
    from stock_sim.services.run_context import RunContext  # type: ignore
except Exception:  # noqa
    from persistence.models_simulation_run import SimulationRun  # type: ignore
    from services.run_context import RunContext  # type: ignore


class SimulationRunService:
    def __init__(self, session: Session):
        self.s = session

    def get(self, run_id: str) -> SimulationRun | None:
        return self.s.get(SimulationRun, run_id)

    def create_run(self, ctx: RunContext, *, name: str | None = None, status: str = "created") -> SimulationRun:
        row = self.s.get(SimulationRun, ctx.run_id)
        if row is not None:
            return row
        now = datetime.utcnow()
        row = SimulationRun(
            run_id=ctx.run_id,
            name=name or ctx.scenario_name or ctx.run_id,
            scenario_name=ctx.scenario_name,
            run_type=ctx.run_type,
            status=status,
            created_at=now,
            updated_at=now,
            sim_start_day=ctx.sim_day,
            last_sim_day=ctx.sim_day,
            last_sim_dt=ctx.sim_dt,
            speed_profile=ctx.speed_profile,
            config_version=ctx.config_version,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def mark_running(self, run_id: str, *, sim_day: int | None = None, sim_dt=None):
        row = self.s.get(SimulationRun, run_id)
        if row is None:
            raise ValueError(f"simulation run not found: {run_id}")
        now = datetime.utcnow()
        row.status = "running"
        row.started_at = row.started_at or now
        row.updated_at = now
        if sim_day is not None:
            row.last_sim_day = sim_day
            row.sim_start_day = row.sim_start_day if row.sim_start_day is not None else sim_day
        if sim_dt is not None:
            row.last_sim_dt = sim_dt
        return row

    def mark_completed(self, run_id: str, *, sim_day: int | None = None, sim_dt=None):
        row = self.s.get(SimulationRun, run_id)
        if row is None:
            raise ValueError(f"simulation run not found: {run_id}")
        now = datetime.utcnow()
        row.status = "completed"
        row.ended_at = now
        row.updated_at = now
        if sim_day is not None:
            row.last_sim_day = sim_day
            row.sim_end_day = sim_day
        if sim_dt is not None:
            row.last_sim_dt = sim_dt
        return row

    def sync_from_run_report(self, run_id: str, report: dict):
        row = self.s.get(SimulationRun, run_id)
        if row is None:
            return None
        now = datetime.utcnow()
        summary = (report or {}).get('summary', {}) or {}
        validation = (report or {}).get('validation', {}) or {}
        sim_day_range = summary.get('sim_day_range')
        sim_dt_range = summary.get('sim_dt_range')
        if isinstance(sim_day_range, (list, tuple)) and sim_day_range:
            row.last_sim_day = sim_day_range[-1]
            if row.sim_start_day is None:
                row.sim_start_day = sim_day_range[0]
        if isinstance(sim_dt_range, (list, tuple)) and sim_dt_range:
            last_sim_dt = sim_dt_range[-1]
            if isinstance(last_sim_dt, datetime):
                row.last_sim_dt = last_sim_dt
        persisted = validation.get('persisted', {}) or {}
        if 'trades' in persisted:
            row.trade_count = int(persisted.get('trades') or 0)
        if 'orders' in persisted:
            row.order_count = int(persisted.get('orders') or 0)
        row.event_count = int(summary.get('event_count') or 0)
        row.updated_at = now
        if report.get('ok') is True and row.status in ('created', 'starting', 'running', 'recovered'):
            row.status = 'running'
        return row


__all__ = ["SimulationRunService"]
