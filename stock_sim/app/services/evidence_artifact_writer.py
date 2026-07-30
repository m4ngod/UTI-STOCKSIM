from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

LIVE_RUNTIME_SOURCE = "live_postgresql_runtime"


class EvidenceArtifactWriter:
    """Write separate Evidence Runner artifacts as canonical JSON files."""

    def __init__(self, artifact_root: str | Path = "output/evidence_artifacts"):
        self.artifact_root = Path(artifact_root)

    def write_calibration_artifact(
        self,
        *,
        world_id: str,
        world_hash: str | None,
        target_profile_id: str,
        metrics: dict[str, Any] | None,
        scorecard: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "calibration_artifact_writer",
        runner_version: str = "v0",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        metrics_payload = dict(metrics or {})
        scorecard_payload = dict(scorecard or {})
        failure_reasons = _calibration_failure_reasons(
            world_hash=world_hash,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
            scorecard=scorecard,
        )
        failure_reasons.extend(str(item) for item in scorecard_payload.get("failure_reasons") or [])
        failure_reasons.extend(str(item) for item in scorecard_payload.get("critical_failures") or [])
        failure_reasons.extend(str(item) for item in scorecard_payload.get("coverage_failures") or [])
        failure_reasons = _dedupe(failure_reasons)

        pass_gate = bool(scorecard_payload.get("pass")) and not failure_reasons
        metric_results = scorecard_payload.get("metric_results") if isinstance(scorecard_payload.get("metric_results"), dict) else {}
        target_bands_payload = (
            metrics_payload.get("target_bands")
            or scorecard_payload.get("target_bands")
            or {}
        )
        missing_metrics = list(scorecard_payload.get("missing_metrics") or metrics_payload.get("missing_metrics") or [])
        failed_metrics = list(scorecard_payload.get("failed_metrics") or metrics_payload.get("failed_metrics") or [])
        base_payload = {
            "artifact_kind": "calibration_artifact_v1",
            "artifact_type": "calibration_artifact_v1",
            "artifact_schema_version": "1",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": str(world_id),
            "world_hash": world_hash,
            "world_spec_version": str(metrics_payload.get("world_spec_version") or "world_spec_v1"),
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "target_profile_id": str(target_profile_id),
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "seed_hashes": list(metrics_payload.get("seed_hashes") or []),
            "metrics": metrics_payload,
            "metric_coverage": dict(metrics_payload.get("metric_coverage") or {}),
            "target_bands": target_bands_payload,
            "observed_values": dict(metrics_payload.get("observed_metrics") or {}),
            "distance_by_metric": dict(
                metrics_payload.get("distance_by_metric")
                or {name: result.get("distance") for name, result in metric_results.items()}
            ),
            "severity_by_metric": dict(
                metrics_payload.get("severity_by_metric")
                or {name: result.get("severity") for name, result in metric_results.items()}
            ),
            "failed_metrics": failed_metrics,
            "missing_metrics": missing_metrics,
            "calibration_score": scorecard_payload.get("score", metrics_payload.get("calibration_score")),
            "scorecard": scorecard_payload,
            "engineering_pass": pass_gate,
            "research_pass": bool(scorecard_payload.get("research_pass")) and str(scorecard_payload.get("target_source") or "") != "engineering_default_v0",
            "pass_level": "engineering",
            "target_source": scorecard_payload.get("target_source") or "engineering_default_v0",
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": _failure_type(failure_reasons, default="missing_metric"),
            "blocking_metrics": _blocking_metrics(scorecard_payload, failure_reasons),
            "next_action": _next_action("calibration_artifact_v1", failure_reasons),
            "failure_reasons": failure_reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"calibration-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def write_baseline_artifact(
        self,
        *,
        world_id: str,
        world_hash: str | None,
        task_name: str,
        baseline_suite: dict[str, Any] | None,
        baseline_results: list[dict[str, Any]] | None,
        benchmark_comparison: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        required_baseline_kinds: list[str] | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "unified_baseline_runner",
        runner_version: str = "v0",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        required = list(
            required_baseline_kinds
            or [
                "no_trade_cash",
                "random_constrained",
                "target_weight_naive_rebalance",
                "twap",
                "vwap",
                "ac_lite",
            ]
        )
        suite_payload = dict(baseline_suite or {})
        results_payload = [dict(item) for item in (baseline_results or [])]
        comparison_payload = dict(benchmark_comparison or {})
        present_kinds = _baseline_kinds_from_results(results_payload)
        missing_required = [item for item in required if item not in present_kinds]
        failure_reasons = _identity_failure_reasons(
            world_hash=world_hash,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
        )
        if not baseline_suite:
            failure_reasons.append("missing_baseline_suite")
        if not baseline_results:
            failure_reasons.append("missing_baseline_results")
        if missing_required:
            failure_reasons.extend(f"missing_required_baseline:{item}" for item in missing_required)
        if not benchmark_comparison:
            failure_reasons.append("missing_benchmark_comparison")
        elif comparison_payload.get("status") == "missing_baselines":
            failure_reasons.append("benchmark_comparison_missing_baselines")
        failure_reasons.extend(str(item) for item in suite_payload.get("failure_reasons") or [])
        failure_reasons = _dedupe(failure_reasons)

        pass_gate = not failure_reasons
        base_payload = {
            "artifact_kind": "baseline_artifact_v1",
            "artifact_schema_version": "1",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": str(world_id),
            "world_hash": world_hash,
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "task_name": str(task_name or ""),
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "required_baseline_kinds": required,
            "present_baseline_kinds": present_kinds,
            "missing_required_baseline_kinds": missing_required,
            "baseline_suite": suite_payload,
            "baseline_results": results_payload,
            "benchmark_comparison": comparison_payload,
            "metrics": {
                "baseline_count": len(results_payload),
                "candidate_count": len(comparison_payload.get("comparisons") or {}),
                "candidate_baseline_pair_count": _candidate_baseline_pair_count(comparison_payload),
            },
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": _failure_type(failure_reasons, default="missing_metric"),
            "blocking_metrics": _blocking_metrics(comparison_payload, failure_reasons),
            "next_action": _next_action("baseline_artifact_v1", failure_reasons),
            "failure_reasons": failure_reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"baseline-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def write_hidden_eval_artifact(
        self,
        *,
        checkpoint_hash: str | None,
        world_id: str,
        world_hash: str | None,
        results: list[dict[str, Any]] | None,
        summary: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "hidden_world_runner",
        runner_version: str = "v0",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        results_payload = [dict(item) for item in (results or [])]
        summary_payload = dict(summary or {})
        failure_reasons = _identity_failure_reasons(
            world_hash=world_hash,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
        )
        if not checkpoint_hash:
            failure_reasons.append("missing_checkpoint_hash")
        if not results_payload:
            failure_reasons.append("missing_hidden_eval_results")
        failure_reasons.extend(str(item) for item in summary_payload.get("failure_reasons") or [])
        failure_reasons = _dedupe(failure_reasons)

        pass_gate = bool(summary_payload.get("pass")) and not failure_reasons
        base_payload = {
            "artifact_kind": "hidden_eval_artifact_v1",
            "artifact_schema_version": "1",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": str(world_id),
            "world_hash": world_hash,
            "checkpoint_hash": checkpoint_hash,
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "results": results_payload,
            "metrics": summary_payload,
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": str(summary_payload.get("failure_type") or _failure_type(failure_reasons, default="underperform_baseline")),
            "blocking_metrics": _blocking_metrics(summary_payload, failure_reasons),
            "next_action": str(summary_payload.get("next_action") or _next_action("hidden_eval_artifact_v1", failure_reasons)),
            "failure_reasons": failure_reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"hidden-eval-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def write_paired_sensitivity_artifact(
        self,
        *,
        checkpoint_hash: str | None,
        base_world_id: str,
        base_world_hash: str | None,
        paired_results: list[dict[str, Any]] | None,
        summary: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "paired_sensitivity_runner",
        runner_version: str = "v0",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        results_payload = [dict(item) for item in (paired_results or [])]
        summary_payload = dict(summary or {})
        failure_reasons = _identity_failure_reasons(
            world_hash=base_world_hash,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
        )
        if not checkpoint_hash:
            failure_reasons.append("missing_checkpoint_hash")
        if not results_payload:
            failure_reasons.append("missing_paired_sensitivity_results")
        failure_reasons.extend(str(item) for item in summary_payload.get("failure_reasons") or [])
        failure_reasons = _dedupe(failure_reasons)

        pass_gate = bool(summary_payload.get("pass")) and not failure_reasons
        base_payload = {
            "artifact_kind": "paired_sensitivity_artifact_v1",
            "artifact_schema_version": "1",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": str(base_world_id),
            "world_hash": base_world_hash,
            "base_world_id": str(base_world_id),
            "base_world_hash": base_world_hash,
            "checkpoint_hash": checkpoint_hash,
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "paired_results": results_payload,
            "metrics": summary_payload,
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": _failure_type(failure_reasons, default="missing_metric"),
            "blocking_metrics": _blocking_metrics(summary_payload, failure_reasons),
            "next_action": _next_action("paired_sensitivity_artifact_v1", failure_reasons),
            "failure_reasons": failure_reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"paired-sensitivity-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def write_exploit_test_artifact(
        self,
        *,
        checkpoint_hash: str | None,
        world_id: str,
        world_hash: str | None,
        details: list[dict[str, Any]] | None,
        summary: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "exploit_test_runner",
        runner_version: str = "v0",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        details_payload = [dict(item) for item in (details or [])]
        summary_payload = dict(summary or {})
        failure_reasons = _identity_failure_reasons(
            world_hash=world_hash,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
        )
        if not checkpoint_hash:
            failure_reasons.append("missing_checkpoint_hash")
        if not details_payload:
            failure_reasons.append("missing_exploit_test_details")
        failure_reasons.extend(str(item) for item in summary_payload.get("failure_reasons") or [])
        failure_reasons = _dedupe(failure_reasons)

        pass_gate = bool(summary_payload.get("pass")) and not failure_reasons
        base_payload = {
            "artifact_kind": "exploit_test_artifact_v1",
            "artifact_schema_version": "1",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": str(world_id),
            "world_hash": world_hash,
            "checkpoint_hash": checkpoint_hash,
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "details": details_payload,
            "metrics": summary_payload,
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": _failure_type(failure_reasons, default="severe_flag"),
            "blocking_metrics": _blocking_metrics(summary_payload, failure_reasons),
            "next_action": _next_action("exploit_test_artifact_v1", failure_reasons),
            "failure_reasons": failure_reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"exploit-test-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def write_parent_gate_artifact(
        self,
        *,
        candidate_id: str,
        checkpoint_hash: str | None,
        required: dict[str, bool] | None,
        eligibility: dict[str, bool] | None,
        evidence_hashes: dict[str, str] | None,
        failure_reasons: list[str] | None,
        metrics: dict[str, Any] | None,
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        source: str = LIVE_RUNTIME_SOURCE,
        source_run_ids: list[str] | None = None,
        runner_name: str = "strict_parent_gate_v2",
        runner_version: str = "v2",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        created = created_at or _utc_now()
        required_payload = dict(required or {})
        eligibility_payload = dict(eligibility or {})
        metrics_payload = dict(metrics or {})
        reasons = _identity_failure_reasons(
            world_hash="parent_gate_not_world_scoped",
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
        )
        if not checkpoint_hash:
            reasons.append("checkpoint_hash")
        if not candidate_id:
            reasons.append("missing_candidate_id")
        reasons.extend(str(item) for item in (failure_reasons or []))
        reasons = _dedupe(reasons)

        pass_gate = bool(eligibility_payload.get("eligible_for_pbt_parent")) and not reasons
        base_payload = {
            "artifact_kind": "parent_gate_artifact_v2",
            "artifact_schema_version": "2",
            "created_at": created,
            "source": str(source),
            "source_run_ids": list(source_run_ids or []),
            "runner_name": str(runner_name),
            "runner_version": str(runner_version),
            "code_identity_hash": code_identity_hash,
            "sim_version_identity": sim_version_identity,
            "world_id": None,
            "world_hash": None,
            "candidate_id": str(candidate_id),
            "checkpoint_hash": checkpoint_hash,
            "reward_hash": reward_hash,
            "reward_not_applicable": reward_hash is None,
            "contract_versions": dict(contract_versions or {}),
            "random_seed_ledger_hash": random_seed_ledger_hash,
            "dependencies": list(dependencies or []),
            "required": required_payload,
            "eligibility": eligibility_payload,
            "eligible_for_pbt_parent": bool(eligibility_payload.get("eligible_for_pbt_parent")),
            "eligible_for_checkpoint_promotion": bool(eligibility_payload.get("eligible_for_checkpoint_promotion")),
            "eligible_for_research_claim": bool(eligibility_payload.get("eligible_for_research_claim")),
            "evidence_hashes": dict(evidence_hashes or {}),
            "metrics": metrics_payload,
            "pass_gate": pass_gate,
            "pass_fail": pass_gate,
            "failure_type": _failure_type(reasons, default="upstream_blocked"),
            "blocking_metrics": list(reasons),
            "next_action": _next_action("parent_gate_artifact_v2", reasons),
            "failure_reasons": reasons,
        }
        preliminary_hash = _canonical_sha256(base_payload)
        artifact_id = f"parent-gate-{preliminary_hash[:16]}"
        artifact = {"artifact_id": artifact_id, **base_payload}
        artifact["artifact_hash"] = _artifact_hash(artifact)
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(artifact), encoding="utf-8")
        return {**artifact, "artifact_path": str(path)}

    def _artifact_path(self, artifact: dict[str, Any]) -> Path:
        kind = str(artifact.get("artifact_kind") or "unknown_artifact")
        artifact_id = str(artifact.get("artifact_id") or _canonical_sha256(artifact)[:16])
        return self.artifact_root / kind / f"{artifact_id}.json"


def _calibration_failure_reasons(
    *,
    world_hash: str | None,
    code_identity_hash: str | None,
    sim_version_identity: dict[str, Any] | str | None,
    random_seed_ledger_hash: str | None,
    contract_versions: dict[str, Any] | None,
    scorecard: dict[str, Any] | None,
) -> list[str]:
    reasons = _identity_failure_reasons(
        world_hash=world_hash,
        code_identity_hash=code_identity_hash,
        sim_version_identity=sim_version_identity,
        random_seed_ledger_hash=random_seed_ledger_hash,
        contract_versions=contract_versions,
    )
    if not scorecard:
        reasons.append("missing_scorecard")
    return reasons


def _identity_failure_reasons(
    *,
    world_hash: str | None,
    code_identity_hash: str | None,
    sim_version_identity: dict[str, Any] | str | None,
    random_seed_ledger_hash: str | None,
    contract_versions: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if not code_identity_hash:
        reasons.append("missing_code_identity_hash")
    if not sim_version_identity:
        reasons.append("missing_sim_version_identity")
    if not world_hash:
        reasons.append("missing_world_hash")
    if not random_seed_ledger_hash:
        reasons.append("missing_random_seed_ledger_hash")
    if not contract_versions:
        reasons.append("missing_contract_versions")
    return reasons


def _baseline_kinds_from_results(results: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(item.get("baseline_kind"))
            for item in results
            if item.get("result_role") == "baseline" and item.get("baseline_kind")
        }
    )


def _candidate_baseline_pair_count(comparison: dict[str, Any]) -> int:
    comparisons = comparison.get("comparisons") if isinstance(comparison, dict) else {}
    if not isinstance(comparisons, dict):
        return 0
    return sum(len(value or {}) for value in comparisons.values() if isinstance(value, dict))


def _failure_type(failure_reasons: list[str], *, default: str) -> str:
    if not failure_reasons:
        return "none"
    text = " ".join(str(item).lower() for item in failure_reasons)
    if "missing" in text:
        return "missing_metric"
    if "underperform" in text or "baseline" in text:
        return "underperform_baseline"
    if "severe" in text or "exploit" in text:
        return "severe_flag"
    if "parent" in text or "upstream" in text or "required_evidence" in text:
        return "upstream_blocked"
    return default


def _blocking_metrics(payload: dict[str, Any], failure_reasons: list[str]) -> list[str]:
    metrics: list[str] = []
    for key in (
        "blocking_metrics",
        "missing_metrics",
        "failed_metrics",
        "severe_flags",
        "blocking_sections",
        "critical_failures",
        "coverage_failures",
    ):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            metrics.extend(str(item) for item in value)
        elif value:
            metrics.append(str(value))
    metrics.extend(str(item) for item in failure_reasons)
    return _dedupe(metrics)


def _next_action(artifact_kind: str, failure_reasons: list[str]) -> str:
    if not failure_reasons:
        return "No action required."
    mapping = {
        "baseline_artifact_v1": "Complete live baseline suite and preserve strong baselines.",
        "calibration_artifact_v1": "Add target band or fix missing runtime metric source.",
        "hidden_eval_artifact_v1": "Candidate underperformed TWAP/VWAP/AC-lite; keep fail and improve candidate/reward/action space.",
        "exploit_test_artifact_v1": "Complete missing probe metrics: timestamp, mark-to-market, order-boundary, fee-accounting, fill-rule, clock-boundary.",
        "paired_sensitivity_artifact_v1": "Run base/high_fee/high_impact/low_liquidity paired worlds with same seed.",
        "parent_gate_artifact_v2": "Upstream evidence still blocking; do not override.",
    }
    return mapping.get(artifact_kind, "Recompute artifact from live PostgreSQL/runtime facts.")


def _artifact_hash(artifact: dict[str, Any]) -> str:
    payload = {key: value for key, value in artifact.items() if key != "artifact_hash"}
    return _canonical_sha256(payload)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


__all__ = ["EvidenceArtifactWriter", "LIVE_RUNTIME_SOURCE"]
