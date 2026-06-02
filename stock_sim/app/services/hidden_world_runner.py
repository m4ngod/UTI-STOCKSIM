from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any, Callable

from app.services.evidence_artifact_writer import EvidenceArtifactWriter
from app.services.evidence_core import hidden_world_specs


REQUIRED_HIDDEN_BASELINES = ["twap", "vwap", "ac_lite"]
DEFAULT_MIN_HIDDEN_WORLDS = 1
HIDDEN_PAIRED_METRICS = [
    "net_return",
    "execution_shortfall",
    "fee_drag",
    "turnover",
    "max_drawdown",
    "inventory_risk",
    "unfilled_ratio",
]


class HiddenWorldRunner:
    """Evaluate a frozen policy on hidden worlds without learning or PBT side effects."""

    def __init__(self, *, artifact_root: str | Path = "output/evidence_artifacts"):
        self._writer = EvidenceArtifactWriter(artifact_root)

    def run_hidden_eval(
        self,
        *,
        checkpoint: dict[str, Any],
        world_registry: dict[str, Any],
        frozen_policy: Any,
        baseline_policies: list[Any],
        evaluate_policy_once: Callable[..., Any],
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        dependencies: list[dict[str, Any]] | None = None,
        risk_limits: dict[str, float] | None = None,
        median_win_threshold: float = 0.60,
        strongest_win_threshold: float = 0.40,
        no_signal_tolerance: float = 0.0,
        required_baseline_names: list[str] | None = None,
        min_hidden_worlds: int = DEFAULT_MIN_HIDDEN_WORLDS,
    ) -> dict[str, Any]:
        checkpoint_hash = _checkpoint_hash(checkpoint)
        candidate_frozen = _checkpoint_frozen(checkpoint)
        training_world_hashes = _checkpoint_training_world_hashes(checkpoint)
        if required_baseline_names is not None:
            required_names = list(required_baseline_names)
        elif int(min_hidden_worlds) > DEFAULT_MIN_HIDDEN_WORLDS:
            required_names = list(REQUIRED_HIDDEN_BASELINES)
        else:
            required_names = []
        present_names = _ordered_policy_names(baseline_policies)
        missing_baseline_names = [name for name in required_names if name not in present_names]
        worlds = hidden_world_specs(world_registry)
        results: list[dict[str, Any]] = []
        split_contamination_worlds: list[str] = []
        for spec in worlds:
            if spec.get("split") != "hidden":
                continue
            world_hash = str(spec.get("world_spec_hash") or "")
            world_id = str(spec.get("world_name") or spec.get("world_id") or world_hash)
            split_contamination = bool(world_hash and world_hash in training_world_hashes)
            if split_contamination:
                split_contamination_worlds.append(world_id)
            model_result = _coerce_result(
                evaluate_policy_once(spec, frozen_policy, allow_learning=False)
            )
            baseline_results = {}
            for baseline in baseline_policies:
                name = _policy_name(baseline)
                baseline_results[name] = _coerce_result(
                    evaluate_policy_once(dict(spec), baseline, allow_learning=False)
                )
            comparison = _compare_to_baselines(model_result, baseline_results)
            results.append(
                {
                    "world_id": world_id,
                    "world_hash": world_hash or None,
                    "seed_hash": _world_seed_hash(spec),
                    "split": spec.get("split"),
                    "scenario_family": spec.get("scenario_family"),
                    "split_contamination": split_contamination,
                    "model": model_result,
                    "baselines": baseline_results,
                    "comparison": comparison,
                }
            )

        summary = _hidden_eval_summary(
            results,
            median_win_threshold=median_win_threshold,
            strongest_win_threshold=strongest_win_threshold,
            no_signal_tolerance=no_signal_tolerance,
            risk_limits=risk_limits or {},
            candidate_frozen=candidate_frozen,
            required_baseline_names=required_names,
            present_baseline_names=present_names,
            missing_baseline_names=missing_baseline_names,
            split_contamination_worlds=split_contamination_worlds,
            min_hidden_worlds=int(min_hidden_worlds),
            candidate_training_world_hashes=sorted(training_world_hashes),
        )
        registry_hash = world_registry.get("registry_hash") if isinstance(world_registry, dict) else None
        artifact = self._writer.write_hidden_eval_artifact(
            checkpoint_hash=checkpoint_hash,
            world_id=str(registry_hash or "hidden_world_registry"),
            world_hash=str(registry_hash) if registry_hash else None,
            results=results,
            summary=summary,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
            reward_hash=reward_hash,
            dependencies=dependencies or [],
        )
        return artifact


