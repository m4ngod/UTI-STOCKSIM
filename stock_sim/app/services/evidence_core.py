from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


REQUIRED_SEED_LABELS = [
    "retail_population",
    "liquidity_noise",
    "model_initialization",
    "episode_sampling",
    "hidden_world_selection",
    "world_generation",
    "calibration",
    "baselines",
    "paired_perturbations",
    "exploit_worlds",
    "pbt_mutation",
]

WORLD_REGISTRY_SPLITS = ["visible", "validation", "hidden", "exploit"]
P0_CALIBRATION_METRICS = [
    "spread",
    "depth",
    "turnover",
    "volatility",
    "return_autocorrelation",
    "fill_rate",
    "cancel_rate",
    "buy_sell_ratio",
    "holding_period",
    "retail_family_mix",
    "order_lifespan",
]
CALIBRATION_TARGET_BANDS_SCHEMA_VERSION = "calibration_target_bands.v0"
DEFAULT_CALIBRATION_TARGET_BANDS_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "evidence" / "calibration_target_bands.v0.json"
)


def engineering_default_target_bands_v0() -> dict[str, Any]:
    return load_calibration_target_bands()


def load_calibration_target_bands(path: str | Path | None = None) -> dict[str, Any]:
    """Load engineering calibration target bands from JSON and validate the P0 contract."""
    target_path = Path(path) if path else DEFAULT_CALIBRATION_TARGET_BANDS_PATH
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    return normalize_calibration_target_bands(payload)


