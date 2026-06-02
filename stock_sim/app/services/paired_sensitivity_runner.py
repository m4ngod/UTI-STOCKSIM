from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any, Callable

from app.services.evidence_artifact_writer import EvidenceArtifactWriter
from app.services.evidence_core import world_spec_hash

REQUIRED_PAIRED_SCENARIOS = ["base", "high_fee", "high_impact", "low_liquidity"]
REQUIRED_PAIRED_BASELINES = ["twap", "vwap", "ac_lite"]
REQUIRED_PAIRED_METRICS = [
    "gross_pnl",
    "net_pnl",
    "net_return",
    "fee_drag",
    "impact_cost",
    "slippage",
    "turnover",
    "unfilled_ratio",
    "max_drawdown",
    "inventory_risk",
    "execution_shortfall",
]


class PairedSensitivityRunner:
    """Run paired fee, impact, and fill-rule perturbations without learning side effects."""

    def __init__(self, *, artifact_root: str | Path = "output/evidence_artifacts"):
        self._writer = EvidenceArtifactWriter(artifact_root)

    def run_paired_sensitivity(
        self,
        *,
        checkpoint: dict[str, Any],
        base_world_spec: dict[str, Any],
        frozen_policy: Any,
        perturbations: list[dict[str, Any]],
        evaluate_policy_once: Callable[..., Any],
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        dependencies: list[dict[str, Any]] | None = None,
        required_perturbation_kinds: list[str] | None = None,
        severe_degradation_ratio: float | None = None,
        baseline_policies: list[Any] | dict[str, Any] | None = None,
        scenarios: list[str] | None = None,
        source_run_ids: list[str] | None = None,
        runner_version: str = "v0",
    ) -> dict[str, Any]:
        checkpoint_hash = _checkpoint_hash(checkpoint)
        base_spec = dict(base_world_spec or {})
        base_world_hash = str(base_spec.get("world_spec_hash") or world_spec_hash(base_spec)) if base_spec else None
        base_world_id = str(base_spec.get("world_name") or base_spec.get("world_id") or base_world_hash or "base_world")
        if baseline_policies is not None or scenarios is not None:
            paired_results = run_scenario_sensitivity(
                base_world_spec=base_spec,
                frozen_policy=frozen_policy,
                baseline_policies=baseline_policies,
                evaluate_policy_once=evaluate_policy_once,
                scenarios=scenarios or REQUIRED_PAIRED_SCENARIOS,
            )
            summary = _scenario_summary(paired_results)
            return self._writer.write_paired_sensitivity_artifact(
                checkpoint_hash=checkpoint_hash,
                base_world_id=base_world_id,
                base_world_hash=base_world_hash,
                paired_results=paired_results,
                summary=summary,
                code_identity_hash=code_identity_hash,
                sim_version_identity=sim_version_identity,
                random_seed_ledger_hash=random_seed_ledger_hash,
                contract_versions=contract_versions,
                reward_hash=reward_hash,
                dependencies=dependencies or [],
                source_run_ids=source_run_ids or [],
                runner_version=runner_version,
            )

        base_result = _evaluate_safely(evaluate_policy_once, base_spec, frozen_policy)

        paired_results = []
        for perturbation in perturbations or []:
            stressed_spec = apply_perturbation(base_spec, perturbation)
            stressed_result = _evaluate_safely(evaluate_policy_once, stressed_spec, frozen_policy)
            paired_results.append(
                {
                    "perturbation": dict(perturbation or {}),
                    "perturbation_kind": _perturbation_kind(perturbation),
                    "base_world_id": base_world_id,
                    "base_world_hash": base_world_hash,
                    "stressed_world_hash": stressed_spec.get("world_spec_hash"),
                    "base_metrics": base_result.get("metrics", {}),
                    "stressed_metrics": stressed_result.get("metrics", {}),
                    "base_error": base_result.get("error"),
                    "stressed_error": stressed_result.get("error"),
                    "delta": metric_delta(base_result.get("metrics", {}), stressed_result.get("metrics", {})),
                }
            )

        summary = _paired_summary(
            paired_results,
            required_perturbation_kinds=required_perturbation_kinds or ["fee", "impact", "latency"],
            severe_degradation_ratio=severe_degradation_ratio,
        )
        return self._writer.write_paired_sensitivity_artifact(
            checkpoint_hash=checkpoint_hash,
            base_world_id=base_world_id,
            base_world_hash=base_world_hash,
            paired_results=paired_results,
            summary=summary,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
            reward_hash=reward_hash,
            dependencies=dependencies or [],
            source_run_ids=source_run_ids or [],
            runner_version=runner_version,
        )


