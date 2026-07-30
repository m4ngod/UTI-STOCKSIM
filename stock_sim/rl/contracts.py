from __future__ import annotations

from typing import Literal, TypedDict


OBS_CONTRACT_VERSION = "obs.v1"
ACT_CONTRACT_VERSION = "act.v1"
REWARD_CONTRACT_VERSION = "rew.v1"

ActionType = Literal["hold", "order", "target_position", "target_weight"]


class RewardComponents(TypedDict, total=False):
    delta_equity: float
    relative_alpha: float
    realized_pnl: float
    unrealized_pnl: float
    fee_penalty: float
    drawdown_penalty: float
    turnover_penalty: float
    inventory_penalty: float


__all__ = [
    "ACT_CONTRACT_VERSION",
    "ActionType",
    "OBS_CONTRACT_VERSION",
    "REWARD_CONTRACT_VERSION",
    "RewardComponents",
]