def normalize_calibration_target_bands(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("calibration_target_bands must be a JSON object")
    schema_version = payload.get("schema_version") or payload.get("schema")
    if schema_version != CALIBRATION_TARGET_BANDS_SCHEMA_VERSION:
        raise ValueError(
            f"calibration_target_bands schema_version must be {CALIBRATION_TARGET_BANDS_SCHEMA_VERSION}; got {schema_version!r}"
        )
    target_bands = payload.get("target_bands") or payload.get("bands")
    if not isinstance(target_bands, dict):
        raise ValueError("calibration_target_bands.target_bands must be an object")
    missing_p0 = [name for name in P0_CALIBRATION_METRICS if name not in target_bands]
    if missing_p0:
        raise ValueError(f"calibration_target_bands missing required P0 metrics: {', '.join(missing_p0)}")

    source = str(payload.get("target_source") or "engineering_default_v0")
    normalized_bands: dict[str, dict[str, Any]] = {}
    public_bands: dict[str, dict[str, Any]] = {}
    for name in P0_CALIBRATION_METRICS:
        band = target_bands.get(name)
        if not isinstance(band, dict):
            raise ValueError(f"calibration_target_bands.{name} must be an object")
        required_fields = ["target_min", "target_max", "severity_on_breach", "required", "description"]
        missing_fields = [field for field in required_fields if field not in band]
        if missing_fields:
            raise ValueError(f"calibration_target_bands.{name} missing fields: {', '.join(missing_fields)}")
        target_min = _optional_float(band.get("target_min"))
        target_max = _optional_float(band.get("target_max"))
        if target_min is None or target_max is None:
            raise ValueError(f"calibration_target_bands.{name} target_min/target_max must be finite numbers")
        if target_min > target_max:
            raise ValueError(f"calibration_target_bands.{name} target_min must be <= target_max")
        severity = str(band.get("severity_on_breach") or "")
        if severity not in {"warning", "severe"}:
            raise ValueError(f"calibration_target_bands.{name} severity_on_breach must be warning or severe")
        if band.get("required") is not True:
            raise ValueError(f"calibration_target_bands.{name} required must be true")
        description = str(band.get("description") or "").strip()
        if not description:
            raise ValueError(f"calibration_target_bands.{name} description must be non-empty")
        public_bands[name] = {
            "target_min": target_min,
            "target_max": target_max,
            "severity_on_breach": severity,
            "required": True,
            "description": description,
        }
        normalized_bands[name] = {
            "min": target_min,
            "max": target_max,
            "source": source,
            "severity_on_breach": severity,
            "required": True,
            "description": description,
        }
    return {
        "schema": CALIBRATION_TARGET_BANDS_SCHEMA_VERSION,
        "schema_version": CALIBRATION_TARGET_BANDS_SCHEMA_VERSION,
        "target_source": source,
        "pass_level": str(payload.get("pass_level") or "engineering_pass"),
        "research_pass": False,
        "description": str(payload.get("description") or ""),
        "metric_names": list(P0_CALIBRATION_METRICS),
        "target_bands": public_bands,
        "bands": normalized_bands,
    }


def canonical_json_hash(value: Any, *, exclude_keys: set[str] | None = None) -> str:
    payload = _drop_keys(value, exclude_keys or set())
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_world_spec_v1(
    *,
    world_name: str,
    split: str,
    symbols: list[str],
    clock: dict[str, Any] | None = None,
    selection_rule: str = "explicit_symbols",
    market_rules: dict[str, Any] | None = None,
    fee_model: dict[str, Any] | None = None,
    impact_model: dict[str, Any] | None = None,
    fill_model: dict[str, Any] | None = None,
    retail_mix: dict[str, Any] | None = None,
    liquidity_seed_ref: str | None = None,
    calibration_target_profile: str | None = None,
    scenario_family: str | None = None,
) -> dict[str, Any]:
    spec = {
        "schema": "world_spec_v1",
        "world_name": str(world_name),
        "split": str(split),
        "universe": {
            "symbols": [str(item) for item in symbols],
            "selection_rule": str(selection_rule),
        },
        "clock": dict(clock or {}),
        "market_rules": _available_or_not(market_rules, "market_rules_not_wired"),
        "fee_model": _available_or_not(fee_model, "fee_model_not_wired"),
        "impact_model": _available_or_not(impact_model, "impact_model_not_wired"),
        "fill_model": _available_or_not(fill_model, "fill_model_not_wired"),
        "retail_mix": _available_or_not(retail_mix, "retail_family_mix_not_reported"),
        "liquidity_seed_ref": liquidity_seed_ref or _not_available("liquidity_seed_ref_not_wired"),
        "calibration_target_profile": calibration_target_profile or _not_available("calibration_target_profile_not_selected"),
        "scenario_family": scenario_family or _not_available("scenario_family_not_selected"),
        "hash_method": "sha256_json_canonical_v1",
    }
    spec["world_spec_hash"] = world_spec_hash(spec)
    return spec


def build_world_spec_from_arena_identity(
    world_identity: dict[str, Any],
    *,
    world_name: str = "arena_world",
    split: str = "train",
) -> dict[str, Any]:
    clock = {
        "clock_start_day": world_identity.get("clock_start_day"),
        "clock_speed": world_identity.get("clock_speed"),
        "run_clock": world_identity.get("run_clock"),
    }
    liquidity_seed_ref = None
    if world_identity.get("seed_training_liquidity") is not None:
        liquidity_seed_ref = "arena_training_liquidity"
    return build_world_spec_v1(
        world_name=world_name,
        split=split,
        symbols=list(world_identity.get("symbols") or []),
        clock=clock,
        liquidity_seed_ref=liquidity_seed_ref,
    )


def world_spec_hash(spec: dict[str, Any]) -> str:
    return canonical_json_hash(spec, exclude_keys={"world_spec_hash"})


def build_world_split_registry(world_specs: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_specs = [_normalize_world_spec_for_registry(spec) for spec in world_specs]
    worlds_by_split = {split: [] for split in WORLD_REGISTRY_SPLITS}
    failure_reasons: list[str] = []
    seen_hashes: dict[str, str] = {}
    for spec in normalized_specs:
        split = str(spec.get("split") or "").strip()
        if split == "train":
            split = "visible"
            spec["split"] = split
        if split not in worlds_by_split:
            failure_reasons.append(f"unsupported_world_split:{split or 'missing'}")
            continue
        spec_hash = str(spec.get("world_spec_hash") or world_spec_hash(spec))
        spec["world_spec_hash"] = spec_hash
        if spec_hash in seen_hashes:
            failure_reasons.append(f"duplicate_world_spec_hash:{spec_hash}")
        seen_hashes[spec_hash] = split
        worlds_by_split[split].append(spec)

    for required in ("visible", "validation", "hidden"):
        if not worlds_by_split[required]:
            failure_reasons.append(f"missing_required_world_split:{required}")

    registry = {
        "schema": "hidden_world_registry_v1",
        "split_names": list(WORLD_REGISTRY_SPLITS),
        "worlds_by_split": worlds_by_split,
        "split_counts": {split: len(worlds_by_split[split]) for split in WORLD_REGISTRY_SPLITS},
        "hidden_world_hashes": [item["world_spec_hash"] for item in worlds_by_split["hidden"]],
        "exploit_world_hashes": [item["world_spec_hash"] for item in worlds_by_split["exploit"]],
        "pass_fail": not failure_reasons,
        "failure_reasons": _dedupe(failure_reasons),
        "hash_method": "sha256_json_canonical_v1",
    }
    registry["registry_hash"] = world_split_registry_hash(registry)
    return registry


def world_split_registry_hash(registry: dict[str, Any]) -> str:
    return canonical_json_hash(registry, exclude_keys={"registry_hash"})


def hidden_world_specs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    worlds_by_split = registry.get("worlds_by_split") if isinstance(registry, dict) else {}
    if not isinstance(worlds_by_split, dict):
        return []
    hidden = worlds_by_split.get("hidden") if isinstance(worlds_by_split.get("hidden"), list) else []
    return [dict(item) for item in hidden if isinstance(item, dict)]


@dataclass(frozen=True)
class RandomSeedLedger:
    master_seed: int
    seeds: dict[str, int]
    schema: str = "random_seed_ledger_v1"
    seed_method: str = "sha256_label_derivation_v1"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "master_seed": int(self.master_seed),
            "seed_method": self.seed_method,
            "seeds": dict(sorted(self.seeds.items())),
        }
        payload["random_seed_ledger_hash"] = random_seed_ledger_hash(payload)
        return payload


def derive_seed(master_seed: int, *labels: str) -> int:
    payload = str(int(master_seed)) + "|" + "|".join(str(label) for label in labels)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16) % (2**31 - 1)