def run_scenario_sensitivity(
    *,
    base_world_spec: dict[str, Any],
    frozen_policy: Any,
    baseline_policies: list[Any] | dict[str, Any] | None,
    evaluate_policy_once: Callable[..., Any],
    scenarios: list[str],
) -> list[dict[str, Any]]:
    baseline_map = _baseline_policy_map(baseline_policies)
    results: list[dict[str, Any]] = []
    base_candidate_metrics: dict[str, Any] | None = None
    for scenario in scenarios:
        spec = scenario_world(base_world_spec, scenario)
        candidate_result = _evaluate_safely(evaluate_policy_once, spec, frozen_policy)
        if scenario == "base":
            base_candidate_metrics = candidate_result.get("metrics", {})
        baselines = {
            name: _evaluate_safely(evaluate_policy_once, dict(spec), policy)
            for name, policy in baseline_map.items()
        }
        results.append(
            {
                "scenario": scenario,
                "base_world_hash": str(base_world_spec.get("world_spec_hash") or world_spec_hash(base_world_spec)),
                "world_hash": spec.get("world_spec_hash"),
                "world_spec": {
                    "world_name": spec.get("world_name"),
                    "scenario_family": spec.get("scenario_family"),
                    "world_spec_hash": spec.get("world_spec_hash"),
                },
                "candidate": candidate_result,
                "baselines": baselines,
                "delta_vs_base": {},
                "recorded_metrics": _recorded_metric_snapshot(candidate_result.get("metrics", {})),
            }
        )
    if base_candidate_metrics is None and results:
        base_candidate_metrics = results[0].get("candidate", {}).get("metrics", {})
    for item in results:
        item["delta_vs_base"] = metric_delta(base_candidate_metrics or {}, item.get("candidate", {}).get("metrics", {}))
    return results


def scenario_world(base_world_spec: dict[str, Any], scenario: str) -> dict[str, Any]:
    name = str(scenario or "").strip().lower()
    spec = deepcopy(base_world_spec or {})
    if name == "base":
        spec["scenario_family"] = "base"
    elif name == "high_fee":
        spec = apply_perturbation(spec, {"kind": "fee", "factor": 2.0})
        spec["scenario_family"] = "high_fee"
    elif name == "high_impact":
        spec = apply_perturbation(spec, {"kind": "impact", "factor": 2.0})
        spec["scenario_family"] = "high_impact"
    elif name == "low_liquidity":
        spec = apply_perturbation(spec, {"kind": "liquidity", "factor": 0.5})
        spec["scenario_family"] = "low_liquidity"
    else:
        spec["scenario_family"] = name or "custom"
        spec.setdefault("scenario_construction_status", "missing")
    spec["scenario"] = name
    spec["world_spec_hash"] = world_spec_hash(spec)
    return spec


def apply_perturbation(base_world_spec: dict[str, Any], perturbation: dict[str, Any]) -> dict[str, Any]:
    spec = deepcopy(base_world_spec or {})
    perturbation = dict(perturbation or {})
    kind = _perturbation_kind(perturbation)
    path = perturbation.get("path")
    if path:
        _apply_path_operation(spec, str(path), str(perturbation.get("op") or "set"), perturbation.get("value"))
    elif kind == "fee":
        _apply_path_operation(spec, "fee_model.commission_bps", "multiply", perturbation.get("factor", 2.0))
    elif kind == "impact":
        _apply_path_operation(spec, "impact_model.params.temporary", "multiply", perturbation.get("factor", 2.0))
    elif kind == "latency":
        _apply_path_operation(spec, "fill_model.latency_ticks", "add", perturbation.get("ticks", perturbation.get("value", 1)))
    elif kind == "queue":
        _apply_path_operation(spec, "fill_model.queue_priority_penalty", "add", perturbation.get("levels", 1))
    elif kind == "spread":
        _apply_path_operation(spec, "market_rules.spread_multiplier", "multiply", perturbation.get("factor", 2.0))
    elif kind == "liquidity":
        _apply_path_operation(spec, "market_rules.liquidity_multiplier", "set", perturbation.get("factor", 0.5))
    elif kind == "partial_fill":
        _apply_path_operation(spec, "fill_model.partial_fill_probability", "multiply", perturbation.get("factor", 0.8))
    spec.setdefault("scenario_family", f"{kind}_stress")
    spec.setdefault("perturbation", perturbation)
    spec["world_spec_hash"] = world_spec_hash(spec)
    return spec


