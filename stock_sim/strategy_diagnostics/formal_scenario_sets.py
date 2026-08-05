from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Literal, Mapping, cast

from .execution_conditions import ResolvedExecutionConditions
from .formal_diagnostic_campaigns import (
    CampaignTransformation,
    DiagnosticCampaignCase,
)
from .isolated_sensitivity_sets import (
    ISOLATED_SENSITIVITY_FAMILIES,
    MAX_CASES_PER_SENSITIVITY_FAMILY,
    MIN_CASES_PER_SENSITIVITY_FAMILY,
)


FormalScenarioSetEligibility = Literal[
    "formal_campaign_eligible",
    "quick_experiment_only",
]
ScenarioExecutionResolutionState = Literal[
    "resolved",
    "not_yet_resolved",
    "incompatible",
    "unavailable",
]
ScenarioSelectionContextStatus = Literal[
    "current",
    "stale",
    "conflict",
    "unavailable",
]


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class FormalScenarioComparison:
    kind: str
    subject_case_id: str
    control_case_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "subject_case_id": self.subject_case_id,
            "control_case_ids": list(self.control_case_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FormalScenarioComparison":
        return cls(
            kind=str(payload["kind"]),
            subject_case_id=str(payload["subject_case_id"]),
            control_case_ids=tuple(
                str(item) for item in cast(list[object], payload["control_case_ids"])
            ),
        )


@dataclass(frozen=True, slots=True)
class FormalScenarioSetRecord:
    scenario_set_id: str
    eligibility: FormalScenarioSetEligibility
    baseline_case: DiagnosticCampaignCase
    isolated_cases: tuple[DiagnosticCampaignCase, ...]
    compound_cases: tuple[DiagnosticCampaignCase, ...]
    comparison_relationships: tuple[FormalScenarioComparison, ...]
    missing_requirements: tuple[str, ...]
    projection_revision: int = 1

    @property
    def case_ids(self) -> tuple[str, ...]:
        return (
            self.baseline_case.case_id,
            *(item.case_id for item in self.isolated_cases),
            *(item.case_id for item in self.compound_cases),
        )

    @property
    def formal_handoff_eligible(self) -> bool:
        return self.eligibility == "formal_campaign_eligible"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "formal-scenario-set.v1",
            "scenario_set_id": self.scenario_set_id,
            "eligibility": self.eligibility,
            "baseline_case": self.baseline_case.to_dict(),
            "isolated_cases": [item.to_dict() for item in self.isolated_cases],
            "compound_cases": [item.to_dict() for item in self.compound_cases],
            "comparison_relationships": [
                item.to_dict() for item in self.comparison_relationships
            ],
            "missing_requirements": list(self.missing_requirements),
            "projection_revision": self.projection_revision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FormalScenarioSetRecord":
        if payload.get("schema_version") != "formal-scenario-set.v1":
            raise ValueError("Unsupported Formal Scenario Set schema version")
        eligibility = str(payload["eligibility"])
        if eligibility not in (
            "formal_campaign_eligible",
            "quick_experiment_only",
        ):
            raise ValueError("Unsupported Formal Scenario Set eligibility")
        return cls(
            scenario_set_id=str(payload["scenario_set_id"]),
            eligibility=cast(FormalScenarioSetEligibility, eligibility),
            baseline_case=DiagnosticCampaignCase.from_dict(
                cast(Mapping[str, object], payload["baseline_case"])
            ),
            isolated_cases=tuple(
                DiagnosticCampaignCase.from_dict(cast(Mapping[str, object], item))
                for item in cast(list[object], payload["isolated_cases"])
            ),
            compound_cases=tuple(
                DiagnosticCampaignCase.from_dict(cast(Mapping[str, object], item))
                for item in cast(list[object], payload["compound_cases"])
            ),
            comparison_relationships=tuple(
                FormalScenarioComparison.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in cast(
                    list[object], payload["comparison_relationships"]
                )
            ),
            missing_requirements=tuple(
                str(item)
                for item in cast(list[object], payload["missing_requirements"])
            ),
            projection_revision=int(str(payload.get("projection_revision", 1))),
        )


def compose_formal_scenario_set(
    *,
    baseline_case: DiagnosticCampaignCase,
    isolated_cases: tuple[DiagnosticCampaignCase, ...],
    compound_cases: tuple[DiagnosticCampaignCase, ...],
    authoritative_cases: tuple[DiagnosticCampaignCase, ...],
    projection_revision: int = 1,
) -> FormalScenarioSetRecord:
    if projection_revision < 1:
        raise ValueError("Formal Scenario Set projection revision must be positive")
    if baseline_case.layer != "baseline":
        raise ValueError("Baseline Scenario Set requires one untransformed case")
    if any(item.layer != "isolated" for item in isolated_cases):
        raise ValueError(
            "Isolated Sensitivity cases require exactly one transformation family"
        )
    if any(item.layer != "compound" for item in compound_cases):
        raise ValueError(
            "Compound Scenario Set requires multiple transformation families"
        )
    cases = (baseline_case, *isolated_cases, *compound_cases)
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Formal Scenario Set cases must be unique")
    _validate_comparable_cases(cases)
    authoritative_by_id = {
        item.case_id: item for item in authoritative_cases
    }
    if len(authoritative_by_id) != len(authoritative_cases):
        raise ValueError("Authoritative Campaign Case identities must be unique")
    if any(authoritative_by_id.get(item.case_id) != item for item in cases):
        raise ValueError(
            "Formal Scenario Set selections must remain authoritative"
        )
    selected_families = tuple(
        item.transformations[0].transformation_family
        for item in isolated_cases
    )
    unexpected_families = tuple(
        sorted(
            set(selected_families) - set(ISOLATED_SENSITIVITY_FAMILIES)
        )
    )
    if unexpected_families:
        raise ValueError(
            "Isolated Sensitivity case uses an unsupported transformation "
            f"family: {unexpected_families!r}"
        )

    comparable_authority = tuple(
        item
        for item in authoritative_cases
        if _cases_are_comparable(baseline_case, item)
    )
    authoritative_isolated = tuple(
        item for item in comparable_authority if item.layer == "isolated"
    )
    authoritative_compounds = tuple(
        item for item in comparable_authority if item.layer == "compound"
    )
    if any(
        item.transformations[0].transformation_family
        not in ISOLATED_SENSITIVITY_FAMILIES
        for item in authoritative_isolated
    ):
        raise ValueError(
            "Authoritative Isolated Sensitivity inventory contains an "
            "unsupported transformation family"
        )

    isolated_by_family = {
        family: tuple(
            item
            for item in isolated_cases
            if item.transformations[0].transformation_family == family
        )
        for family in ISOLATED_SENSITIVITY_FAMILIES
    }
    selected_isolated_slots = tuple(
        _isolated_scenario_slot(item) for item in isolated_cases
    )
    authoritative_isolated_slots = {
        _isolated_scenario_slot(item) for item in authoritative_isolated
    }
    complete_isolated = all(
        MIN_CASES_PER_SENSITIVITY_FAMILY
        <= len(family_cases)
        <= MAX_CASES_PER_SENSITIVITY_FAMILY
        and len(
            {
                item.transformations[0].transformation_parameters
                for item in family_cases
            }
        )
        == len(family_cases)
        and len(
            {
                (
                    item.transformations[0].transformation_id,
                    item.transformations[0].transformation_implementation_version,
                )
                for item in family_cases
            }
        )
        == 1
        for family_cases in isolated_by_family.values()
    ) and (
        len(selected_isolated_slots) == len(set(selected_isolated_slots))
        and set(selected_isolated_slots) == authoritative_isolated_slots
    )
    missing: list[str] = []
    if not complete_isolated:
        missing.append("complete isolated sensitivity sweep")
    selected_compound_slots = tuple(
        _compound_scenario_slot(item) for item in compound_cases
    )
    authoritative_compound_slots = {
        _compound_scenario_slot(item) for item in authoritative_compounds
    }
    if (
        not compound_cases
        or len(selected_compound_slots) != len(set(selected_compound_slots))
        or set(selected_compound_slots) != authoritative_compound_slots
    ):
        missing.append("declared compound scenario set")
    eligibility: FormalScenarioSetEligibility = (
        "formal_campaign_eligible" if not missing else "quick_experiment_only"
    )
    relationships = tuple(
        FormalScenarioComparison(
            kind="isolated-vs-baseline",
            subject_case_id=item.case_id,
            control_case_ids=(baseline_case.case_id,),
        )
        for item in isolated_cases
    ) + tuple(
        FormalScenarioComparison(
            kind="compound-vs-baseline-and-isolated",
            subject_case_id=item.case_id,
            control_case_ids=(
                baseline_case.case_id,
                *(
                    isolated.case_id
                    for isolated in isolated_cases
                    if isolated.transformations[0].transformation_family
                    in {
                        transform.transformation_family
                        for transform in item.transformations
                    }
                ),
            ),
        )
        for item in compound_cases
    )
    identity_payload = {
        "eligibility": eligibility,
        "cases": [item.to_dict() for item in cases],
        "comparisons": [item.to_dict() for item in relationships],
        "missing_requirements": missing,
    }
    return FormalScenarioSetRecord(
        scenario_set_id=(
            "formal-scenario-set-" + _canonical_hash(identity_payload)[:24]
        ),
        eligibility=eligibility,
        baseline_case=baseline_case,
        isolated_cases=isolated_cases,
        compound_cases=compound_cases,
        comparison_relationships=relationships,
        missing_requirements=tuple(missing),
        projection_revision=projection_revision,
    )


_COMPARABLE_CASE_FIELDS = (
    "historical_segment_id",
    "historical_segment_content_hash",
    "source_snapshot_id",
    "materialization_seed",
    "expander_version",
    "source_resolution",
    "runtime_resolution",
    "numeric_tolerance",
    "normalization_provenance",
    "transformation_catalog_version",
    "market_rule_profile_version",
    "decision_cadence_minutes",
    "requested_execution_conditions",
)


def _isolated_scenario_slot(
    case: DiagnosticCampaignCase,
) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    transformation = case.transformations[0]
    return (
        transformation.transformation_family,
        transformation.transformation_id,
        transformation.transformation_implementation_version,
        transformation.transformation_parameters,
    )


def _compound_scenario_slot(
    case: DiagnosticCampaignCase,
) -> tuple[
    tuple[str, str, str, tuple[tuple[str, str], ...]],
    ...,
]:
    return tuple(
        sorted(
            (
                transformation.transformation_family,
                transformation.transformation_id,
                transformation.transformation_implementation_version,
                transformation.transformation_parameters,
            )
            for transformation in case.transformations
        )
    )


def _cases_are_comparable(
    first: DiagnosticCampaignCase,
    candidate: DiagnosticCampaignCase,
) -> bool:
    return all(
        getattr(candidate, field) == getattr(first, field)
        for field in _COMPARABLE_CASE_FIELDS
    )


def _validate_comparable_cases(
    cases: tuple[DiagnosticCampaignCase, ...],
) -> None:
    first = cases[0]
    for field in _COMPARABLE_CASE_FIELDS:
        expected = getattr(first, field)
        if any(getattr(item, field) != expected for item in cases[1:]):
            raise ValueError(
                "Formal Scenario Set requires comparable pinned inputs; "
                f"{field} differs"
            )


@dataclass(frozen=True, slots=True)
class ScenarioExecutionTargetResolutionRecord:
    strategy_id: str
    strategy_version: str
    compatibility_manifest_hash: str
    guardrail_profile_id: str
    guardrail_profile_version: str
    campaign_case_id: str
    state: ScenarioExecutionResolutionState
    decision_time: datetime | None
    after_decision_time: datetime | None
    activation_time: datetime | None
    decision_cadence_minutes: int
    decision_grid: str
    activation_policy: str
    execution_policy_version: str
    resolved_conditions: ResolvedExecutionConditions | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "compatibility_manifest_hash": self.compatibility_manifest_hash,
            "guardrail_profile_id": self.guardrail_profile_id,
            "guardrail_profile_version": self.guardrail_profile_version,
            "campaign_case_id": self.campaign_case_id,
            "state": self.state,
            "decision_time": (
                None if self.decision_time is None else self.decision_time.isoformat()
            ),
            "after_decision_time": (
                None
                if self.after_decision_time is None
                else self.after_decision_time.isoformat()
            ),
            "activation_time": (
                None if self.activation_time is None else self.activation_time.isoformat()
            ),
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "decision_grid": self.decision_grid,
            "activation_policy": self.activation_policy,
            "execution_policy_version": self.execution_policy_version,
            "resolved_conditions": (
                None
                if self.resolved_conditions is None
                else self.resolved_conditions.to_dict()
            ),
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ScenarioExecutionTargetResolutionRecord":
        state = str(payload["state"])
        if state not in (
            "resolved",
            "not_yet_resolved",
            "incompatible",
            "unavailable",
        ):
            raise ValueError("Unsupported Scenario execution resolution state")
        conditions = payload.get("resolved_conditions")
        return cls(
            strategy_id=str(payload["strategy_id"]),
            strategy_version=str(payload["strategy_version"]),
            compatibility_manifest_hash=str(
                payload["compatibility_manifest_hash"]
            ),
            guardrail_profile_id=str(payload["guardrail_profile_id"]),
            guardrail_profile_version=str(payload["guardrail_profile_version"]),
            campaign_case_id=str(payload["campaign_case_id"]),
            state=cast(ScenarioExecutionResolutionState, state),
            decision_time=_optional_datetime(payload.get("decision_time")),
            after_decision_time=_optional_datetime(
                payload.get("after_decision_time")
            ),
            activation_time=_optional_datetime(payload.get("activation_time")),
            decision_cadence_minutes=int(
                str(payload["decision_cadence_minutes"])
            ),
            decision_grid=str(payload["decision_grid"]),
            activation_policy=str(payload["activation_policy"]),
            execution_policy_version=str(payload["execution_policy_version"]),
            resolved_conditions=(
                None
                if not isinstance(conditions, Mapping)
                else ResolvedExecutionConditions.from_dict(
                    cast(Mapping[str, object], conditions)
                )
            ),
            reasons=tuple(
                str(item) for item in cast(list[object], payload["reasons"])
            ),
        )


@dataclass(frozen=True, slots=True)
class ScenarioExecutionResolutionRecord:
    resolution_id: str
    scenario_set_id: str
    scenario_set_projection_revision: int
    targets: tuple[ScenarioExecutionTargetResolutionRecord, ...]
    formal_handoff_eligible: bool
    projection_revision: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scenario-execution-resolution.v1",
            "resolution_id": self.resolution_id,
            "scenario_set_id": self.scenario_set_id,
            "scenario_set_projection_revision": (
                self.scenario_set_projection_revision
            ),
            "targets": [item.to_dict() for item in self.targets],
            "formal_handoff_eligible": self.formal_handoff_eligible,
            "projection_revision": self.projection_revision,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ScenarioExecutionResolutionRecord":
        if payload.get("schema_version") != "scenario-execution-resolution.v1":
            raise ValueError("Unsupported execution resolution schema version")
        return cls(
            resolution_id=str(payload["resolution_id"]),
            scenario_set_id=str(payload["scenario_set_id"]),
            scenario_set_projection_revision=int(
                str(payload.get("scenario_set_projection_revision", 1))
            ),
            targets=tuple(
                ScenarioExecutionTargetResolutionRecord.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in cast(list[object], payload["targets"])
            ),
            formal_handoff_eligible=bool(payload["formal_handoff_eligible"]),
            projection_revision=int(str(payload.get("projection_revision", 1))),
        )


def scenario_execution_resolution_identity(
    scenario_set_id: str,
    scenario_set_projection_revision: int,
    targets: tuple[ScenarioExecutionTargetResolutionRecord, ...],
) -> str:
    return "scenario-execution-resolution-" + _canonical_hash(
        {
            "scenario_set_id": scenario_set_id,
            "scenario_set_projection_revision": (
                scenario_set_projection_revision
            ),
            "targets": [item.to_dict() for item in targets],
        }
    )[:24]


@dataclass(frozen=True, slots=True)
class ScenarioSelectionCaseBindingRecord:
    campaign_case_id: str
    recipe_version_id: str
    recipe_content_hash: str
    reference_path_id: str
    reference_path_content_hash: str
    historical_segment_id: str
    historical_segment_content_hash: str
    source_snapshot_id: str
    materialization_seed: int
    expander_version: str
    source_resolution: str
    runtime_resolution: str
    numeric_tolerance: str
    normalization_provenance: str
    transformation_catalog_version: str
    transformations: tuple[CampaignTransformation, ...]
    market_rule_profile_version: str
    decision_cadence_minutes: int

    @classmethod
    def from_case(
        cls,
        case: DiagnosticCampaignCase,
    ) -> "ScenarioSelectionCaseBindingRecord":
        return cls(
            campaign_case_id=case.case_id,
            recipe_version_id=case.recipe_version_id,
            recipe_content_hash=case.recipe_content_hash,
            reference_path_id=case.materialization_hash,
            reference_path_content_hash=case.materialization_hash,
            historical_segment_id=case.historical_segment_id,
            historical_segment_content_hash=(
                case.historical_segment_content_hash
            ),
            source_snapshot_id=case.source_snapshot_id,
            materialization_seed=case.materialization_seed,
            expander_version=case.expander_version,
            source_resolution=case.source_resolution,
            runtime_resolution=case.runtime_resolution,
            numeric_tolerance=case.numeric_tolerance,
            normalization_provenance=case.normalization_provenance,
            transformation_catalog_version=(
                case.transformation_catalog_version
            ),
            transformations=case.transformations,
            market_rule_profile_version=case.market_rule_profile_version,
            decision_cadence_minutes=case.decision_cadence_minutes,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_case_id": self.campaign_case_id,
            "recipe_version_id": self.recipe_version_id,
            "recipe_content_hash": self.recipe_content_hash,
            "reference_path_id": self.reference_path_id,
            "reference_path_content_hash": self.reference_path_content_hash,
            "historical_segment_id": self.historical_segment_id,
            "historical_segment_content_hash": (
                self.historical_segment_content_hash
            ),
            "source_snapshot_id": self.source_snapshot_id,
            "materialization_seed": self.materialization_seed,
            "expander_version": self.expander_version,
            "source_resolution": self.source_resolution,
            "runtime_resolution": self.runtime_resolution,
            "numeric_tolerance": self.numeric_tolerance,
            "normalization_provenance": self.normalization_provenance,
            "transformation_catalog_version": (
                self.transformation_catalog_version
            ),
            "transformations": [
                item.to_dict() for item in self.transformations
            ],
            "market_rule_profile_version": self.market_rule_profile_version,
            "decision_cadence_minutes": self.decision_cadence_minutes,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ScenarioSelectionCaseBindingRecord":
        return cls(
            campaign_case_id=str(payload["campaign_case_id"]),
            recipe_version_id=str(payload["recipe_version_id"]),
            recipe_content_hash=str(payload["recipe_content_hash"]),
            reference_path_id=str(payload["reference_path_id"]),
            reference_path_content_hash=str(
                payload["reference_path_content_hash"]
            ),
            historical_segment_id=str(payload["historical_segment_id"]),
            historical_segment_content_hash=str(
                payload["historical_segment_content_hash"]
            ),
            source_snapshot_id=str(payload["source_snapshot_id"]),
            materialization_seed=int(str(payload["materialization_seed"])),
            expander_version=str(payload["expander_version"]),
            source_resolution=str(payload["source_resolution"]),
            runtime_resolution=str(payload["runtime_resolution"]),
            numeric_tolerance=str(payload["numeric_tolerance"]),
            normalization_provenance=str(
                payload["normalization_provenance"]
            ),
            transformation_catalog_version=str(
                payload["transformation_catalog_version"]
            ),
            transformations=tuple(
                CampaignTransformation.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in cast(list[object], payload["transformations"])
            ),
            market_rule_profile_version=str(
                payload["market_rule_profile_version"]
            ),
            decision_cadence_minutes=int(
                str(payload["decision_cadence_minutes"])
            ),
        )


@dataclass(frozen=True, slots=True)
class ScenarioSelectionStrategyBindingRecord:
    strategy_id: str
    strategy_version: str
    compatibility_manifest_hash: str
    guardrail_profile_id: str
    guardrail_profile_version: str
    execution_policy_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "compatibility_manifest_hash": self.compatibility_manifest_hash,
            "guardrail_profile_id": self.guardrail_profile_id,
            "guardrail_profile_version": self.guardrail_profile_version,
            "execution_policy_version": self.execution_policy_version,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ScenarioSelectionStrategyBindingRecord":
        return cls(
            strategy_id=str(payload["strategy_id"]),
            strategy_version=str(payload["strategy_version"]),
            compatibility_manifest_hash=str(
                payload["compatibility_manifest_hash"]
            ),
            guardrail_profile_id=str(payload["guardrail_profile_id"]),
            guardrail_profile_version=str(
                payload["guardrail_profile_version"]
            ),
            execution_policy_version=str(
                payload["execution_policy_version"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ScenarioSelectionContextRecord:
    selection_context_id: str
    scenario_set_id: str
    scenario_set_projection_revision: int
    case_ids: tuple[str, ...]
    case_bindings: tuple[ScenarioSelectionCaseBindingRecord, ...]
    strategy_bindings: tuple[ScenarioSelectionStrategyBindingRecord, ...]
    execution_resolution_id: str
    execution_resolution_projection_revision: int
    status: ScenarioSelectionContextStatus
    selection_revision: int
    originating_view_revision: int
    source_revision: str
    source_generation: int
    formal_handoff_eligible: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scenario-selection-context.v1",
            "selection_context_id": self.selection_context_id,
            "scenario_set_id": self.scenario_set_id,
            "scenario_set_projection_revision": (
                self.scenario_set_projection_revision
            ),
            "case_ids": list(self.case_ids),
            "case_bindings": [
                item.to_dict() for item in self.case_bindings
            ],
            "strategy_bindings": [
                item.to_dict() for item in self.strategy_bindings
            ],
            "execution_resolution_id": self.execution_resolution_id,
            "execution_resolution_projection_revision": (
                self.execution_resolution_projection_revision
            ),
            "status": self.status,
            "selection_revision": self.selection_revision,
            "originating_view_revision": self.originating_view_revision,
            "source_revision": self.source_revision,
            "source_generation": self.source_generation,
            "formal_handoff_eligible": self.formal_handoff_eligible,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ScenarioSelectionContextRecord":
        if payload.get("schema_version") != "scenario-selection-context.v1":
            raise ValueError("Unsupported selection context schema version")
        status = str(payload["status"])
        if status not in ("current", "stale", "conflict", "unavailable"):
            raise ValueError("Unsupported Scenario selection context status")
        return cls(
            selection_context_id=str(payload["selection_context_id"]),
            scenario_set_id=str(payload["scenario_set_id"]),
            scenario_set_projection_revision=int(
                str(payload.get("scenario_set_projection_revision", 1))
            ),
            case_ids=tuple(
                str(item) for item in cast(list[object], payload["case_ids"])
            ),
            case_bindings=tuple(
                ScenarioSelectionCaseBindingRecord.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in cast(list[object], payload["case_bindings"])
            ),
            strategy_bindings=tuple(
                ScenarioSelectionStrategyBindingRecord.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in cast(list[object], payload["strategy_bindings"])
            ),
            execution_resolution_id=str(payload["execution_resolution_id"]),
            execution_resolution_projection_revision=int(
                str(
                    payload.get(
                        "execution_resolution_projection_revision",
                        1,
                    )
                )
            ),
            status=cast(ScenarioSelectionContextStatus, status),
            selection_revision=int(str(payload["selection_revision"])),
            originating_view_revision=int(
                str(payload["originating_view_revision"])
            ),
            source_revision=str(payload["source_revision"]),
            source_generation=int(str(payload["source_generation"])),
            formal_handoff_eligible=bool(payload["formal_handoff_eligible"]),
        )


def create_scenario_selection_context(
    *,
    scenario_set: FormalScenarioSetRecord,
    execution_resolution: ScenarioExecutionResolutionRecord,
    case_ids: tuple[str, ...],
    originating_view_revision: int,
    source_revision: str,
    source_generation: int,
    selection_revision: int,
) -> ScenarioSelectionContextRecord:
    if not scenario_set.formal_handoff_eligible:
        raise ValueError("Quick Experiment is ineligible for formal handoff")
    if not execution_resolution.formal_handoff_eligible:
        raise ValueError("Execution assumptions are not fully resolved")
    if execution_resolution.scenario_set_id != scenario_set.scenario_set_id:
        raise ValueError("Execution resolution does not belong to Scenario Set")
    if (
        execution_resolution.scenario_set_projection_revision
        != scenario_set.projection_revision
    ):
        raise ValueError(
            "Execution resolution belongs to a stale Scenario Set projection"
        )
    if case_ids != scenario_set.case_ids:
        raise ValueError("Formal selection must bind every exact Scenario Set case")
    cases = (
        scenario_set.baseline_case,
        *scenario_set.isolated_cases,
        *scenario_set.compound_cases,
    )
    case_bindings = tuple(
        ScenarioSelectionCaseBindingRecord.from_case(item) for item in cases
    )
    target_keys = tuple(
        (item.strategy_id, item.campaign_case_id)
        for item in execution_resolution.targets
    )
    if len(target_keys) != len(set(target_keys)):
        raise ValueError("Execution resolution targets must be unique")
    strategies: dict[str, ScenarioSelectionStrategyBindingRecord] = {}
    for target in execution_resolution.targets:
        binding = ScenarioSelectionStrategyBindingRecord(
            strategy_id=target.strategy_id,
            strategy_version=target.strategy_version,
            compatibility_manifest_hash=(
                target.compatibility_manifest_hash
            ),
            guardrail_profile_id=target.guardrail_profile_id,
            guardrail_profile_version=target.guardrail_profile_version,
            execution_policy_version=target.execution_policy_version,
        )
        predecessor = strategies.setdefault(target.strategy_id, binding)
        if predecessor != binding:
            raise ValueError(
                "Execution resolution strategy bindings are inconsistent"
            )
    expected_target_keys = {
        (strategy_id, case_id)
        for strategy_id in strategies
        for case_id in case_ids
    }
    if set(target_keys) != expected_target_keys:
        raise ValueError(
            "Execution resolution does not bind every exact Strategy/Case target"
        )
    strategy_bindings = tuple(
        strategies[identity] for identity in sorted(strategies)
    )
    identity_payload = {
        "scenario_set_id": scenario_set.scenario_set_id,
        "scenario_set_projection_revision": (
            scenario_set.projection_revision
        ),
        "case_ids": list(case_ids),
        "case_bindings": [item.to_dict() for item in case_bindings],
        "strategy_bindings": [
            item.to_dict() for item in strategy_bindings
        ],
        "execution_resolution_id": execution_resolution.resolution_id,
        "execution_resolution_projection_revision": (
            execution_resolution.projection_revision
        ),
        "originating_view_revision": originating_view_revision,
        "source_revision": source_revision,
        "source_generation": source_generation,
        "selection_revision": selection_revision,
    }
    return ScenarioSelectionContextRecord(
        selection_context_id=(
            "scenario-selection-context-"
            + _canonical_hash(identity_payload)[:24]
        ),
        scenario_set_id=scenario_set.scenario_set_id,
        scenario_set_projection_revision=scenario_set.projection_revision,
        case_ids=case_ids,
        case_bindings=case_bindings,
        strategy_bindings=strategy_bindings,
        execution_resolution_id=execution_resolution.resolution_id,
        execution_resolution_projection_revision=(
            execution_resolution.projection_revision
        ),
        status="current",
        selection_revision=selection_revision,
        originating_view_revision=originating_view_revision,
        source_revision=source_revision,
        source_generation=source_generation,
        formal_handoff_eligible=True,
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


__all__ = [
    "FormalScenarioComparison",
    "FormalScenarioSetEligibility",
    "FormalScenarioSetRecord",
    "ScenarioExecutionResolutionRecord",
    "ScenarioExecutionResolutionState",
    "ScenarioExecutionTargetResolutionRecord",
    "ScenarioSelectionCaseBindingRecord",
    "ScenarioSelectionContextRecord",
    "ScenarioSelectionContextStatus",
    "ScenarioSelectionStrategyBindingRecord",
    "compose_formal_scenario_set",
    "create_scenario_selection_context",
    "scenario_execution_resolution_identity",
]
