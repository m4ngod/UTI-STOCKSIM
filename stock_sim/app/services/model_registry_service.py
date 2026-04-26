from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
from typing import Any, Protocol
import zlib

try:
    from stock_sim.persistence.models_imports import SessionLocal
    from stock_sim.persistence.models_training import ModelCheckpoint, ModelLineage
except Exception:  # pragma: no cover
    SessionLocal = None  # type: ignore
    ModelCheckpoint = None  # type: ignore
    ModelLineage = None  # type: ignore


class ModelPolicy(Protocol):
    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    policy_type: str
    description: str = ""
    parent_model_id: str | None = None
    checkpoint_id: str | None = None
    checkpoint_path: str | None = None


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


class CheckpointBackedModel:
    def __init__(
        self,
        *,
        model_id: str,
        parent_model_id: str,
        base_policy: ModelPolicy,
        checkpoint_id: str | None = None,
        checkpoint_path: str | None = None,
        mutation: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
    ):
        self.model_id = model_id
        self.parent_model_id = parent_model_id
        self.checkpoint_id = checkpoint_id
        self.checkpoint_path = checkpoint_path
        self.mutation = dict(mutation or {})
        self.artifact = dict(artifact or {})
        self._base_policy = base_policy

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        action = dict(self._base_policy.act(observation))
        meta = dict(action.get("meta") or {})
        meta.update(
            {
                "model_id": self.model_id,
                "parent_model_id": self.parent_model_id,
                "checkpoint_id": self.checkpoint_id,
                "checkpoint_path": self.checkpoint_path,
                "policy_type": "checkpoint_backed",
                "mutation": self.mutation,
            }
        )
        action["meta"] = meta
        return action


