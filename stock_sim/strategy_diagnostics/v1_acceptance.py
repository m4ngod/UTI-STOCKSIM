"""Executable release boundary for Strategy Diagnostics Laboratory V1."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal

from .ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
)

V1_ACCEPTANCE_REPORT_SCHEMA_VERSION = (
    "strategy-diagnostics-v1-acceptance-report.v1"
)

V1_TRANSFORMATION_FAMILIES = (
    "execution-stress",
    "liquidity",
    "market-structure",
    "shock-recovery",
    "trend-regime",
    "volatility",
)

V1_ACCEPTANCE_CHECK_IDS = (
    "historical_interval",
    "transformation_profile",
    "recipe_authoring_and_freeze",
    "ptrade_representative_strategies",
    "accelerated_simulation_time",
    "formal_campaign_layers",
    "isolated_immutable_replicas",
    "guided_ui_evidence",
    "deterministic_reproduction",
    "first_version_boundary",
)

V1_EXCLUDED_CAPABILITIES = (
    "legacy_strategy_matrix",
    "tick_order_book_hft",
    "live_trading",
    "news_macro_generation",
    "endogenous_price_impact",
    "autonomous_black_box_search",
    "ai_executable_logic",
)

V1_PRODUCT_SURFACE_INVENTORY_SCHEMA_VERSION = (
    "strategy-diagnostics-v1-product-surface.v1"
)

V1_REQUIRED_APPLICATION_COMMANDS = (
    "admit_historical_segment",
    "approve_recipe_draft",
    "author_recipe_with_ai",
    "build_selected_diagnostic_evidence",
    "create_manual_recipe_draft",
    "evaluate_v1_acceptance",
    "explain_diagnostic_findings",
    "materialize_reference_path",
    "plan_diagnostic_campaign",
    "plan_isolated_sensitivity_set",
    "reproduce_strategy_run",
    "reproduction_manifests",
    "recipe_authoring_capabilities",
    "resume_diagnostic_campaign",
    "run_baseline_campaign",
    "v1_diagnostic_configuration",
    "v1_product_surface_inventory",
    "validate_recipe_draft",
)

V1_ALLOWED_APPLICATION_COMMANDS = (
    "admit_historical_segment",
    "advance_diagnostic_campaign",
    "advance_isolated_sensitivity_set",
    "advance_strategy_run",
    "approve_diagnostic_task_configuration",
    "approve_recipe_draft",
    "author_recipe_with_ai",
    "build_diagnostic_evidence",
    "build_selected_diagnostic_evidence",
    "cancel_diagnostic_target",
    "cancel_strategy_run",
    "compare_reference_market_paths",
    "complete_strategy_run",
    "create_diagnostic_campaign_case",
    "create_diagnostic_task",
    "create_isolated_sensitivity_case",
    "create_manual_recipe_draft",
    "diagnostic_campaign_status",
    "diagnostic_evidence_status",
    "evaluate_v1_acceptance",
    "explain_diagnostic_findings",
    "get_ai_recipe_audit",
    "get_diagnostic_task",
    "get_recipe_version",
    "historical_segment_catalog_view",
    "initialize_persistence",
    "isolated_sensitivity_set_status",
    "latest_segment_admission",
    "list_approved_scenario_recipes",
    "list_available_diagnostic_campaign_cases",
    "list_historical_segments",
    "list_materialized_market_paths",
    "materialize_baseline_reference_path",
    "materialize_reference_path",
    "open_scenario_market_view",
    "pause_diagnostic_target",
    "pause_strategy_run",
    "plan_diagnostic_campaign",
    "plan_isolated_sensitivity_set",
    "preview_reference_market_path",
    "read_diagnostic_campaign_case_inventory",
    "read_strategy_under_test_inventory",
    "recipe_authoring_capabilities",
    "recommend_historical_segments",
    "reproduce_strategy_run",
    "reproduction_manifests",
    "reproduction_status",
    "resume_diagnostic_campaign",
    "resume_diagnostic_target",
    "resume_isolated_sensitivity_set",
    "resume_strategy_run",
    "retry_diagnostic_campaign_case",
    "retry_failed_diagnostic_campaign_node",
    "retry_isolated_sensitivity_case",
    "revise_diagnostic_task_configuration",
    "revise_recipe_version",
    "run_baseline_campaign",
    "start",
    "start_baseline_strategy_run",
    "start_formal_diagnostic_task_campaign",
    "status",
    "strategy_guardrail_profiles",
    "strategy_run_status",
    "transformation_catalog_view",
    "v1_diagnostic_configuration",
    "v1_product_surface_inventory",
    "validate_diagnostic_task_configuration",
    "validate_recipe_draft",
)

_EXCLUDED_COMMAND_PATTERNS = {
    "legacy_strategy_matrix": (
        "all_legacy_strategies",
        "legacy_strategy",
    ),
    "tick_order_book_hft": (
        "hft",
        "level2",
        "order_book",
        "orderbook",
        "tick_data",
    ),
    "live_trading": (
        "broker_order",
        "live_order",
        "live_trading",
        "submit_order",
    ),
    "news_macro_generation": (
        "generate_macro",
        "generate_news",
        "macro_generation",
        "news_generation",
    ),
    "endogenous_price_impact": (
        "endogenous_impact",
        "market_impact",
        "price_impact",
    ),
    "autonomous_black_box_search": (
        "autonomous_search",
        "black_box",
        "worst_case_search",
    ),
    "ai_executable_logic": (
        "ai_code",
        "compile_ai",
        "execute_ai",
        "generate_engine",
        "generate_transformation",
    ),
}

_REQUIRED_GUIDED_UI_STEPS = frozenset(
    {
        "approve_recipe",
        "build_evidence",
        "configure_guardrails",
        "configure_strategies",
        "inspect_findings",
        "materialize_recipe",
        "reproduce_run",
        "run_formal_campaign",
        "select_segment",
    }
)
_REQUIRED_PROVENANCE_SECTIONS = frozenset(
    {
        "campaign",
        "evidence",
        "effective_execution",
        "recipe",
        "reproduction",
        "requested_execution",
        "source",
        "strategy",
        "transformation",
    }
)
_REQUIRED_CURVE_OVERLAYS = frozenset({"drawdown", "equity", "sensitivity"})
_REQUIRED_CAMPAIGN_LAYERS = frozenset(
    {"baseline", "isolated_sensitivity", "compound"}
)
_SUCCESSFUL_REPRODUCTION_STATUSES = frozenset(
    {"reproduced_exactly", "reproduced_within_tolerance"}
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class V1ProductSurfaceInventory:
    """Authoritative inventory of public Diagnostics application commands."""

    application_commands: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.application_commands or any(
            not command.strip() for command in self.application_commands
        ):
            raise ValueError(
                "V1 product surface commands must not be empty"
            )
        if len(set(self.application_commands)) != len(
            self.application_commands
        ):
            raise ValueError("V1 product surface commands must be unique")
        object.__setattr__(
            self,
            "application_commands",
            tuple(sorted(self.application_commands)),
        )

    @property
    def missing_required_commands(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(V1_REQUIRED_APPLICATION_COMMANDS)
                - set(self.application_commands)
            )
        )

    @property
    def unclassified_commands(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.application_commands)
                - set(V1_ALLOWED_APPLICATION_COMMANDS)
            )
        )

    @property
    def status(self) -> Literal["verified", "incomplete"]:
        return (
            "verified"
            if (
                not self.missing_required_commands
                and not self.unclassified_commands
            )
            else "incomplete"
        )

    @property
    def present_excluded_capabilities(self) -> tuple[str, ...]:
        present = []
        for capability_id in V1_EXCLUDED_CAPABILITIES:
            patterns = _EXCLUDED_COMMAND_PATTERNS[capability_id]
            if any(
                pattern in command
                for command in self.application_commands
                for pattern in patterns
            ):
                present.append(capability_id)
        return tuple(present)

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self._content_payload())

    @property
    def inventory_id(self) -> str:
        return f"v1-product-surface-{self.content_hash[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "inventory_id": self.inventory_id,
            "content_hash": self.content_hash,
            **self._content_payload(),
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            "schema_version": (
                V1_PRODUCT_SURFACE_INVENTORY_SCHEMA_VERSION
            ),
            "status": self.status,
            "application_commands": list(self.application_commands),
            "missing_required_commands": list(
                self.missing_required_commands
            ),
            "unclassified_commands": list(
                self.unclassified_commands
            ),
            "present_excluded_capabilities": list(
                self.present_excluded_capabilities
            ),
        }


@dataclass(frozen=True, slots=True)
class V1CadenceProof:
    """Persisted two-strategy artifacts proving one accepted cadence."""

    decision_cadence_minutes: int
    campaign_id: str
    run_ids: tuple[str, str]
    run_artifact_hashes: tuple[str, str]

    def __post_init__(self) -> None:
        if self.decision_cadence_minutes not in (30, 60):
            raise ValueError("V1 cadence proof must use 30 or 60 minutes")
        if not self.campaign_id.strip() or any(
            not run_id.strip() for run_id in self.run_ids
        ):
            raise ValueError("V1 cadence proof identities must not be blank")
        if len(set(self.run_ids)) != 2:
            raise ValueError("V1 cadence proof requires two unique runs")
        for value in self.run_artifact_hashes:
            if len(value) != 64 or any(
                character not in "0123456789abcdef"
                for character in value
            ):
                raise ValueError(
                    "V1 cadence proof hashes must be lowercase SHA-256"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "campaign_id": self.campaign_id,
            "run_ids": list(self.run_ids),
            "run_artifact_hashes": list(self.run_artifact_hashes),
        }


@dataclass(frozen=True, slots=True)
class V1AcceptanceFacts:
    """Observable product facts supplied to the V1 release gate."""

    historical_segment_admitted: bool
    source_provenance_available: bool
    transformation_families: tuple[str, ...]
    manual_recipe_authoring_available: bool
    ai_recipe_authoring_available: bool
    recipe_validated: bool
    recipe_approved: bool
    recipe_frozen: bool
    recipe_versioned: bool
    recipe_hashed: bool
    selected_strategy_versions: tuple[tuple[str, str], ...]
    selected_guardrail_profiles: tuple[tuple[str, str, str], ...]
    supported_decision_cadences: tuple[int, ...]
    accelerated_simulation_time: bool
    next_node_activation: bool
    campaign_type: str
    campaign_status: str
    completed_campaign_layers: tuple[str, ...]
    isolated_cases_by_family: tuple[tuple[str, int], ...]
    isolated_replicas_share_immutable_inputs: bool
    guided_ui_steps: tuple[str, ...]
    provenance_sections: tuple[str, ...]
    curve_overlays: tuple[str, ...]
    evidence_status: str
    diagnostic_finding_count: int
    accepted_manifest_count: int
    reproduction_status: str
    ai_explanation_is_limited_to_sealed_findings: bool
    product_surface_inventory: V1ProductSurfaceInventory

    def __post_init__(self) -> None:
        if self.diagnostic_finding_count < 0:
            raise ValueError("diagnostic finding count must not be negative")
        if self.accepted_manifest_count < 0:
            raise ValueError("accepted manifest count must not be negative")
        if any(count < 0 for _, count in self.isolated_cases_by_family):
            raise ValueError("isolated case counts must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "historical_segment_admitted": (
                self.historical_segment_admitted
            ),
            "source_provenance_available": (
                self.source_provenance_available
            ),
            "transformation_families": list(
                self.transformation_families
            ),
            "manual_recipe_authoring_available": (
                self.manual_recipe_authoring_available
            ),
            "ai_recipe_authoring_available": (
                self.ai_recipe_authoring_available
            ),
            "recipe_validated": self.recipe_validated,
            "recipe_approved": self.recipe_approved,
            "recipe_frozen": self.recipe_frozen,
            "recipe_versioned": self.recipe_versioned,
            "recipe_hashed": self.recipe_hashed,
            "selected_strategy_versions": [
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                }
                for strategy_id, strategy_version in (
                    self.selected_strategy_versions
                )
            ],
            "selected_guardrail_profiles": [
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                    "profile_version": profile_version,
                }
                for (
                    strategy_id,
                    strategy_version,
                    profile_version,
                ) in self.selected_guardrail_profiles
            ],
            "supported_decision_cadences": list(
                self.supported_decision_cadences
            ),
            "accelerated_simulation_time": (
                self.accelerated_simulation_time
            ),
            "next_node_activation": self.next_node_activation,
            "campaign_type": self.campaign_type,
            "campaign_status": self.campaign_status,
            "completed_campaign_layers": list(
                self.completed_campaign_layers
            ),
            "isolated_cases_by_family": [
                {"family": family, "case_count": case_count}
                for family, case_count in self.isolated_cases_by_family
            ],
            "isolated_replicas_share_immutable_inputs": (
                self.isolated_replicas_share_immutable_inputs
            ),
            "guided_ui_steps": list(self.guided_ui_steps),
            "provenance_sections": list(self.provenance_sections),
            "curve_overlays": list(self.curve_overlays),
            "evidence_status": self.evidence_status,
            "diagnostic_finding_count": self.diagnostic_finding_count,
            "accepted_manifest_count": self.accepted_manifest_count,
            "reproduction_status": self.reproduction_status,
            "ai_explanation_is_limited_to_sealed_findings": (
                self.ai_explanation_is_limited_to_sealed_findings
            ),
            "product_surface_inventory": (
                self.product_surface_inventory.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class V1AcceptanceSubject:
    """Exact accepted artifacts and selections bound into one report."""

    campaign_id: str
    evidence_package_id: str
    evidence_artifact_hash: str
    measurement_artifact_hash: str
    reproduction_manifest_id: str
    reproduction_attempt_id: str
    selected_strategy_versions: tuple[tuple[str, str], ...]
    selected_guardrail_profiles: tuple[tuple[str, str, str], ...]
    cadence_proofs: tuple[V1CadenceProof, ...]
    product_surface_inventory_hash: str

    def __post_init__(self) -> None:
        identities = (
            self.campaign_id,
            self.evidence_package_id,
            self.reproduction_manifest_id,
            self.reproduction_attempt_id,
        )
        if any(not identity.strip() for identity in identities):
            raise ValueError(
                "V1 acceptance subject identities must not be blank"
            )
        for value in (
            self.evidence_artifact_hash,
            self.measurement_artifact_hash,
            self.product_surface_inventory_hash,
        ):
            if len(value) != 64 or any(
                character not in "0123456789abcdef"
                for character in value
            ):
                raise ValueError(
                    "V1 acceptance subject hashes must be lowercase SHA-256"
                )
        if tuple(
            proof.decision_cadence_minutes
            for proof in self.cadence_proofs
        ) != tuple(
            sorted(
                proof.decision_cadence_minutes
                for proof in self.cadence_proofs
            )
        ):
            raise ValueError("V1 cadence proofs must be ordered by cadence")
        if len(
            {
                proof.decision_cadence_minutes
                for proof in self.cadence_proofs
            }
        ) != len(self.cadence_proofs):
            raise ValueError("V1 cadence proofs must have unique cadences")

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "evidence_package_id": self.evidence_package_id,
            "evidence_artifact_hash": self.evidence_artifact_hash,
            "measurement_artifact_hash": (
                self.measurement_artifact_hash
            ),
            "reproduction_manifest_id": self.reproduction_manifest_id,
            "reproduction_attempt_id": self.reproduction_attempt_id,
            "selected_strategy_versions": [
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                }
                for strategy_id, strategy_version in (
                    self.selected_strategy_versions
                )
            ],
            "selected_guardrail_profiles": [
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                    "profile_version": profile_version,
                }
                for (
                    strategy_id,
                    strategy_version,
                    profile_version,
                ) in self.selected_guardrail_profiles
            ],
            "cadence_proofs": [
                proof.to_dict() for proof in self.cadence_proofs
            ],
            "product_surface_inventory_hash": (
                self.product_surface_inventory_hash
            ),
        }


@dataclass(frozen=True, slots=True)
class V1AcceptanceCheck:
    """One required capability decision and its human-readable evidence."""

    check_id: str
    title: str
    passed: bool
    evidence: str
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": "passed" if self.passed else "failed",
            "passed": self.passed,
            "evidence": self.evidence,
            "missing": list(self.missing),
        }


@dataclass(frozen=True, slots=True)
class V1ExcludedCapability:
    """Proof that one explicitly excluded capability is absent or present."""

    capability_id: str
    status: Literal["absent", "present", "unverified"]
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "status": self.status,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class V1AcceptanceReport:
    """Canonical, content-addressed result of the complete V1 release gate."""

    subject: V1AcceptanceSubject
    evaluated_facts: V1AcceptanceFacts
    checks: tuple[V1AcceptanceCheck, ...]
    excluded_capabilities: tuple[V1ExcludedCapability, ...]

    def __post_init__(self) -> None:
        if tuple(check.check_id for check in self.checks) != (
            V1_ACCEPTANCE_CHECK_IDS
        ):
            raise ValueError("V1 acceptance checks must be complete and ordered")
        if tuple(
            item.capability_id for item in self.excluded_capabilities
        ) != V1_EXCLUDED_CAPABILITIES:
            raise ValueError(
                "V1 excluded capabilities must be complete and ordered"
            )
        if (
            self.subject.selected_strategy_versions
            != self.evaluated_facts.selected_strategy_versions
            or self.subject.selected_guardrail_profiles
            != self.evaluated_facts.selected_guardrail_profiles
            or tuple(
                proof.decision_cadence_minutes
                for proof in self.subject.cadence_proofs
            )
            != self.evaluated_facts.supported_decision_cadences
            or self.subject.product_surface_inventory_hash
            != self.evaluated_facts.product_surface_inventory.content_hash
        ):
            raise ValueError(
                "V1 acceptance subject does not match evaluated facts"
            )

    @property
    def status(self) -> Literal["passed", "failed"]:
        if all(check.passed for check in self.checks) and all(
            item.status == "absent"
            for item in self.excluded_capabilities
        ):
            return "passed"
        return "failed"

    @property
    def content_hash(self) -> str:
        return _canonical_hash(self._content_payload())

    @property
    def report_id(self) -> str:
        return f"v1-acceptance-{self.content_hash[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "content_hash": self.content_hash,
            **self._content_payload(),
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            "schema_version": V1_ACCEPTANCE_REPORT_SCHEMA_VERSION,
            "subject": self.subject.to_dict(),
            "evaluated_facts": self.evaluated_facts.to_dict(),
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "excluded_capabilities": [
                item.to_dict() for item in self.excluded_capabilities
            ],
        }


class V1AcceptanceGate:
    """Evaluate all V1 requirements and exclusions without hidden fallback."""

    def evaluate(
        self,
        facts: V1AcceptanceFacts,
        subject: V1AcceptanceSubject,
    ) -> V1AcceptanceReport:
        inventory = facts.product_surface_inventory
        present_exclusions = set(
            inventory.present_excluded_capabilities
        )
        if not facts.ai_explanation_is_limited_to_sealed_findings:
            present_exclusions.add("ai_executable_logic")
        exclusions = tuple(
            V1ExcludedCapability(
                capability_id=capability_id,
                status=(
                    "present"
                    if capability_id in present_exclusions
                    else (
                        "absent"
                        if inventory.status == "verified"
                        else "unverified"
                    )
                ),
                evidence=(
                    f"{capability_id} is present in the accepted V1 product surface"
                    if capability_id in present_exclusions
                    else (
                        (
                            f"{capability_id} is absent from the authoritative "
                            "V1 product surface inventory"
                        )
                        if inventory.status == "verified"
                        else (
                            f"{capability_id} cannot be verified because the "
                            "V1 product surface inventory is incomplete"
                        )
                    )
                ),
            )
            for capability_id in V1_EXCLUDED_CAPABILITIES
        )
        checks = (
            self._historical_interval(facts),
            self._transformation_profile(facts),
            self._recipe_authoring_and_freeze(facts),
            self._representative_strategies(facts),
            self._accelerated_simulation_time(facts),
            self._formal_campaign_layers(facts),
            self._isolated_immutable_replicas(facts),
            self._guided_ui_evidence(facts),
            self._deterministic_reproduction(facts),
            V1AcceptanceCheck(
                check_id="first_version_boundary",
                title="V1 product boundary excludes deferred capabilities",
                passed=(
                    inventory.status == "verified"
                    and not present_exclusions
                ),
                evidence=(
                    (
                        "The authoritative inventory verifies all seven "
                        "deferred capability families are absent"
                    )
                    if (
                        inventory.status == "verified"
                        and not present_exclusions
                    )
                    else (
                        "The V1 product surface is incomplete or includes "
                        "a deferred capability"
                    )
                ),
                missing=tuple(
                    sorted(
                        present_exclusions
                        | set(inventory.missing_required_commands)
                        | {
                            f"unclassified:{command}"
                            for command in inventory.unclassified_commands
                        }
                    )
                ),
            ),
        )
        return V1AcceptanceReport(
            subject=subject,
            evaluated_facts=facts,
            checks=checks,
            excluded_capabilities=exclusions,
        )

    @staticmethod
    def _historical_interval(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        missing = []
        if not facts.historical_segment_admitted:
            missing.append("admitted_contiguous_a_share_interval")
        if not facts.source_provenance_available:
            missing.append("source_provenance")
        return V1AcceptanceCheck(
            check_id="historical_interval",
            title="Contiguous A-share interval with source provenance",
            passed=not missing,
            evidence=(
                "An admitted interval and source provenance are available"
                if not missing
                else "Historical interval admission is incomplete"
            ),
            missing=tuple(missing),
        )

    @staticmethod
    def _transformation_profile(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        available = set(facts.transformation_families)
        required = set(V1_TRANSFORMATION_FAMILIES)
        missing = tuple(sorted(required - available))
        unexpected = tuple(sorted(available - required))
        return V1AcceptanceCheck(
            check_id="transformation_profile",
            title="Six accepted transformation families",
            passed=not missing and not unexpected,
            evidence=(
                "Exactly the six V1 transformation families are catalogued"
                if not missing and not unexpected
                else "The transformation catalogue differs from the V1 profile"
            ),
            missing=missing + tuple(
                f"unexpected:{item}" for item in unexpected
            ),
        )

    @staticmethod
    def _recipe_authoring_and_freeze(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        capabilities = {
            "manual_authoring": facts.manual_recipe_authoring_available,
            "ai_authoring": facts.ai_recipe_authoring_available,
            "validation": facts.recipe_validated,
            "approval": facts.recipe_approved,
            "frozen": facts.recipe_frozen,
            "versioned": facts.recipe_versioned,
            "content_hash": facts.recipe_hashed,
        }
        missing = tuple(
            name for name, available in capabilities.items() if not available
        )
        return V1AcceptanceCheck(
            check_id="recipe_authoring_and_freeze",
            title="Manual/AI authoring and deterministic recipe freeze",
            passed=not missing,
            evidence=(
                "Recipe authoring, validation, approval, version and hash are proven"
                if not missing
                else "The approved-recipe lifecycle is incomplete"
            ),
            missing=missing,
        )

    @staticmethod
    def _representative_strategies(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        expected = {
            (
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
            (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
            ),
        }
        selected = set(facts.selected_strategy_versions)
        profile_strategies = {
            (strategy_id, strategy_version)
            for strategy_id, strategy_version, profile_version in (
                facts.selected_guardrail_profiles
            )
            if profile_version.strip()
        }
        missing = tuple(
            f"{strategy_id}@{strategy_version}"
            for strategy_id, strategy_version in sorted(
                (expected - selected) | (expected - profile_strategies)
            )
        )
        unexpected = tuple(
            f"unexpected:{strategy_id}@{strategy_version}"
            for strategy_id, strategy_version in sorted(selected - expected)
        )
        passed = (
            selected == expected
            and profile_strategies == expected
            and len(facts.selected_guardrail_profiles) == 2
        )
        return V1AcceptanceCheck(
            check_id="ptrade_representative_strategies",
            title="Two representative PTrade strategies and guardrails",
            passed=passed,
            evidence=(
                "Both versioned representative strategies and profiles are selected"
                if passed
                else "The selected strategy/guardrail pair is incomplete"
            ),
            missing=missing + unexpected,
        )

    @staticmethod
    def _accelerated_simulation_time(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        cadences = set(facts.supported_decision_cadences)
        missing = []
        if not {30, 60}.issubset(cadences):
            missing.append("30_and_60_minute_cadences")
        if not facts.accelerated_simulation_time:
            missing.append("accelerated_simulation_time")
        if not facts.next_node_activation:
            missing.append("next_node_order_activation")
        return V1AcceptanceCheck(
            check_id="accelerated_simulation_time",
            title="Accelerated 30/60-minute simulation-time execution",
            passed=not missing,
            evidence=(
                "30/60-minute scheduling and next-node activation are enforced"
                if not missing
                else "Simulation-time execution support is incomplete"
            ),
            missing=tuple(missing),
        )

    @staticmethod
    def _formal_campaign_layers(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        completed = set(facts.completed_campaign_layers)
        missing = tuple(sorted(_REQUIRED_CAMPAIGN_LAYERS - completed))
        if facts.campaign_type != "formal_diagnostic_campaign":
            missing += ("formal_diagnostic_campaign",)
        if facts.campaign_status != "completed":
            missing += ("completed_campaign",)
        return V1AcceptanceCheck(
            check_id="formal_campaign_layers",
            title="Completed baseline, isolated and compound campaign layers",
            passed=not missing,
            evidence=(
                "All three Formal Diagnostic Campaign layers completed"
                if not missing
                else "Formal Diagnostic Campaign coverage is incomplete"
            ),
            missing=missing,
        )

    @staticmethod
    def _isolated_immutable_replicas(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        counts = dict(facts.isolated_cases_by_family)
        missing = tuple(
            f"{family}:2"
            for family in V1_TRANSFORMATION_FAMILIES
            if counts.get(family) != 2
        )
        if not facts.isolated_replicas_share_immutable_inputs:
            missing += ("shared_immutable_path_and_random_sources",)
        return V1AcceptanceCheck(
            check_id="isolated_immutable_replicas",
            title="Isolated replicas share immutable path and random sources",
            passed=not missing,
            evidence=(
                "Two cases per family share the accepted immutable inputs"
                if not missing
                else "Isolated sensitivity comparability is incomplete"
            ),
            missing=missing,
        )

    @staticmethod
    def _guided_ui_evidence(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        missing = list(
            sorted(_REQUIRED_GUIDED_UI_STEPS - set(facts.guided_ui_steps))
        )
        missing.extend(
            sorted(
                _REQUIRED_PROVENANCE_SECTIONS
                - set(facts.provenance_sections)
            )
        )
        missing.extend(
            sorted(_REQUIRED_CURVE_OVERLAYS - set(facts.curve_overlays))
        )
        if facts.evidence_status != "sealed":
            missing.append("sealed_evidence")
        if facts.diagnostic_finding_count <= 0:
            missing.append("diagnostic_findings")
        return V1AcceptanceCheck(
            check_id="guided_ui_evidence",
            title="Guided UI workflow, overlays, evidence and provenance",
            passed=not missing,
            evidence=(
                "The guided workspace exposes the complete evidence chain"
                if not missing
                else "The guided workspace evidence chain is incomplete"
            ),
            missing=tuple(missing),
        )

    @staticmethod
    def _deterministic_reproduction(
        facts: V1AcceptanceFacts,
    ) -> V1AcceptanceCheck:
        missing = []
        if facts.accepted_manifest_count != 28:
            missing.append("28_accepted_run_manifests")
        if facts.reproduction_status not in (
            _SUCCESSFUL_REPRODUCTION_STATUSES
        ):
            missing.append("exact_or_tolerance_reproduction")
        return V1AcceptanceCheck(
            check_id="deterministic_reproduction",
            title="Accepted run reproduction is exact or within tolerance",
            passed=not missing,
            evidence=(
                "All accepted runs have manifests and one replay is verified"
                if not missing
                else "Accepted-run reproduction proof is incomplete"
            ),
            missing=tuple(missing),
        )
