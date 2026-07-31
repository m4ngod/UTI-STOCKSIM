"""Versioned three-layer diagnostic campaign composition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Literal, Mapping, Protocol, TypeAlias, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .execution_conditions import RequestedExecutionAssumptions
from .isolated_sensitivity_sets import (
    IsolatedSensitivitySetSpecification,
    SensitivityCampaignCase,
)

DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION = "diagnostic-campaign.v1"
DiagnosticCampaignType = Literal[
    "formal_diagnostic_campaign",
    "quick_experiment",
]
DiagnosticCampaignLayer = Literal["baseline", "isolated", "compound"]
DiagnosticCampaignExecutionLayer = Literal[
    "baseline",
    "isolated_sensitivity",
    "compound",
]
DiagnosticCampaignStatus = Literal[
    "planned",
    "partial",
    "completed",
    "incomplete",
]
DiagnosticCampaignCaseStatus = Literal["planned", "completed", "incomplete"]


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


@dataclass(frozen=True, slots=True)
class CampaignTransformation:
    transformation_id: str
    transformation_family: str
    transformation_implementation_version: str
    transformation_parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.transformation_id,
                self.transformation_family,
                self.transformation_implementation_version,
            )
        ):
            raise ValueError("Campaign Transformation identities must not be blank")
        if not self.transformation_parameters:
            raise ValueError("Campaign Transformation parameters must not be empty")
        names = tuple(name for name, _ in self.transformation_parameters)
        if any(not name.strip() for name in names):
            raise ValueError("Campaign Transformation parameter names must not be blank")
        if len(set(names)) != len(names):
            raise ValueError("Campaign Transformation parameter names must be unique")
        if self.transformation_parameters != tuple(
            sorted(self.transformation_parameters)
        ):
            raise ValueError("Campaign Transformation parameters must be canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "transformation_id": self.transformation_id,
            "transformation_family": self.transformation_family,
            "transformation_implementation_version": (
                self.transformation_implementation_version
            ),
            "transformation_parameters": dict(self.transformation_parameters),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "CampaignTransformation":
        parameters = cast(
            Mapping[str, object],
            payload["transformation_parameters"],
        )
        return cls(
            transformation_id=str(payload["transformation_id"]),
            transformation_family=str(payload["transformation_family"]),
            transformation_implementation_version=str(
                payload["transformation_implementation_version"]
            ),
            transformation_parameters=tuple(
                sorted(
                    (str(name), str(value))
                    for name, value in parameters.items()
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCase:
    """One immutable baseline, isolated, or compound scenario condition."""

    recipe_version_id: str
    recipe_content_hash: str
    materialization_hash: str
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
    requested_execution_conditions: RequestedExecutionAssumptions

    def __post_init__(self) -> None:
        text_fields = (
            self.recipe_version_id,
            self.recipe_content_hash,
            self.materialization_hash,
            self.historical_segment_id,
            self.historical_segment_content_hash,
            self.source_snapshot_id,
            self.expander_version,
            self.source_resolution,
            self.runtime_resolution,
            self.numeric_tolerance,
            self.normalization_provenance,
            self.transformation_catalog_version,
            self.market_rule_profile_version,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("Diagnostic Campaign Case identities must not be blank")
        if self.materialization_seed < 0:
            raise ValueError("materialization seed must not be negative")
        if self.decision_cadence_minutes <= 0:
            raise ValueError("decision cadence must be positive")
        transformation_ids = tuple(
            item.transformation_id for item in self.transformations
        )
        transformation_families = tuple(
            item.transformation_family for item in self.transformations
        )
        if len(set(transformation_ids)) != len(transformation_ids):
            raise ValueError(
                "Diagnostic Campaign Case transformations must be unique"
            )
        if len(set(transformation_families)) != len(transformation_families):
            raise ValueError(
                "Diagnostic Campaign Case transformation families must be unique"
            )
        if self.transformations != tuple(
            sorted(
                self.transformations,
                key=lambda item: (
                    item.transformation_family,
                    item.transformation_id,
                ),
            )
        ):
            raise ValueError(
                "Diagnostic Campaign Case transformations must be canonical"
            )

    @property
    def layer(self) -> DiagnosticCampaignLayer:
        if not self.transformations:
            return "baseline"
        if len(self.transformations) == 1:
            return "isolated"
        return "compound"

    @property
    def case_id(self) -> str:
        return f"campaign-case-{_canonical_hash(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_version_id": self.recipe_version_id,
            "recipe_content_hash": self.recipe_content_hash,
            "materialization_hash": self.materialization_hash,
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
            "requested_execution_conditions": (
                self.requested_execution_conditions.to_dict()
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticCampaignCase":
        transformations = cast(list[object], payload["transformations"])
        requested = cast(
            Mapping[str, object],
            payload["requested_execution_conditions"],
        )
        return cls(
            recipe_version_id=str(payload["recipe_version_id"]),
            recipe_content_hash=str(payload["recipe_content_hash"]),
            materialization_hash=str(payload["materialization_hash"]),
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
                for item in transformations
            ),
            market_rule_profile_version=str(
                payload["market_rule_profile_version"]
            ),
            decision_cadence_minutes=int(
                str(payload["decision_cadence_minutes"])
            ),
            requested_execution_conditions=(
                RequestedExecutionAssumptions.from_dict(requested)
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignStrategySelection:
    """One exact approved Strategy and guardrail profile for a Campaign."""

    strategy_id: str
    strategy_version: str
    compatibility_manifest_hash: str
    guardrail_profile_id: str
    guardrail_profile_version: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.strategy_id,
                self.strategy_version,
                self.compatibility_manifest_hash,
                self.guardrail_profile_id,
                self.guardrail_profile_version,
            )
        ):
            raise ValueError(
                "Diagnostic Campaign Strategy identities must not be blank"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "compatibility_manifest_hash": self.compatibility_manifest_hash,
            "guardrail_profile_id": self.guardrail_profile_id,
            "guardrail_profile_version": self.guardrail_profile_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticCampaignStrategySelection":
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
        )


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignSpecification:
    """Complete formal selection or explicitly non-attributive experiment."""

    campaign_replica_id: str
    baseline_case: DiagnosticCampaignCase | None
    isolated_sensitivity_set: IsolatedSensitivitySetSpecification | None
    compound_cases: tuple[DiagnosticCampaignCase, ...]
    initial_cash: Decimal
    order_shares: int
    approved_strategies: tuple[
        DiagnosticCampaignStrategySelection,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not self.campaign_replica_id.strip():
            raise ValueError("campaign replica id must not be blank")
        if self.initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        if self.order_shares <= 0:
            raise ValueError("order shares must be positive")
        if self.approved_strategies:
            if len(self.approved_strategies) != 2:
                raise ValueError(
                    "Formal Campaign execution requires exactly two "
                    "approved Strategies"
                )
            strategy_ids = tuple(
                item.strategy_id for item in self.approved_strategies
            )
            if len(set(strategy_ids)) != len(strategy_ids):
                raise ValueError(
                    "Diagnostic Campaign Strategies must be unique"
                )
        if self.isolated_sensitivity_set is not None:
            if (
                self.initial_cash
                != self.isolated_sensitivity_set.initial_cash
            ):
                raise ValueError(
                    "Diagnostic Campaign initial cash must match its "
                    "Isolated Sensitivity Set"
                )
            if (
                self.order_shares
                != self.isolated_sensitivity_set.order_shares
            ):
                raise ValueError(
                    "Diagnostic Campaign order shares must match its "
                    "Isolated Sensitivity Set"
                )
        if self.baseline_case is not None and self.baseline_case.layer != "baseline":
            raise ValueError("Baseline Scenario Set requires an untransformed case")
        if any(case.layer != "compound" for case in self.compound_cases):
            raise ValueError(
                "Compound Scenario Set requires at least two transformation families "
                "per case"
            )
        case_ids = tuple(case.case_id for case in self.compound_cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Compound Scenario Set case identities must be unique")
        _validate_comparable_inputs(self)

    @property
    def campaign_type(self) -> DiagnosticCampaignType:
        if (
            self.baseline_case is not None
            and self.isolated_sensitivity_set is not None
            and bool(self.compound_cases)
        ):
            return "formal_diagnostic_campaign"
        return "quick_experiment"

    @property
    def campaign_id(self) -> str:
        return f"diagnostic-campaign-{_canonical_hash(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        isolated_cases = (
            self.isolated_sensitivity_set.ordered_cases
            if self.isolated_sensitivity_set is not None
            else ()
        )
        missing_layers: list[str] = []
        if self.baseline_case is None:
            missing_layers.append("baseline")
        if self.isolated_sensitivity_set is None:
            missing_layers.append("isolated_sensitivity")
        if not self.compound_cases:
            missing_layers.append("compound")
        relationships: list[dict[str, object]] = []
        if self.baseline_case is not None:
            relationships.extend(
                {
                    "kind": "isolated-vs-baseline",
                    "subject_case_id": case.case_id,
                    "control_case_ids": [self.baseline_case.case_id],
                }
                for case in isolated_cases
            )
        for compound in self.compound_cases:
            families = {
                item.transformation_family for item in compound.transformations
            }
            controls: list[str] = []
            if self.baseline_case is not None:
                controls.append(self.baseline_case.case_id)
            controls.extend(
                case.case_id
                for case in isolated_cases
                if case.transformation_family in families
            )
            relationships.append(
                {
                    "kind": "compound-vs-baseline-and-isolated",
                    "subject_case_id": compound.case_id,
                    "control_case_ids": controls,
                }
            )
        payload: dict[str, object] = {
            "schema_version": DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION,
            "campaign_replica_id": self.campaign_replica_id,
            "campaign_type": self.campaign_type,
            "formal_attribution": {
                "eligible": not missing_layers,
                "claim_status": (
                    "pending_completion"
                    if not missing_layers
                    else "not_permitted"
                ),
                "missing_layers": missing_layers,
            },
            "execution_order": "sequential",
            "initial_cash": _decimal_text(self.initial_cash),
            "order_shares": self.order_shares,
            "layers": {
                "baseline": {
                    "present": self.baseline_case is not None,
                    "case_count": 1 if self.baseline_case is not None else 0,
                },
                "isolated_sensitivity": {
                    "present": self.isolated_sensitivity_set is not None,
                    "case_count": len(isolated_cases),
                },
                "compound": {
                    "present": bool(self.compound_cases),
                    "case_count": len(self.compound_cases),
                },
            },
            "baseline_case": (
                self.baseline_case.to_dict()
                if self.baseline_case is not None
                else None
            ),
            "isolated_sensitivity_set": (
                self.isolated_sensitivity_set.to_dict()
                if self.isolated_sensitivity_set is not None
                else None
            ),
            "compound_cases": [
                case.to_dict() for case in self.compound_cases
            ],
            "comparison_relationships": relationships,
        }
        if self.approved_strategies:
            payload["approved_strategies"] = [
                item.to_dict()
                for item in sorted(
                    self.approved_strategies,
                    key=lambda candidate: candidate.strategy_id,
                )
            ]
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticCampaignSpecification":
        if payload.get("schema_version") != DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION:
            raise ValueError("Unsupported Diagnostic Campaign schema version")
        baseline_value = payload.get("baseline_case")
        isolated_value = payload.get("isolated_sensitivity_set")
        compound_values = cast(list[object], payload["compound_cases"])
        strategy_values = cast(
            list[object],
            payload.get("approved_strategies", []),
        )
        return cls(
            campaign_replica_id=str(payload["campaign_replica_id"]),
            baseline_case=(
                DiagnosticCampaignCase.from_dict(
                    cast(Mapping[str, object], baseline_value)
                )
                if isinstance(baseline_value, Mapping)
                else None
            ),
            isolated_sensitivity_set=(
                IsolatedSensitivitySetSpecification.from_dict(
                    cast(Mapping[str, object], isolated_value)
                )
                if isinstance(isolated_value, Mapping)
                else None
            ),
            compound_cases=tuple(
                DiagnosticCampaignCase.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in compound_values
            ),
            initial_cash=Decimal(str(payload["initial_cash"])),
            order_shares=int(str(payload["order_shares"])),
            approved_strategies=tuple(
                DiagnosticCampaignStrategySelection.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in strategy_values
            ),
        )


def _validate_comparable_inputs(
    specification: DiagnosticCampaignSpecification,
) -> None:
    cases: list[object] = []
    if specification.baseline_case is not None:
        cases.append(specification.baseline_case)
    if specification.isolated_sensitivity_set is not None:
        cases.extend(specification.isolated_sensitivity_set.ordered_cases)
    cases.extend(specification.compound_cases)
    if not cases:
        raise ValueError("Diagnostic Campaign requires at least one Campaign Case")

    first = cases[0]
    fields = (
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
    for field in fields:
        expected = getattr(first, field)
        if any(getattr(case, field) != expected for case in cases[1:]):
            raise ValueError(
                "Diagnostic Campaign requires comparable pinned inputs; "
                f"{field} differs"
            )


class _CampaignOutcome(Protocol):
    @property
    def campaign_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class _StoredCampaignOutcome:
    payload_json: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "_StoredCampaignOutcome":
        return cls(
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def _payload(self) -> dict[str, object]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Stored campaign outcome must be a JSON object")
        return cast(dict[str, object], payload)

    @property
    def campaign_id(self) -> str:
        return str(self._payload()["campaign_id"])

    @property
    def status(self) -> str:
        return str(self._payload()["status"])

    def to_dict(self) -> dict[str, object]:
        return self._payload()


CampaignCaseSpecification: TypeAlias = (
    DiagnosticCampaignCase | SensitivityCampaignCase
)
DiagnosticCampaignCaseExecutor = Callable[
    [
        DiagnosticCampaignSpecification,
        DiagnosticCampaignExecutionLayer,
        CampaignCaseSpecification,
        int,
        int,
    ],
    _CampaignOutcome,
]


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseAttempt:
    attempt_number: int
    campaign: _CampaignOutcome | None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def status(self) -> Literal["completed", "incomplete"]:
        if self.campaign is not None and self.campaign.status == "completed":
            return "completed"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        payload = (
            dict(self.campaign.to_dict())
            if self.campaign is not None
            else {
                "campaign_id": None,
                "members": [],
                "failure": {
                    "code": self.failure_code,
                    "message": self.failure_message,
                },
            }
        )
        payload["attempt_number"] = self.attempt_number
        payload["status"] = self.status
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticCampaignCaseAttempt":
        attempt_number = int(str(payload["attempt_number"]))
        campaign_id = payload.get("campaign_id")
        if isinstance(campaign_id, str):
            campaign_payload = dict(payload)
            campaign_payload.pop("attempt_number", None)
            return cls(
                attempt_number=attempt_number,
                campaign=_StoredCampaignOutcome.from_dict(campaign_payload),
            )
        failure = payload.get("failure", {})
        failure_mapping = (
            cast(Mapping[str, object], failure)
            if isinstance(failure, Mapping)
            else {}
        )
        return cls(
            attempt_number=attempt_number,
            campaign=None,
            failure_code=(
                str(failure_mapping["code"])
                if failure_mapping.get("code") is not None
                else None
            ),
            failure_message=(
                str(failure_mapping["message"])
                if failure_mapping.get("message") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseSnapshot:
    layer: DiagnosticCampaignExecutionLayer
    specification: CampaignCaseSpecification
    attempts: tuple[DiagnosticCampaignCaseAttempt, ...] = ()

    @property
    def case_id(self) -> str:
        return self.specification.case_id

    @property
    def status(self) -> DiagnosticCampaignCaseStatus:
        if not self.attempts:
            return "planned"
        if self.attempts[-1].status == "completed":
            return "completed"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "layer": self.layer,
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignSnapshot:
    specification: DiagnosticCampaignSpecification
    cases: tuple[DiagnosticCampaignCaseSnapshot, ...]

    @property
    def campaign_id(self) -> str:
        return self.specification.campaign_id

    @property
    def completed_count(self) -> int:
        return sum(case.status == "completed" for case in self.cases)

    @property
    def pending_count(self) -> int:
        return sum(case.status == "planned" for case in self.cases)

    @property
    def incomplete_count(self) -> int:
        return sum(case.status == "incomplete" for case in self.cases)

    @property
    def status(self) -> DiagnosticCampaignStatus:
        if self.completed_count == len(self.cases):
            return "completed"
        attempted = len(self.cases) - self.pending_count
        if attempted == 0:
            return "planned"
        if self.pending_count:
            return "partial"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        specification_view = self.specification.to_dict()
        attribution = dict(
            cast(
                Mapping[str, object],
                specification_view["formal_attribution"],
            )
        )
        if attribution["eligible"]:
            attribution["claim_status"] = (
                "supported" if self.status == "completed" else "pending_completion"
            )
        layers = {
            layer: _layer_progress(self.cases, layer)
            for layer in (
                "baseline",
                "isolated_sensitivity",
                "compound",
            )
        }
        return {
            "schema_version": DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "campaign_replica_id": self.specification.campaign_replica_id,
            "campaign_type": self.specification.campaign_type,
            "status": self.status,
            "execution_order": "sequential",
            "formal_attribution": attribution,
            "comparison_relationships": specification_view[
                "comparison_relationships"
            ],
            "progress": {
                "completed_count": self.completed_count,
                "incomplete_count": self.incomplete_count,
                "pending_count": self.pending_count,
                "total_count": len(self.cases),
            },
            "layers": layers,
            "failures": _campaign_failures(self.cases),
            "compound_case_outcomes": _compound_case_outcomes(self.cases),
            "cases": [case.to_dict() for case in self.cases],
        }

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "schema_version": DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION,
            "specification": self.specification.to_dict(),
            "case_attempts": [
                {
                    "case_id": case.case_id,
                    "attempts": [
                        attempt.to_dict() for attempt in case.attempts
                    ],
                }
                for case in self.cases
            ],
        }

    @classmethod
    def from_storage_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticCampaignSnapshot":
        if payload.get("schema_version") != DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION:
            raise ValueError("Unsupported stored Diagnostic Campaign version")
        specification = DiagnosticCampaignSpecification.from_dict(
            cast(Mapping[str, object], payload["specification"])
        )
        attempts_by_case: dict[
            str,
            tuple[DiagnosticCampaignCaseAttempt, ...],
        ] = {}
        for item_value in cast(list[object], payload["case_attempts"]):
            item = cast(Mapping[str, object], item_value)
            case_id = str(item["case_id"])
            if case_id in attempts_by_case:
                raise ValueError(
                    "Persisted Diagnostic Campaign contains duplicate cases"
                )
            restored_attempts = tuple(
                DiagnosticCampaignCaseAttempt.from_dict(
                    cast(Mapping[str, object], attempt)
                )
                for attempt in cast(list[object], item["attempts"])
            )
            if tuple(
                attempt.attempt_number for attempt in restored_attempts
            ) != tuple(range(1, len(restored_attempts) + 1)):
                raise ValueError(
                    "Persisted Diagnostic Campaign attempts must be contiguous"
                )
            attempts_by_case[case_id] = restored_attempts
        planned_cases = _planned_case_snapshots(specification)
        expected_case_ids = {case.case_id for case in planned_cases}
        if set(attempts_by_case) != expected_case_ids:
            raise ValueError(
                "Persisted Diagnostic Campaign cases do not match its specification"
            )
        return cls(
            specification=specification,
            cases=tuple(
                replace(
                    case,
                    attempts=attempts_by_case[case.case_id],
                )
                for case in planned_cases
            ),
        )


def _planned_case_snapshots(
    specification: DiagnosticCampaignSpecification,
) -> tuple[DiagnosticCampaignCaseSnapshot, ...]:
    cases: list[DiagnosticCampaignCaseSnapshot] = []
    if specification.baseline_case is not None:
        cases.append(
            DiagnosticCampaignCaseSnapshot(
                layer="baseline",
                specification=specification.baseline_case,
            )
        )
    if specification.isolated_sensitivity_set is not None:
        cases.extend(
            DiagnosticCampaignCaseSnapshot(
                layer="isolated_sensitivity",
                specification=case,
            )
            for case in specification.isolated_sensitivity_set.ordered_cases
        )
    cases.extend(
        DiagnosticCampaignCaseSnapshot(
            layer="compound",
            specification=case,
        )
        for case in specification.compound_cases
    )
    return tuple(cases)


def _layer_progress(
    cases: tuple[DiagnosticCampaignCaseSnapshot, ...],
    layer: str,
) -> dict[str, object]:
    selected = tuple(case for case in cases if case.layer == layer)
    completed_count = sum(case.status == "completed" for case in selected)
    incomplete_count = sum(case.status == "incomplete" for case in selected)
    pending_count = sum(case.status == "planned" for case in selected)
    if completed_count == len(selected) and selected:
        status = "completed"
    elif not selected or (not completed_count and not incomplete_count):
        status = "planned"
    elif pending_count:
        status = "partial"
    else:
        status = "incomplete"
    return {
        "status": status,
        "completed_count": completed_count,
        "incomplete_count": incomplete_count,
        "pending_count": pending_count,
        "total_count": len(selected),
    }


def _campaign_failures(
    cases: tuple[DiagnosticCampaignCaseSnapshot, ...],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for case in cases:
        if case.status != "incomplete":
            continue
        attempt = case.attempts[-1]
        attempt_view = attempt.to_dict()
        common: dict[str, object] = {
            "case_id": case.case_id,
            "layer": case.layer,
            "attempt_number": attempt.attempt_number,
        }
        member_failures: list[dict[str, object]] = []
        members = attempt_view.get("members", [])
        if isinstance(members, list):
            for member_value in members:
                if not isinstance(member_value, Mapping):
                    continue
                if member_value.get("status") == "completed":
                    continue
                failure_value = member_value.get("failure", {})
                failure = (
                    failure_value
                    if isinstance(failure_value, Mapping)
                    else {}
                )
                member_failures.append(
                    {
                        **common,
                        "strategy_id": member_value.get("strategy_id"),
                        "run_id": member_value.get("run_id"),
                        "code": (
                            failure.get("code") or "IncompleteStrategyRun"
                        ),
                        "message": (
                            failure.get("message")
                            or "Strategy Run result is incomplete"
                        ),
                    }
                )
        if member_failures:
            failures.extend(member_failures)
            continue
        failure_value = attempt_view.get("failure", {})
        failure = (
            failure_value if isinstance(failure_value, Mapping) else {}
        )
        failures.append(
            {
                **common,
                "code": failure.get("code") or "IncompleteCampaign",
                "message": (
                    failure.get("message")
                    or "Campaign result is incomplete"
                ),
            }
        )
    return failures


def _compound_case_outcomes(
    cases: tuple[DiagnosticCampaignCaseSnapshot, ...],
) -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    for case in cases:
        if case.layer != "compound" or not case.attempts:
            continue
        attempt = case.attempts[-1]
        attempt_view = attempt.to_dict()
        outcomes.append(
            {
                "case_id": case.case_id,
                "status": attempt.status,
                "attempt_number": attempt.attempt_number,
                "campaign_id": attempt_view.get("campaign_id"),
                "members": attempt_view.get("members", []),
            }
        )
    return outcomes


class DiagnosticCampaignRepository(Protocol):
    def add(self, snapshot: DiagnosticCampaignSnapshot) -> None: ...

    def get(self, campaign_id: str) -> DiagnosticCampaignSnapshot | None: ...

    def save(self, snapshot: DiagnosticCampaignSnapshot) -> None: ...


class InMemoryDiagnosticCampaignRepository:
    def __init__(self) -> None:
        self._snapshots: dict[str, DiagnosticCampaignSnapshot] = {}

    def add(self, snapshot: DiagnosticCampaignSnapshot) -> None:
        if snapshot.campaign_id in self._snapshots:
            raise ValueError(
                f"Diagnostic Campaign {snapshot.campaign_id!r} already exists"
            )
        self._snapshots[snapshot.campaign_id] = snapshot

    def get(self, campaign_id: str) -> DiagnosticCampaignSnapshot | None:
        return self._snapshots.get(campaign_id)

    def save(self, snapshot: DiagnosticCampaignSnapshot) -> None:
        if snapshot.campaign_id not in self._snapshots:
            raise KeyError(
                f"Unknown Diagnostic Campaign {snapshot.campaign_id!r}"
            )
        self._snapshots[snapshot.campaign_id] = snapshot


class SqlDiagnosticCampaignRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, snapshot: DiagnosticCampaignSnapshot) -> None:
        row = _campaign_snapshot_row(snapshot)
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT campaign_id FROM diagnostic_campaigns "
                    "WHERE campaign_id = :campaign_id"
                ),
                {"campaign_id": snapshot.campaign_id},
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(
                    f"Diagnostic Campaign {snapshot.campaign_id!r} already exists"
                )
            connection.execute(
                text(
                    "INSERT INTO diagnostic_campaigns ("
                    "campaign_id, campaign_type, status, schema_version, "
                    "specification_json, snapshot_json, updated_at_utc"
                    ") VALUES ("
                    ":campaign_id, :campaign_type, :status, :schema_version, "
                    ":specification_json, :snapshot_json, :updated_at_utc"
                    ")"
                ),
                row,
            )

    def get(self, campaign_id: str) -> DiagnosticCampaignSnapshot | None:
        with self._engine.connect() as connection:
            snapshot_json = connection.execute(
                text(
                    "SELECT snapshot_json FROM diagnostic_campaigns "
                    "WHERE campaign_id = :campaign_id"
                ),
                {"campaign_id": campaign_id},
            ).scalar_one_or_none()
        if snapshot_json is None:
            return None
        payload = json.loads(str(snapshot_json))
        if not isinstance(payload, dict):
            raise ValueError(
                "Persisted Diagnostic Campaign snapshot must be a JSON object"
            )
        snapshot = DiagnosticCampaignSnapshot.from_storage_dict(
            cast(Mapping[str, object], payload)
        )
        if snapshot.campaign_id != campaign_id:
            raise ValueError(
                "Persisted Diagnostic Campaign identity does not match its row"
            )
        return snapshot

    def save(self, snapshot: DiagnosticCampaignSnapshot) -> None:
        row = _campaign_snapshot_row(snapshot)
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE diagnostic_campaigns SET "
                    "campaign_type = :campaign_type, "
                    "status = :status, "
                    "schema_version = :schema_version, "
                    "specification_json = :specification_json, "
                    "snapshot_json = :snapshot_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE campaign_id = :campaign_id"
                ),
                row,
            )
        if result.rowcount != 1:
            raise KeyError(
                f"Unknown Diagnostic Campaign {snapshot.campaign_id!r}"
            )


def _campaign_snapshot_row(
    snapshot: DiagnosticCampaignSnapshot,
) -> dict[str, object]:
    return {
        "campaign_id": snapshot.campaign_id,
        "campaign_type": snapshot.specification.campaign_type,
        "status": snapshot.status,
        "schema_version": DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION,
        "specification_json": json.dumps(
            snapshot.specification.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "snapshot_json": json.dumps(
            snapshot.to_storage_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


class DiagnosticCampaignRunner:
    """Advance every selected Campaign Case in deterministic layer order."""

    def __init__(
        self,
        executor: DiagnosticCampaignCaseExecutor,
        repository: DiagnosticCampaignRepository | None = None,
    ) -> None:
        self._executor = executor
        self._repository = repository or InMemoryDiagnosticCampaignRepository()

    def replace_repository(
        self,
        repository: DiagnosticCampaignRepository,
    ) -> None:
        self._repository = repository

    def plan(
        self,
        specification: DiagnosticCampaignSpecification,
    ) -> DiagnosticCampaignSnapshot:
        campaign_id = specification.campaign_id
        existing = self._repository.get(campaign_id)
        if existing is not None:
            if existing.specification != specification:
                raise ValueError("Diagnostic Campaign identity collision")
            return existing
        snapshot = DiagnosticCampaignSnapshot(
            specification=specification,
            cases=_planned_case_snapshots(specification),
        )
        self._repository.add(snapshot)
        return snapshot

    def get(self, campaign_id: str) -> DiagnosticCampaignSnapshot:
        snapshot = self._repository.get(campaign_id)
        if snapshot is None:
            raise ValueError("Unknown Diagnostic Campaign")
        return snapshot

    def advance(
        self,
        campaign_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        if max_cases <= 0:
            raise ValueError("max cases must be positive")
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(campaign_id)
        pending_ids = [
            case.case_id for case in snapshot.cases if case.status == "planned"
        ][:max_cases]
        for case_id in pending_ids:
            snapshot = self._execute_case(
                snapshot,
                case_id,
                nodes_per_batch=nodes_per_batch,
            )
        return snapshot

    def resume(
        self,
        campaign_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        if max_cases is not None and max_cases <= 0:
            raise ValueError("max cases must be positive")
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(campaign_id)
        if not snapshot.pending_count:
            return snapshot
        return self.advance(
            campaign_id,
            max_cases=(
                snapshot.pending_count if max_cases is None else max_cases
            ),
            nodes_per_batch=nodes_per_batch,
        )

    def retry_case(
        self,
        campaign_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> DiagnosticCampaignSnapshot:
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(campaign_id)
        case = next(
            (item for item in snapshot.cases if item.case_id == case_id),
            None,
        )
        if case is None:
            raise ValueError("Unknown Diagnostic Campaign Case")
        if case.status != "incomplete":
            raise ValueError(
                "Only an incomplete Diagnostic Campaign Case can be retried"
            )
        return self._execute_case(
            snapshot,
            case_id,
            nodes_per_batch=nodes_per_batch,
        )

    def _execute_case(
        self,
        snapshot: DiagnosticCampaignSnapshot,
        case_id: str,
        *,
        nodes_per_batch: int,
    ) -> DiagnosticCampaignSnapshot:
        index = next(
            index
            for index, case in enumerate(snapshot.cases)
            if case.case_id == case_id
        )
        case = snapshot.cases[index]
        attempt_number = len(case.attempts) + 1
        try:
            campaign = self._executor(
                snapshot.specification,
                case.layer,
                case.specification,
                attempt_number,
                nodes_per_batch,
            )
            attempt = DiagnosticCampaignCaseAttempt(
                attempt_number=attempt_number,
                campaign=campaign,
            )
        except Exception as error:
            attempt = DiagnosticCampaignCaseAttempt(
                attempt_number=attempt_number,
                campaign=None,
                failure_code=type(error).__name__,
                failure_message=str(error),
            )
        updated_case = replace(case, attempts=case.attempts + (attempt,))
        cases = list(snapshot.cases)
        cases[index] = updated_case
        updated = replace(snapshot, cases=tuple(cases))
        self._repository.save(updated)
        return updated


__all__ = [
    "DIAGNOSTIC_CAMPAIGN_SCHEMA_VERSION",
    "CampaignTransformation",
    "DiagnosticCampaignCase",
    "DiagnosticCampaignCaseAttempt",
    "DiagnosticCampaignCaseExecutor",
    "DiagnosticCampaignCaseSnapshot",
    "DiagnosticCampaignCaseStatus",
    "DiagnosticCampaignExecutionLayer",
    "DiagnosticCampaignLayer",
    "DiagnosticCampaignRepository",
    "DiagnosticCampaignRunner",
    "DiagnosticCampaignSnapshot",
    "DiagnosticCampaignSpecification",
    "DiagnosticCampaignStatus",
    "DiagnosticCampaignStrategySelection",
    "DiagnosticCampaignType",
    "InMemoryDiagnosticCampaignRepository",
    "SqlDiagnosticCampaignRepository",
]
