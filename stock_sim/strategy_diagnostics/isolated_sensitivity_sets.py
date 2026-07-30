"""Immutable one-family sensitivity cases and resumable sequential execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Callable, Literal, Mapping, Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from .ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTRADE_SUBPROCESS_HOST_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    ptrade_manifest_for,
)
from .strategy_campaigns import (
    RANDOM_SOURCE_VERSION,
    BaselineCampaignSpecification,
)
from .strategy_runs import (
    BASELINE_EXECUTION_POLICY_VERSION,
    StrategyRunSpecification,
)


SensitivitySetStatus = Literal["planned", "partial", "completed", "incomplete"]
SensitivityCaseStatus = Literal["planned", "completed", "incomplete"]

ISOLATED_SENSITIVITY_FAMILIES = (
    "trend-regime",
    "volatility",
    "shock-recovery",
    "market-structure",
    "liquidity",
    "execution-stress",
)
MIN_CASES_PER_SENSITIVITY_FAMILY = 2
MAX_CASES_PER_SENSITIVITY_FAMILY = 12


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
class SensitivityCampaignCase:
    """One approved, materialized, single-family campaign case."""

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
    transformation_id: str
    transformation_family: str
    transformation_implementation_version: str
    transformation_parameters: tuple[tuple[str, str], ...]
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
            self.transformation_id,
            self.transformation_family,
            self.transformation_implementation_version,
            self.market_rule_profile_version,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("Sensitivity Campaign Case identities must not be blank")
        if self.materialization_seed < 0:
            raise ValueError("materialization seed must not be negative")
        if self.decision_cadence_minutes <= 0:
            raise ValueError("decision cadence must be positive")
        if not self.transformation_parameters:
            raise ValueError("Sensitivity Campaign Case parameters must not be empty")
        parameter_names = tuple(name for name, _ in self.transformation_parameters)
        if any(not name.strip() for name in parameter_names):
            raise ValueError("Sensitivity Campaign Case parameter names must not be blank")
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("Sensitivity Campaign Case parameter names must be unique")
        if self.transformation_parameters != tuple(
            sorted(self.transformation_parameters)
        ):
            raise ValueError("Sensitivity Campaign Case parameters must be canonical")

    @property
    def case_id(self) -> str:
        return f"sensitivity-case-{_canonical_hash(self.to_dict())[:24]}"

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
            "transformation_catalog_version": self.transformation_catalog_version,
            "transformation_id": self.transformation_id,
            "transformation_family": self.transformation_family,
            "transformation_implementation_version": (
                self.transformation_implementation_version
            ),
            "transformation_parameters": dict(self.transformation_parameters),
            "market_rule_profile_version": self.market_rule_profile_version,
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "requested_execution_conditions": (
                self.requested_execution_conditions.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SensitivityCampaignCase":
        parameters = cast(Mapping[str, object], payload["transformation_parameters"])
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
            normalization_provenance=str(payload["normalization_provenance"]),
            transformation_catalog_version=str(
                payload["transformation_catalog_version"]
            ),
            transformation_id=str(payload["transformation_id"]),
            transformation_family=str(payload["transformation_family"]),
            transformation_implementation_version=str(
                payload["transformation_implementation_version"]
            ),
            transformation_parameters=tuple(
                sorted((str(name), str(value)) for name, value in parameters.items())
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
class SensitivitySweepDefinition:
    """Reviewed bounded levels for one registered transformation family."""

    transformation_family: str
    transformation_id: str
    transformation_implementation_version: str
    levels: tuple[SensitivityCampaignCase, ...]

    def __post_init__(self) -> None:
        if self.transformation_family not in ISOLATED_SENSITIVITY_FAMILIES:
            raise ValueError(
                f"Unsupported sensitivity sweep family: {self.transformation_family}"
            )
        if not self.transformation_id.strip():
            raise ValueError("Sensitivity sweep transformation id must not be blank")
        if not self.transformation_implementation_version.strip():
            raise ValueError(
                "Sensitivity sweep implementation version must not be blank"
            )
        if len(self.levels) < MIN_CASES_PER_SENSITIVITY_FAMILY:
            raise ValueError(
                f"{self.transformation_family} requires at least "
                f"{MIN_CASES_PER_SENSITIVITY_FAMILY} sweep levels"
            )
        if len(self.levels) > MAX_CASES_PER_SENSITIVITY_FAMILY:
            raise ValueError(
                f"{self.transformation_family} exceeds the bounded maximum of "
                f"{MAX_CASES_PER_SENSITIVITY_FAMILY} sweep levels"
            )
        for level in self.levels:
            if (
                level.transformation_family != self.transformation_family
                or level.transformation_id != self.transformation_id
                or level.transformation_implementation_version
                != self.transformation_implementation_version
            ):
                raise ValueError(
                    "Every sensitivity sweep level must use its declared family, "
                    "transformation, and implementation"
                )
        parameters = tuple(level.transformation_parameters for level in self.levels)
        if len(set(parameters)) != len(parameters):
            raise ValueError(
                f"{self.transformation_family} sweep levels require unique parameters"
            )

    @property
    def ordered_levels(self) -> tuple[SensitivityCampaignCase, ...]:
        return tuple(
            sorted(
                self.levels,
                key=lambda level: (
                    level.transformation_parameters,
                    level.case_id,
                ),
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "transformation_family": self.transformation_family,
            "transformation_id": self.transformation_id,
            "transformation_implementation_version": (
                self.transformation_implementation_version
            ),
            "levels": [level.to_dict() for level in self.ordered_levels],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "SensitivitySweepDefinition":
        levels = cast(list[object], payload["levels"])
        return cls(
            transformation_family=str(payload["transformation_family"]),
            transformation_id=str(payload["transformation_id"]),
            transformation_implementation_version=str(
                payload["transformation_implementation_version"]
            ),
            levels=tuple(
                SensitivityCampaignCase.from_dict(cast(Mapping[str, object], level))
                for level in levels
            ),
        )


@dataclass(frozen=True, slots=True)
class IsolatedSensitivitySetSpecification:
    """A bounded six-family sensitivity plan with fixed comparison controls."""

    sensitivity_set_replica_id: str
    sweeps: tuple[SensitivitySweepDefinition, ...]
    initial_cash: Decimal
    order_shares: int

    def __post_init__(self) -> None:
        if not self.sensitivity_set_replica_id.strip():
            raise ValueError("sensitivity set replica id must not be blank")
        if self.initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        if self.order_shares <= 0:
            raise ValueError("order shares must be positive")
        families = tuple(sweep.transformation_family for sweep in self.sweeps)
        if set(families) != set(ISOLATED_SENSITIVITY_FAMILIES):
            missing = tuple(
                family
                for family in ISOLATED_SENSITIVITY_FAMILIES
                if family not in families
            )
            unexpected = tuple(
                family
                for family in families
                if family not in ISOLATED_SENSITIVITY_FAMILIES
            )
            raise ValueError(
                "Isolated Sensitivity Set requires exactly one sweep for every "
                f"registered family; missing={missing}, unexpected={unexpected}"
            )
        if len(families) != len(set(families)):
            raise ValueError(
                "Isolated Sensitivity Set requires one sweep per family"
            )
        cases = self.cases
        case_ids = tuple(case.case_id for case in cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Sensitivity Campaign Case identities must be unique")
        materialization_hashes = tuple(
            case.materialization_hash for case in cases
        )
        if len(set(materialization_hashes)) != len(materialization_hashes):
            raise ValueError("Sensitivity Campaign Case materializations must be unique")

        first = cases[0]
        comparable_fields: tuple[tuple[str, object], ...] = (
            ("historical segment", first.historical_segment_id),
            ("historical segment content", first.historical_segment_content_hash),
            ("source snapshot", first.source_snapshot_id),
            ("materialization seed", first.materialization_seed),
            ("expander version", first.expander_version),
            ("source resolution", first.source_resolution),
            ("runtime resolution", first.runtime_resolution),
            ("numeric tolerance", first.numeric_tolerance),
            ("normalization provenance", first.normalization_provenance),
            ("transformation catalog", first.transformation_catalog_version),
            ("Market Rule Profile", first.market_rule_profile_version),
            ("decision cadence", first.decision_cadence_minutes),
            (
                "requested execution conditions",
                first.requested_execution_conditions,
            ),
        )
        for label, expected in comparable_fields:
            if any(
                _comparable_case_value(case, label) != expected
                for case in cases[1:]
            ):
                raise ValueError(
                    f"Isolated Sensitivity Set requires the same {label} for every case"
                )

    @property
    def cases(self) -> tuple[SensitivityCampaignCase, ...]:
        """Expand the reviewed bounded sweeps into immutable campaign cases."""

        return tuple(
            level
            for sweep in self.ordered_sweeps
            for level in sweep.ordered_levels
        )

    @property
    def ordered_sweeps(self) -> tuple[SensitivitySweepDefinition, ...]:
        order = {
            family: index for index, family in enumerate(ISOLATED_SENSITIVITY_FAMILIES)
        }
        return tuple(
            sorted(
                self.sweeps,
                key=lambda sweep: order[sweep.transformation_family],
            )
        )

    @property
    def ordered_cases(self) -> tuple[SensitivityCampaignCase, ...]:
        return self.cases

    @property
    def sensitivity_set_id(self) -> str:
        return f"isolated-sensitivity-{_canonical_hash(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        first = self.cases[0]
        return {
            "sensitivity_set_replica_id": self.sensitivity_set_replica_id,
            "initial_cash": _decimal_text(self.initial_cash),
            "order_shares": self.order_shares,
            "execution_order": "sequential",
            "bounded_cases_per_family": {
                "minimum": MIN_CASES_PER_SENSITIVITY_FAMILY,
                "maximum": MAX_CASES_PER_SENSITIVITY_FAMILY,
            },
            "sweeps": [sweep.to_dict() for sweep in self.ordered_sweeps],
            "pinned_comparison_inputs": {
                "historical_segment_id": first.historical_segment_id,
                "historical_segment_content_hash": (
                    first.historical_segment_content_hash
                ),
                "source_snapshot_id": first.source_snapshot_id,
                "materialization_seed": first.materialization_seed,
                "controlled_random_source": RANDOM_SOURCE_VERSION,
                "expander_version": first.expander_version,
                "source_resolution": first.source_resolution,
                "runtime_resolution": first.runtime_resolution,
                "numeric_tolerance": first.numeric_tolerance,
                "normalization_provenance": first.normalization_provenance,
                "transformation_catalog_version": (
                    first.transformation_catalog_version
                ),
                "market_rule_profile_version": first.market_rule_profile_version,
                "decision_cadence_minutes": first.decision_cadence_minutes,
                "requested_execution_conditions": (
                    first.requested_execution_conditions.to_dict()
                ),
            },
            "cases": [case.to_dict() for case in self.ordered_cases],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "IsolatedSensitivitySetSpecification":
        sweeps = cast(list[object], payload["sweeps"])
        return cls(
            sensitivity_set_replica_id=str(
                payload["sensitivity_set_replica_id"]
            ),
            sweeps=tuple(
                SensitivitySweepDefinition.from_dict(
                    cast(Mapping[str, object], sweep)
                )
                for sweep in sweeps
            ),
            initial_cash=Decimal(str(payload["initial_cash"])),
            order_shares=int(str(payload["order_shares"])),
        )


def _comparable_case_value(
    case: SensitivityCampaignCase,
    label: str,
) -> object:
    return {
        "historical segment": case.historical_segment_id,
        "historical segment content": case.historical_segment_content_hash,
        "source snapshot": case.source_snapshot_id,
        "materialization seed": case.materialization_seed,
        "expander version": case.expander_version,
        "source resolution": case.source_resolution,
        "runtime resolution": case.runtime_resolution,
        "numeric tolerance": case.numeric_tolerance,
        "normalization provenance": case.normalization_provenance,
        "transformation catalog": case.transformation_catalog_version,
        "Market Rule Profile": case.market_rule_profile_version,
        "decision cadence": case.decision_cadence_minutes,
        "requested execution conditions": case.requested_execution_conditions,
    }[label]


class _CampaignSnapshot(Protocol):
    @property
    def campaign_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class _StoredCampaignSnapshot:
    payload_json: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "_StoredCampaignSnapshot":
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
            raise ValueError("Stored campaign snapshot must be a JSON object")
        return cast(dict[str, object], payload)

    @property
    def campaign_id(self) -> str:
        return str(self._payload()["campaign_id"])

    @property
    def status(self) -> str:
        return str(self._payload()["status"])

    def to_dict(self) -> dict[str, object]:
        return self._payload()


SensitivityCaseExecutor = Callable[
    [IsolatedSensitivitySetSpecification, SensitivityCampaignCase, int, int],
    _CampaignSnapshot,
]


@dataclass(frozen=True, slots=True)
class SensitivityCaseAttempt:
    attempt_number: int
    campaign: _CampaignSnapshot | None
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
    def from_dict(cls, payload: Mapping[str, object]) -> "SensitivityCaseAttempt":
        attempt_number = int(str(payload["attempt_number"]))
        campaign_id = payload.get("campaign_id")
        if isinstance(campaign_id, str):
            campaign_payload = dict(payload)
            campaign_payload.pop("attempt_number", None)
            campaign = _StoredCampaignSnapshot.from_dict(campaign_payload)
            return cls(attempt_number=attempt_number, campaign=campaign)
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
class SensitivityCaseSnapshot:
    specification: SensitivityCampaignCase
    attempts: tuple[SensitivityCaseAttempt, ...] = ()

    @property
    def case_id(self) -> str:
        return self.specification.case_id

    @property
    def status(self) -> SensitivityCaseStatus:
        if not self.attempts:
            return "planned"
        if self.attempts[-1].status == "completed":
            return "completed"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "family": self.specification.transformation_family,
            "transformation_id": self.specification.transformation_id,
            "parameters": dict(self.specification.transformation_parameters),
            "recipe_version_id": self.specification.recipe_version_id,
            "materialization_hash": self.specification.materialization_hash,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass(frozen=True, slots=True)
class IsolatedSensitivitySetSnapshot:
    specification: IsolatedSensitivitySetSpecification
    cases: tuple[SensitivityCaseSnapshot, ...]

    @property
    def sensitivity_set_id(self) -> str:
        return self.specification.sensitivity_set_id

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
    def status(self) -> SensitivitySetStatus:
        if self.completed_count == len(self.cases):
            return "completed"
        attempted = len(self.cases) - self.pending_count
        if attempted == 0:
            return "planned"
        if self.pending_count:
            return "partial"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        return {
            "sensitivity_set_id": self.sensitivity_set_id,
            "sensitivity_set_replica_id": (
                self.specification.sensitivity_set_replica_id
            ),
            "status": self.status,
            "execution_order": "sequential",
            "completeness": {
                "completed_count": self.completed_count,
                "incomplete_count": self.incomplete_count,
                "pending_count": self.pending_count,
                "total_count": len(self.cases),
                "is_complete": self.status == "completed",
            },
            "pinned_comparison_inputs": self.specification.to_dict()[
                "pinned_comparison_inputs"
            ],
            "cases": [case.to_dict() for case in self.cases],
            "sensitivity_curves": _sensitivity_curves(self.cases),
        }

    def to_storage_dict(self) -> dict[str, object]:
        return {
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
    ) -> "IsolatedSensitivitySetSnapshot":
        specification_payload = cast(
            Mapping[str, object], payload["specification"]
        )
        specification = IsolatedSensitivitySetSpecification.from_dict(
            specification_payload
        )
        attempts_by_case: dict[str, tuple[SensitivityCaseAttempt, ...]] = {}
        case_attempts = cast(list[object], payload["case_attempts"])
        for item_value in case_attempts:
            item = cast(Mapping[str, object], item_value)
            case_id = str(item["case_id"])
            if case_id in attempts_by_case:
                raise ValueError(
                    "Persisted Isolated Sensitivity Set contains duplicate cases"
                )
            attempts = cast(list[object], item["attempts"])
            restored_attempts = tuple(
                SensitivityCaseAttempt.from_dict(
                    cast(Mapping[str, object], attempt)
                )
                for attempt in attempts
            )
            if tuple(
                attempt.attempt_number for attempt in restored_attempts
            ) != tuple(range(1, len(restored_attempts) + 1)):
                raise ValueError(
                    "Persisted sensitivity case attempts must be contiguous"
                )
            attempts_by_case[case_id] = restored_attempts
        expected_case_ids = {case.case_id for case in specification.ordered_cases}
        if set(attempts_by_case) != expected_case_ids:
            raise ValueError(
                "Persisted Isolated Sensitivity Set cases do not match its sweeps"
            )
        snapshot = cls(
            specification=specification,
            cases=tuple(
                SensitivityCaseSnapshot(
                    case,
                    attempts=attempts_by_case[case.case_id],
                )
                for case in specification.ordered_cases
            ),
        )
        for case in snapshot.cases:
            for attempt in case.attempts:
                if attempt.campaign is not None:
                    _validate_campaign_assignment(
                        specification,
                        case.specification,
                        attempt.attempt_number,
                        attempt.campaign,
                    )
        return snapshot


class IsolatedSensitivitySetRepository(Protocol):
    def add(self, snapshot: IsolatedSensitivitySetSnapshot) -> None: ...

    def get(
        self,
        sensitivity_set_id: str,
    ) -> IsolatedSensitivitySetSnapshot | None: ...

    def save(self, snapshot: IsolatedSensitivitySetSnapshot) -> None: ...


class InMemoryIsolatedSensitivitySetRepository:
    def __init__(self) -> None:
        self._snapshots: dict[str, IsolatedSensitivitySetSnapshot] = {}

    def add(self, snapshot: IsolatedSensitivitySetSnapshot) -> None:
        sensitivity_set_id = snapshot.sensitivity_set_id
        if sensitivity_set_id in self._snapshots:
            raise ValueError(
                f"Isolated Sensitivity Set {sensitivity_set_id!r} already exists"
            )
        self._snapshots[sensitivity_set_id] = snapshot

    def get(
        self,
        sensitivity_set_id: str,
    ) -> IsolatedSensitivitySetSnapshot | None:
        return self._snapshots.get(sensitivity_set_id)

    def save(self, snapshot: IsolatedSensitivitySetSnapshot) -> None:
        sensitivity_set_id = snapshot.sensitivity_set_id
        if sensitivity_set_id not in self._snapshots:
            raise KeyError(
                f"Unknown Isolated Sensitivity Set {sensitivity_set_id!r}"
            )
        self._snapshots[sensitivity_set_id] = snapshot


class SqlIsolatedSensitivitySetRepository:
    """Transactional JSON snapshot store for resumable sensitivity sets."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, snapshot: IsolatedSensitivitySetSnapshot) -> None:
        sensitivity_set_id = snapshot.sensitivity_set_id
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT sensitivity_set_id FROM "
                    "diagnostic_isolated_sensitivity_sets "
                    "WHERE sensitivity_set_id = :sensitivity_set_id"
                ),
                {"sensitivity_set_id": sensitivity_set_id},
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(
                    f"Isolated Sensitivity Set {sensitivity_set_id!r} already exists"
                )
            connection.execute(
                text(
                    "INSERT INTO diagnostic_isolated_sensitivity_sets ("
                    "sensitivity_set_id, status, specification_json, "
                    "snapshot_json, updated_at_utc"
                    ") VALUES ("
                    ":sensitivity_set_id, :status, :specification_json, "
                    ":snapshot_json, :updated_at_utc"
                    ")"
                ),
                _sensitivity_snapshot_row(snapshot),
            )

    def get(
        self,
        sensitivity_set_id: str,
    ) -> IsolatedSensitivitySetSnapshot | None:
        with self._engine.connect() as connection:
            snapshot_json = connection.execute(
                text(
                    "SELECT snapshot_json FROM "
                    "diagnostic_isolated_sensitivity_sets "
                    "WHERE sensitivity_set_id = :sensitivity_set_id"
                ),
                {"sensitivity_set_id": sensitivity_set_id},
            ).scalar_one_or_none()
        if snapshot_json is None:
            return None
        payload = json.loads(str(snapshot_json))
        if not isinstance(payload, dict):
            raise ValueError(
                "Persisted Isolated Sensitivity Set snapshot must be a JSON object"
            )
        snapshot = IsolatedSensitivitySetSnapshot.from_storage_dict(
            cast(Mapping[str, object], payload)
        )
        if snapshot.sensitivity_set_id != sensitivity_set_id:
            raise ValueError(
                "Persisted Isolated Sensitivity Set identity does not match its row"
            )
        return snapshot

    def save(self, snapshot: IsolatedSensitivitySetSnapshot) -> None:
        row = _sensitivity_snapshot_row(snapshot)
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE diagnostic_isolated_sensitivity_sets SET "
                    "status = :status, "
                    "specification_json = :specification_json, "
                    "snapshot_json = :snapshot_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE sensitivity_set_id = :sensitivity_set_id"
                ),
                row,
            )
        if result.rowcount != 1:
            raise KeyError(
                f"Unknown Isolated Sensitivity Set "
                f"{snapshot.sensitivity_set_id!r}"
            )