def _checkpoint_hash(checkpoint: dict[str, Any]) -> str | None:
    for key in ("checkpoint_hash", "hash", "artifact_hash"):
        value = checkpoint.get(key) if isinstance(checkpoint, dict) else None
        if value:
            return str(value)
    return None


def _checkpoint_frozen(checkpoint: dict[str, Any]) -> bool:
    if not isinstance(checkpoint, dict):
        return False
    if checkpoint.get("frozen") is True or checkpoint.get("is_frozen") is True:
        return True
    if checkpoint.get("frozen") is False or checkpoint.get("is_frozen") is False:
        return False
    if _checkpoint_training_world_hashes(checkpoint):
        return False
    return bool(_checkpoint_hash(checkpoint))


def _checkpoint_training_world_hashes(checkpoint: dict[str, Any]) -> set[str]:
    if not isinstance(checkpoint, dict):
        return set()
    values = (
        checkpoint.get("training_world_hashes")
        or checkpoint.get("training_worlds")
        or checkpoint.get("training_world_spec_hashes")
        or []
    )
    if isinstance(values, str):
        values = [values]
    return {str(item) for item in values if item}


def _world_seed_hash(spec: dict[str, Any]) -> str | None:
    for key in ("seed_hash", "random_seed_hash", "random_seed_ledger_hash", "seed"):
        value = spec.get(key) if isinstance(spec, dict) else None
        if value:
            return str(value)
    return None


def _policy_name(policy: Any) -> str:
    for attr in ("name", "model_id", "baseline_kind"):
        value = getattr(policy, attr, None)
        if value:
            return str(value)
    if isinstance(policy, dict):
        return str(policy.get("name") or policy.get("model_id") or policy.get("baseline_kind") or "baseline")
    return policy.__class__.__name__


def _ordered_policy_names(policies: list[Any]) -> list[str]:
    names = []
    for policy in policies:
        name = _policy_name(policy)
        if name not in names:
            names.append(name)
    return names


def _coerce_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = dict(getattr(result, "metrics", {}) or {})
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    return {"metrics": dict(metrics), "score": _score(metrics)}


def _score(metrics: dict[str, Any]) -> float:
    for key in ("score", "equity_return", "reward_total", "pnl"):
        if metrics.get(key) is not None:
            try:
                return float(metrics.get(key))
            except Exception:
                return 0.0
    return 0.0


