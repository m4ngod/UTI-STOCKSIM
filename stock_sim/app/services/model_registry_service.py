from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Protocol


class ModelPolicy(Protocol):
    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    policy_type: str
    description: str = ""


class HoldModel:
    def __init__(self, *, model_id: str = "hold_model_v1"):
        self.model_id = model_id

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        return {
            "contract_version": "act.v1",
            "action_type": "hold",
            "target": {"account_id": (context or {}).get("agent_id")},
            "payload": {},
            "constraints": {},
            "meta": {"model_id": self.model_id},
        }


class RandomWeightModel:
    def __init__(self, *, model_id: str = "random_weight_v1", seed: int | None = None):
        self.model_id = model_id
        self._rng = random.Random(seed)

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        symbols = list((context or {}).get("symbol_universe") or [])
        weights: dict[str, float] = {}
        if not symbols:
            return HoldModel(model_id=self.model_id).act(observation)
        budget = 0.6
        raw = [self._rng.random() for _ in symbols]
        total = sum(raw) or 1.0
        weights = {sym: round((val / total) * budget, 4) for sym, val in zip(symbols, raw)}
        return {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {"account_id": (context or {}).get("agent_id"), "symbols": symbols},
            "payload": {
                "weights": weights,
                "cash_buffer_ratio": 0.05,
                "rebalance_mode": "market",
            },
            "constraints": {
                "allow_short": False,
                "max_gross_leverage": 1.0,
                "clip_to_limits": True,
            },
            "meta": {"model_id": self.model_id},
        }


class ModelRegistryService:
    def __init__(self):
        self._specs: dict[str, ModelSpec] = {
            "hold_model_v1": ModelSpec("hold_model_v1", "hold", "Always emits hold actions."),
            "random_weight_v1": ModelSpec("random_weight_v1", "random_weight", "Random long-only target weights."),
        }

    def list_models(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def create_policy(self, model_id: str, *, seed: int | None = None) -> ModelPolicy:
        spec = self._specs.get(model_id)
        if spec is None:
            raise KeyError(f"unknown model_id: {model_id}")
        if spec.policy_type == "random_weight":
            return RandomWeightModel(model_id=model_id, seed=seed)
        return HoldModel(model_id=model_id)


__all__ = [
    "HoldModel",
    "ModelPolicy",
    "ModelRegistryService",
    "ModelSpec",
    "RandomWeightModel",
]