def metric_delta(base_metrics: dict[str, Any], stressed_metrics: dict[str, Any]) -> dict[str, Any]:
    base_score = _score(base_metrics)
    stressed_score = _score(stressed_metrics)
    deltas: dict[str, Any] = {
        "base_score": base_score,
        "stressed_score": stressed_score,
        "score_delta": _optional_delta(base_score, stressed_score),
        "score_degradation": _optional_delta(stressed_score, base_score),
    }
    if base_score not in (None, 0.0) and stressed_score is not None:
        deltas["score_degradation_ratio"] = (base_score - stressed_score) / abs(base_score)
    metric_names = sorted(set(base_metrics.keys()) & set(stressed_metrics.keys()))
    numeric_metric_delta = {}
    for name in metric_names:
        left = _optional_float(base_metrics.get(name))
        right = _optional_float(stressed_metrics.get(name))
        if left is not None and right is not None:
            numeric_metric_delta[name] = right - left
    deltas["numeric_metric_delta"] = numeric_metric_delta
    return deltas


def _evaluate_safely(evaluator: Callable[..., Any], spec: dict[str, Any], policy: Any) -> dict[str, Any]:
    try:
        result = evaluator(spec, policy, allow_learning=False)
    except Exception as exc:
        return {"metrics": {}, "score": None, "error": exc.__class__.__name__}
    coerced = _coerce_result(result)
    coerced["error"] = None
    return coerced


def _paired_summary(
    paired_results: list[dict[str, Any]],
    *,
    required_perturbation_kinds: list[str],
    severe_degradation_ratio: float | None,
) -> dict[str, Any]:
    present_kinds = sorted({str(item.get("perturbation_kind")) for item in paired_results if item.get("perturbation_kind")})
    missing_kinds = [kind for kind in required_perturbation_kinds if kind not in present_kinds]
    failures = []
    warnings = []
    if not paired_results:
        failures.append("missing_paired_sensitivity_results")
    if missing_kinds:
        failures.extend(f"missing_required_perturbation:{kind}" for kind in missing_kinds)
    if any(item.get("base_error") or item.get("stressed_error") for item in paired_results):
        failures.append("paired_sensitivity_evaluation_error")
    if any(not _has_finite_score(item.get("delta", {})) for item in paired_results):
        failures.append("paired_sensitivity_missing_score_curve")
    curve = []
    for item in paired_results:
        delta = item.get("delta") if isinstance(item.get("delta"), dict) else {}
        ratio = delta.get("score_degradation_ratio")
        point = {
            "perturbation_kind": item.get("perturbation_kind"),
            "base_score": delta.get("base_score"),
            "stressed_score": delta.get("stressed_score"),
            "score_delta": delta.get("score_delta"),
            "score_degradation": delta.get("score_degradation"),
            "score_degradation_ratio": ratio,
        }
        curve.append(point)
        if severe_degradation_ratio is not None and ratio is not None and ratio > severe_degradation_ratio:
            warnings.append(f"severe_score_degradation:{item.get('perturbation_kind')}")
    return {
        "schema": "paired_sensitivity_summary_v1",
        "paired_count": len(paired_results),
        "required_perturbation_kinds": list(required_perturbation_kinds),
        "present_perturbation_kinds": present_kinds,
        "missing_perturbation_kinds": missing_kinds,
        "degradation_curve": curve,
        "warnings": warnings,
        "pass": not failures,
        "failure_reasons": _dedupe(failures),
    }