class ModelRegistryService:
    def __init__(self, *, session_factory: Any | None = None):
        self._specs: dict[str, ModelSpec] = {
            "hold_model_v1": ModelSpec("hold_model_v1", "hold", "Always emits hold actions."),
            "random_weight_v1": ModelSpec("random_weight_v1", "random_weight", "Random long-only target weights."),
        }
        self._session_factory = session_factory if session_factory is not None else SessionLocal

    def list_models(self) -> list[ModelSpec]:
        specs = {model_id: spec for model_id, spec in self._specs.items()}
        for item in self._list_checkpoint_specs():
            specs.setdefault(item.model_id, item)
        return list(specs.values())

    def create_policy(self, model_id: str, *, seed: int | None = None) -> ModelPolicy:
        model_id = str(model_id or "hold_model_v1").strip() or "hold_model_v1"
        spec = self._specs.get(model_id)
        if spec is not None:
            return self._create_builtin_policy(model_id, seed=seed)
        checkpoint = self._resolve_checkpoint_model(model_id)
        if checkpoint is not None:
            return self._create_checkpoint_policy(checkpoint, seed=seed)
        fallback_parent = self._infer_parent_model_id(model_id)
        if fallback_parent is not None:
            return CheckpointBackedModel(
                model_id=model_id,
                parent_model_id=fallback_parent,
                base_policy=self._create_builtin_policy(fallback_parent, seed=seed),
            )
        raise KeyError(f"unknown model_id: {model_id}")

    def _create_builtin_policy(self, model_id: str, *, seed: int | None = None) -> ModelPolicy:
        spec = self._specs.get(model_id)
        if spec is not None and spec.policy_type == "random_weight":
            return RandomWeightModel(model_id=model_id, seed=seed)
        return HoldModel(model_id=model_id)

    def _create_checkpoint_policy(self, checkpoint: dict[str, Any], *, seed: int | None = None) -> ModelPolicy:
        parent_model_id = str(checkpoint.get("parent_model_id") or checkpoint.get("artifact_model_id") or "hold_model_v1")
        policy_seed = seed
        if policy_seed is None:
            seed_material = f"{checkpoint.get('child_model_id')}:{checkpoint.get('checkpoint_id')}:{checkpoint.get('path')}"
            policy_seed = zlib.crc32(seed_material.encode("utf-8")) & 0xFFFFFFFF
        return CheckpointBackedModel(
            model_id=str(checkpoint.get("child_model_id") or checkpoint.get("model_id")),
            parent_model_id=parent_model_id,
            checkpoint_id=checkpoint.get("checkpoint_id"),
            checkpoint_path=checkpoint.get("path"),
            mutation=checkpoint.get("mutation") or {},
            artifact=checkpoint.get("artifact") or {},
            base_policy=self._create_builtin_policy(parent_model_id, seed=policy_seed),
        )

    def _resolve_checkpoint_model(self, model_id: str) -> dict[str, Any] | None:
        session_factory = self._session_factory
        if session_factory is None or ModelCheckpoint is None or ModelLineage is None:
            return None
        session = session_factory()
        try:
            lineage = (
                session.query(ModelLineage)
                .filter(ModelLineage.child_model_id == model_id)
                .order_by(ModelLineage.created_at.desc())
                .first()
            )
            if lineage is None:
                checkpoint = (
                    session.query(ModelCheckpoint)
                    .filter(ModelCheckpoint.model_id == model_id)
                    .order_by(ModelCheckpoint.created_at.desc())
                    .first()
                )
                if checkpoint is None:
                    return None
                artifact = self._load_checkpoint_artifact(checkpoint.path)
                return {
                    "child_model_id": checkpoint.model_id,
                    "parent_model_id": (artifact.get("model_id") if isinstance(artifact, dict) else None) or checkpoint.model_id,
                    "artifact_model_id": artifact.get("model_id") if isinstance(artifact, dict) else checkpoint.model_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "path": checkpoint.path,
                    "mutation": {},
                    "artifact": artifact,
                }
            checkpoint = session.get(ModelCheckpoint, lineage.parent_checkpoint_id) if lineage.parent_checkpoint_id else None
            artifact = self._load_checkpoint_artifact(checkpoint.path) if checkpoint is not None else {}
            return {
                "child_model_id": lineage.child_model_id,
                "parent_model_id": lineage.parent_model_id,
                "artifact_model_id": artifact.get("model_id") if isinstance(artifact, dict) else None,
                "checkpoint_id": lineage.parent_checkpoint_id,
                "path": checkpoint.path if checkpoint is not None else None,
                "mutation": _json_loads(lineage.mutation_json) or {},
                "artifact": artifact,
            }
        finally:
            session.close()

    def _list_checkpoint_specs(self) -> list[ModelSpec]:
        session_factory = self._session_factory
        if session_factory is None or ModelCheckpoint is None or ModelLineage is None:
            return []
        session = session_factory()
        try:
            rows = (
                session.query(ModelLineage)
                .order_by(ModelLineage.created_at.desc())
                .limit(200)
                .all()
            )
            specs: list[ModelSpec] = []
            for row in rows:
                checkpoint = session.get(ModelCheckpoint, row.parent_checkpoint_id) if row.parent_checkpoint_id else None
                specs.append(
                    ModelSpec(
                        model_id=row.child_model_id,
                        policy_type="checkpoint_backed",
                        description=f"Checkpoint-backed child of {row.parent_model_id}.",
                        parent_model_id=row.parent_model_id,
                        checkpoint_id=row.parent_checkpoint_id,
                        checkpoint_path=checkpoint.path if checkpoint is not None else None,
                    )
                )
            return specs
        finally:
            session.close()

    @staticmethod
    def _load_checkpoint_artifact(path: str | None) -> dict[str, Any]:
        if not path:
            return {}
        try:
            resolved = Path(path)
            if not resolved.exists():
                return {}
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _infer_parent_model_id(self, model_id: str) -> str | None:
        if ".gen" not in model_id:
            return None
        parent = model_id.split(".gen", 1)[0]
        return parent if parent in self._specs else None


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


__all__ = [
    "CheckpointBackedModel",
    "HoldModel",
    "ModelPolicy",
    "ModelRegistryService",
    "ModelSpec",
    "RandomWeightModel",
]