def _sensitivity_snapshot_row(
    snapshot: IsolatedSensitivitySetSnapshot,
) -> dict[str, object]:
    return {
        "sensitivity_set_id": snapshot.sensitivity_set_id,
        "status": snapshot.status,
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


class IsolatedSensitivitySetRunner:
    """Advance immutable cases in order while retaining every attempt."""

    def __init__(
        self,
        executor: SensitivityCaseExecutor,
        repository: IsolatedSensitivitySetRepository | None = None,
    ) -> None:
        self._executor = executor
        self._repository = (
            repository or InMemoryIsolatedSensitivitySetRepository()
        )

    def replace_repository(
        self,
        repository: IsolatedSensitivitySetRepository,
    ) -> None:
        self._repository = repository

    def plan(
        self,
        specification: IsolatedSensitivitySetSpecification,
    ) -> IsolatedSensitivitySetSnapshot:
        sensitivity_set_id = specification.sensitivity_set_id
        existing = self._repository.get(sensitivity_set_id)
        if existing is not None:
            if existing.specification != specification:
                raise ValueError("Sensitivity Set identity collision")
            return existing
        snapshot = IsolatedSensitivitySetSnapshot(
            specification=specification,
            cases=tuple(
                SensitivityCaseSnapshot(case)
                for case in specification.ordered_cases
            ),
        )
        self._repository.add(snapshot)
        return snapshot

    def get(self, sensitivity_set_id: str) -> IsolatedSensitivitySetSnapshot:
        snapshot = self._repository.get(sensitivity_set_id)
        if snapshot is None:
            raise ValueError("Unknown Isolated Sensitivity Set")
        return snapshot

    def advance(
        self,
        sensitivity_set_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        if max_cases <= 0:
            raise ValueError("max cases must be positive")
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(sensitivity_set_id)
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
        sensitivity_set_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        if max_cases is not None and max_cases <= 0:
            raise ValueError("max cases must be positive")
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(sensitivity_set_id)
        pending_count = snapshot.pending_count
        if not pending_count:
            return snapshot
        return self.advance(
            sensitivity_set_id,
            max_cases=pending_count if max_cases is None else max_cases,
            nodes_per_batch=nodes_per_batch,
        )

    def retry_case(
        self,
        sensitivity_set_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> IsolatedSensitivitySetSnapshot:
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        snapshot = self.get(sensitivity_set_id)
        case = next((item for item in snapshot.cases if item.case_id == case_id), None)
        if case is None:
            raise ValueError("Unknown Sensitivity Campaign Case")
        if case.status != "incomplete":
            raise ValueError("Only an incomplete Sensitivity Campaign Case can be retried")
        return self._execute_case(
            snapshot,
            case_id,
            nodes_per_batch=nodes_per_batch,
        )

    def _execute_case(
        self,
        snapshot: IsolatedSensitivitySetSnapshot,
        case_id: str,
        *,
        nodes_per_batch: int,
    ) -> IsolatedSensitivitySetSnapshot:
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
                case.specification,
                attempt_number,
                nodes_per_batch,
            )
            _validate_campaign_assignment(
                snapshot.specification,
                case.specification,
                attempt_number,
                campaign,
            )
            attempt = SensitivityCaseAttempt(
                attempt_number=attempt_number,
                campaign=campaign,
            )
        except Exception as error:
            attempt = SensitivityCaseAttempt(
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


def _validate_campaign_assignment(
    specification: IsolatedSensitivitySetSpecification,
    case: SensitivityCampaignCase,
    attempt_number: int,
    campaign: _CampaignSnapshot,
) -> None:
    view = campaign.to_dict()
    if view.get("status") != campaign.status:
        raise ValueError("Sensitivity case campaign status evidence is inconsistent")
    expected_campaign_replica_id = (
        f"{specification.sensitivity_set_replica_id}:"
        f"{case.case_id}:attempt-{attempt_number}"
    )
    if view.get("campaign_replica_id") != expected_campaign_replica_id:
        raise ValueError(
            "Sensitivity case campaign replica does not match its assigned case"
        )
    members_value = view.get("members")
    if not isinstance(members_value, list) or len(members_value) != 2:
        raise ValueError("Sensitivity case campaign requires both strategy members")
    members = [
        cast(Mapping[str, object], member)
        for member in members_value
        if isinstance(member, Mapping)
    ]
    if len(members) != 2:
        raise ValueError("Sensitivity case campaign members are malformed")
    expected_strategy_order = (
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    )
    if tuple(
        str(member.get("strategy_id")) for member in members
    ) != expected_strategy_order:
        raise ValueError(
            "Sensitivity case campaign members are not in canonical "
            "representative strategy order"
        )
    expected_replica_ids = {
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID: (
            f"{expected_campaign_replica_id}:quentx"
        ),
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID: (
            f"{expected_campaign_replica_id}:live-minute"
        ),
    }
    expected_strategy_versions = {
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID: (
            QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION
        ),
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID: (
            LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION
        ),
    }
    expected_execution_conditions = resolve_execution_conditions(
        case.requested_execution_conditions,
        (
            dict(case.transformation_parameters)
            if case.transformation_family == "execution-stress"
            else {}
        ),
    )
    run_specifications: dict[str, StrategyRunSpecification] = {}
    for member in members:
        member_specification = member.get("specification")
        if not isinstance(member_specification, Mapping):
            raise ValueError(
                "Sensitivity case campaign member specification is missing"
            )
        run_specification = StrategyRunSpecification.from_pinned_dict(
            cast(Mapping[str, object], member_specification)
        )
        strategy_id = str(member.get("strategy_id"))
        strategy_version = expected_strategy_versions[strategy_id]
        expected_replica_id = expected_replica_ids[strategy_id]
        manifest = ptrade_manifest_for(strategy_id, strategy_version)
        expected_run_specification = StrategyRunSpecification(
            recipe_version_id=case.recipe_version_id,
            recipe_content_hash=case.recipe_content_hash,
            materialization_hash=case.materialization_hash,
            source_snapshot_id=case.source_snapshot_id,
            materialization_seed=case.materialization_seed,
            transformation_catalog_version=(
                case.transformation_catalog_version
            ),
            transformation_implementation_versions=(
                f"{case.transformation_id}@"
                f"{case.transformation_implementation_version}",
            ),
            market_rule_profile_version=case.market_rule_profile_version,
            execution_policy_version=BASELINE_EXECUTION_POLICY_VERSION,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            decision_cadence_minutes=case.decision_cadence_minutes,
            initial_cash=specification.initial_cash,
            order_shares=specification.order_shares,
            replica_id=expected_replica_id,
            code_identity="strategy-diagnostics.v1",
            ptrade_surface_version=manifest.surface_version,
            ptrade_manifest_hash=manifest.content_hash,
            ptrade_host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
            commission_bps=(
                expected_execution_conditions.effective.commission_bps
            ),
            resolved_execution_conditions=expected_execution_conditions,
        )
        if (
            run_specification != expected_run_specification
            or run_specification.to_dict() != dict(member_specification)
            or member.get("replica_id") != expected_replica_id
            or member.get("strategy_version")
            != run_specification.strategy_version
            or str(member.get("materialization_hash"))
            != case.materialization_hash
        ):
            raise ValueError(
                "Sensitivity case campaign result belongs to another case"
            )
        if member.get("run_id") != run_specification.run_id:
            raise ValueError(
                "Sensitivity case campaign member run identity is not canonical"
            )
        run_specifications[strategy_id] = run_specification
    if len({str(member.get("run_id")) for member in members}) != 2:
        raise ValueError("Sensitivity case campaign run identities must be unique")
    expected_campaign = BaselineCampaignSpecification(
        campaign_replica_id=expected_campaign_replica_id,
        strategy_runs=(
            run_specifications[QUENTX_SCENARIO_NATIVE_STRATEGY_ID],
            run_specifications[LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID],
        ),
    )
    if campaign.campaign_id != expected_campaign.campaign_id:
        raise ValueError("Sensitivity case campaign identity is not canonical")
    if campaign.status == "completed":
        completeness = view.get("completeness")
        shared_market_nodes = view.get("shared_market_nodes")
        isolation = view.get("isolation")
        if (
            any(member.get("status") != "completed" for member in members)
            or not isinstance(completeness, Mapping)
            or completeness.get("completed_count") != 2
            or completeness.get("total_count") != 2
            or completeness.get("is_complete") is not True
            or not isinstance(shared_market_nodes, Mapping)
            or shared_market_nodes.get("identical_observed_timeline") is not True
            or not isinstance(isolation, Mapping)
            or isolation.get("verification_status") != "verified"
            or isolation.get("fresh_subprocess_per_callback") is not True
        ):
            raise ValueError(
                "Completed sensitivity campaign lacks complete, comparable, "
                "isolated member evidence"
            )


def _sensitivity_curves(
    cases: tuple[SensitivityCaseSnapshot, ...],
) -> list[dict[str, object]]:
    curves: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for case in cases:
        if case.status != "completed":
            continue
        attempt = case.attempts[-1]
        if attempt.campaign is None:
            continue
        campaign_view = attempt.campaign.to_dict()
        members = campaign_view.get("members", [])
        if not isinstance(members, list):
            continue
        for member_value in members:
            if not isinstance(member_value, Mapping):
                continue
            member = cast(Mapping[str, object], member_value)
            if member.get("status") != "completed":
                continue
            equity_curve = member.get("equity_curve", [])
            if not isinstance(equity_curve, list) or not equity_curve:
                continue
            points = [
                cast(Mapping[str, object], point)
                for point in equity_curve
                if isinstance(point, Mapping)
            ]
            if not points:
                continue
            strategy_id = str(member.get("strategy_id", "unknown"))
            strategy_version = str(member.get("strategy_version", "unknown"))
            key = (
                case.specification.transformation_family,
                strategy_id,
                strategy_version,
            )
            curves.setdefault(key, []).append(
                {
                    "case_id": case.case_id,
                    "attempt_number": attempt.attempt_number,
                    "campaign_id": attempt.campaign.campaign_id,
                    "run_id": str(member.get("run_id", "unknown")),
                    "recipe_version_id": case.specification.recipe_version_id,
                    "materialization_hash": (
                        case.specification.materialization_hash
                    ),
                    "parameters": dict(
                        case.specification.transformation_parameters
                    ),
                    "final_equity": str(points[-1].get("equity", "0")),
                    "max_drawdown": _max_drawdown(points),
                }
            )
    family_order = {
        family: index for index, family in enumerate(ISOLATED_SENSITIVITY_FAMILIES)
    }
    return [
        {
            "family": family,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "points": points,
        }
        for (family, strategy_id, strategy_version), points in sorted(
            curves.items(),
            key=lambda item: (
                family_order[item[0][0]],
                item[0][1],
                item[0][2],
            ),
        )
    ]


def _max_drawdown(points: list[Mapping[str, object]]) -> str:
    peak: Decimal | None = None
    maximum = Decimal("0")
    for point in points:
        equity = Decimal(str(point.get("equity", "0")))
        peak = equity if peak is None else max(peak, equity)
        drawdown = Decimal("0") if peak <= 0 else (peak - equity) / peak
        maximum = max(maximum, drawdown)
    return _decimal_text(maximum)


__all__ = [
    "ISOLATED_SENSITIVITY_FAMILIES",
    "MAX_CASES_PER_SENSITIVITY_FAMILY",
    "MIN_CASES_PER_SENSITIVITY_FAMILY",
    "InMemoryIsolatedSensitivitySetRepository",
    "IsolatedSensitivitySetRepository",
    "IsolatedSensitivitySetRunner",
    "IsolatedSensitivitySetSnapshot",
    "IsolatedSensitivitySetSpecification",
    "SensitivityCampaignCase",
    "SensitivityCaseAttempt",
    "SensitivityCaseSnapshot",
    "SensitivityCaseStatus",
    "SensitivitySweepDefinition",
    "SensitivitySetStatus",
    "SqlIsolatedSensitivitySetRepository",
]