def _scenario_summary(paired_results: list[dict[str, Any]]) -> dict[str, Any]:
    present_scenarios = [str(item.get("scenario")) for item in paired_results if item.get("scenario")]
    missing_scenarios = [name for name in REQUIRED_PAIRED_SCENARIOS if name not in present_scenarios]
    baseline_names = _ordered_baseline_names(
        str(name)
        for item in paired_results
        for name in (item.get("baselines") or {}).keys()
    )
    missing_baselines = [name for name in REQUIRED_PAIRED_BASELINES if name not in baseline_names]
    failures: list[str] = []
    if missing_scenarios:
        failures.extend(f"missing_required_scenario:{name}" for name in missing_scenarios)
    if missing_baselines:
        failures.extend(f"missing_required_baseline:{name}" for name in missing_baselines)
    if any((item.get("candidate") or {}).get("error") for item in paired_results):
        failures.append("paired_sensitivity_candidate_evaluation_error")
    if any((result or {}).get("error") for item in paired_results for result in (item.get("baselines") or {}).values()):
        failures.append("paired_sensitivity_baseline_evaluation_error")
    if any(not _has_finite_score(item.get("delta_vs_base", {})) for item in paired_results):
        failures.append("paired_sensitivity_missing_score_curve")
    scenario_results = [_scenario_result_summary(item) for item in paired_results]
    candidate_metrics = {str(item.get("scenario")): _recorded_metric_snapshot(((item.get("candidate") or {}).get("metrics") or {})) for item in paired_results}
    baseline_metrics = {
        str(item.get("scenario")): {
            str(name): _recorded_metric_snapshot((result or {}).get("metrics") or {})
            for name, result in (item.get("baselines") or {}).items()
        }
        for item in paired_results
    }
    scenario_world_hashes = {str(item.get("scenario")): item.get("world_hash") for item in paired_results if item.get("scenario")}
    scenario_deltas = {str(item.get("scenario")): item.get("delta_vs_base") or {} for item in paired_results if item.get("scenario")}
    missing_required_metrics = _missing_required_metric_names(candidate_metrics)
    catastrophic_flags = _catastrophic_collapse_flags(paired_results)
    return {
        "schema": "paired_sensitivity_summary_v2",
        "paired_count": len(paired_results),
        "base_world_hashes": sorted({str(item.get("base_world_hash")) for item in paired_results if item.get("base_world_hash")}),
        "scenario_world_hashes": scenario_world_hashes,
        "seed_hashes": _paired_seed_hashes(paired_results),
        "required_scenarios": list(REQUIRED_PAIRED_SCENARIOS),
        "present_scenarios": present_scenarios,
        "missing_scenarios": missing_scenarios,
        "required_baseline_names": list(REQUIRED_PAIRED_BASELINES),
        "present_baseline_names": baseline_names,
        "missing_baseline_names": missing_baselines,
        "required_metric_names": list(REQUIRED_PAIRED_METRICS),
        "missing_required_metrics": missing_required_metrics,
        "candidate_metrics": candidate_metrics,
        "baseline_metrics": baseline_metrics,
        "scenario_deltas": scenario_deltas,
        "catastrophic_collapse_flags": catastrophic_flags,
        "explainability_flags": _explainability_flags(candidate_metrics),
        "scenario_results": scenario_results,
        "degradation_curve": [
            {
                "scenario": item.get("scenario"),
                "score_delta": (item.get("delta_vs_base") or {}).get("score_delta"),
                "score_degradation": (item.get("delta_vs_base") or {}).get("score_degradation"),
                "score_degradation_ratio": (item.get("delta_vs_base") or {}).get("score_degradation_ratio"),
            }
            for item in paired_results
        ],
        "pass": not failures,
        "failure_type": "none" if not failures else "missing_metric",
        "failure_reasons": _dedupe(failures),
        "next_action": (
            "No action required."
            if not failures
            else "Run base/high_fee/high_impact/low_liquidity paired worlds with same seed and TWAP/VWAP/AC-lite baselines."
        ),
    }


def _scenario_result_summary(item: dict[str, Any]) -> dict[str, Any]:
    candidate_metrics = ((item.get("candidate") or {}).get("metrics") or {})
    return {
        "scenario": item.get("scenario"),
        "world_hash": item.get("world_hash"),
        "baseline_names": _ordered_baseline_names((item.get("baselines") or {}).keys()),
        "candidate_metrics": _recorded_metric_snapshot(candidate_metrics),
        "baseline_metrics": {
            str(name): _recorded_metric_snapshot((result or {}).get("metrics") or {})
            for name, result in (item.get("baselines") or {}).items()
        },
        "delta_vs_base": item.get("delta_vs_base") or {},
    }


def _recorded_metric_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    names = [
        "gross_pnl",
        "pnl",
        "net_pnl",
        "net_return",
        "equity_return",
        "fee_drag",
        "impact_cost",
        "slippage",
        "turnover",
        "unfilled_ratio",
        "max_drawdown",
        "inventory_risk",
        "execution_shortfall",
        "score",
    ]
    return {name: metrics.get(name) for name in names if name in metrics}


def _missing_required_metric_names(candidate_metrics: dict[str, dict[str, Any]]) -> list[str]:
    missing = []
    for scenario, metrics in candidate_metrics.items():
        for name in REQUIRED_PAIRED_METRICS:
            if name not in metrics:
                missing.append(f"{scenario}:{name}")
    return missing


