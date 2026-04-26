from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
from typing import Any, Callable, Protocol
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


class TrainableModelPolicy(ModelPolicy, Protocol):
    def learn(self, transition: dict[str, Any]) -> dict[str, Any]:
        ...

    def save_checkpoint(self, path: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    policy_type: str
    description: str = ""
    parent_model_id: str | None = None
    checkpoint_id: str | None = None
    checkpoint_path: str | None = None
    adapter_type: str | None = None
    config: dict[str, Any] | None = None


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


class ExternalPolicyAdapter:
    """Adapter boundary for non-built-in policies.

    The first supported providers are intentionally simple:
    - static_action: deterministic contract action, useful for wiring tests.
    - callable: an injected factory-owned policy object for local trainable code.
    """

    def __init__(
        self,
        *,
        model_id: str,
        adapter_type: str,
        config: dict[str, Any] | None = None,
        policy: ModelPolicy | None = None,
    ):
        self.model_id = str(model_id)
        self.adapter_type = str(adapter_type or "static_action")
        self.config = dict(config or {})
        self._policy = policy

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._policy is not None:
            action = dict(self._policy.act(observation))
        else:
            action = dict(self.config.get("action") or self._hold_action(observation))
        return self._normalize_action(action, observation)

    def learn(self, transition: dict[str, Any]) -> dict[str, Any]:
        learner = getattr(self._policy, "learn", None)
        if callable(learner):
            result = learner(transition)
            return result if isinstance(result, dict) else {"ok": True}
        return {"ok": False, "reason": "LEARN_NOT_SUPPORTED", "model_id": self.model_id}

    def save_checkpoint(self, path: str) -> dict[str, Any]:
        saver = getattr(self._policy, "save_checkpoint", None)
        if callable(saver):
            result = saver(path)
            return result if isinstance(result, dict) else {"ok": True, "path": path}
        payload = {
            "schema": "stock_sim.external_policy_checkpoint.v1",
            "model_id": self.model_id,
            "adapter_type": self.adapter_type,
            "config": self.config,
        }
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(_json_dumps(payload), encoding="utf-8")
        return {"ok": True, "path": str(resolved)}

    def _normalize_action(self, action: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(action)
        normalized.setdefault("contract_version", "act.v1")
        normalized.setdefault("action_type", "hold")
        normalized.setdefault("target", {})
        normalized.setdefault("payload", {})
        normalized.setdefault("constraints", {})
        context = observation.get("context") if isinstance(observation, dict) else {}
        target = dict(normalized.get("target") or {})
        target.setdefault("account_id", (context or {}).get("agent_id"))
        if normalized.get("action_type") == "target_weight":
            payload = dict(normalized.get("payload") or {})
            weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else {}
            target.setdefault("symbols", list(target.get("symbols") or weights.keys() or (context or {}).get("symbol_universe") or []))
            payload.setdefault("cash_buffer_ratio", 0.05)
            payload.setdefault("rebalance_mode", "market")
            normalized["payload"] = payload
            constraints = dict(normalized.get("constraints") or {})
            constraints.setdefault("allow_short", False)
            constraints.setdefault("max_gross_leverage", 1.0)
            constraints.setdefault("clip_to_limits", True)
            normalized["constraints"] = constraints
        meta = dict(normalized.get("meta") or {})
        meta.update({"model_id": self.model_id, "policy_type": "external", "adapter_type": self.adapter_type})
        normalized["target"] = target
        normalized["meta"] = meta
        return normalized

    def _hold_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        return {
            "contract_version": "act.v1",
            "action_type": "hold",
            "target": {"account_id": (context or {}).get("agent_id")},
            "payload": {},
            "constraints": {},
            "meta": {"model_id": self.model_id},
        }


class ModelRegistryService:
    def __init__(
        self,
        *,
        session_factory: Any | None = None,
        registry_path: str | Path | None = "output/model_registry/policies.json",
        external_policy_factories: dict[str, Callable[..., ModelPolicy]] | None = None,
    ):
        self._specs: dict[str, ModelSpec] = {
            "hold_model_v1": ModelSpec("hold_model_v1", "hold", "Always emits hold actions."),
            "random_weight_v1": ModelSpec("random_weight_v1", "random_weight", "Random long-only target weights."),
        }
        self._session_factory = session_factory if session_factory is not None else SessionLocal
        self._registry_path = Path(registry_path) if registry_path is not None else None
        self._external_policy_factories = dict(external_policy_factories or {})

    def list_models(self) -> list[ModelSpec]:
        specs = {model_id: spec for model_id, spec in self._specs.items()}
        for item in self._list_registered_specs():
            specs[item.model_id] = item
        for item in self._list_checkpoint_specs():
            specs.setdefault(item.model_id, item)
        return list(specs.values())

    def register_external_policy(
        self,
        model_id: str,
        *,
        adapter_type: str = "static_action",
        config: dict[str, Any] | None = None,
        description: str = "",
        persist: bool = True,
    ) -> ModelSpec:
        model_id = str(model_id or "").strip()
        if not model_id:
            raise ValueError("model_id is required")
        adapter_type = str(adapter_type or "static_action").strip() or "static_action"
        spec = ModelSpec(
            model_id=model_id,
            policy_type="external",
            description=description or f"External policy adapter: {adapter_type}.",
            adapter_type=adapter_type,
            config=dict(config or {}),
        )
        if persist:
            self._upsert_registered_spec(spec)
        return spec

    def create_policy(self, model_id: str, *, seed: int | None = None) -> ModelPolicy:
        model_id = str(model_id or "hold_model_v1").strip() or "hold_model_v1"
        spec = self._specs.get(model_id)
        if spec is not None:
            return self._create_builtin_policy(model_id, seed=seed)
        registered = self._get_registered_spec(model_id)
        if registered is not None:
            return self._create_external_policy(registered)
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

    def _create_external_policy(self, spec: ModelSpec) -> ModelPolicy:
        adapter_type = spec.adapter_type or "static_action"
        config = dict(spec.config or {})
        factory_key = str(config.get("factory") or adapter_type)
        factory = self._external_policy_factories.get(factory_key)
        policy = None
        if callable(factory):
            policy = factory(model_id=spec.model_id, config=config, spec=spec)
        return ExternalPolicyAdapter(
            model_id=spec.model_id,
            adapter_type=adapter_type,
            config=config,
            policy=policy,
        )

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

    def _get_registered_spec(self, model_id: str) -> ModelSpec | None:
        for spec in self._list_registered_specs():
            if spec.model_id == model_id:
                return spec
        return None

    def _list_registered_specs(self) -> list[ModelSpec]:
        path = self._registry_path
        if path is None or not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []
        specs: list[ModelSpec] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or "").strip()
            if not model_id:
                continue
            config = item.get("config") if isinstance(item.get("config"), dict) else {}
            specs.append(
                ModelSpec(
                    model_id=model_id,
                    policy_type=str(item.get("policy_type") or "external"),
                    description=str(item.get("description") or ""),
                    adapter_type=str(item.get("adapter_type") or "static_action"),
                    config=dict(config or {}),
                )
            )
        return specs

    def _upsert_registered_spec(self, spec: ModelSpec) -> None:
        path = self._registry_path
        if path is None:
            return
        specs = {item.model_id: item for item in self._list_registered_specs()}
        specs[spec.model_id] = spec
        payload = {
            "schema": "stock_sim.model_registry.v1",
            "models": [
                {
                    "model_id": item.model_id,
                    "policy_type": item.policy_type,
                    "description": item.description,
                    "adapter_type": item.adapter_type or "static_action",
                    "config": item.config or {},
                }
                for item in sorted(specs.values(), key=lambda row: row.model_id)
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(payload), encoding="utf-8")

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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


__all__ = [
    "CheckpointBackedModel",
    "ExternalPolicyAdapter",
    "HoldModel",
    "ModelPolicy",
    "ModelRegistryService",
    "ModelSpec",
    "RandomWeightModel",
    "TrainableModelPolicy",
]