def build_random_seed_ledger(master_seed: int, labels: list[str] | None = None) -> dict[str, Any]:
    seed_labels = labels or REQUIRED_SEED_LABELS
    ledger = RandomSeedLedger(
        master_seed=int(master_seed),
        seeds={label: derive_seed(int(master_seed), label) for label in seed_labels},
    )
    return ledger.to_dict()


def random_seed_ledger_hash(ledger: dict[str, Any]) -> str:
    return canonical_json_hash(ledger, exclude_keys={"random_seed_ledger_hash"})


class MarketMetricsExtractor:
    def extract(
        self,
        *,
        orders: list[dict[str, Any]] | None = None,
        trades: list[dict[str, Any]] | None = None,
        snapshots: list[dict[str, Any]] | None = None,
        bars: list[dict[str, Any]] | None = None,
        accounts: list[dict[str, Any]] | None = None,
        account_equity_snapshots: list[dict[str, Any]] | None = None,
        holdings: list[dict[str, Any]] | None = None,
        agent_bindings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        orders = list(orders or [])
        trades = list(trades or [])
        snapshots = list(snapshots or [])
        bars = list(bars or [])
        accounts = list(accounts or [])
        account_equity_snapshots = list(account_equity_snapshots or [])
        holdings = list(holdings or [])
        agent_bindings = list(agent_bindings or [])

        prices = _prices_from_bars(bars) or _prices_from_trades(trades)
        returns = _returns(prices)
        spreads = _spreads(snapshots)
        depths = _depths(snapshots)
        trade_values = [_positive_float(item.get("price")) * _positive_float(item.get("qty", item.get("quantity"))) for item in trades]
        order_counts = _buy_sell_counts(orders)
        metrics = {
            "return_volatility": _pstdev_or_none(returns),
            "return_skew": _skew_or_none(returns),
            "return_kurtosis": _kurtosis_or_none(returns),
            "return_autocorr_lag1": _autocorr_or_none(returns),
            "squared_return_autocorr_lag1": _autocorr_or_none([value * value for value in returns]),
            "spread_mean": _mean_or_none(spreads),
            "spread_p90": _quantile_or_none(spreads, 0.9),
            "depth_mean": _mean_or_none(depths),
            "order_imbalance": _order_imbalance(orders),
            "turnover": sum(trade_values) if trade_values else None,
            "volume": sum(_positive_float(item.get("qty", item.get("quantity"))) for item in trades) if trades else None,
            "active_agent_count": len({str(item.get("agent_id")) for item in orders if item.get("agent_id")}) if orders else None,
            "market_limit_order_ratio": _market_limit_order_ratio(orders),
            "empty_book_ratio": _empty_book_ratio(snapshots),
            "buy_sell_ratio": _buy_sell_ratio(orders),
            "buy_order_count": order_counts["buy"],
            "sell_order_count": order_counts["sell"],
            "agent_order_concentration": _agent_order_concentration(orders),
            "holding_period_mean": _holding_period_mean(holdings, orders),
            "order_lifespan_mean": _mean_or_none([_positive_float(item.get("lifespan_bars", item.get("order_lifespan"))) for item in orders]),
            "fill_rate": _fill_rate(orders),
            "cancel_rate": _cancel_rate(orders),
            "retail_family_mix": _retail_family_mix(orders, agent_bindings),
            "account_equity_volatility": _account_equity_volatility(account_equity_snapshots),
            "account_count": len(accounts) if accounts else None,
            "t_plus_1_rejection_rate": None,
            "short_sell_rejection_rate": None,
            "fee_ledger_consistency": None,
            "frozen_release_consistency": None,
        }
        metric_coverage = {
            name: _coverage_for_metric(name, value)
            for name, value in metrics.items()
        }
        return {
            "schema": "market_metrics_extractor_v0",
            "metrics": metrics,
            "metric_coverage": metric_coverage,
            "source_counts": {
                "orders": len(orders),
                "trades": len(trades),
                "snapshots": len(snapshots),
                "bars": len(bars),
                "accounts": len(accounts),
                "account_equity_snapshots": len(account_equity_snapshots),
                "holdings": len(holdings),
                "agent_bindings": len(agent_bindings),
            },
        }


def normalize_calibration_observed_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metrics or {})
    return {
        "spread": payload.get("spread_mean"),
        "depth": payload.get("depth_mean"),
        "turnover": payload.get("turnover"),
        "volatility": payload.get("return_volatility"),
        "return_autocorrelation": payload.get("return_autocorr_lag1"),
        "fill_rate": payload.get("fill_rate"),
        "cancel_rate": payload.get("cancel_rate"),
        "buy_sell_ratio": payload.get("buy_sell_ratio"),
        "buy_order_count": payload.get("buy_order_count"),
        "sell_order_count": payload.get("sell_order_count"),
        "holding_period": payload.get("holding_period_mean"),
        "retail_family_mix": payload.get("retail_family_mix"),
        "order_lifespan": payload.get("order_lifespan_mean"),
    }