def _paired_seed_hashes(paired_results: list[dict[str, Any]]) -> list[str]:
    values = []
    for item in paired_results:
        spec = item.get("world_spec") if isinstance(item.get("world_spec"), dict) else {}
        for key in ("seed_hash", "random_seed_hash", "random_seed_ledger_hash", "seed"):
            value = item.get(key) or spec.get(key)
            if value:
                values.append(str(value))
    return sorted(set(values))


def _catastrophic_collapse_flags(paired_results: list[dict[str, Any]]) -> list[str]:
    flags = []
    for item in paired_results:
        scenario = item.get("scenario")
        if scenario == "base":
            continue
        delta = item.get("delta_vs_base") if isinstance(item.get("delta_vs_base"), dict) else {}
        ratio = _optional_float(delta.get("score_degradation_ratio"))
        stressed_score = _optional_float(delta.get("stressed_score"))
        if stressed_score is None:
            flags.append(f"{scenario}:missing_score")
        elif ratio is not None and ratio >= 1.0:
            flags.append(f"{scenario}:score_collapse")
    return flags


def _explainability_flags(candidate_metrics: dict[str, dict[str, Any]]) -> list[str]:
    flags = []
    checks = {
        "high_fee": "fee_drag",
        "high_impact": "impact_cost",
        "low_liquidity": "unfilled_ratio",
    }
    for scenario, metric_name in checks.items():
        metrics = candidate_metrics.get(scenario) or {}
        if metrics.get(metric_name) is not None:
            flags.append(f"{scenario}:{metric_name}_recorded")
    return flags


def _apply_path_operation(payload: dict[str, Any], path: str, op: str, value: Any) -> None:
    current = payload
    parts = [part for part in path.split(".") if part]
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict) or child.get("status") == "not_available":
            child = {}
            current[part] = child
        current = child
    if not parts:
        return
    key = parts[-1]
    existing = current.get(key, 0.0)
    if op == "multiply":
        current[key] = _number_or_default(existing, 1.0) * _number_or_default(value, 1.0)
    elif op == "add":
        current[key] = _number_or_default(existing, 0.0) + _number_or_default(value, 0.0)
    else:
        current[key] = value


def _checkpoint_hash(checkpoint: dict[str, Any]) -> str | None:
    for key in ("checkpoint_hash", "hash", "artifact_hash"):
        value = checkpoint.get(key) if isinstance(checkpoint, dict) else None
        if value:
            return str(value)
    return None


def _perturbation_kind(perturbation: dict[str, Any]) -> str:
    text = str((perturbation or {}).get("kind") or (perturbation or {}).get("name") or "").lower()
    if "fee" in text or "commission" in text:
        return "fee"
    if "impact" in text:
        return "impact"
    if "latency" in text or "delay" in text:
        return "latency"
    if "queue" in text:
        return "queue"
    if "spread" in text:
        return "spread"
    if "liquidity" in text:
        return "liquidity"
    if "partial" in text or "fill" in text:
        return "partial_fill"
    return text or "custom"


def _baseline_policy_map(baseline_policies: list[Any] | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(baseline_policies, dict):
        return {str(key): value for key, value in baseline_policies.items()}
    result = {}
    for policy in baseline_policies or []:
        name = _policy_name(policy)
        result[name] = policy
    return result


def _ordered_baseline_names(names: Any) -> list[str]:
    available = {str(name) for name in names}
    ordered = [name for name in REQUIRED_PAIRED_BASELINES if name in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


def _policy_name(policy: Any) -> str:
    if isinstance(policy, dict):
        return str(policy.get("name") or policy.get("model_id") or policy.get("baseline_kind") or "baseline")
    for attr in ("name", "model_id", "baseline_kind"):
        value = getattr(policy, attr, None)
        if value:
            return str(value)
    return policy.__class__.__name__


def _coerce_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = dict(getattr(result, "metrics", {}) or {})
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    return {"metrics": dict(metrics), "score": _score(metrics)}


def _score(metrics: dict[str, Any]) -> float | None:
    for key in ("score", "equity_return", "reward_total", "pnl"):
        value = _optional_float(metrics.get(key))
        if value is not None:
            return value
    return None


def _optional_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return right - left


def _has_finite_score(delta: dict[str, Any]) -> bool:
    return _optional_float(delta.get("base_score")) is not None and _optional_float(delta.get("stressed_score")) is not None


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _number_or_default(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else float(default)


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = [
    "PairedSensitivityRunner",
    "REQUIRED_PAIRED_BASELINES",
    "REQUIRED_PAIRED_METRICS",
    "REQUIRED_PAIRED_SCENARIOS",
    "apply_perturbation",
    "metric_delta",
    "run_scenario_sensitivity",
    "scenario_world",
]
