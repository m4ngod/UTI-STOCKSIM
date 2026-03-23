from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RunContext:
    run_id: str
    run_type: str = "manual"
    scenario_name: str | None = None
    sim_day: int | None = None
    sim_dt: datetime | None = None
    config_version: str | None = None
    speed_profile: str | None = None


__all__ = ["RunContext"]