def compare_to_calibration_target_bands(
    *,
    observed_metrics: dict[str, Any],
    target_bands: dict[str, Any] | None = None,
    required_metrics: list[str] | None = None,
) -> dict[str, Any]:
    targets = dict(target_bands or engineering_default_target_bands_v0())
    bands = _comparison_bands(targets)
    required = list(required_metrics or targets.get("metric_names") or (targets.get("target_bands") or {}).keys() or P0_CALIBRATION_METRICS)
    metric_results: dict[str, dict[str, Any]] = {}
    missing_metrics: list[str] = []
    failed_metrics: list[str] = []
    severity_counts: Counter[str] = Counter()
    distances: list[float] = []
    for name in required:
        band = dict(bands.get(name) or {}) if isinstance(bands, dict) else {}
        source = str(band.get("source") or targets.get("target_source") or "engineering_default_v0")
        value = observed_metrics.get(name)
        if value is None:
            status = "missing"
            severity = "severe"
            distance = None
            missing_metrics.append(name)
        else:
            parsed = _optional_float(value)
            if parsed is None:
                status = "missing"
                severity = "severe"
                distance = None
                missing_metrics.append(name)
            else:
                min_value = _optional_float(band.get("min"))
                max_value = _optional_float(band.get("max"))
                distance = _band_distance(parsed, min_value, max_value)
                status = "pass" if distance <= 0.0 else "fail"
                severity = "none" if status == "pass" else str(band.get("severity_on_breach") or ("severe" if distance > 1.0 else "warning"))
                if status == "fail":
                    failed_metrics.append(name)
                distances.append(distance)
        severity_counts.update([severity])
        metric_results[name] = {
            "metric_name": name,
            "target_band": {
                "min": band.get("min"),
                "max": band.get("max"),
                "severity_on_breach": band.get("severity_on_breach"),
                "required": band.get("required"),
                "description": band.get("description"),
                "source": source,
            },
            "observed_value": value,
            "distance": distance,
            "severity": severity,
            "status": status,
        }
    engineering_pass = not missing_metrics and not any(
        item["severity"] == "severe" or item["status"] == "fail"
        for item in metric_results.values()
    )
    target_source = str(targets.get("target_source") or "engineering_default_v0")
    return {
        "schema": "calibration_target_band_scorecard_v0",
        "target_source": target_source,
        "target_bands": targets,
        "metric_results": metric_results,
        "score": mean(distances) if distances else None,
        "missing_metrics": missing_metrics,
        "failed_metrics": failed_metrics,
        "severity_counts": dict(severity_counts),
        "engineering_pass": engineering_pass,
        "research_pass": bool(engineering_pass and target_source != "engineering_default_v0"),
        "pass": engineering_pass,
        "failure_reasons": _dedupe(
            [f"missing_metric:{name}" for name in missing_metrics]
            + [f"target_distance:{name}" for name in failed_metrics]
        ),
    }


