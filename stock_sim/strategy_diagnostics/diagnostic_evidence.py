"""Sealed multidimensional evidence for completed Formal Diagnostic Campaigns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import (
    Callable,
    Literal,
    Mapping,
    Protocol,
    Sequence,
    cast,
)

from .formal_diagnostic_campaigns import (
    DiagnosticCampaignCase,
    DiagnosticCampaignSnapshot,
)
from .isolated_sensitivity_sets import (
    SensitivityCampaignCase,
    SensitivitySweepDefinition,
)
from .market_paths import MaterializedMarketPath


DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION = "diagnostic-evidence.v1"
EVIDENCE_FAMILIES = (
    "return_and_risk",
    "trading_behavior",
    "execution_erosion",
    "environmental_sensitivity",
)
GuardrailOperator = Literal["greater_than", "less_than"]
FindingKind = Literal["profit_source", "weakness", "robustness"]

_COMPARISON_METRICS = (
    "total_return",
    "maximum_drawdown",
    "turnover",
    "execution_erosion_bps",
    "instrument_concentration",
)
_SUPPORTED_GUARDRAIL_METRICS = frozenset(
    {
        "total_return",
        "net_return",
        "benchmark_relative_return",
        "maximum_drawdown",
        "maximum_recovery_duration_minutes",
        "return_volatility",
        "turnover",
        "average_holding_duration_minutes",
        "instrument_concentration",
        "industry_concentration",
        "rejection_count",
        "fill_rate",
        "total_fees",
        "execution_erosion",
        "execution_erosion_bps",
    }
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


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class GuardrailThreshold:
    metric_name: str
    operator: GuardrailOperator
    value: Decimal

    def __post_init__(self) -> None:
        if self.metric_name not in _SUPPORTED_GUARDRAIL_METRICS:
            raise ValueError(
                f"Unsupported Strategy Guardrail metric {self.metric_name!r}"
            )
        if self.operator not in ("greater_than", "less_than"):
            raise ValueError("Unsupported Strategy Guardrail operator")

    @property
    def threshold_id(self) -> str:
        return (
            "guardrail-threshold-"
            f"{_canonical_hash(self._identity_payload())[:24]}"
        )

    def crossed_by(self, value: Decimal) -> bool:
        if self.operator == "greater_than":
            return value > self.value
        return value < self.value

    def to_dict(self) -> dict[str, object]:
        return {
            "threshold_id": self.threshold_id,
            **self._identity_payload(),
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "operator": self.operator,
            "value": _decimal_text(self.value),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GuardrailThreshold":
        return cls(
            metric_name=str(payload["metric_name"]),
            operator=cast(GuardrailOperator, str(payload["operator"])),
            value=_decimal(payload["value"]),
        )


@dataclass(frozen=True, slots=True)
class StrategyGuardrailProfile:
    strategy_id: str
    strategy_version: str
    profile_version: str
    thresholds: tuple[GuardrailThreshold, ...]

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.strategy_id,
                self.strategy_version,
                self.profile_version,
            )
        ):
            raise ValueError("Strategy Guardrail Profile identity must not be blank")
        if not self.thresholds:
            raise ValueError("Strategy Guardrail Profile requires thresholds")
        names = tuple(item.metric_name for item in self.thresholds)
        if len(set(names)) != len(names):
            raise ValueError(
                "Strategy Guardrail Profile metric thresholds must be unique"
            )
        object.__setattr__(
            self,
            "thresholds",
            tuple(
                sorted(
                    self.thresholds,
                    key=lambda item: (
                        item.metric_name,
                        item.operator,
                        item.value,
                    ),
                )
            ),
        )

    @property
    def profile_id(self) -> str:
        return (
            "guardrail-profile-"
            f"{_canonical_hash(self._identity_payload())[:24]}"
        )

    def threshold_for(self, metric_name: str) -> GuardrailThreshold | None:
        return next(
            (
                threshold
                for threshold in self.thresholds
                if threshold.metric_name == metric_name
            ),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            **self._identity_payload(),
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "profile_version": self.profile_version,
            "thresholds": [
                threshold.to_dict() for threshold in self.thresholds
            ],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "StrategyGuardrailProfile":
        return cls(
            strategy_id=str(payload["strategy_id"]),
            strategy_version=str(payload["strategy_version"]),
            profile_version=str(payload["profile_version"]),
            thresholds=tuple(
                GuardrailThreshold.from_dict(
                    cast(Mapping[str, object], threshold)
                )
                for threshold in cast(
                    Sequence[object],
                    payload["thresholds"],
                )
            ),
        )


class DiagnosticEvidenceArtifactStore(Protocol):
    def put(self, payload: Mapping[str, object]) -> str: ...

    def get(self, artifact_hash: str) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class DiagnosticEvidencePackage:
    artifact_hash: str
    payload_json: str

    def __post_init__(self) -> None:
        payload = self.sealed_payload()
        if payload.get("schema_version") != DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("Unsupported Diagnostic Evidence schema version")
        if payload.get("status") != "sealed":
            raise ValueError("Diagnostic Evidence Package must be sealed")
        if _canonical_hash(payload) != self.artifact_hash:
            raise ValueError("Diagnostic Evidence Package hash verification failed")
        _reject_composite_score_keys(payload)

    @property
    def evidence_package_id(self) -> str:
        return f"diagnostic-evidence-{self.artifact_hash[:24]}"

    @property
    def campaign_id(self) -> str:
        return str(self.sealed_payload()["campaign_id"])

    def sealed_payload(self) -> dict[str, object]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Diagnostic Evidence payload must be an object")
        return cast(dict[str, object], payload)

    def validate_artifacts(
        self,
        artifact_store: DiagnosticEvidenceArtifactStore,
    ) -> None:
        sealed = artifact_store.get(self.artifact_hash)
        if sealed != self.sealed_payload():
            raise ValueError(
                "Diagnostic Evidence artifact does not match its index"
            )
        measurement_hash = str(sealed["measurement_artifact_hash"])
        measurement = artifact_store.get(measurement_hash)
        if measurement != _measurement_payload_from_sealed(sealed):
            raise ValueError(
                "Diagnostic Evidence measurement artifact does not match "
                "the sealed package"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.sealed_payload(),
            "evidence_package_id": self.evidence_package_id,
            "artifact_hash": self.artifact_hash,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        artifact_hash: str,
    ) -> "DiagnosticEvidencePackage":
        return cls(
            artifact_hash=artifact_hash,
            payload_json=_canonical_json(dict(payload)),
        )


def _measurement_payload_from_sealed(
    sealed: Mapping[str, object],
) -> dict[str, object]:
    def without_measurement_lineage(
        values: object,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for value in cast(Sequence[object], values):
            item = dict(cast(Mapping[str, object], value))
            item.pop("measurement_artifact_hash", None)
            result.append(item)
        return result

    return {
        "schema_version": sealed["schema_version"],
        "campaign_id": sealed["campaign_id"],
        "guardrail_profiles": sealed["guardrail_profiles"],
        "metrics": sealed["metrics"],
        "comparisons": sealed["comparisons"],
        "guardrail_breaches": without_measurement_lineage(
            sealed["guardrail_breaches"]
        ),
        "sensitivity_curves": sealed["sensitivity_curves"],
        "sensitivity_breakpoints": without_measurement_lineage(
            sealed["sensitivity_breakpoints"]
        ),
        "reproduction_manifests": sealed["reproduction_manifests"],
    }


class DiagnosticEvidenceRepository(Protocol):
    def add(self, package: DiagnosticEvidencePackage) -> None: ...

    def get(self, evidence_package_id: str) -> DiagnosticEvidencePackage | None: ...


class InMemoryDiagnosticEvidenceRepository:
    def __init__(self) -> None:
        self._packages: dict[str, DiagnosticEvidencePackage] = {}

    def add(self, package: DiagnosticEvidencePackage) -> None:
        existing = self._packages.get(package.evidence_package_id)
        if existing is not None and existing != package:
            raise ValueError("Diagnostic Evidence identity collision")
        self._packages[package.evidence_package_id] = package

    def get(self, evidence_package_id: str) -> DiagnosticEvidencePackage | None:
        return self._packages.get(evidence_package_id)


@dataclass(frozen=True, slots=True)
class DiagnosticFindingExplanation:
    finding_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.finding_id.strip():
            raise ValueError("Diagnostic Finding explanation requires a finding id")
        if not self.text.strip():
            raise ValueError("Diagnostic Finding explanation must not be blank")

    def to_dict(self) -> dict[str, str]:
        return {
            "finding_id": self.finding_id,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class SealedFindingExplanationRequest:
    evidence_package_id: str
    evidence_artifact_hash: str
    findings: tuple[Mapping[str, object], ...]


class DiagnosticFindingExplanationProvider(Protocol):
    def explain(
        self,
        request: SealedFindingExplanationRequest,
    ) -> tuple[DiagnosticFindingExplanation, ...]: ...


@dataclass(frozen=True, slots=True)
class DiagnosticExplanationBundle:
    evidence_package_id: str
    evidence_artifact_hash: str
    explanations: tuple[DiagnosticFindingExplanation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_package_id": self.evidence_package_id,
            "evidence_artifact_hash": self.evidence_artifact_hash,
            "explanations": [item.to_dict() for item in self.explanations],
        }


CampaignLoader = Callable[[str], DiagnosticCampaignSnapshot]
MarketPathLoader = Callable[[str], MaterializedMarketPath]


@dataclass(frozen=True, slots=True)
class _RunEvidence:
    case_id: str
    layer: str
    parameters: Mapping[str, str]
    strategy_id: str
    strategy_version: str
    run_id: str
    run_artifact_hash: str
    reproduction_manifest_id: str
    metrics: Mapping[str, Mapping[str, object]]


class DiagnosticEvidenceBuilder:
    """Calculate, seal, persist, and retrieve deterministic campaign evidence."""

    def __init__(
        self,
        campaign_loader: CampaignLoader,
        path_loader: MarketPathLoader,
        artifact_store: DiagnosticEvidenceArtifactStore,
        repository: DiagnosticEvidenceRepository | None = None,
    ) -> None:
        self._campaign_loader = campaign_loader
        self._path_loader = path_loader
        self._artifact_store = artifact_store
        self._repository = (
            repository or InMemoryDiagnosticEvidenceRepository()
        )

    def replace_repository(
        self,
        repository: DiagnosticEvidenceRepository,
    ) -> None:
        self._repository = repository

    def build(
        self,
        campaign_id: str,
        guardrail_profiles: tuple[StrategyGuardrailProfile, ...],
    ) -> DiagnosticEvidencePackage:
        campaign = self._campaign_loader(campaign_id)
        if campaign.specification.campaign_type != "formal_diagnostic_campaign":
            raise ValueError(
                "Diagnostic Evidence requires a Formal Diagnostic Campaign"
            )
        if campaign.status != "completed":
            raise ValueError(
                "Diagnostic Evidence requires a completed Formal Diagnostic Campaign"
            )
        profiles = _validate_profiles(campaign, guardrail_profiles)
        ordered_profiles = tuple(
            sorted(
                profiles.values(),
                key=lambda item: (
                    item.strategy_id,
                    item.strategy_version,
                    item.profile_version,
                ),
            )
        )
        (
            runs,
            metrics,
            manifests,
        ) = self._calculate_run_evidence(campaign)
        comparisons = _build_comparisons(campaign, runs)
        breaches = _build_guardrail_breaches(runs, profiles, comparisons)
        sensitivity_curves = _build_sensitivity_curves(
            campaign,
            runs,
        )
        breakpoints = _build_sensitivity_breakpoints(
            sensitivity_curves,
            profiles,
            comparisons,
        )
        measurement_payload: dict[str, object] = {
            "schema_version": DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
            "campaign_id": campaign.campaign_id,
            "guardrail_profiles": [
                profile.to_dict() for profile in ordered_profiles
            ],
            "metrics": metrics,
            "comparisons": comparisons,
            "guardrail_breaches": breaches,
            "sensitivity_curves": sensitivity_curves,
            "sensitivity_breakpoints": breakpoints,
            "reproduction_manifests": manifests,
        }
        measurement_hash = self._artifact_store.put(measurement_payload)
        breaches_with_lineage = tuple(
            {**item, "measurement_artifact_hash": measurement_hash}
            for item in breaches
        )
        breakpoints_with_lineage = tuple(
            {**item, "measurement_artifact_hash": measurement_hash}
            for item in breakpoints
        )
        findings = _build_findings(
            runs,
            profiles,
            comparisons,
            breaches_with_lineage,
            breakpoints_with_lineage,
            measurement_hash,
        )
        sealed_payload: dict[str, object] = {
            "schema_version": DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
            "status": "sealed",
            "campaign_id": campaign.campaign_id,
            "campaign_type": campaign.specification.campaign_type,
            "campaign_schema_version": campaign.to_dict()["schema_version"],
            "evidence_families": list(EVIDENCE_FAMILIES),
            "measurement_artifact_hash": measurement_hash,
            "guardrail_profiles": [
                profile.to_dict() for profile in ordered_profiles
            ],
            "metrics": metrics,
            "comparisons": comparisons,
            "guardrail_breaches": list(breaches_with_lineage),
            "sensitivity_curves": sensitivity_curves,
            "sensitivity_breakpoints": list(breakpoints_with_lineage),
            "diagnostic_findings": findings,
            "reproduction_manifests": manifests,
            "ai_explanation_authority": {
                "allowed": True,
                "scope": "sealed_findings_only",
                "may_recalculate_measurements": False,
                "may_add_or_remove_findings": False,
            },
        }
        _reject_composite_score_keys(sealed_payload)
        artifact_hash = self._artifact_store.put(sealed_payload)
        package = DiagnosticEvidencePackage.from_payload(
            sealed_payload,
            artifact_hash,
        )
        self._repository.add(package)
        return package

    def get(self, evidence_package_id: str) -> DiagnosticEvidencePackage:
        package = self._repository.get(evidence_package_id)
        if package is None:
            raise ValueError("Unknown Diagnostic Evidence Package")
        package.validate_artifacts(self._artifact_store)
        return package

    def explain(
        self,
        evidence_package_id: str,
        provider: DiagnosticFindingExplanationProvider,
    ) -> DiagnosticExplanationBundle:
        package = self.get(evidence_package_id)
        payload = package.sealed_payload()
        findings = tuple(
            cast(Mapping[str, object], item)
            for item in cast(
                Sequence[object],
                payload["diagnostic_findings"],
            )
        )
        request = SealedFindingExplanationRequest(
            evidence_package_id=package.evidence_package_id,
            evidence_artifact_hash=package.artifact_hash,
            findings=findings,
        )
        explanations = provider.explain(request)
        finding_ids = {str(item["finding_id"]) for item in findings}
        if any(item.finding_id not in finding_ids for item in explanations):
            raise ValueError(
                "AI explanation must reference an existing sealed Diagnostic Finding"
            )
        return DiagnosticExplanationBundle(
            evidence_package_id=package.evidence_package_id,
            evidence_artifact_hash=package.artifact_hash,
            explanations=explanations,
        )

    def _calculate_run_evidence(
        self,
        campaign: DiagnosticCampaignSnapshot,
    ) -> tuple[
        tuple[_RunEvidence, ...],
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        runs: list[_RunEvidence] = []
        metrics: list[dict[str, object]] = []
        manifests: list[dict[str, object]] = []
        case_specifications = _case_specifications(campaign)
        for case_view_value in cast(
            Sequence[object],
            campaign.to_dict()["cases"],
        ):
            case_view = cast(Mapping[str, object], case_view_value)
            case_id = str(case_view["case_id"])
            attempts = cast(Sequence[object], case_view["attempts"])
            if not attempts:
                raise ValueError(
                    "Completed campaign case is missing its execution attempt"
                )
            attempt = cast(Mapping[str, object], attempts[-1])
            members = cast(Sequence[object], attempt.get("members", ()))
            case = case_specifications[case_id]
            parameters = _case_parameters(case)
            for member_value in members:
                member = cast(Mapping[str, object], member_value)
                if member.get("status") != "completed":
                    raise ValueError(
                        "Sealed evidence requires completed Strategy Runs"
                    )
                run_artifact_hash = member.get("run_artifact_hash")
                if not isinstance(run_artifact_hash, str):
                    raise ValueError(
                        "Sealed evidence requires a Strategy Run artifact hash"
                    )
                specification = cast(
                    Mapping[str, object],
                    member["specification"],
                )
                manifest = _reproduction_manifest_reference(
                    case,
                    member,
                    specification,
                )
                path = self._path_loader(str(member["materialization_hash"]))
                run_metrics = _calculate_metrics(
                    case_id=case_id,
                    layer=str(case_view["layer"]),
                    member=member,
                    path=path,
                    reproduction_manifest_id=str(
                        manifest["reproduction_manifest_id"]
                    ),
                )
                metrics.extend(run_metrics.values())
                manifests.append(manifest)
                runs.append(
                    _RunEvidence(
                        case_id=case_id,
                        layer=str(case_view["layer"]),
                        parameters=parameters,
                        strategy_id=str(member["strategy_id"]),
                        strategy_version=str(member["strategy_version"]),
                        run_id=str(member["run_id"]),
                        run_artifact_hash=run_artifact_hash,
                        reproduction_manifest_id=str(
                            manifest["reproduction_manifest_id"]
                        ),
                        metrics=run_metrics,
                    )
                )
        return tuple(runs), metrics, manifests


def _validate_profiles(
    campaign: DiagnosticCampaignSnapshot,
    profiles: tuple[StrategyGuardrailProfile, ...],
) -> Mapping[tuple[str, str], StrategyGuardrailProfile]:
    if not profiles:
        raise ValueError("Diagnostic Evidence requires Strategy Guardrail Profiles")
    by_strategy = {
        (profile.strategy_id, profile.strategy_version): profile
        for profile in profiles
    }
    if len(by_strategy) != len(profiles):
        raise ValueError("Strategy Guardrail Profiles must be unique per strategy")
    strategy_versions: set[tuple[str, str]] = set()
    for case_value in cast(Sequence[object], campaign.to_dict()["cases"]):
        case = cast(Mapping[str, object], case_value)
        attempts = cast(Sequence[object], case["attempts"])
        if not attempts:
            continue
        attempt = cast(Mapping[str, object], attempts[-1])
        for member_value in cast(
            Sequence[object],
            attempt.get("members", ()),
        ):
            member = cast(Mapping[str, object], member_value)
            strategy_versions.add(
                (
                    str(member["strategy_id"]),
                    str(member["strategy_version"]),
                )
            )
    if set(by_strategy) != strategy_versions:
        raise ValueError(
            "Strategy Guardrail Profiles must exactly cover campaign strategies"
        )
    return by_strategy


def _case_specifications(
    campaign: DiagnosticCampaignSnapshot,
) -> dict[str, DiagnosticCampaignCase | SensitivityCampaignCase]:
    specification = campaign.specification
    cases: list[DiagnosticCampaignCase | SensitivityCampaignCase] = []
    if specification.baseline_case is not None:
        cases.append(specification.baseline_case)
    if specification.isolated_sensitivity_set is not None:
        cases.extend(specification.isolated_sensitivity_set.ordered_cases)
    cases.extend(specification.compound_cases)
    return {case.case_id: case for case in cases}


def _case_parameters(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
) -> Mapping[str, str]:
    if isinstance(case, SensitivityCampaignCase):
        return dict(case.transformation_parameters)
    return {
        f"{transformation.transformation_family}.{name}": value
        for transformation in case.transformations
        for name, value in transformation.transformation_parameters
    }


def _reproduction_manifest_reference(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
    member: Mapping[str, object],
    specification: Mapping[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_run_specification": dict(specification),
        "run_id": str(member["run_id"]),
        "run_artifact_hash": str(member["run_artifact_hash"]),
        "numeric_tolerance": case.numeric_tolerance,
    }
    return {
        "reproduction_manifest_id": (
            f"reproduction-manifest-{_canonical_hash(payload)[:24]}"
        ),
        **payload,
    }


def _calculate_metrics(
    *,
    case_id: str,
    layer: str,
    member: Mapping[str, object],
    path: MaterializedMarketPath,
    reproduction_manifest_id: str,
) -> dict[str, dict[str, object]]:
    specification = cast(
        Mapping[str, object],
        member["specification"],
    )
    initial_cash = _decimal(specification["initial_cash"])
    equity_curve = tuple(
        cast(Mapping[str, object], point)
        for point in cast(Sequence[object], member["equity_curve"])
    )
    if not equity_curve:
        raise ValueError("Sealed evidence requires a non-empty equity curve")
    equities = tuple(_decimal(point["equity"]) for point in equity_curve)
    cash_values = tuple(_decimal(point["cash"]) for point in equity_curve)
    simulation_times = tuple(
        datetime.fromisoformat(str(point["simulation_time"]))
        for point in equity_curve
    )
    ending_equity = equities[-1]
    fills = tuple(
        cast(Mapping[str, object], fill)
        for fill in cast(Sequence[object], member["fills"])
    )
    orders = tuple(
        cast(Mapping[str, object], order)
        for order in cast(Sequence[object], member["orders"])
    )
    positions = tuple(
        cast(Mapping[str, object], position)
        for position in cast(
            Sequence[object],
            cast(Mapping[str, object], member["portfolio"])["positions"],
        )
    )
    total_fees = sum(
        (
            _decimal(cast(Mapping[str, object], fill["fees"])["total"])
            for fill in fills
        ),
        Decimal("0"),
    )
    commissions = sum(
        (
            _decimal(cast(Mapping[str, object], fill["fees"])["commission"])
            for fill in fills
        ),
        Decimal("0"),
    )
    transfer_fees = sum(
        (
            _decimal(cast(Mapping[str, object], fill["fees"])["transfer_fee"])
            for fill in fills
        ),
        Decimal("0"),
    )
    stamp_duties = sum(
        (
            _decimal(cast(Mapping[str, object], fill["fees"])["stamp_duty"])
            for fill in fills
        ),
        Decimal("0"),
    )
    execution_erosion = sum(
        (_decimal(fill["execution_erosion"]) for fill in fills),
        Decimal("0"),
    )
    gross_traded_value = sum(
        (abs(_decimal(fill["gross_value"])) for fill in fills),
        Decimal("0"),
    )
    requested_quantity = sum(
        (abs(int(str(order["requested_shares"]))) for order in orders),
        0,
    )
    filled_quantity = sum(
        (abs(int(str(fill["shares"]))) for fill in fills),
        0,
    )
    unfilled_quantity = sum(
        (abs(int(str(order["unfilled_shares"]))) for order in orders),
        0,
    )
    period_returns = tuple(
        (
            (current / prior) - Decimal("1")
            if prior != 0
            else Decimal("0")
        )
        for prior, current in zip(equities, equities[1:])
    )
    average_return = (
        sum(period_returns, Decimal("0")) / Decimal(len(period_returns))
        if period_returns
        else Decimal("0")
    )
    variance = (
        sum(
            (
                (value - average_return) * (value - average_return)
                for value in period_returns
            ),
            Decimal("0"),
        )
        / Decimal(len(period_returns))
        if period_returns
        else Decimal("0")
    )
    average_equity = sum(equities, Decimal("0")) / Decimal(len(equities))
    benchmark_return = _benchmark_return(path)
    position_values = tuple(
        _decimal(position["market_value"]) for position in positions
    )
    positions_total = sum(position_values, Decimal("0"))
    instrument_concentration = (
        max(position_values) / positions_total
        if positions_total
        else Decimal("0")
    )
    current_simulation_time = member.get("current_simulation_time")
    if not isinstance(current_simulation_time, str):
        raise ValueError(
            "Industry concentration requires a completed Simulation Time"
        )
    industry_concentration = _industry_concentration(
        path,
        positions,
        as_of=datetime.fromisoformat(current_simulation_time),
    )
    total_return = (ending_equity / initial_cash) - Decimal("1")
    values: tuple[tuple[str, str, Decimal], ...] = (
        ("total_return", "return_and_risk", total_return),
        ("net_return", "return_and_risk", total_return),
        (
            "gross_return_before_execution_erosion",
            "return_and_risk",
            total_return + (execution_erosion / initial_cash),
        ),
        ("benchmark_return", "return_and_risk", benchmark_return),
        (
            "benchmark_relative_return",
            "return_and_risk",
            total_return - benchmark_return,
        ),
        (
            "maximum_drawdown",
            "return_and_risk",
            _maximum_drawdown(equities),
        ),
        (
            "maximum_recovery_duration_minutes",
            "return_and_risk",
            _maximum_recovery_duration_minutes(
                equities,
                simulation_times,
            ),
        ),
        ("return_volatility", "return_and_risk", variance.sqrt()),
        (
            "loss_period_fraction",
            "return_and_risk",
            (
                Decimal(sum(value < 0 for value in period_returns))
                / Decimal(len(period_returns))
                if period_returns
                else Decimal("0")
            ),
        ),
        (
            "worst_period_return",
            "return_and_risk",
            min(period_returns) if period_returns else Decimal("0"),
        ),
        (
            "turnover",
            "trading_behavior",
            gross_traded_value / average_equity,
        ),
        (
            "average_holding_duration_minutes",
            "trading_behavior",
            _average_holding_duration_minutes(
                fills,
                simulation_times[-1],
            ),
        ),
        (
            "average_cash_utilization",
            "trading_behavior",
            sum(
                (
                    (
                        (equity - cash) / equity
                        if equity
                        else Decimal("0")
                    )
                    for equity, cash in zip(equities, cash_values, strict=True)
                ),
                Decimal("0"),
            )
            / Decimal(len(equities)),
        ),
        (
            "instrument_concentration",
            "trading_behavior",
            instrument_concentration,
        ),
        (
            "industry_concentration",
            "trading_behavior",
            industry_concentration,
        ),
        ("order_count", "trading_behavior", Decimal(len(orders))),
        ("trade_count", "trading_behavior", Decimal(len(fills))),
        ("fill_count", "execution_erosion", Decimal(len(fills))),
        (
            "partial_fill_count",
            "execution_erosion",
            Decimal(sum(order.get("status") == "partially_filled" for order in orders)),
        ),
        (
            "rejection_count",
            "execution_erosion",
            Decimal(sum(order.get("status") == "rejected" for order in orders)),
        ),
        (
            "filled_quantity",
            "execution_erosion",
            Decimal(filled_quantity),
        ),
        (
            "unfilled_quantity",
            "execution_erosion",
            Decimal(unfilled_quantity),
        ),
        (
            "fill_rate",
            "execution_erosion",
            (
                Decimal(filled_quantity) / Decimal(requested_quantity)
                if requested_quantity
                else Decimal("0")
            ),
        ),
        ("commission_fees", "execution_erosion", commissions),
        ("transfer_fees", "execution_erosion", transfer_fees),
        ("stamp_duties", "execution_erosion", stamp_duties),
        ("total_fees", "execution_erosion", total_fees),
        ("execution_erosion", "execution_erosion", execution_erosion),
        (
            "execution_erosion_bps",
            "execution_erosion",
            (
                execution_erosion / gross_traded_value * Decimal("10000")
                if gross_traded_value
                else Decimal("0")
            ),
        ),
    )
    result: dict[str, dict[str, object]] = {}
    for name, family, value in values:
        payload: dict[str, object] = {
            "family": family,
            "name": name,
            "value": _decimal_text(value),
            "case_id": case_id,
            "layer": layer,
            "strategy_id": str(member["strategy_id"]),
            "strategy_version": str(member["strategy_version"]),
            "run_id": str(member["run_id"]),
            "run_artifact_hash": str(member["run_artifact_hash"]),
            "reproduction_manifest_id": reproduction_manifest_id,
        }
        result[name] = {
            "metric_id": f"diagnostic-metric-{_canonical_hash(payload)[:24]}",
            **payload,
        }
    return result


def _maximum_drawdown(equities: tuple[Decimal, ...]) -> Decimal:
    peak = equities[0]
    maximum = Decimal("0")
    for equity in equities:
        peak = max(peak, equity)
        if peak:
            maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _maximum_recovery_duration_minutes(
    equities: tuple[Decimal, ...],
    simulation_times: tuple[datetime, ...],
) -> Decimal:
    peak = equities[0]
    underwater_started_at: datetime | None = None
    maximum_seconds = Decimal("0")
    for equity, simulation_time in zip(
        equities,
        simulation_times,
        strict=True,
    ):
        if equity >= peak:
            peak = equity
            if underwater_started_at is not None:
                maximum_seconds = max(
                    maximum_seconds,
                    Decimal(
                        str(
                            (
                                simulation_time - underwater_started_at
                            ).total_seconds()
                        )
                    ),
                )
                underwater_started_at = None
        elif underwater_started_at is None:
            underwater_started_at = simulation_time
    if underwater_started_at is not None:
        maximum_seconds = max(
            maximum_seconds,
            Decimal(
                str(
                    (
                        simulation_times[-1] - underwater_started_at
                    ).total_seconds()
                )
            ),
        )
    return maximum_seconds / Decimal("60")


def _average_holding_duration_minutes(
    fills: tuple[Mapping[str, object], ...],
    end_time: datetime,
) -> Decimal:
    lots: dict[str, list[tuple[int, datetime]]] = {}
    weighted_minutes = Decimal("0")
    measured_shares = 0
    for fill in sorted(
        fills,
        key=lambda item: datetime.fromisoformat(
            str(item["simulation_time"])
        ),
    ):
        instrument = str(fill["instrument"])
        shares = int(str(fill["shares"]))
        simulation_time = datetime.fromisoformat(
            str(fill["simulation_time"])
        )
        if shares > 0:
            lots.setdefault(instrument, []).append((shares, simulation_time))
            continue
        remaining_to_close = abs(shares)
        open_lots = lots.setdefault(instrument, [])
        while remaining_to_close and open_lots:
            quantity, opened_at = open_lots[0]
            matched = min(quantity, remaining_to_close)
            weighted_minutes += (
                Decimal(str((simulation_time - opened_at).total_seconds()))
                / Decimal("60")
                * Decimal(matched)
            )
            measured_shares += matched
            remaining_to_close -= matched
            if matched == quantity:
                open_lots.pop(0)
            else:
                open_lots[0] = (quantity - matched, opened_at)
        if remaining_to_close:
            raise ValueError(
                "Holding-duration evidence found an unmatched sell fill"
            )
    for open_lots in lots.values():
        for quantity, opened_at in open_lots:
            weighted_minutes += (
                Decimal(str((end_time - opened_at).total_seconds()))
                / Decimal("60")
                * Decimal(quantity)
            )
            measured_shares += quantity
    return (
        weighted_minutes / Decimal(measured_shares)
        if measured_shares
        else Decimal("0")
    )


def _benchmark_return(path: MaterializedMarketPath) -> Decimal:
    closes: dict[str, list[Decimal]] = {}
    for node in sorted(
        path.nodes,
        key=lambda item: (item.instrument, item.simulation_time),
    ):
        closes.setdefault(node.instrument, []).append(node.close)
    returns = tuple(
        (values[-1] / values[0]) - Decimal("1")
        for values in closes.values()
        if values and values[0] != 0
    )
    if not returns:
        raise ValueError("Benchmark evidence requires visible market prices")
    return sum(returns, Decimal("0")) / Decimal(len(returns))


def _industry_concentration(
    path: MaterializedMarketPath,
    positions: tuple[Mapping[str, object], ...],
    *,
    as_of: datetime,
) -> Decimal:
    industry_by_instrument = {
        state.instrument: state.industry
        for state in sorted(
            (
                state
                for state in path.instrument_states
                if state.effective_at <= as_of
            ),
            key=lambda item: (item.instrument, item.effective_at),
        )
    }
    by_industry: dict[str, Decimal] = {}
    total = Decimal("0")
    for position in positions:
        instrument = str(position["instrument"])
        try:
            industry = industry_by_instrument[instrument]
        except KeyError as error:
            raise ValueError(
                "Industry concentration requires point-in-time industry provenance"
            ) from error
        value = _decimal(position["market_value"])
        by_industry[industry] = by_industry.get(industry, Decimal("0")) + value
        total += value
    return max(by_industry.values()) / total if total else Decimal("0")


def _build_comparisons(
    campaign: DiagnosticCampaignSnapshot,
    runs: tuple[_RunEvidence, ...],
) -> list[dict[str, object]]:
    by_case_strategy = {
        (run.case_id, run.strategy_id): run for run in runs
    }
    comparisons: list[dict[str, object]] = []
    for relationship_value in cast(
        Sequence[object],
        campaign.to_dict()["comparison_relationships"],
    ):
        relationship = cast(Mapping[str, object], relationship_value)
        subject_case_id = str(relationship["subject_case_id"])
        control_case_ids = tuple(
            str(value)
            for value in cast(
                Sequence[object],
                relationship["control_case_ids"],
            )
        )
        for strategy_id in sorted({run.strategy_id for run in runs}):
            subject = by_case_strategy[(subject_case_id, strategy_id)]
            for control_case_id in control_case_ids:
                control = by_case_strategy[(control_case_id, strategy_id)]
                for metric_name in _COMPARISON_METRICS:
                    subject_metric = subject.metrics[metric_name]
                    control_metric = control.metrics[metric_name]
                    payload: dict[str, object] = {
                        "kind": str(relationship["kind"]),
                        "metric_name": metric_name,
                        "strategy_id": subject.strategy_id,
                        "strategy_version": subject.strategy_version,
                        "subject_strategy_id": subject.strategy_id,
                        "subject_strategy_version": subject.strategy_version,
                        "subject_case_id": subject.case_id,
                        "subject_run_id": subject.run_id,
                        "subject_metric_id": subject_metric["metric_id"],
                        "subject_run_artifact_hash": (
                            subject.run_artifact_hash
                        ),
                        "subject_reproduction_manifest_id": (
                            subject.reproduction_manifest_id
                        ),
                        "control_strategy_id": control.strategy_id,
                        "control_strategy_version": control.strategy_version,
                        "control_case_id": control.case_id,
                        "control_run_id": control.run_id,
                        "control_metric_id": control_metric["metric_id"],
                        "control_run_artifact_hash": (
                            control.run_artifact_hash
                        ),
                        "control_reproduction_manifest_id": (
                            control.reproduction_manifest_id
                        ),
                        "delta": _decimal_text(
                            _decimal(subject_metric["value"])
                            - _decimal(control_metric["value"])
                        ),
                    }
                    comparisons.append(
                        {
                            "comparison_id": (
                                "diagnostic-comparison-"
                                f"{_canonical_hash(payload)[:24]}"
                            ),
                            **payload,
                        }
                    )
    by_case: dict[str, list[_RunEvidence]] = {}
    for run in runs:
        by_case.setdefault(run.case_id, []).append(run)
    for case_id in sorted(by_case):
        case_runs = sorted(
            by_case[case_id],
            key=lambda item: (item.strategy_id, item.strategy_version),
        )
        for subject_index, subject in enumerate(case_runs):
            for control in case_runs[subject_index + 1 :]:
                for metric_name in _COMPARISON_METRICS:
                    subject_metric = subject.metrics[metric_name]
                    control_metric = control.metrics[metric_name]
                    payload = {
                        "kind": "cross-strategy",
                        "case_id": case_id,
                        "layer": subject.layer,
                        "metric_name": metric_name,
                        "strategy_id": subject.strategy_id,
                        "strategy_version": subject.strategy_version,
                        "subject_strategy_id": subject.strategy_id,
                        "subject_strategy_version": subject.strategy_version,
                        "subject_case_id": subject.case_id,
                        "subject_run_id": subject.run_id,
                        "subject_metric_id": subject_metric["metric_id"],
                        "subject_run_artifact_hash": (
                            subject.run_artifact_hash
                        ),
                        "subject_reproduction_manifest_id": (
                            subject.reproduction_manifest_id
                        ),
                        "control_strategy_id": control.strategy_id,
                        "control_strategy_version": control.strategy_version,
                        "control_case_id": control.case_id,
                        "control_run_id": control.run_id,
                        "control_metric_id": control_metric["metric_id"],
                        "control_run_artifact_hash": (
                            control.run_artifact_hash
                        ),
                        "control_reproduction_manifest_id": (
                            control.reproduction_manifest_id
                        ),
                        "delta": _decimal_text(
                            _decimal(subject_metric["value"])
                            - _decimal(control_metric["value"])
                        ),
                    }
                    comparisons.append(
                        {
                            "comparison_id": (
                                "diagnostic-comparison-"
                                f"{_canonical_hash(payload)[:24]}"
                            ),
                            **payload,
                        }
                    )
    return comparisons


def _related_comparisons(
    comparisons: Sequence[Mapping[str, object]],
    *,
    case_id: str,
    metric_name: str,
    strategy_id: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        item
        for item in comparisons
        if item["metric_name"] == metric_name
        and strategy_id
        in (
            item.get("subject_strategy_id", item["strategy_id"]),
            item.get("control_strategy_id", item["strategy_id"]),
        )
        and case_id in (item["subject_case_id"], item["control_case_id"])
    )


def _build_guardrail_breaches(
    runs: tuple[_RunEvidence, ...],
    profiles: Mapping[tuple[str, str], StrategyGuardrailProfile],
    comparisons: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    breaches: list[dict[str, object]] = []
    for run in runs:
        profile = profiles[(run.strategy_id, run.strategy_version)]
        for threshold in profile.thresholds:
            metric = run.metrics[threshold.metric_name]
            if not threshold.crossed_by(_decimal(metric["value"])):
                continue
            related = _related_comparisons(
                comparisons,
                case_id=run.case_id,
                metric_name=threshold.metric_name,
                strategy_id=run.strategy_id,
            )
            payload: dict[str, object] = {
                "strategy_id": run.strategy_id,
                "strategy_version": run.strategy_version,
                "case_id": run.case_id,
                "run_id": run.run_id,
                "metric_id": metric["metric_id"],
                "metric_name": threshold.metric_name,
                "metric_value": metric["value"],
                "guardrail_profile_id": profile.profile_id,
                "threshold": threshold.to_dict(),
                "comparison_ids": [
                    item["comparison_id"] for item in related
                ],
                "run_artifact_hash": run.run_artifact_hash,
                "reproduction_manifest_id": run.reproduction_manifest_id,
            }
            breaches.append(
                {
                    "breach_id": (
                        f"guardrail-breach-{_canonical_hash(payload)[:24]}"
                    ),
                    **payload,
                }
            )
    return breaches


def _build_sensitivity_curves(
    campaign: DiagnosticCampaignSnapshot,
    runs: tuple[_RunEvidence, ...],
) -> list[dict[str, object]]:
    isolated = campaign.specification.isolated_sensitivity_set
    if isolated is None:
        return []
    by_case_strategy = {
        (run.case_id, run.strategy_id): run for run in runs
    }
    curves: list[dict[str, object]] = []
    strategy_ids = sorted({run.strategy_id for run in runs})
    metric_names = (
        "total_return",
        "maximum_drawdown",
        "turnover",
        "execution_erosion_bps",
        "instrument_concentration",
    )
    for sweep in isolated.ordered_sweeps:
        ordered_levels, sweep_axis = _ordered_sweep_levels(sweep)
        for strategy_id in strategy_ids:
            for metric_name in metric_names:
                points: list[dict[str, object]] = []
                for case in ordered_levels:
                    run = by_case_strategy[(case.case_id, strategy_id)]
                    metric = run.metrics[metric_name]
                    points.append(
                        {
                            "case_id": case.case_id,
                            "run_id": run.run_id,
                            "metric_id": metric["metric_id"],
                            "parameters": dict(
                                case.transformation_parameters
                            ),
                            "value": metric["value"],
                            "run_artifact_hash": run.run_artifact_hash,
                            "reproduction_manifest_id": (
                                run.reproduction_manifest_id
                            ),
                        }
                    )
                payload: dict[str, object] = {
                    "transformation_family": sweep.transformation_family,
                    "transformation_id": sweep.transformation_id,
                    "strategy_id": strategy_id,
                    "strategy_version": by_case_strategy[
                        (ordered_levels[0].case_id, strategy_id)
                    ].strategy_version,
                    "metric_name": metric_name,
                    "sweep_axis": sweep_axis,
                    "points": points,
                }
                curves.append(
                    {
                        "curve_id": (
                            f"sensitivity-curve-{_canonical_hash(payload)[:24]}"
                        ),
                        **payload,
                    }
                )
    return curves


def _ordered_sweep_levels(
    sweep: SensitivitySweepDefinition,
) -> tuple[
    tuple[SensitivityCampaignCase, ...],
    Mapping[str, object] | None,
]:
    canonical_levels = sweep.ordered_levels
    parameter_views = tuple(
        dict(level.transformation_parameters) for level in canonical_levels
    )
    parameter_names = set(parameter_views[0])
    if any(set(parameters) != parameter_names for parameters in parameter_views):
        return canonical_levels, None
    varying_parameters = tuple(
        name
        for name in sorted(parameter_names)
        if len({parameters[name] for parameters in parameter_views}) > 1
    )
    if len(varying_parameters) != 1:
        return canonical_levels, None
    axis_name = varying_parameters[0]
    try:
        numeric_values = {
            level.case_id: Decimal(
                dict(level.transformation_parameters)[axis_name]
            )
            for level in canonical_levels
        }
    except (InvalidOperation, ValueError):
        return canonical_levels, None
    return (
        tuple(
            sorted(
                canonical_levels,
                key=lambda level: (
                    numeric_values[level.case_id],
                    level.transformation_parameters,
                    level.case_id,
                ),
            )
        ),
        {
            "parameter_name": axis_name,
            "value_type": "decimal",
            "order": "ascending",
        },
    )


def _build_sensitivity_breakpoints(
    curves: Sequence[Mapping[str, object]],
    profiles: Mapping[tuple[str, str], StrategyGuardrailProfile],
    comparisons: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    breakpoints: list[dict[str, object]] = []
    for curve in curves:
        profile = profiles[
            (
                str(curve["strategy_id"]),
                str(curve["strategy_version"]),
            )
        ]
        threshold = profile.threshold_for(str(curve["metric_name"]))
        if threshold is None:
            continue
        points = tuple(
            cast(Mapping[str, object], point)
            for point in cast(Sequence[object], curve["points"])
        )
        crossed = tuple(
            threshold.crossed_by(_decimal(point["value"]))
            for point in points
        )
        first_crossed_index = next(
            (index for index, value in enumerate(crossed) if value),
            None,
        )
        sweep_axis = curve.get("sweep_axis")
        selected: tuple[Mapping[str, object], ...]
        if sweep_axis is None:
            if first_crossed_index is None:
                continue
            observed = points[first_crossed_index]
            selected = (observed,)
            observed_level: Mapping[str, object] | None = {
                "case_id": observed["case_id"],
                "parameters": observed["parameters"],
            }
            bounded_interval: Mapping[str, object] | None = None
        else:
            transition_index = next(
                (
                    index
                    for index in range(1, len(points))
                    if not crossed[index - 1] and crossed[index]
                ),
                None,
            )
            if transition_index is None and first_crossed_index is None:
                continue
            if transition_index is None:
                observed = points[cast(int, first_crossed_index)]
                selected = (observed,)
                observed_level = {
                    "case_id": observed["case_id"],
                    "parameters": observed["parameters"],
                }
                bounded_interval = None
            else:
                lower = points[transition_index - 1]
                upper = points[transition_index]
                selected = (lower, upper)
                observed_level = None
                bounded_interval = {
                    "lower_case_id": lower["case_id"],
                    "lower_parameters": lower["parameters"],
                    "upper_case_id": upper["case_id"],
                    "upper_parameters": upper["parameters"],
                }
        comparison_ids = [
            comparison["comparison_id"]
            for point in selected
            for comparison in _related_comparisons(
                comparisons,
                case_id=str(point["case_id"]),
                metric_name=str(curve["metric_name"]),
                strategy_id=str(curve["strategy_id"]),
            )
        ]
        payload: dict[str, object] = {
            "kind": "guardrail_crossing",
            "curve_id": curve["curve_id"],
            "transformation_family": curve["transformation_family"],
            "strategy_id": curve["strategy_id"],
            "strategy_version": curve["strategy_version"],
            "metric_name": curve["metric_name"],
            "sweep_axis": sweep_axis,
            "guardrail_profile_id": profile.profile_id,
            "threshold": threshold.to_dict(),
            "observed_level": observed_level,
            "bounded_interval": bounded_interval,
            "case_ids": [point["case_id"] for point in selected],
            "run_ids": [point["run_id"] for point in selected],
            "metric_ids": [point["metric_id"] for point in selected],
            "comparison_ids": list(dict.fromkeys(comparison_ids)),
            "run_artifact_hashes": [
                point["run_artifact_hash"] for point in selected
            ],
            "reproduction_manifest_ids": [
                point["reproduction_manifest_id"] for point in selected
            ],
        }
        breakpoints.append(
            {
                "breakpoint_id": (
                    f"sensitivity-breakpoint-{_canonical_hash(payload)[:24]}"
                ),
                **payload,
            }
        )
    return breakpoints


def _build_findings(
    runs: tuple[_RunEvidence, ...],
    profiles: Mapping[tuple[str, str], StrategyGuardrailProfile],
    comparisons: Sequence[Mapping[str, object]],
    breaches: Sequence[Mapping[str, object]],
    breakpoints: Sequence[Mapping[str, object]],
    measurement_hash: str,
) -> list[dict[str, object]]:
    by_case_strategy = {
        (run.case_id, run.strategy_id): run for run in runs
    }
    findings: list[dict[str, object]] = []
    for breach in breaches:
        related = _related_comparisons(
            comparisons,
            case_id=str(breach["case_id"]),
            metric_name=str(breach["metric_name"]),
            strategy_id=str(breach["strategy_id"]),
        )
        if not related:
            continue
        findings.append(
            _finding(
                kind="weakness",
                statement=(
                    f"{breach['strategy_id']} crossed its "
                    f"{breach['metric_name']} guardrail in case "
                    f"{breach['case_id']}."
                ),
                strategy_id=str(breach["strategy_id"]),
                strategy_version=str(breach["strategy_version"]),
                profile_id=str(breach["guardrail_profile_id"]),
                threshold_ids=(
                    str(
                        cast(Mapping[str, object], breach["threshold"])[
                            "threshold_id"
                        ]
                    ),
                ),
                comparisons=related,
                metric_ids=(str(breach["metric_id"]),),
                case_ids=(str(breach["case_id"]),),
                run_ids=(str(breach["run_id"]),),
                breakpoint_ids=(),
                reproduction_manifest_ids=(
                    str(breach["reproduction_manifest_id"]),
                ),
                measurement_hash=measurement_hash,
            )
        )
    for breakpoint in breakpoints:
        related = tuple(
            comparison
            for comparison in comparisons
            if comparison["comparison_id"]
            in cast(Sequence[object], breakpoint["comparison_ids"])
        )
        if not related:
            continue
        breakpoint_threshold_view = cast(
            Mapping[str, object],
            breakpoint["threshold"],
        )
        findings.append(
            _finding(
                kind="weakness",
                statement=(
                    f"{breakpoint['strategy_id']} has an observed "
                    f"{breakpoint['metric_name']} sensitivity boundary in "
                    f"{breakpoint['transformation_family']}."
                ),
                strategy_id=str(breakpoint["strategy_id"]),
                strategy_version=str(breakpoint["strategy_version"]),
                profile_id=str(breakpoint["guardrail_profile_id"]),
                threshold_ids=(
                    str(breakpoint_threshold_view["threshold_id"]),
                ),
                comparisons=related,
                metric_ids=tuple(
                    str(value)
                    for value in cast(
                        Sequence[object],
                        breakpoint["metric_ids"],
                    )
                ),
                case_ids=tuple(
                    str(value)
                    for value in cast(
                        Sequence[object],
                        breakpoint["case_ids"],
                    )
                ),
                run_ids=tuple(
                    str(value)
                    for value in cast(
                        Sequence[object],
                        breakpoint["run_ids"],
                    )
                ),
                breakpoint_ids=(str(breakpoint["breakpoint_id"]),),
                reproduction_manifest_ids=tuple(
                    str(value)
                    for value in cast(
                        Sequence[object],
                        breakpoint["reproduction_manifest_ids"],
                    )
                ),
                measurement_hash=measurement_hash,
            )
        )
    for comparison in comparisons:
        if (
            comparison["kind"] != "cross-strategy"
            or comparison["metric_name"] != "total_return"
            or comparison["layer"] != "compound"
        ):
            continue
        subject = by_case_strategy[
            (
                str(comparison["subject_case_id"]),
                str(comparison["subject_strategy_id"]),
            )
        ]
        control = by_case_strategy[
            (
                str(comparison["control_case_id"]),
                str(comparison["control_strategy_id"]),
            )
        ]
        if _decimal(comparison["delta"]) >= 0:
            stronger, weaker = subject, control
        else:
            stronger, weaker = control, subject
        profile = profiles[
            (stronger.strategy_id, stronger.strategy_version)
        ]
        total_return_threshold = profile.threshold_for("total_return")
        if total_return_threshold is None:
            continue
        if any(
            breach["strategy_id"] == stronger.strategy_id
            and breach["case_id"] == stronger.case_id
            for breach in breaches
        ):
            continue
        baseline_comparison = next(
            (
                candidate
                for candidate in comparisons
                if candidate["kind"]
                == "compound-vs-baseline-and-isolated"
                and candidate["metric_name"] == "total_return"
                and candidate["strategy_id"] == stronger.strategy_id
                and candidate["subject_case_id"] == stronger.case_id
                and by_case_strategy[
                    (
                        str(candidate["control_case_id"]),
                        stronger.strategy_id,
                    )
                ].layer
                == "baseline"
                and _decimal(candidate["delta"]) >= 0
            ),
            None,
        )
        if baseline_comparison is None:
            continue
        baseline = by_case_strategy[
            (
                str(baseline_comparison["control_case_id"]),
                stronger.strategy_id,
            )
        ]
        findings.append(
            _finding(
                kind="robustness",
                statement=(
                    f"{stronger.strategy_id} satisfied its selected guardrails, "
                    "preserved baseline total return, and retained the stronger "
                    "sealed total return in cross-strategy compound case "
                    f"{stronger.case_id} versus {weaker.strategy_id}."
                ),
                strategy_id=stronger.strategy_id,
                strategy_version=stronger.strategy_version,
                profile_id=profile.profile_id,
                threshold_ids=(total_return_threshold.threshold_id,),
                comparisons=(comparison, baseline_comparison),
                metric_ids=(
                    str(comparison["subject_metric_id"]),
                    str(comparison["control_metric_id"]),
                    str(baseline_comparison["control_metric_id"]),
                ),
                case_ids=(stronger.case_id, baseline.case_id),
                run_ids=(subject.run_id, control.run_id, baseline.run_id),
                breakpoint_ids=(),
                reproduction_manifest_ids=(
                    subject.reproduction_manifest_id,
                    control.reproduction_manifest_id,
                    baseline.reproduction_manifest_id,
                ),
                measurement_hash=measurement_hash,
            )
        )
    for strategy_id, strategy_version in sorted(profiles):
        profile = profiles[(strategy_id, strategy_version)]
        candidates = [
            comparison
            for comparison in comparisons
            if comparison["strategy_id"] == strategy_id
            and comparison["metric_name"] == "total_return"
            and comparison["kind"] == "isolated-vs-baseline"
            and _decimal(comparison["delta"]) > 0
        ]
        total_return_threshold = profile.threshold_for("total_return")
        if total_return_threshold is None:
            continue
        if candidates:
            comparison = max(
                candidates,
                key=lambda item: _decimal(item["delta"]),
            )
            subject = by_case_strategy[
                (str(comparison["subject_case_id"]), strategy_id)
            ]
            control = by_case_strategy[
                (str(comparison["control_case_id"]), strategy_id)
            ]
            findings.append(
                _finding(
                    kind="profit_source",
                    statement=(
                        f"{strategy_id} improved total return versus baseline in "
                        f"isolated case {subject.case_id}."
                    ),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    profile_id=profile.profile_id,
                    threshold_ids=(total_return_threshold.threshold_id,),
                    comparisons=(comparison,),
                    metric_ids=(
                        str(comparison["subject_metric_id"]),
                        str(comparison["control_metric_id"]),
                    ),
                    case_ids=(subject.case_id, control.case_id),
                    run_ids=(subject.run_id, control.run_id),
                    breakpoint_ids=(),
                    reproduction_manifest_ids=(
                        subject.reproduction_manifest_id,
                        control.reproduction_manifest_id,
                    ),
                    measurement_hash=measurement_hash,
                )
            )
        compound_candidates = [
            comparison
            for comparison in comparisons
            if comparison["strategy_id"] == strategy_id
            and comparison["metric_name"] == "total_return"
            and comparison["kind"] == "compound-vs-baseline-and-isolated"
            and by_case_strategy[
                (str(comparison["subject_case_id"]), strategy_id)
            ].layer
            == "compound"
            and by_case_strategy[
                (str(comparison["control_case_id"]), strategy_id)
            ].layer
            == "baseline"
            and _decimal(comparison["delta"]) >= 0
        ]
        for compound_comparison in compound_candidates:
            subject = by_case_strategy[
                (
                    str(compound_comparison["subject_case_id"]),
                    strategy_id,
                )
            ]
            control = by_case_strategy[
                (
                    str(compound_comparison["control_case_id"]),
                    strategy_id,
                )
            ]
            subject_breaches = tuple(
                breach
                for breach in breaches
                if breach["strategy_id"] == strategy_id
                and breach["case_id"] == subject.case_id
            )
            if subject_breaches:
                continue
            findings.append(
                _finding(
                    kind="robustness",
                    statement=(
                        f"{strategy_id} preserved baseline total return without "
                        f"a guardrail crossing in compound case {subject.case_id}."
                    ),
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    profile_id=profile.profile_id,
                    threshold_ids=(total_return_threshold.threshold_id,),
                    comparisons=(compound_comparison,),
                    metric_ids=(
                        str(compound_comparison["subject_metric_id"]),
                        str(compound_comparison["control_metric_id"]),
                    ),
                    case_ids=(subject.case_id, control.case_id),
                    run_ids=(subject.run_id, control.run_id),
                    breakpoint_ids=(),
                    reproduction_manifest_ids=(
                        subject.reproduction_manifest_id,
                        control.reproduction_manifest_id,
                    ),
                    measurement_hash=measurement_hash,
                )
            )
    return findings


def _finding(
    *,
    kind: FindingKind,
    statement: str,
    strategy_id: str,
    strategy_version: str,
    profile_id: str,
    threshold_ids: tuple[str, ...],
    comparisons: Sequence[Mapping[str, object]],
    metric_ids: tuple[str, ...],
    case_ids: tuple[str, ...],
    run_ids: tuple[str, ...],
    breakpoint_ids: tuple[str, ...],
    reproduction_manifest_ids: tuple[str, ...],
    measurement_hash: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "statement": statement,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "case_ids": list(dict.fromkeys(case_ids)),
        "run_ids": list(dict.fromkeys(run_ids)),
        "comparison_ids": list(
            dict.fromkeys(str(item["comparison_id"]) for item in comparisons)
        ),
        "metric_ids": list(dict.fromkeys(metric_ids)),
        "guardrail_profile_id": profile_id,
        "threshold_ids": list(dict.fromkeys(threshold_ids)),
        "breakpoint_ids": list(dict.fromkeys(breakpoint_ids)),
        "reproduction_manifest_ids": list(
            dict.fromkeys(reproduction_manifest_ids)
        ),
        "measurement_artifact_hash": measurement_hash,
    }
    return {
        "finding_id": f"diagnostic-finding-{_canonical_hash(payload)[:24]}",
        **payload,
    }


def _reject_composite_score_keys(value: object) -> None:
    forbidden = {
        "score",
        "composite_score",
        "universal_score",
        "ranking",
        "rank",
    }
    if isinstance(value, Mapping):
        overlap = forbidden.intersection(str(key) for key in value)
        if overlap:
            raise ValueError(
                "Universal composite strategy scores and rankings are prohibited"
            )
        for child in value.values():
            _reject_composite_score_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _reject_composite_score_keys(child)


__all__ = [
    "DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION",
    "DiagnosticEvidenceArtifactStore",
    "DiagnosticEvidenceBuilder",
    "DiagnosticEvidencePackage",
    "DiagnosticEvidenceRepository",
    "DiagnosticExplanationBundle",
    "DiagnosticFindingExplanation",
    "DiagnosticFindingExplanationProvider",
    "EVIDENCE_FAMILIES",
    "GuardrailThreshold",
    "InMemoryDiagnosticEvidenceRepository",
    "SealedFindingExplanationRequest",
    "StrategyGuardrailProfile",
]
