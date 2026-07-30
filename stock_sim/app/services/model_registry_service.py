from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import shlex
import subprocess
from typing import Any, Callable, Protocol
from urllib import request as urlrequest
import zlib

try:
    from stock_sim.persistence.models_imports import SessionLocal
    from persistence.models_training import ModelCheckpoint, ModelLineage
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
    def __init__(self, *, model_id: str = "hold_model_v1", seed: int | None = None):
        self.model_id = model_id
        self._rng = random.Random(seed)

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        account = observation.get("account") if isinstance(observation, dict) else {}
        market = observation.get("market") if isinstance(observation, dict) else {}
        symbols = [str(item).strip() for item in ((context or {}).get("symbol_universe") or []) if str(item).strip()]
        order_books = (market or {}).get("order_books") if isinstance(market, dict) else {}
        cash = _positive_float((account or {}).get("cash"))
        candidates: list[dict[str, Any]] = []
        for symbol in symbols:
            book = (order_books or {}).get(symbol) if isinstance(order_books, dict) else {}
            best_bid = _positive_float((book or {}).get("best_bid") or (book or {}).get("best_bid_price"))
            best_ask = _positive_float((book or {}).get("best_ask") or (book or {}).get("best_ask_price"))
            if best_ask is not None:
                candidates.append({"symbol": symbol, "side": "BUY", "price": best_ask})
            if best_bid is None:
                continue
            sellable_qty = _available_qty_from_account(account if isinstance(account, dict) else {}, symbol)
            candidates.append({"symbol": symbol, "side": "SELL", "price": best_bid, "sellable_qty": sellable_qty})
        if candidates:
            choice = dict(self._rng.choice(candidates))
            price = float(choice["price"])
            side = str(choice["side"])
            if side == "BUY":
                available_cash = float(cash or 0.0)
                cash_budget = max(price, min(available_cash * 0.08, max(available_cash * 0.02, price)))
                qty_cap = int(cash_budget / price)
            else:
                sellable_qty = int(choice.get("sellable_qty") or 0)
                qty_cap = sellable_qty if sellable_qty > 0 else 5000
            qty_cap = max(0, min(qty_cap, 5000))
            if qty_cap > 0:
                min_qty = max(1, qty_cap // 5)
                quantity = self._rng.randint(min_qty, qty_cap)
                return {
                    "contract_version": "act.v1",
                    "action_type": "order",
                    "target": {"account_id": (context or {}).get("agent_id"), "symbol": choice["symbol"]},
                    "payload": {
                        "symbol": choice["symbol"],
                        "side": side,
                        "order_type": "LIMIT",
                        "tif": "GFD",
                        "quantity": quantity,
                        "price": price,
                    },
                    "constraints": {"clip_to_limits": True},
                    "meta": {
                        "model_id": self.model_id,
                        "policy_type": "random_top_of_book",
                    },
                }
        return {
            "contract_version": "act.v1",
            "action_type": "hold",
            "target": {"account_id": (context or {}).get("agent_id")},
            "payload": {},
            "constraints": {},
            "meta": {"model_id": self.model_id, "reason": "NO_TOP_OF_BOOK_CANDIDATE"},
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


class TargetWeightNaiveRebalanceModel:
    def __init__(
        self,
        *,
        model_id: str = "target_weight_naive_rebalance_v1",
        gross_budget: float = 0.6,
        cash_buffer_ratio: float = 0.05,
    ):
        self.model_id = model_id
        self.gross_budget = max(0.0, min(1.0, float(gross_budget)))
        self.cash_buffer_ratio = max(0.0, min(0.95, float(cash_buffer_ratio)))

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        symbols = [str(item).strip() for item in ((context or {}).get("symbol_universe") or []) if str(item).strip()]
        if not symbols:
            return HoldModel(model_id=self.model_id).act(observation)
        weight = round(self.gross_budget / len(symbols), 6)
        weights = {symbol: weight for symbol in symbols}
        return {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {"account_id": (context or {}).get("agent_id"), "symbols": symbols},
            "payload": {
                "weights": weights,
                "cash_buffer_ratio": self.cash_buffer_ratio,
                "rebalance_mode": "market",
            },
            "constraints": {
                "allow_short": False,
                "max_gross_leverage": 1.0,
                "clip_to_limits": True,
            },
            "meta": {
                "model_id": self.model_id,
                "baseline_kind": "target_weight_naive_rebalance",
            },
        }


class ScheduledExecutionBaselineModel:
    def __init__(
        self,
        *,
        model_id: str,
        baseline_kind: str,
        rebalance_mode: str,
        gross_budget: float = 0.6,
        cash_buffer_ratio: float = 0.05,
        horizon_steps: int = 10,
        volume_curve: list[float] | None = None,
        sigma: float = 0.02,
        eta: float = 0.01,
        risk_aversion: float = 1.0,
    ):
        self.model_id = model_id
        self.baseline_kind = baseline_kind
        self.rebalance_mode = rebalance_mode
        self.gross_budget = max(0.0, min(1.0, float(gross_budget)))
        self.cash_buffer_ratio = max(0.0, min(0.95, float(cash_buffer_ratio)))
        self.horizon_steps = max(1, int(horizon_steps or 1))
        self.volume_curve = list(volume_curve or [])
        self.sigma = max(0.0, float(sigma))
        self.eta = max(1e-9, float(eta))
        self.risk_aversion = max(0.0, float(risk_aversion))

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        context = observation.get("context") if isinstance(observation, dict) else {}
        symbols = [str(item).strip() for item in ((context or {}).get("symbol_universe") or []) if str(item).strip()]
        if not symbols:
            return HoldModel(model_id=self.model_id).act(observation)
        step_index = _step_index(observation)
        progress = self._progress(step_index)
        total_budget = round(self.gross_budget * progress, 6)
        weight = round(total_budget / len(symbols), 6)
        return {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {"account_id": (context or {}).get("agent_id"), "symbols": symbols},
            "payload": {
                "weights": {symbol: weight for symbol in symbols},
                "cash_buffer_ratio": self.cash_buffer_ratio,
                "rebalance_mode": self.rebalance_mode,
                "schedule": {
                    "schedule_type": self.baseline_kind,
                    "step_index": step_index,
                    "horizon_steps": self.horizon_steps,
                    "progress": progress,
                    "target_gross_budget": self.gross_budget,
                    "sigma": self.sigma if self.baseline_kind == "ac_lite" else None,
                    "eta": self.eta if self.baseline_kind == "ac_lite" else None,
                    "risk_aversion": self.risk_aversion if self.baseline_kind == "ac_lite" else None,
                },
            },
            "constraints": {
                "allow_short": False,
                "max_gross_leverage": 1.0,
                "clip_to_limits": True,
            },
            "meta": {
                "model_id": self.model_id,
                "baseline_kind": self.baseline_kind,
                "policy_type": "scheduled_execution_baseline",
            },
        }

    def _progress(self, step_index: int) -> float:
        bounded_step = max(0, min(self.horizon_steps - 1, int(step_index)))
        if self.baseline_kind == "vwap" and self.volume_curve:
            curve = [max(0.0, float(item)) for item in self.volume_curve[: self.horizon_steps]]
            if len(curve) < self.horizon_steps:
                curve.extend([1.0] * (self.horizon_steps - len(curve)))
            total = sum(curve) or 1.0
            return min(1.0, sum(curve[: bounded_step + 1]) / total)
        if self.baseline_kind == "ac_lite":
            t = (bounded_step + 1) / self.horizon_steps
            kappa = (max(self.risk_aversion * self.sigma * self.sigma / self.eta, 1e-12)) ** 0.5
            denominator = max(math.sinh(kappa), 1e-9)
            remaining = math.sinh(kappa * (1.0 - t)) / denominator
            return min(1.0, max(0.0, 1.0 - remaining))
        return min(1.0, (bounded_step + 1) / self.horizon_steps)


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
    - http: an out-of-process policy endpoint that returns act.v1.
    - subprocess: a short-lived local process that exchanges JSON over stdio.
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
        if self.adapter_type == "http":
            action = self._act_http(observation)
        elif self.adapter_type == "subprocess":
            action = self._act_subprocess(observation)
        elif self._policy is not None:
            action = dict(self._policy.act(observation))
        else:
            action = dict(self.config.get("action") or self._hold_action(observation))
        return self._normalize_action(action, observation)

    def learn(self, transition: dict[str, Any]) -> dict[str, Any]:
        if self.adapter_type == "http":
            endpoint = self._http_endpoint("learn_endpoint", default_suffix="/learn")
            if not endpoint:
                return {"ok": False, "reason": "LEARN_NOT_SUPPORTED", "model_id": self.model_id}
            return self._post_json(endpoint, {"model_id": self.model_id, "transition": transition})
        if self.adapter_type == "subprocess":
            command = self._process_command("learn_command")
            if not command:
                return {"ok": False, "reason": "LEARN_NOT_SUPPORTED", "model_id": self.model_id}
            return self._run_process_json(command, {"op": "learn", "model_id": self.model_id, "transition": transition})
        learner = getattr(self._policy, "learn", None)
        if callable(learner):
            result = learner(transition)
            return result if isinstance(result, dict) else {"ok": True}
        return {"ok": False, "reason": "LEARN_NOT_SUPPORTED", "model_id": self.model_id}

    def save_checkpoint(self, path: str) -> dict[str, Any]:
        if self.adapter_type == "http":
            endpoint = self._http_endpoint("checkpoint_endpoint", default_suffix="/checkpoint")
            if endpoint:
                result = self._post_json(endpoint, {"model_id": self.model_id, "path": path})
                if isinstance(result, dict) and result.get("ok") is not False:
                    return result
        if self.adapter_type == "subprocess":
            command = self._process_command("checkpoint_command")
            if command:
                result = self._run_process_json(command, {"op": "checkpoint", "model_id": self.model_id, "path": path})
                if isinstance(result, dict) and result.get("ok") is not False:
                    return result
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

    def _act_http(self, observation: dict[str, Any]) -> dict[str, Any]:
        endpoint = self._http_endpoint("endpoint", default_suffix="/act")
        if not endpoint:
            return self._hold_action(observation)
        try:
            payload = self._post_json(endpoint, {"model_id": self.model_id, "observation": observation})
        except Exception as exc:
            fallback = self._hold_action(observation)
            fallback["meta"] = {
                "model_id": self.model_id,
                "adapter_type": "http",
                "error": str(exc),
                "fallback": "hold",
            }
            return fallback
        action = payload.get("action") if isinstance(payload, dict) and isinstance(payload.get("action"), dict) else payload
        return action if isinstance(action, dict) else self._hold_action(observation)

    def _act_subprocess(self, observation: dict[str, Any]) -> dict[str, Any]:
        command = self._process_command("command")
        if not command:
            return self._hold_action(observation)
        try:
            payload = self._run_process_json(command, {"op": "act", "model_id": self.model_id, "observation": observation})
        except Exception as exc:
            fallback = self._hold_action(observation)
            fallback["meta"] = {
                "model_id": self.model_id,
                "adapter_type": "subprocess",
                "error": str(exc),
                "fallback": "hold",
            }
            return fallback
        action = payload.get("action") if isinstance(payload, dict) and isinstance(payload.get("action"), dict) else payload
        return action if isinstance(action, dict) else self._hold_action(observation)

    def _http_endpoint(self, key: str, *, default_suffix: str) -> str | None:
        explicit = str(self.config.get(key) or "").strip()
        if explicit:
            return explicit
        base_url = str(self.config.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            return None
        return f"{base_url}{default_suffix}"

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = _json_dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        timeout_s = float(self.config.get("timeout_s") or 2.0)
        with urlrequest.urlopen(req, timeout=max(0.1, timeout_s)) as response:
            raw = response.read().decode("utf-8")
        result = json.loads(raw) if raw else {}
        return result if isinstance(result, dict) else {"result": result}

    def _process_command(self, key: str) -> list[str]:
        value = self.config.get(key) or self.config.get("command")
        if isinstance(value, list):
            return [str(part) for part in value if str(part).strip()]
        if isinstance(value, str) and value.strip():
            return shlex.split(value)
        return []

    def _run_process_json(self, command: list[str], payload: dict[str, Any]) -> dict[str, Any]:
        timeout_s = float(self.config.get("timeout_s") or 2.0)
        cwd = self.config.get("cwd")
        proc = subprocess.run(
            command,
            input=_json_dumps(payload),
            text=True,
            capture_output=True,
            cwd=str(cwd) if cwd else None,
            timeout=max(0.1, timeout_s),
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"process adapter failed rc={proc.returncode}: {detail}")
        raw = (proc.stdout or "").strip()
        result = json.loads(raw) if raw else {}
        return result if isinstance(result, dict) else {"result": result}


class ModelRegistryService:
    def __init__(
        self,
        *,
        session_factory: Any | None = None,
        registry_path: str | Path | None = "output/model_registry/policies.json",
        external_policy_factories: dict[str, Callable[..., ModelPolicy]] | None = None,
    ):
        self._specs: dict[str, ModelSpec] = {
            "hold_model_v1": ModelSpec(
                "hold_model_v1",
                "hold",
                "Randomly buys at best ask or sells at best bid when executable top-of-book liquidity exists.",
            ),
            "random_weight_v1": ModelSpec("random_weight_v1", "random_weight", "Random long-only target weights."),
            "target_weight_naive_rebalance_v1": ModelSpec(
                "target_weight_naive_rebalance_v1",
                "target_weight_naive_rebalance",
                "Deterministic long-only equal-weight target rebalance baseline.",
            ),
            "twap_execution_v1": ModelSpec(
                "twap_execution_v1",
                "scheduled_execution_baseline",
                "Time-weighted scheduled target-weight execution baseline.",
                config={"baseline_kind": "twap", "rebalance_mode": "twap", "horizon_steps": 10},
            ),
            "vwap_execution_v1": ModelSpec(
                "vwap_execution_v1",
                "scheduled_execution_baseline",
                "Volume-weighted scheduled target-weight execution baseline.",
                config={
                    "baseline_kind": "vwap",
                    "rebalance_mode": "vwap",
                    "horizon_steps": 10,
                    "volume_curve": [1.5, 1.3, 1.1, 0.9, 0.7, 0.7, 0.8, 0.9, 1.0, 1.1],
                },
            ),
            "ac_lite_execution_v1": ModelSpec(
                "ac_lite_execution_v1",
                "scheduled_execution_baseline",
                "Simplified Almgren-Chriss style risk/cost scheduled target-weight execution baseline.",
                config={
                    "baseline_kind": "ac_lite",
                    "rebalance_mode": "ac_lite",
                    "horizon_steps": 10,
                    "sigma": 0.02,
                    "eta": 0.01,
                    "risk_aversion": 1.0,
                },
            ),
            "ppo_lstm_v1": ModelSpec(
                "ppo_lstm_v1",
                "ppo_recurrent",
                "PyTorch PPO-style recurrent actor-critic baseline.",
                config={"max_symbols": 8, "device": "cpu"},
            ),
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
        if spec is not None and spec.policy_type == "target_weight_naive_rebalance":
            return TargetWeightNaiveRebalanceModel(model_id=model_id)
        if spec is not None and spec.policy_type == "scheduled_execution_baseline":
            config = dict(spec.config or {})
            return ScheduledExecutionBaselineModel(
                model_id=model_id,
                baseline_kind=str(config.get("baseline_kind") or model_id),
                rebalance_mode=str(config.get("rebalance_mode") or config.get("baseline_kind") or "market"),
                horizon_steps=int(config.get("horizon_steps") or 10),
                volume_curve=list(config.get("volume_curve") or []),
                sigma=float(config.get("sigma") or 0.02),
                eta=float(config.get("eta") or 0.01),
                risk_aversion=float(config.get("risk_aversion") or 1.0),
            )
        if spec is not None and spec.policy_type == "ppo_recurrent":
            from rl.model_adapters.ppo_recurrent_adapter import RecurrentPPOPolicyAdapter

            return RecurrentPPOPolicyAdapter(model_id=model_id, config=spec.config or {}, seed=seed)
        return HoldModel(model_id=model_id, seed=seed)

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


def _step_index(observation: dict[str, Any]) -> int:
    sources = []
    if isinstance(observation, dict):
        sources.extend([
            observation.get("context"),
            observation.get("market"),
            observation,
        ])
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("step_index", "step", "bar_index"):
            if source.get(key) is None:
                continue
            try:
                return max(0, int(source.get(key)))
            except Exception:
                return 0
    return 0


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _available_qty_from_account(account: dict[str, Any], symbol: str) -> int:
    for position in account.get("positions") or []:
        if not isinstance(position, dict):
            continue
        if str(position.get("symbol") or "") != str(symbol):
            continue
        quantity = int(position.get("quantity") or 0)
        frozen_qty = int(position.get("frozen_qty") or 0)
        return max(0, quantity - frozen_qty)
    return 0


__all__ = [
    "CheckpointBackedModel",
    "ExternalPolicyAdapter",
    "HoldModel",
    "ModelPolicy",
    "ModelRegistryService",
    "ModelSpec",
    "RandomWeightModel",
    "ScheduledExecutionBaselineModel",
    "TargetWeightNaiveRebalanceModel",
    "TrainableModelPolicy",
]