def normalized_distance(sim_value: float, target_mean: float, target_scale: float, cap: float = 5.0) -> float:
    if target_scale <= 0:
        return 0.0 if abs(sim_value - target_mean) < 1e-12 else cap
    return min(abs(sim_value - target_mean) / target_scale, cap)


def _comparison_bands(targets: dict[str, Any]) -> dict[str, Any]:
    if isinstance(targets.get("bands"), dict):
        return targets["bands"]
    if isinstance(targets.get("target_bands"), dict):
        return {
            name: {
                "min": band.get("target_min", band.get("min")),
                "max": band.get("target_max", band.get("max")),
                "severity_on_breach": band.get("severity_on_breach"),
                "required": band.get("required"),
                "description": band.get("description"),
                "source": targets.get("target_source"),
            }
            for name, band in targets["target_bands"].items()
            if isinstance(band, dict)
        }
    return targets


def compute_calibration_scorecard(
    *,
    sim_metrics: dict[str, Any],
    target_profile: dict[str, Any],
    metric_coverage: dict[str, str] | None = None,
) -> dict[str, Any]:
    target_profile_id = str(target_profile.get("target_profile_id") or target_profile.get("id") or "unknown_target_profile")
    target_metrics = target_profile.get("metrics") if isinstance(target_profile.get("metrics"), dict) else {
        key: value
        for key, value in target_profile.items()
        if isinstance(value, dict) and ("mean" in value or "target" in value)
    }
    weights = dict(target_profile.get("weights") or {})
    required = list(target_profile.get("required_metrics") or target_metrics.keys())
    pass_threshold = float(target_profile.get("pass_threshold", 1.0))
    metric_coverage = dict(metric_coverage or {})

    parts: dict[str, dict[str, float]] = {}
    coverage_failures: list[str] = []
    critical_failures: list[str] = []
    for name in required:
        if metric_coverage.get(name, "present" if sim_metrics.get(name) is not None else "missing") != "present":
            coverage_failures.append(name)

    for name, target in target_metrics.items():
        if name in coverage_failures:
            continue
        raw_value = sim_metrics.get(name)
        if raw_value is None:
            coverage_failures.append(name)
            continue
        value = float(raw_value)
        mean_value = float(target.get("mean", target.get("target", 0.0)))
        scale = float(target.get("scale", target.get("std", 1.0)))
        cap = float(target.get("cap", 5.0))
        weight = float(weights.get(name, target.get("weight", 1.0)))
        distance = normalized_distance(value, mean_value, scale, cap=cap)
        parts[name] = {
            "value": value,
            "target_mean": mean_value,
            "target_scale": scale,
            "distance": distance,
            "weight": weight,
            "weighted": distance * weight,
        }
        if distance > float(target.get("critical_max_distance", 3.0)):
            critical_failures.append(name)

    total_weight = sum(item["weight"] for item in parts.values())
    score = (
        sum(item["weighted"] for item in parts.values()) / total_weight
        if total_weight > 0
        else None
    )
    failure_reasons = []
    failure_reasons.extend(f"required_metric_not_present:{name}" for name in sorted(set(coverage_failures)))
    failure_reasons.extend(f"critical_metric_out_of_band:{name}" for name in sorted(set(critical_failures)))
    if score is None:
        failure_reasons.append("no_scored_metrics")
    elif score > pass_threshold:
        failure_reasons.append("calibration_score_above_threshold")
    return {
        "schema": "calibration_scorecard_v0",
        "target_profile_id": target_profile_id,
        "score": score,
        "pass_threshold": pass_threshold,
        "parts": parts,
        "pass": bool(score is not None and score <= pass_threshold and not coverage_failures and not critical_failures),
        "critical_failures": sorted(set(critical_failures)),
        "coverage_failures": sorted(set(coverage_failures)),
        "failure_reasons": _dedupe(failure_reasons),
    }


