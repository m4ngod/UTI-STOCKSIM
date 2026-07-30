from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_ALLOWED_MODEL_ROUTES = [
    "ppo_lstm_v1",
    "hold_model_v1",
    "random_weight_v1",
    "target_weight_naive_rebalance_v1",
    "twap_execution_v1",
    "vwap_execution_v1",
    "ac_lite_execution_v1",
]

ADVANCED_ROUTE_TOKENS = [
    "transformer",
    "gtrxl",
    "marl",
    "multi_agent_rl",
    "historical_replay",
    "hybrid_env",
    "alpha_claim",
]


class ModelRouteGate:
    """Gate complex model routes until Evidence Runner gates are stable."""

    def __init__(self, *, output_root: str | Path = "output/evidence_artifacts"):
        self.output_root = Path(output_root)

    def evaluate(
        self,
        *,
        model_specs: list[dict[str, Any]],
        go_no_go_review: dict[str, Any] | None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        review = dict(go_no_go_review or {})
        decision = _decision(review)
        advanced_allowed = decision == "go"
        routes = [_route_status(item, advanced_allowed=advanced_allowed) for item in (model_specs or [])]
        blocked = [item for item in routes if item["status"] == "blocked"]
        record = {
            "record_kind": "model_route_gate_v1",
            "schema_version": "1",
            "created_at": created_at or _utc_now(),
            "source": "UTI-STOCKSIM_第二轮专家评审与Evidence_Runner落地设计.md section 16",
            "go_no_go_decision": decision,
            "advanced_routes_allowed": advanced_allowed,
            "allowed_current_routes": list(DEFAULT_ALLOWED_MODEL_ROUTES),
            "advanced_route_tokens": list(ADVANCED_ROUTE_TOKENS),
            "routes": routes,
            "allowed_model_ids": [item["model_id"] for item in routes if item["status"] == "allowed"],
            "blocked_model_ids": [item["model_id"] for item in blocked],
            "status": "pass" if not blocked else "fail",
            "failure_reasons": _failure_reasons(blocked, decision),
        }
        record["route_gate_hash"] = _route_gate_hash(record)
        path = self._record_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(record), encoding="utf-8")
        return {**record, "record_path": str(path)}

    def _record_path(self, record: dict[str, Any]) -> Path:
        gate_hash = str(record.get("route_gate_hash") or _route_gate_hash(record))
        return self.output_root / "model_route_gate_v1" / f"model-route-gate-{gate_hash[:16]}.json"


def _route_status(spec: dict[str, Any], *, advanced_allowed: bool) -> dict[str, Any]:
    model_id = str(spec.get("model_id") or "").strip()
    policy_type = str(spec.get("policy_type") or spec.get("type") or "").strip()
    route_text = " ".join([model_id, policy_type, json.dumps(spec.get("config") or {}, sort_keys=True, default=str)]).lower()
    is_advanced = any(token in route_text for token in ADVANCED_ROUTE_TOKENS)
    allowed = not is_advanced or advanced_allowed
    return {
        "model_id": model_id,
        "policy_type": policy_type,
        "is_advanced_route": is_advanced,
        "status": "allowed" if allowed else "blocked",
        "reason": None if allowed else "evidence_runner_no_go_blocks_complex_model_route",
    }


def _decision(review: dict[str, Any]) -> str:
    for key in ("decision", "go_no_go", "status"):
        text = str(review.get(key) or "").strip().lower()
        if text in {"go", "no_go", "no-go", "nogo"}:
            return "go" if text == "go" else "no_go"
    return "no_go"


def _failure_reasons(blocked: list[dict[str, Any]], decision: str) -> list[str]:
    reasons = []
    if decision != "go" and blocked:
        reasons.append("evidence_runner_no_go_blocks_complex_model_route")
    reasons.extend(f"blocked_model_route:{item.get('model_id')}" for item in blocked if item.get("model_id"))
    return _dedupe(reasons)


def _route_gate_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key not in {"route_gate_hash", "record_path"}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


__all__ = ["ADVANCED_ROUTE_TOKENS", "DEFAULT_ALLOWED_MODEL_ROUTES", "ModelRouteGate"]