def _compare_to_baselines(model_result: dict[str, Any], baseline_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    model_score = float(model_result.get("score") or 0.0)
    baseline_scores = {
        name: float(result.get("score") or 0.0)
        for name, result in baseline_results.items()
    }
    if not baseline_scores:
        return {
            "status": "missing_baselines",
            "model_score": model_score,
            "baseline_scores": {},
            "paired_metrics": {},
            "beats_baseline_median": False,
            "beats_strongest_baseline": False,
        }
    values = list(baseline_scores.values())
    baseline_median = float(median(values))
    strongest = max(values)
    return {
        "status": "available",
        "model_score": model_score,
        "baseline_scores": baseline_scores,
        "paired_metrics": {
            name: _paired_metric_deltas(
                model_result.get("metrics") if isinstance(model_result.get("metrics"), dict) else {},
                result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
            )
            for name, result in baseline_results.items()
        },
        "baseline_median": baseline_median,
        "strongest_baseline_score": strongest,
        "beats_baseline_median": model_score > baseline_median,
        "beats_strongest_baseline": model_score > strongest,
    }


def _paired_metric_deltas(model_metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    deltas: dict[str, dict[str, float | None]] = {}
    for name in HIDDEN_PAIRED_METRICS:
        candidate = _maybe_float(model_metrics.get(name))
        baseline = _maybe_float(baseline_metrics.get(name))
        deltas[name] = {
            "candidate": candidate,
            "baseline": baseline,
            "delta": candidate - baseline if candidate is not None and baseline is not None else None,
        }
    return deltas


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _hidden_eval_summary(
    results: list[dict[str, Any]],
    *,
    median_win_threshold: float,
    strongest_win_threshold: float,
    no_signal_tolerance: float,
    risk_limits: dict[str, float],
    candidate_frozen: bool,
    required_baseline_names: list[str],
    present_baseline_names: list[str],
    missing_baseline_names: list[str],
    split_contamination_worlds: list[str],
    min_hidden_worlds: int,
    candidate_training_world_hashes: list[str],
) -> dict[str, Any]:
    total = len(results)
    median_wins = sum(1 for item in results if (item.get("comparison") or {}).get("beats_baseline_median"))
    strongest_wins = sum(1 for item in results if (item.get("comparison") or {}).get("beats_strongest_baseline"))
    no_signal_failures = []
    risk_failures = []
    for item in results:
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        metrics = model.get("metrics") if isinstance(model.get("metrics"), dict) else {}
        scenario = str((metrics or {}).get("scenario_family") or item.get("scenario_family") or "")
        if scenario == "no_signal" and float(model.get("score") or 0.0) > no_signal_tolerance:
            no_signal_failures.append(str(item.get("world_id")))
        risk_failures.extend(_risk_limit_failures(item, metrics, risk_limits))

    median_win_rate = median_wins / total if total else 0.0
    strongest_win_rate = strongest_wins / total if total else 0.0
    failure_reasons = []
    if total <= 0:
        failure_reasons.append("missing_hidden_world_results")
    if total < min_hidden_worlds:
        failure_reasons.append("hidden_sample_size_too_small")
    if not candidate_frozen:
        failure_reasons.append("candidate_checkpoint_not_frozen")
    for name in missing_baseline_names:
        failure_reasons.append(f"hidden_missing_required_baseline:{name}")
    for world_id in split_contamination_worlds:
        failure_reasons.append(f"hidden_split_contamination:{world_id}")
    if any((item.get("comparison") or {}).get("status") == "missing_baselines" for item in results):
        failure_reasons.append("hidden_world_missing_baselines")
    if median_win_rate < median_win_threshold:
        failure_reasons.append("hidden_median_win_rate_below_threshold")
    if strongest_win_rate < strongest_win_threshold:
        failure_reasons.append("hidden_strongest_win_rate_below_threshold")
    if no_signal_failures:
        failure_reasons.append("no_signal_hidden_positive_alpha")
    if risk_failures:
        failure_reasons.append("hidden_risk_limit_breached")
    return {
        "schema": "hidden_eval_summary_v1",
        "hidden_world_count": total,
        "min_hidden_worlds": min_hidden_worlds,
        "candidate_frozen": candidate_frozen,
        "candidate_training_world_hashes": list(candidate_training_world_hashes),
        "hidden_world_hashes": sorted(str(item.get("world_hash")) for item in results if item.get("world_hash")),
        "seed_hashes": sorted(str(item.get("seed_hash")) for item in results if item.get("seed_hash")),
        "baseline_names": list(present_baseline_names),
        "required_baseline_names": list(required_baseline_names),
        "present_baseline_names": list(present_baseline_names),
        "missing_baseline_names": list(missing_baseline_names),
        "split_contamination_worlds": list(split_contamination_worlds),
        "split_contamination_check": {
            "status": "fail" if split_contamination_worlds else "pass",
            "contaminated_worlds": list(split_contamination_worlds),
            "candidate_training_world_hashes": list(candidate_training_world_hashes),
        },
        "metric_summary": _hidden_metric_summary(results),
        "median_win_count": median_wins,
        "median_win_rate": median_win_rate,
        "median_win_threshold": median_win_threshold,
        "strongest_win_count": strongest_wins,
        "strongest_win_rate": strongest_win_rate,
        "strongest_win_threshold": strongest_win_threshold,
        "no_signal_failures": no_signal_failures,
        "risk_limits": dict(risk_limits),
        "risk_failures": risk_failures,
        "risk_budget_breaches": risk_failures,
        "pass": not failure_reasons,
        "failure_type": _hidden_failure_type(failure_reasons),
        "next_action": _hidden_next_action(failure_reasons),
        "failure_reasons": failure_reasons,
    }


def _hidden_failure_type(failure_reasons: list[str]) -> str:
    if not failure_reasons:
        return "none"
    text = " ".join(failure_reasons)
    if "split_contamination" in text:
        return "split_contamination"
    if "risk_limit" in text or "risk_budget" in text:
        return "risk_budget_breach"
    if "sample_size" in text:
        return "sample_size_too_small"
    if "missing" in text:
        return "missing_metric"
    return "underperform_baseline"


def _hidden_next_action(failure_reasons: list[str]) -> str:
    if not failure_reasons:
        return "No action required."
    failure_type = _hidden_failure_type(failure_reasons)
    mapping = {
        "split_contamination": "Rebuild hidden registry from worlds never used for training, validation, PBT, or manual tuning.",
        "risk_budget_breach": "Keep hidden evaluation failed and reduce risk budget breaches before parent eligibility.",
        "sample_size_too_small": "Add enough hidden worlds before treating hidden evaluation as research evidence.",
        "missing_metric": "Run hidden evaluation with TWAP, VWAP, and AC-lite baselines on the same hidden worlds and seeds.",
        "underperform_baseline": "Candidate underperformed TWAP/VWAP/AC-lite; keep fail and improve candidate/reward/action space.",
    }
    return mapping[failure_type]


def _hidden_metric_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_metrics = {}
    baseline_metrics = {}
    for item in results:
        world_id = str(item.get("world_id"))
        model_metrics = ((item.get("model") or {}).get("metrics") or {})
        candidate_metrics[world_id] = {
            name: model_metrics.get(name)
            for name in HIDDEN_PAIRED_METRICS + ["score"]
            if name in model_metrics
        }
        baseline_metrics[world_id] = {
            str(name): {
                metric_name: ((result or {}).get("metrics") or {}).get(metric_name)
                for metric_name in HIDDEN_PAIRED_METRICS + ["score"]
                if metric_name in ((result or {}).get("metrics") or {})
            }
            for name, result in (item.get("baselines") or {}).items()
        }
    return {
        "required_metric_names": list(HIDDEN_PAIRED_METRICS),
        "candidate_metrics": candidate_metrics,
        "baseline_metrics": baseline_metrics,
    }


def _risk_limit_failures(
    result: dict[str, Any],
    metrics: dict[str, Any],
    risk_limits: dict[str, float],
) -> list[dict[str, Any]]:
    failures = []
    for metric_name, raw_limit in risk_limits.items():
        raw_value = metrics.get(metric_name)
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
            limit = float(raw_limit)
        except Exception:
            continue
        if value > limit:
            failures.append(
                {
                    "world_id": result.get("world_id"),
                    "metric": str(metric_name),
                    "value": value,
                    "limit": limit,
                }
            )
    return failures


__all__ = [
    "DEFAULT_MIN_HIDDEN_WORLDS",
    "HIDDEN_PAIRED_METRICS",
    "REQUIRED_HIDDEN_BASELINES",
    "HiddenWorldRunner",
]