def _available_or_not(value: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    return dict(value) if value is not None else _not_available(reason)


def _not_available(reason: str) -> dict[str, str]:
    return {"status": "not_available", "reason": reason}


def _normalize_world_spec_for_registry(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    if payload.get("schema") != "world_spec_v1":
        payload.setdefault("schema", "world_spec_v1")
    payload.setdefault("world_name", "unknown_world")
    payload.setdefault("split", "visible")
    payload.setdefault("hash_method", "sha256_json_canonical_v1")
    payload["world_spec_hash"] = world_spec_hash(payload)
    return payload


def _drop_keys(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: _drop_keys(val, keys) for key, val in value.items() if key not in keys}
    if isinstance(value, list):
        return [_drop_keys(item, keys) for item in value]
    return value


def _prices_from_bars(bars: list[dict[str, Any]]) -> list[float]:
    return [_positive_float(item.get("close", item.get("price"))) for item in bars if _positive_float(item.get("close", item.get("price"))) > 0]


def _prices_from_trades(trades: list[dict[str, Any]]) -> list[float]:
    return [_positive_float(item.get("price")) for item in trades if _positive_float(item.get("price")) > 0]


def _returns(prices: list[float]) -> list[float]:
    return [
        (right - left) / left
        for left, right in zip(prices, prices[1:])
        if left > 0
    ]


def _spreads(snapshots: list[dict[str, Any]]) -> list[float]:
    values = []
    for item in snapshots:
        explicit = _optional_float(item.get("spread"))
        if explicit is not None and explicit >= 0:
            values.append(explicit)
            continue
        bid = _first_float(item, "best_bid", "bid1", "bid", "bid_price", "best_bid_price")
        ask = _first_float(item, "best_ask", "ask1", "ask", "ask_price", "best_ask_price")
        if bid is not None and ask is not None and ask >= bid:
            values.append(ask - bid)
    return values


def _depths(snapshots: list[dict[str, Any]]) -> list[float]:
    values = []
    for item in snapshots:
        bid_depth = _first_float(item, "bid_depth", "best_bid_qty", "bid1_qty", "bid_qty", "best_bid_size")
        ask_depth = _first_float(item, "ask_depth", "best_ask_qty", "ask1_qty", "ask_qty", "best_ask_size")
        if bid_depth is not None or ask_depth is not None:
            values.append((bid_depth or 0.0) + (ask_depth or 0.0))
    return values


def _coverage_for_metric(name: str, value: Any) -> str:
    if name in {
        "t_plus_1_rejection_rate",
        "short_sell_rejection_rate",
        "fee_ledger_consistency",
        "frozen_release_consistency",
    }:
        return "not_available"
    return "present" if value is not None else "missing"


def _order_imbalance(orders: list[dict[str, Any]]) -> float | None:
    buys = sum(1 for item in orders if _order_side(item) == "buy")
    sells = sum(1 for item in orders if _order_side(item) == "sell")
    total = buys + sells
    return (buys - sells) / total if total > 0 else None


def _buy_sell_ratio(orders: list[dict[str, Any]]) -> float | None:
    counts = _buy_sell_counts(orders)
    buys = counts["buy"]
    sells = counts["sell"]
    if buys == 0 and sells == 0:
        return None
    return float("inf") if sells == 0 else buys / sells


def _buy_sell_counts(orders: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "buy": sum(1 for item in orders if _order_side(item) == "buy"),
        "sell": sum(1 for item in orders if _order_side(item) == "sell"),
    }


def _market_limit_order_ratio(orders: list[dict[str, Any]]) -> float | None:
    market = 0
    limit = 0
    for item in orders:
        order_type = _norm_token(item.get("order_type", item.get("type", item.get("style", ""))))
        if "market" in order_type:
            market += 1
        elif "limit" in order_type:
            limit += 1
    if market == 0 and limit == 0:
        return None
    return float("inf") if limit == 0 else market / limit


def _empty_book_ratio(snapshots: list[dict[str, Any]]) -> float | None:
    if not snapshots:
        return None
    empty = 0
    for item in snapshots:
        bid = _first_float(item, "best_bid", "bid1", "bid", "bid_price", "best_bid_price")
        ask = _first_float(item, "best_ask", "ask1", "ask", "ask_price", "best_ask_price")
        if bid is None or ask is None:
            empty += 1
    return empty / len(snapshots)


def _agent_order_concentration(orders: list[dict[str, Any]]) -> float | None:
    counts = Counter(str(item.get("agent_id")) for item in orders if item.get("agent_id"))
    total = sum(counts.values())
    return max(counts.values()) / total if total else None


def _fill_rate(orders: list[dict[str, Any]]) -> float | None:
    if not orders:
        return None
    filled = 0
    eligible = 0
    for item in orders:
        status = _norm_token(item.get("status") or item.get("order_status") or "")
        if not status and item.get("filled") is None and item.get("filled_qty") is None:
            continue
        eligible += 1
        qty = _optional_float(item.get("filled", item.get("filled_qty")))
        if status in {"filled", "partially_filled", "partial"} or (qty is not None and qty > 0):
            filled += 1
    return filled / eligible if eligible else None


def _cancel_rate(orders: list[dict[str, Any]]) -> float | None:
    if not orders:
        return None
    observed = 0
    cancelled = 0
    for item in orders:
        status = _norm_token(item.get("status") or item.get("order_status") or "")
        if not status:
            continue
        observed += 1
        if status in {"cancelled", "canceled"}:
            cancelled += 1
    return cancelled / observed if observed else None


def _retail_family_mix(orders: list[dict[str, Any]], agent_bindings: list[dict[str, Any]] | None = None) -> float | None:
    family_by_account = _retail_family_by_account(agent_bindings or [])
    families = set()
    for item in orders:
        family = (
            item.get("retail_family")
            or item.get("agent_family")
            or family_by_account.get(str(item.get("account_id") or ""))
            or _family_from_identifier(item.get("account_id") or item.get("agent_id"))
        )
        if family:
            families.add(str(family))
    return min(len(families) / 10.0, 1.0) if families else None


def _retail_family_by_account(agent_bindings: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in agent_bindings:
        account_id = str(item.get("account_id") or item.get("agent_id") or item.get("agent_name") or "")
        if not account_id:
            continue
        family = item.get("retail_family") or item.get("agent_family") or item.get("strategy")
        meta = item.get("meta")
        if family is None and meta:
            try:
                payload = json.loads(meta) if isinstance(meta, str) else dict(meta)
                family = payload.get("retail_family") or payload.get("agent_family") or payload.get("strategy")
            except Exception:
                family = None
        if family is None:
            family = _family_from_identifier(account_id)
        if family:
            result[account_id] = str(family)
    return result


def _family_from_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    known = [
        "buy_the_dip",
        "momentum_chase",
        "mean_revert",
        "stop_loss",
        "liquidity_noise",
        "arena_passive_seed_bid",
        "arena_passive_seed_ask",
    ]
    for family in known:
        if lowered.startswith(family):
            return family
    return None


def _holding_period_mean(holdings: list[dict[str, Any]], orders: list[dict[str, Any]]) -> float | None:
    explicit = [
        _first_float(item, "holding_bars", "holding_period", "holding_period_bars", "age_bars")
        for item in holdings
    ]
    explicit_values = [value for value in explicit if value is not None]
    if explicit_values:
        return _mean_or_none(explicit_values)
    derived = _holding_periods_from_orders(orders)
    return _mean_or_none(derived)


def _holding_periods_from_orders(orders: list[dict[str, Any]]) -> list[float]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in orders:
        if _filled_qty(item) <= 0:
            continue
        account_id = str(item.get("account_id") or item.get("agent_id") or "")
        symbol = str(item.get("symbol") or "")
        if account_id and symbol:
            grouped[(account_id, symbol)].append(item)
    periods: list[float] = []
    for rows in grouped.values():
        rows.sort(key=_order_time_value)
        open_times: list[float] = []
        last_time = _order_time_value(rows[-1]) if rows else 0.0
        for row in rows:
            side = _order_side(row)
            current = _order_time_value(row)
            if side == "buy":
                open_times.append(current)
            elif side == "sell" and open_times:
                opened = open_times.pop(0)
                periods.append(max(current - opened, 0.0))
        periods.extend(max(last_time - opened, 0.0) for opened in open_times)
    if periods:
        return periods
    return [0.0] if any(_filled_qty(item) > 0 for item in orders) else []


def _account_equity_volatility(samples: list[dict[str, Any]]) -> float | None:
    equities = [_positive_float(item.get("equity")) for item in samples if _positive_float(item.get("equity")) > 0]
    returns = _returns(equities)
    return _pstdev_or_none(returns)


def _mean_or_none(values: list[float]) -> float | None:
    clean = [float(item) for item in values if item is not None and not math.isnan(float(item))]
    return mean(clean) if clean else None


def _pstdev_or_none(values: list[float]) -> float | None:
    return pstdev(values) if len(values) >= 2 else None


def _quantile_or_none(values: list[float], q: float) -> float | None:
    clean = sorted(values)
    if not clean:
        return None
    index = min(len(clean) - 1, max(0, math.ceil(q * len(clean)) - 1))
    return clean[index]


def _skew_or_none(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mu = mean(values)
    sigma = pstdev(values)
    if sigma <= 0:
        return 0.0
    return mean([((value - mu) / sigma) ** 3 for value in values])


def _kurtosis_or_none(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    mu = mean(values)
    sigma = pstdev(values)
    if sigma <= 0:
        return 0.0
    return mean([((value - mu) / sigma) ** 4 for value in values])


def _autocorr_or_none(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    left = values[:-1]
    right = values[1:]
    left_mu = mean(left)
    right_mu = mean(right)
    numerator = sum((a - left_mu) * (b - right_mu) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mu) ** 2 for a in left) * sum((b - right_mu) ** 2 for b in right))
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _first_float(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in item:
            continue
        value = _optional_float(item.get(key))
        if value is not None:
            return value
    return None


def _norm_token(value: Any) -> str:
    if hasattr(value, "name"):
        value = getattr(value, "name")
    elif hasattr(value, "value"):
        value = getattr(value, "value")
    text = str(value or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _order_side(item: dict[str, Any]) -> str:
    side = _norm_token(item.get("side", item.get("order_side", "")))
    if side in {"b", "bid"}:
        return "buy"
    if side in {"s", "ask", "offer"}:
        return "sell"
    return side


def _filled_qty(item: dict[str, Any]) -> float:
    return _first_float(item, "filled", "filled_qty", "filled_quantity", "fill_qty") or 0.0


def _order_time_value(item: dict[str, Any]) -> float:
    sim_day = _first_float(item, "sim_day")
    if sim_day is not None:
        return sim_day
    for key in ("ts_last", "updated_at", "ts_created", "created_at", "ts"):
        value = item.get(key)
        if value is None:
            continue
        if hasattr(value, "timestamp"):
            try:
                return float(value.timestamp())
            except Exception:
                pass
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return float(parsed.timestamp())
        except Exception:
            continue
    return 0.0


def _band_distance(value: float, min_value: float | None, max_value: float | None) -> float:
    if min_value is None and max_value is None:
        return 0.0
    if min_value is not None and value < min_value:
        width = abs(max_value - min_value) if max_value is not None and max_value > min_value else max(abs(min_value), 1.0)
        return (min_value - value) / width
    if max_value is not None and value > max_value:
        width = abs(max_value - min_value) if min_value is not None and max_value > min_value else max(abs(max_value), 1.0)
        return (value - max_value) / width
    return 0.0


def _positive_float(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None and parsed > 0 else 0.0


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = [
    "CALIBRATION_TARGET_BANDS_SCHEMA_VERSION",
    "DEFAULT_CALIBRATION_TARGET_BANDS_PATH",
    "MarketMetricsExtractor",
    "REQUIRED_SEED_LABELS",
    "RandomSeedLedger",
    "WORLD_REGISTRY_SPLITS",
    "build_random_seed_ledger",
    "build_world_split_registry",
    "build_world_spec_from_arena_identity",
    "build_world_spec_v1",
    "canonical_json_hash",
    "compare_to_calibration_target_bands",
    "compute_calibration_scorecard",
    "derive_seed",
    "engineering_default_target_bands_v0",
    "hidden_world_specs",
    "load_calibration_target_bands",
    "normalize_calibration_observed_metrics",
    "normalize_calibration_target_bands",
    "normalized_distance",
    "P0_CALIBRATION_METRICS",
    "random_seed_ledger_hash",
    "world_split_registry_hash",
    "world_spec_hash",
]
