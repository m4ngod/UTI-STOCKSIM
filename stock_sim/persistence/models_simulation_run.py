from __future__ import annotations

from datetime import datetime
from .models_imports import Base, Column, String, DateTime, Integer, Float


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    run_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    scenario_name = Column(String(128), nullable=True)
    run_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="created")
    failure_reason = Column(String(512), nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sim_start_day = Column(Integer, nullable=True)
    sim_end_day = Column(Integer, nullable=True)
    last_sim_day = Column(Integer, nullable=True)
    last_sim_dt = Column(DateTime, nullable=True)

    speed_profile = Column(String(64), nullable=True)
    config_version = Column(String(64), nullable=True)
    environment_tag = Column(String(64), nullable=True)

    retail_count = Column(Integer, nullable=False, default=0)
    agent_count = Column(Integer, nullable=False, default=0)
    instrument_count = Column(Integer, nullable=False, default=0)

    final_equity = Column(Float, nullable=True)
    final_pnl = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    trade_count = Column(Integer, nullable=False, default=0)
    order_count = Column(Integer, nullable=False, default=0)
    event_count = Column(Integer, nullable=False, default=0)


__all__ = ["SimulationRun"]
