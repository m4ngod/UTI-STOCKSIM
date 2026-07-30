from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from app.services.evidence_artifact_writer import EvidenceArtifactWriter
from app.services.evidence_core import (
    MarketMetricsExtractor,
    compare_to_calibration_target_bands,
    engineering_default_target_bands_v0,
    normalize_calibration_observed_metrics,
    world_spec_hash,
)


class CalibrationRunner:
    """Build calibration_artifact_v1 from live PostgreSQL/runtime fact payloads."""

    def __init__(self, *, artifact_root: str | Path = "output/evidence_artifacts"):
        self._writer = EvidenceArtifactWriter(artifact_root)
        self._extractor = MarketMetricsExtractor()

    def run_calibration(
        self,
        *,
        world_specs: list[dict[str, Any]],
        seeds: list[int],
        run_world_once: Callable[..., Any],
        fetch_runtime_facts: Callable[[str], dict[str, Any]],
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        target_bands: dict[str, Any] | None = None,
        reward_hash: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        targets = target_bands or engineering_default_target_bands_v0()
        for world in world_specs or []:
            spec = dict(world or {})
            spec_hash = str(spec.get("world_spec_hash") or world_spec_hash(spec))
            spec["world_spec_hash"] = spec_hash
            per_seed: list[dict[str, Any]] = []
            source_run_ids: list[str] = []
            runtime_errors: list[str] = []
            for seed in seeds or []:
                run_id = _coerce_run_id(
                    run_world_once(
                        world_spec=dict(spec),
                        seed=int(seed),
                        backend="postgresql_runtime",
                    )
                )
                if not run_id:
                    runtime_errors.append(f"missing_run_id:{seed}")
                    continue
                source_run_ids.append(run_id)
                try:
                    facts = dict(fetch_runtime_facts(run_id) or {})
                except Exception as exc:
                    runtime_errors.append(f"fetch_runtime_facts_failed:{run_id}:{exc.__class__.__name__}")
                    continue
                extracted = self._extractor.extract(
                    orders=list(facts.get("orders") or []),
                    trades=list(facts.get("trades") or []),
                    snapshots=list(facts.get("snapshots") or facts.get("snapshots_1s") or facts.get("order_book_snapshots") or []),
                    bars=list(facts.get("bars") or facts.get("bars_1m") or []),
                    accounts=list(facts.get("accounts") or []),
                    account_equity_snapshots=list(facts.get("account_equity_snapshots") or []),
                    holdings=list(facts.get("holdings") or []),
                    agent_bindings=list(facts.get("agent_bindings") or []),
                )
                per_seed.append(
                    {
                        "seed": int(seed),
                        "seed_hash": _seed_hash(seed=int(seed), world_hash=spec_hash),
                        "run_id": run_id,
                        "metrics": extracted["metrics"],
                        "observed_metrics": normalize_calibration_observed_metrics(extracted["metrics"]),
                        "metric_coverage": extracted["metric_coverage"],
                        "source_counts": extracted["source_counts"],
                        "runtime_fact_counts": _runtime_fact_counts(facts),
                    }
                )
            observed = _aggregate_observed_metrics([item["observed_metrics"] for item in per_seed])
            metric_coverage = _aggregate_metric_coverage([item["metric_coverage"] for item in per_seed])
            scorecard = compare_to_calibration_target_bands(
                observed_metrics=observed,
                target_bands=targets,
            )
            if runtime_errors:
                scorecard["failure_reasons"] = _dedupe(
                    list(scorecard.get("failure_reasons") or []) + runtime_errors
                )
                scorecard["pass"] = False
                scorecard["engineering_pass"] = False
            metrics_payload = {
                "schema": "calibration_live_runtime_metrics_v1",
                "source": "live_postgresql_runtime",
                "world_hash": spec_hash,
                "world_spec_version": str(spec.get("schema") or "world_spec_v1"),
                "seed_count": len(per_seed),
                "seed_hashes": [str(item["seed_hash"]) for item in per_seed],
                "source_run_ids": list(source_run_ids),
                "source_fact_tables": [
                    "orders",
                    "trades",
                    "snapshots_1s",
                    "bars_1m",
                    "agent_bindings",
                    "account_equity_snapshots",
                    "training_episodes",
                    "model_episode_results",
                    "model_transitions",
                ],
                "runtime_fact_counts": _aggregate_fact_counts([item["runtime_fact_counts"] for item in per_seed]),
                "per_seed_metrics": per_seed,
                "observed_metrics": observed,
                "metric_coverage": metric_coverage,
                "target_bands": targets,
                "distance_by_metric": {
                    name: result.get("distance")
                    for name, result in (scorecard.get("metric_results") or {}).items()
                },
                "severity_by_metric": {
                    name: result.get("severity")
                    for name, result in (scorecard.get("metric_results") or {}).items()
                },
                "failed_metrics": list(scorecard.get("failed_metrics") or []),
                "missing_metrics": list(scorecard.get("missing_metrics") or []),
                "severity_counts": dict(scorecard.get("severity_counts") or {}),
                "calibration_score": scorecard.get("score"),
            }
            artifacts.append(
                self._writer.write_calibration_artifact(
                    world_id=str(spec.get("world_name") or spec.get("world_id") or spec_hash),
                    world_hash=spec_hash,
                    target_profile_id=str(targets.get("target_source") or targets.get("target_profile_id") or "engineering_default_v0"),
                    metrics=metrics_payload,
                    scorecard=scorecard,
                    code_identity_hash=code_identity_hash,
                    sim_version_identity=sim_version_identity,
                    random_seed_ledger_hash=random_seed_ledger_hash,
                    contract_versions=contract_versions,
                    reward_hash=reward_hash,
                    dependencies=dependencies or [],
                    source_run_ids=source_run_ids,
                )
            )
        return artifacts


def _aggregate_observed_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    missing = Counter()
    for item in items:
        for name, raw in item.items():
            parsed = _optional_float(raw)
            if parsed is None:
                missing.update([name])
            else:
                values[name].append(parsed)
    names = sorted(set(values) | set(missing))
    result = {
        name: (mean(values[name]) if values.get(name) else None)
        for name in names
    }
    buy_count = sum(values.get("buy_order_count") or [])
    sell_count = sum(values.get("sell_order_count") or [])
    if buy_count > 0 or sell_count > 0:
        result["buy_sell_ratio"] = (float("inf") if sell_count <= 0 else buy_count / sell_count)
    return result


def _aggregate_metric_coverage(items: list[dict[str, Any]]) -> dict[str, str]:
    coverage: dict[str, str] = {}
    names = sorted({name for item in items for name in item})
    for name in names:
        statuses = [str(item.get(name) or "missing") for item in items]
        if any(status == "present" for status in statuses):
            coverage[name] = "present"
        elif any(status == "not_available" for status in statuses):
            coverage[name] = "not_available"
        else:
            coverage[name] = "missing"
    return coverage


def _runtime_fact_counts(facts: dict[str, Any]) -> dict[str, int]:
    aliases = {
        "orders": ("orders",),
        "trades": ("trades",),
        "snapshots_1s": ("snapshots_1s", "snapshots", "order_book_snapshots"),
        "bars_1m": ("bars_1m", "bars"),
        "agent_bindings": ("agent_bindings",),
        "account_equity_snapshots": ("account_equity_snapshots",),
        "training_episodes": ("training_episodes",),
        "model_episode_results": ("model_episode_results",),
        "model_transitions": ("model_transitions",),
    }
    counts: dict[str, int] = {}
    for table_name, keys in aliases.items():
        value = None
        for key in keys:
            if key in facts:
                value = facts.get(key)
                break
        counts[table_name] = len(value) if isinstance(value, list) else (1 if value else 0)
    return counts


def _aggregate_fact_counts(items: list[dict[str, int]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update({name: int(value or 0) for name, value in item.items()})
    return dict(counts)


def _seed_hash(*, seed: int, world_hash: str) -> str:
    payload = json.dumps({"seed": int(seed), "world_hash": str(world_hash)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coerce_run_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("run_id", "episode_id", "series_id"):
            if value.get(key):
                return str(value.get(key))
    if value:
        return str(value)
    return None


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


__all__ = ["CalibrationRunner"]
