"""Pinned manifests and deterministic replay reports for accepted Strategy Runs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Callable, Literal, Mapping, Protocol, Sequence, cast

from .diagnostic_evidence import (
    DiagnosticEvidencePackage,
    calculate_run_evidence_metrics,
)
from .historical_segments import SourceSnapshot
from .market_paths import MaterializedMarketPath
from .strategy_runs import StrategyRunSnapshot, StrategyRunSpecification


REPRODUCTION_MANIFEST_SCHEMA_VERSION = "reproduction-manifest.v1"
REPRODUCTION_REPORT_SCHEMA_VERSION = "reproduction-report.v1"
DIAGNOSTIC_CODE_IDENTITY = "strategy-diagnostics.v1"
ReproductionLayer = Literal[
    "baseline",
    "isolated_sensitivity",
    "compound",
]
ReproductionStatus = Literal[
    "reproduced_exactly",
    "reproduced_within_tolerance",
    "reproducibility_invalid",
]
ReproductionCheckStatus = Literal[
    "exact",
    "within_tolerance",
    "mismatch",
    "not_run",
]


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


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ReproductionManifest:
    """Immutable dependencies and accepted outputs for one Strategy Run."""

    strategy_run_specification_json: str
    run_artifact_hash: str
    numeric_tolerance: Decimal
    case_id: str
    layer: ReproductionLayer
    evidence_package_id: str
    evidence_artifact_hash: str
    measurement_artifact_hash: str
    accepted_result_json: str

    def __post_init__(self) -> None:
        specification = self.specification
        if StrategyRunSpecification.from_pinned_dict(
            specification.to_dict()
        ) != specification:
            raise ValueError(
                "Reproduction Manifest requires a fully pinned Strategy Run "
                "specification"
            )
        for field, value in (
            ("run_artifact_hash", self.run_artifact_hash),
            ("evidence_artifact_hash", self.evidence_artifact_hash),
            ("measurement_artifact_hash", self.measurement_artifact_hash),
        ):
            _require_sha256(value, field=field)
        if not self.numeric_tolerance.is_finite() or self.numeric_tolerance < 0:
            raise ValueError(
                "Reproduction Manifest numeric tolerance must be finite and "
                "non-negative"
            )
        if not self.case_id.strip():
            raise ValueError("Reproduction Manifest case identity must not be blank")
        if self.layer not in (
            "baseline",
            "isolated_sensitivity",
            "compound",
        ):
            raise ValueError("Unsupported Reproduction Manifest campaign layer")
        expected_evidence_id = (
            f"diagnostic-evidence-{self.evidence_artifact_hash[:24]}"
        )
        if self.evidence_package_id != expected_evidence_id:
            raise ValueError(
                "Reproduction Manifest evidence identity does not match its "
                "artifact hash"
            )
        accepted = self.accepted_result
        required_result_keys = {
            "orders",
            "fills",
            "portfolio",
            "equity_curve",
            "metrics",
            "evidence",
        }
        if set(accepted) != required_result_keys:
            raise ValueError(
                "Reproduction Manifest accepted result schema mismatch"
            )
        if not isinstance(accepted["evidence"], Mapping):
            raise ValueError(
                "Reproduction Manifest evidence projection must be an object"
            )

    @property
    def specification(self) -> StrategyRunSpecification:
        payload = json.loads(self.strategy_run_specification_json)
        if not isinstance(payload, dict):
            raise ValueError(
                "Reproduction Manifest Strategy Run specification must be an object"
            )
        return StrategyRunSpecification.from_pinned_dict(
            cast(Mapping[str, object], payload)
        )

    @property
    def run_id(self) -> str:
        return self.specification.run_id

    @property
    def accepted_result(self) -> dict[str, object]:
        payload = json.loads(self.accepted_result_json)
        if not isinstance(payload, dict):
            raise ValueError(
                "Reproduction Manifest accepted result must be an object"
            )
        return cast(dict[str, object], payload)

    @property
    def evidence_reference_id(self) -> str:
        return (
            "reproduction-manifest-"
            f"{_canonical_hash(self._reference_payload())[:24]}"
        )

    @property
    def manifest_content_hash(self) -> str:
        return _canonical_hash(self._manifest_payload())

    @property
    def manifest_id(self) -> str:
        return (
            "reproduction-manifest-"
            f"{self.manifest_content_hash[:24]}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self._manifest_payload(),
            "manifest_id": self.manifest_id,
            "manifest_content_hash": self.manifest_content_hash,
        }

    def _reference_payload(self) -> dict[str, object]:
        return {
            "strategy_run_specification": self.specification.to_dict(),
            "run_id": self.run_id,
            "run_artifact_hash": self.run_artifact_hash,
            "numeric_tolerance": _decimal_text(self.numeric_tolerance),
        }

    def _manifest_payload(self) -> dict[str, object]:
        return {
            "schema_version": REPRODUCTION_MANIFEST_SCHEMA_VERSION,
            "evidence_reference_id": self.evidence_reference_id,
            **self._reference_payload(),
            "case_id": self.case_id,
            "layer": self.layer,
            "evidence_package_id": self.evidence_package_id,
            "evidence_artifact_hash": self.evidence_artifact_hash,
            "measurement_artifact_hash": self.measurement_artifact_hash,
            "accepted_result": self.accepted_result,
        }

    @classmethod
    def create(
        cls,
        *,
        specification: StrategyRunSpecification,
        run_artifact_hash: str,
        numeric_tolerance: Decimal,
        case_id: str,
        layer: ReproductionLayer,
        evidence_package_id: str,
        evidence_artifact_hash: str,
        measurement_artifact_hash: str,
        accepted_result: Mapping[str, object],
    ) -> "ReproductionManifest":
        return cls(
            strategy_run_specification_json=_canonical_json(
                specification.to_dict()
            ),
            run_artifact_hash=run_artifact_hash,
            numeric_tolerance=numeric_tolerance,
            case_id=case_id,
            layer=layer,
            evidence_package_id=evidence_package_id,
            evidence_artifact_hash=evidence_artifact_hash,
            measurement_artifact_hash=measurement_artifact_hash,
            accepted_result_json=_canonical_json(dict(accepted_result)),
        )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ReproductionManifest":
        required_keys = {
            "schema_version",
            "manifest_id",
            "manifest_content_hash",
            "evidence_reference_id",
            "strategy_run_specification",
            "run_id",
            "run_artifact_hash",
            "numeric_tolerance",
            "case_id",
            "layer",
            "evidence_package_id",
            "evidence_artifact_hash",
            "measurement_artifact_hash",
            "accepted_result",
        }
        if set(payload) != required_keys:
            raise ValueError("Reproduction Manifest schema mismatch")
        if payload["schema_version"] != REPRODUCTION_MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported Reproduction Manifest schema version")
        specification = cast(
            Mapping[str, object],
            payload["strategy_run_specification"],
        )
        accepted_result = cast(
            Mapping[str, object],
            payload["accepted_result"],
        )
        manifest = cls.create(
            specification=StrategyRunSpecification.from_pinned_dict(
                specification
            ),
            run_artifact_hash=str(payload["run_artifact_hash"]),
            numeric_tolerance=Decimal(str(payload["numeric_tolerance"])),
            case_id=str(payload["case_id"]),
            layer=cast(ReproductionLayer, str(payload["layer"])),
            evidence_package_id=str(payload["evidence_package_id"]),
            evidence_artifact_hash=str(payload["evidence_artifact_hash"]),
            measurement_artifact_hash=str(
                payload["measurement_artifact_hash"]
            ),
            accepted_result=accepted_result,
        )
        if str(payload["run_id"]) != manifest.run_id:
            raise ValueError(
                "Reproduction Manifest run identity does not match its "
                "Strategy Run specification"
            )
        if (
            str(payload["evidence_reference_id"])
            != manifest.evidence_reference_id
        ):
            raise ValueError(
                "Reproduction Manifest evidence reference identity "
                "verification failed"
            )
        if str(payload["manifest_id"]) != manifest.manifest_id:
            raise ValueError("Reproduction Manifest identity verification failed")
        if (
            str(payload["manifest_content_hash"])
            != manifest.manifest_content_hash
        ):
            raise ValueError(
                "Reproduction Manifest content hash verification failed"
            )
        return manifest


@dataclass(frozen=True, slots=True)
class ReproductionMismatch:
    code: str
    path: str
    expected: str
    actual: str
    message: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.code, self.path, self.message)
        ):
            raise ValueError(
                "Reproduction mismatch code, path, and message must not be blank"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ReproductionMismatch":
        if set(payload) != {
            "code",
            "path",
            "expected",
            "actual",
            "message",
        }:
            raise ValueError("Reproduction mismatch schema mismatch")
        return cls(
            code=str(payload["code"]),
            path=str(payload["path"]),
            expected=str(payload["expected"]),
            actual=str(payload["actual"]),
            message=str(payload["message"]),
        )


@dataclass(frozen=True, slots=True)
class ReproductionCheck:
    category: str
    status: ReproductionCheckStatus
    message: str

    def __post_init__(self) -> None:
        if not self.category.strip() or not self.message.strip():
            raise ValueError(
                "Reproduction check category and message must not be blank"
            )
        if self.status not in (
            "exact",
            "within_tolerance",
            "mismatch",
            "not_run",
        ):
            raise ValueError("Unsupported Reproduction check status")

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "status": self.status,
            "message": self.message,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ReproductionCheck":
        if set(payload) != {"category", "status", "message"}:
            raise ValueError("Reproduction check schema mismatch")
        return cls(
            category=str(payload["category"]),
            status=cast(
                ReproductionCheckStatus,
                str(payload["status"]),
            ),
            message=str(payload["message"]),
        )


@dataclass(frozen=True, slots=True)
class ReproductionReport:
    manifest_id: str
    accepted_run_id: str
    reproduced_run_id: str | None
    status: ReproductionStatus
    numeric_tolerance: Decimal
    reproduced_run_artifact_hash: str | None
    checks: tuple[ReproductionCheck, ...]
    mismatches: tuple[ReproductionMismatch, ...]

    def __post_init__(self) -> None:
        if not self.manifest_id.strip() or not self.accepted_run_id.strip():
            raise ValueError(
                "Reproduction Report identities must not be blank"
            )
        if self.status not in (
            "reproduced_exactly",
            "reproduced_within_tolerance",
            "reproducibility_invalid",
        ):
            raise ValueError("Unsupported Reproduction Report status")
        if not self.numeric_tolerance.is_finite() or self.numeric_tolerance < 0:
            raise ValueError(
                "Reproduction Report numeric tolerance must be finite and "
                "non-negative"
            )
        if self.reproduced_run_artifact_hash is not None:
            _require_sha256(
                self.reproduced_run_artifact_hash,
                field="reproduced_run_artifact_hash",
            )
        if not self.checks:
            raise ValueError(
                "Reproduction Report must include observable checks"
            )
        if self.status == "reproducibility_invalid":
            if not self.mismatches:
                raise ValueError(
                    "An invalid reproduction must include mismatch reasons"
                )
        elif self.mismatches:
            raise ValueError(
                "A successful reproduction cannot include mismatches"
            )
        if self.status in (
            "reproduced_exactly",
            "reproduced_within_tolerance",
        ) and (
            self.reproduced_run_id is None
            or self.reproduced_run_artifact_hash is None
        ):
            raise ValueError(
                "A successful reproduction requires a completed run identity "
                "and artifact hash"
            )

    @property
    def attempt_id(self) -> str:
        return (
            "reproduction-attempt-"
            f"{_canonical_hash(self._report_payload())[:24]}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REPRODUCTION_REPORT_SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            **self._identity_payload(),
        }

    def _report_payload(self) -> dict[str, object]:
        return {
            "schema_version": REPRODUCTION_REPORT_SCHEMA_VERSION,
            **self._identity_payload(),
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "accepted_run_id": self.accepted_run_id,
            "reproduced_run_id": self.reproduced_run_id,
            "status": self.status,
            "numeric_tolerance": _decimal_text(self.numeric_tolerance),
            "reproduced_run_artifact_hash": (
                self.reproduced_run_artifact_hash
            ),
            "checks": [item.to_dict() for item in self.checks],
            "mismatches": [item.to_dict() for item in self.mismatches],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ReproductionReport":
        required_keys = {
            "schema_version",
            "attempt_id",
            "manifest_id",
            "accepted_run_id",
            "reproduced_run_id",
            "status",
            "numeric_tolerance",
            "reproduced_run_artifact_hash",
            "checks",
            "mismatches",
        }
        if set(payload) != required_keys:
            raise ValueError("Reproduction Report schema mismatch")
        if payload["schema_version"] != REPRODUCTION_REPORT_SCHEMA_VERSION:
            raise ValueError("Unsupported Reproduction Report schema version")
        checks = cast(Sequence[object], payload["checks"])
        mismatches = cast(Sequence[object], payload["mismatches"])
        report = cls(
            manifest_id=str(payload["manifest_id"]),
            accepted_run_id=str(payload["accepted_run_id"]),
            reproduced_run_id=(
                str(payload["reproduced_run_id"])
                if payload.get("reproduced_run_id") is not None
                else None
            ),
            status=cast(ReproductionStatus, str(payload["status"])),
            numeric_tolerance=Decimal(str(payload["numeric_tolerance"])),
            reproduced_run_artifact_hash=(
                str(payload["reproduced_run_artifact_hash"])
                if payload.get("reproduced_run_artifact_hash") is not None
                else None
            ),
            checks=tuple(
                ReproductionCheck.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in checks
            ),
            mismatches=tuple(
                ReproductionMismatch.from_dict(
                    cast(Mapping[str, object], item)
                )
                for item in mismatches
            ),
        )
        if str(payload["attempt_id"]) != report.attempt_id:
            raise ValueError("Reproduction Report identity verification failed")
        return report


def _validate_report_against_manifest(
    report: ReproductionReport,
    manifest: ReproductionManifest,
) -> None:
    if (
        report.manifest_id != manifest.manifest_id
        or report.accepted_run_id != manifest.run_id
        or report.numeric_tolerance != manifest.numeric_tolerance
    ):
        raise ValueError(
            "Reproduction Report does not match its Reproduction Manifest"
        )


class ReproductionRepository(Protocol):
    def add_manifests(
        self,
        manifests: Sequence[ReproductionManifest],
    ) -> None: ...

    def get_manifest(self, manifest_id: str) -> ReproductionManifest: ...

    def list_manifests(
        self,
        evidence_package_id: str,
    ) -> tuple[ReproductionManifest, ...]: ...

    def manifest_format_identity(
        self,
        evidence_package_id: str,
        manifest_id: str,
    ) -> str | None: ...

    def save_report(self, report: ReproductionReport) -> None: ...

    def latest_report(self, manifest_id: str) -> ReproductionReport | None: ...


class InMemoryReproductionRepository:
    def __init__(self) -> None:
        self._manifests: dict[str, ReproductionManifest] = {}
        self._reports: dict[str, ReproductionReport] = {}

    def add_manifests(
        self,
        manifests: Sequence[ReproductionManifest],
    ) -> None:
        pending: dict[str, ReproductionManifest] = {}
        for manifest in manifests:
            pending_existing = pending.get(manifest.manifest_id)
            stored_existing = self._manifests.get(manifest.manifest_id)
            if (
                pending_existing is not None
                and pending_existing != manifest
            ) or (
                stored_existing is not None
                and stored_existing != manifest
            ):
                raise ValueError(
                    "Reproduction Manifest identity collision"
                )
            pending[manifest.manifest_id] = manifest
        self._manifests.update(pending)

    def get_manifest(self, manifest_id: str) -> ReproductionManifest:
        try:
            return self._manifests[manifest_id]
        except KeyError as error:
            raise KeyError("Unknown Reproduction Manifest") from error

    def list_manifests(
        self,
        evidence_package_id: str,
    ) -> tuple[ReproductionManifest, ...]:
        return tuple(
            sorted(
                (
                    manifest
                    for manifest in self._manifests.values()
                    if manifest.evidence_package_id == evidence_package_id
                ),
                key=lambda item: item.manifest_id,
            )
        )

    def manifest_format_identity(
        self,
        evidence_package_id: str,
        manifest_id: str,
    ) -> str | None:
        manifest = self._manifests.get(manifest_id)
        if (
            manifest is None
            or manifest.evidence_package_id != evidence_package_id
        ):
            return None
        value = manifest.to_dict().get("schema_version")
        return str(value) if value is not None else None

    def save_report(self, report: ReproductionReport) -> None:
        manifest = self.get_manifest(report.manifest_id)
        _validate_report_against_manifest(report, manifest)
        self._reports[report.manifest_id] = report

    def latest_report(self, manifest_id: str) -> ReproductionReport | None:
        report = self._reports.get(manifest_id)
        if report is not None:
            _validate_report_against_manifest(
                report,
                self.get_manifest(manifest_id),
            )
        return report


_TOLERANT_NUMERIC_FIELDS = frozenset(
    {
        "accepted_shares",
        "average_cost",
        "cash",
        "cash_change",
        "commission",
        "equity",
        "execution_erosion",
        "execution_price",
        "gross_value",
        "market_price",
        "market_value",
        "positions_value",
        "price",
        "price_limit_lower",
        "price_limit_upper",
        "reference_price",
        "slippage_bps",
        "stamp_duty",
        "total",
        "transfer_fee",
        "unrealized_pnl",
        "value",
    }
)


class ReproductionService:
    """Accept sealed run evidence and rerun it without dependency substitution."""

    def __init__(
        self,
        *,
        run_loader: Callable[[str], StrategyRunSnapshot],
        recipe_hash_loader: Callable[[str], str],
        path_loader: Callable[[str], MaterializedMarketPath],
        evidence_loader: Callable[[str], DiagnosticEvidencePackage],
        source_snapshot_loader: Callable[[str], SourceSnapshot],
        replay_run: Callable[[StrategyRunSpecification], StrategyRunSnapshot],
        code_identity: str,
        repository: ReproductionRepository | None = None,
    ) -> None:
        self._run_loader = run_loader
        self._recipe_hash_loader = recipe_hash_loader
        self._path_loader = path_loader
        self._evidence_loader = evidence_loader
        self._source_snapshot_loader = source_snapshot_loader
        self._replay_run = replay_run
        self._code_identity = code_identity
        self._repository = (
            repository
            if repository is not None
            else InMemoryReproductionRepository()
        )

    def replace_repository(
        self,
        repository: ReproductionRepository,
    ) -> None:
        self._repository = repository

    def accept_evidence(
        self,
        package: DiagnosticEvidencePackage,
    ) -> tuple[ReproductionManifest, ...]:
        payload = package.sealed_payload()
        metrics = tuple(
            cast(Mapping[str, object], item)
            for item in cast(Sequence[object], payload["metrics"])
        )
        manifests: list[ReproductionManifest] = []
        for reference_value in cast(
            Sequence[object],
            payload["reproduction_manifests"],
        ):
            reference = cast(Mapping[str, object], reference_value)
            specification = StrategyRunSpecification.from_pinned_dict(
                cast(
                    Mapping[str, object],
                    reference["strategy_run_specification"],
                )
            )
            run_id = str(reference["run_id"])
            if specification.run_id != run_id:
                raise ValueError(
                    "Evidence Reproduction Manifest run identity mismatch"
                )
            snapshot = self._run_loader(run_id)
            if (
                snapshot.status != "completed"
                or snapshot.run_artifact_hash is None
                or snapshot.run_artifact_hash
                != str(reference["run_artifact_hash"])
                or snapshot.specification != specification
            ):
                raise ValueError(
                    "Only the exact completed Strategy Run can be accepted "
                    "for reproduction"
                )
            run_metrics = tuple(
                item for item in metrics if item["run_id"] == run_id
            )
            case_ids = {str(item["case_id"]) for item in run_metrics}
            layers = {str(item["layer"]) for item in run_metrics}
            if len(case_ids) != 1 or len(layers) != 1:
                raise ValueError(
                    "Accepted Strategy Run metrics require one case and layer"
                )
            case_id = next(iter(case_ids))
            layer = cast(ReproductionLayer, next(iter(layers)))
            accepted_result = _accepted_result(
                snapshot,
                run_metrics,
                _evidence_projection(payload, run_id),
            )
            manifest = ReproductionManifest.create(
                specification=specification,
                run_artifact_hash=snapshot.run_artifact_hash,
                numeric_tolerance=Decimal(
                    str(reference["numeric_tolerance"])
                ),
                case_id=case_id,
                layer=layer,
                evidence_package_id=package.evidence_package_id,
                evidence_artifact_hash=package.artifact_hash,
                measurement_artifact_hash=str(
                    payload["measurement_artifact_hash"]
                ),
                accepted_result=accepted_result,
            )
            if manifest.evidence_reference_id != str(
                reference["reproduction_manifest_id"]
            ):
                raise ValueError(
                    "Evidence Reproduction Manifest identity does not match "
                    "the formal manifest"
                )
            manifests.append(manifest)
        self._repository.add_manifests(manifests)
        return tuple(sorted(manifests, key=lambda item: item.manifest_id))

    def manifests_for(
        self,
        evidence_package_id: str,
    ) -> tuple[ReproductionManifest, ...]:
        return self._repository.list_manifests(evidence_package_id)

    def manifest_format_identity(
        self,
        evidence_package_id: str,
        manifest_id: str,
    ) -> str | None:
        """Read only the stored format identity without model deserialization."""

        return self._repository.manifest_format_identity(
            evidence_package_id,
            manifest_id,
        )

    def latest_report(
        self,
        manifest_id: str,
    ) -> ReproductionReport | None:
        self._repository.get_manifest(manifest_id)
        return self._repository.latest_report(manifest_id)

    def reproduce(self, manifest_id: str) -> ReproductionReport:
        manifest = self._repository.get_manifest(manifest_id)
        dependency_mismatches, evidence = self._validate_dependencies(
            manifest
        )
        if dependency_mismatches:
            report = _invalid_report(
                manifest,
                dependency_mismatches,
                category="dependencies",
            )
            self._repository.save_report(report)
            return report
        try:
            replayed = self._replay_run(manifest.specification)
        except Exception as error:
            report = _invalid_report(
                manifest,
                (
                    ReproductionMismatch(
                        code="dependency.execution_environment",
                        path="strategy_run",
                        expected="pinned execution environment",
                        actual=type(error).__name__,
                        message=str(error),
                    ),
                ),
                category="dependencies",
            )
            self._repository.save_report(report)
            return report
        if replayed.status != "completed" or replayed.run_artifact_hash is None:
            report = _invalid_report(
                manifest,
                (
                    ReproductionMismatch(
                        code="result.run_not_completed",
                        path="status",
                        expected="completed",
                        actual=replayed.status,
                        message=(
                            replayed.failure_message
                            or "Reproduced Strategy Run did not complete"
                        ),
                    ),
                ),
                category="strategy_run",
                reproduced_run_id=replayed.run_id,
                reproduced_run_artifact_hash=replayed.run_artifact_hash,
            )
            self._repository.save_report(report)
            return report
        path = self._path_loader(
            manifest.specification.materialization_hash
        )
        reproduced_metrics = calculate_run_evidence_metrics(
            snapshot=replayed,
            path=path,
            case_id=manifest.case_id,
            layer=manifest.layer,
            reproduction_manifest_id=manifest.evidence_reference_id,
        )
        accepted = manifest.accepted_result
        replayed_view = replayed.to_dict()
        categories = (
            ("orders", accepted["orders"], replayed_view["orders"]),
            ("fills", accepted["fills"], replayed_view["fills"]),
            (
                "portfolio",
                accepted["portfolio"],
                replayed_view["portfolio"],
            ),
            (
                "equity_curve",
                accepted["equity_curve"],
                replayed_view["equity_curve"],
            ),
            (
                "metrics",
                _comparable_metrics(accepted["metrics"]),
                _comparable_metrics(reproduced_metrics),
            ),
        )
        checks: list[ReproductionCheck] = [
            ReproductionCheck(
                category="dependencies",
                status="exact",
                message="Every pinned dependency is available and unchanged.",
            )
        ]
        mismatches: list[ReproductionMismatch] = []
        used_tolerance = False
        for category, expected, actual in categories:
            category_mismatches, category_tolerance = _compare_values(
                expected,
                actual,
                tolerance=manifest.numeric_tolerance,
                path=category,
            )
            mismatches.extend(category_mismatches)
            used_tolerance = used_tolerance or category_tolerance
            checks.append(
                ReproductionCheck(
                    category=category,
                    status=(
                        "mismatch"
                        if category_mismatches
                        else (
                            "within_tolerance"
                            if category_tolerance
                            else "exact"
                        )
                    ),
                    message=(
                        "Mismatch exceeds the declared numeric tolerance."
                        if category_mismatches
                        else (
                            "Numeric differences remain within tolerance."
                            if category_tolerance
                            else "Accepted and reproduced values are identical."
                        )
                    ),
                )
            )
        accepted_evidence = cast(
            Mapping[str, object],
            accepted["evidence"],
        )
        current_evidence = (
            _evidence_projection(evidence.sealed_payload(), manifest.run_id)
            if evidence is not None
            else {}
        )
        if accepted_evidence != current_evidence:
            mismatches.append(
                ReproductionMismatch(
                    code="result.evidence_mismatch",
                    path="evidence",
                    expected=_canonical_json(accepted_evidence),
                    actual=_canonical_json(current_evidence),
                    message=(
                        "Sealed evidence references changed after acceptance."
                    ),
                )
            )
            checks.append(
                ReproductionCheck(
                    category="evidence",
                    status="mismatch",
                    message="Sealed evidence projection no longer matches.",
                )
            )
        else:
            checks.append(
                ReproductionCheck(
                    category="evidence",
                    status="exact",
                    message="Sealed evidence and hashes remain unchanged.",
                )
            )
        hash_matches = (
            replayed.run_artifact_hash == manifest.run_artifact_hash
        )
        if not hash_matches and not used_tolerance:
            mismatches.append(
                ReproductionMismatch(
                    code="result.run_artifact_hash_mismatch",
                    path="run_artifact_hash",
                    expected=manifest.run_artifact_hash,
                    actual=replayed.run_artifact_hash,
                    message=(
                        "Run artifact hash changed without an allowed numeric "
                        "difference."
                    ),
                )
            )
        checks.append(
            ReproductionCheck(
                category="hashes",
                status=(
                    "exact"
                    if hash_matches
                    else (
                        "within_tolerance"
                        if used_tolerance and not mismatches
                        else "mismatch"
                    )
                ),
                message=(
                    "Run artifact hash is identical."
                    if hash_matches
                    else (
                        "Hash changed only because tolerated numeric values changed."
                        if used_tolerance and not mismatches
                        else "Run artifact hash does not match."
                    )
                ),
            )
        )
        status: ReproductionStatus
        if mismatches:
            status = "reproducibility_invalid"
        elif hash_matches and not used_tolerance:
            status = "reproduced_exactly"
        else:
            status = "reproduced_within_tolerance"
        report = ReproductionReport(
            manifest_id=manifest.manifest_id,
            accepted_run_id=manifest.run_id,
            reproduced_run_id=replayed.run_id,
            status=status,
            numeric_tolerance=manifest.numeric_tolerance,
            reproduced_run_artifact_hash=replayed.run_artifact_hash,
            checks=tuple(checks),
            mismatches=tuple(mismatches),
        )
        self._repository.save_report(report)
        return report

    def _validate_dependencies(
        self,
        manifest: ReproductionManifest,
    ) -> tuple[
        tuple[ReproductionMismatch, ...],
        DiagnosticEvidencePackage | None,
    ]:
        specification = manifest.specification
        mismatches: list[ReproductionMismatch] = []
        try:
            recipe_hash = self._recipe_hash_loader(
                specification.recipe_version_id
            )
        except Exception as error:
            mismatches.append(
                ReproductionMismatch(
                    code="dependency.recipe_missing",
                    path="strategy_run_specification.recipe_version_id",
                    expected=specification.recipe_version_id,
                    actual=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            if recipe_hash != specification.recipe_content_hash:
                mismatches.append(
                    ReproductionMismatch(
                        code="dependency.recipe_hash_changed",
                        path="strategy_run_specification.recipe_content_hash",
                        expected=specification.recipe_content_hash,
                        actual=recipe_hash,
                        message=(
                            "Pinned recipe version no longer has its accepted "
                            "content hash."
                        ),
                    )
                )
        try:
            source_snapshot = self._source_snapshot_loader(
                specification.source_snapshot_id
            )
        except Exception as error:
            mismatches.append(
                ReproductionMismatch(
                    code="dependency.source_snapshot_missing",
                    path="strategy_run_specification.source_snapshot_id",
                    expected=specification.source_snapshot_id,
                    actual=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            if source_snapshot.snapshot_id != specification.source_snapshot_id:
                mismatches.append(
                    ReproductionMismatch(
                        code="dependency.source_snapshot_changed",
                        path="strategy_run_specification.source_snapshot_id",
                        expected=specification.source_snapshot_id,
                        actual=source_snapshot.snapshot_id,
                        message=(
                            "Pinned source snapshot identity no longer matches "
                            "the accepted run."
                        ),
                    )
                )
        try:
            path = self._path_loader(specification.materialization_hash)
        except Exception as error:
            mismatches.append(
                ReproductionMismatch(
                    code="dependency.materialization_missing",
                    path="strategy_run_specification.materialization_hash",
                    expected=specification.materialization_hash,
                    actual=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            expected_path_identity = (
                specification.materialization_hash,
                specification.source_snapshot_id,
                specification.materialization_seed,
                specification.transformation_catalog_version,
                specification.market_rule_profile_version,
                specification.transformation_implementation_versions,
            )
            actual_path_identity = (
                path.artifact_hash,
                path.source_snapshot_id,
                path.seed,
                path.transformation_catalog_version,
                path.market_rule_profile_version,
                tuple(
                    f"{item.transformation_id}@{item.implementation_version}"
                    for item in path.applied_transformations
                ),
            )
            if actual_path_identity != expected_path_identity:
                mismatches.append(
                    ReproductionMismatch(
                        code="dependency.materialization_changed",
                        path="strategy_run_specification.materialization",
                        expected=_canonical_json(expected_path_identity),
                        actual=_canonical_json(actual_path_identity),
                        message=(
                            "Pinned materialization dependencies no longer "
                            "match the accepted path."
                        ),
                    )
                )
        if specification.code_identity != self._code_identity:
            mismatches.append(
                ReproductionMismatch(
                    code="dependency.code_identity_changed",
                    path="strategy_run_specification.code_identity",
                    expected=specification.code_identity,
                    actual=self._code_identity,
                    message=(
                        "Current diagnostic code identity does not match the "
                        "accepted run."
                    ),
                )
            )
        evidence: DiagnosticEvidencePackage | None = None
        try:
            evidence = self._evidence_loader(
                manifest.evidence_package_id
            )
        except Exception as error:
            mismatches.append(
                ReproductionMismatch(
                    code="dependency.evidence_missing",
                    path="evidence_package_id",
                    expected=manifest.evidence_package_id,
                    actual=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            evidence_view = evidence.sealed_payload()
            if (
                evidence.artifact_hash != manifest.evidence_artifact_hash
                or str(evidence_view["measurement_artifact_hash"])
                != manifest.measurement_artifact_hash
            ):
                mismatches.append(
                    ReproductionMismatch(
                        code="dependency.evidence_hash_changed",
                        path="evidence_artifact_hash",
                        expected=(
                            f"{manifest.evidence_artifact_hash}/"
                            f"{manifest.measurement_artifact_hash}"
                        ),
                        actual=(
                            f"{evidence.artifact_hash}/"
                            f"{evidence_view['measurement_artifact_hash']}"
                        ),
                        message=(
                            "Accepted sealed evidence hashes no longer match."
                        ),
                    )
                )
        return tuple(mismatches), evidence


def _accepted_result(
    snapshot: StrategyRunSnapshot,
    metrics: Sequence[Mapping[str, object]],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    view = snapshot.to_dict()
    return {
        "orders": view["orders"],
        "fills": view["fills"],
        "portfolio": view["portfolio"],
        "equity_curve": view["equity_curve"],
        "metrics": sorted(
            (dict(item) for item in metrics),
            key=lambda item: str(item["name"]),
        ),
        "evidence": dict(evidence),
    }


def _evidence_projection(
    payload: Mapping[str, object],
    run_id: str,
) -> dict[str, object]:
    metrics = tuple(
        cast(Mapping[str, object], item)
        for item in cast(Sequence[object], payload["metrics"])
    )
    comparisons = tuple(
        cast(Mapping[str, object], item)
        for item in cast(Sequence[object], payload["comparisons"])
    )
    breaches = tuple(
        cast(Mapping[str, object], item)
        for item in cast(
            Sequence[object],
            payload["guardrail_breaches"],
        )
    )
    breakpoints = tuple(
        cast(Mapping[str, object], item)
        for item in cast(
            Sequence[object],
            payload["sensitivity_breakpoints"],
        )
    )
    findings = tuple(
        cast(Mapping[str, object], item)
        for item in cast(
            Sequence[object],
            payload["diagnostic_findings"],
        )
    )
    return {
        "metric_ids": sorted(
            str(item["metric_id"])
            for item in metrics
            if item["run_id"] == run_id
        ),
        "comparison_ids": sorted(
            str(item["comparison_id"])
            for item in comparisons
            if run_id in (
                item["subject_run_id"],
                item["control_run_id"],
            )
        ),
        "breach_ids": sorted(
            str(item["breach_id"])
            for item in breaches
            if item["run_id"] == run_id
        ),
        "breakpoint_ids": sorted(
            str(item["breakpoint_id"])
            for item in breakpoints
            if run_id in cast(Sequence[object], item["run_ids"])
        ),
        "finding_ids": sorted(
            str(item["finding_id"])
            for item in findings
            if run_id in cast(Sequence[object], item["run_ids"])
        ),
    }


def _comparable_metrics(value: object) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item_value in cast(Sequence[object], value):
        item = cast(Mapping[str, object], item_value)
        result.append(
            {
                key: item[key]
                for key in (
                    "family",
                    "name",
                    "value",
                    "case_id",
                    "layer",
                    "strategy_id",
                    "strategy_version",
                    "run_id",
                )
            }
        )
    return sorted(result, key=lambda item: str(item["name"]))


def _compare_values(
    expected: object,
    actual: object,
    *,
    tolerance: Decimal,
    path: str,
) -> tuple[list[ReproductionMismatch], bool]:
    if type(expected) is not type(actual):
        return (
            [
                ReproductionMismatch(
                    code="result.type_mismatch",
                    path=path,
                    expected=type(expected).__name__,
                    actual=type(actual).__name__,
                    message="Accepted and reproduced value types differ.",
                )
            ],
            False,
        )
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        if set(expected) != set(actual):
            return (
                [
                    ReproductionMismatch(
                        code="result.schema_mismatch",
                        path=path,
                        expected=_canonical_json(sorted(expected)),
                        actual=_canonical_json(sorted(actual)),
                        message=(
                            "Accepted and reproduced object fields differ."
                        ),
                    )
                ],
                False,
            )
        mismatches: list[ReproductionMismatch] = []
        used_tolerance = False
        for key in sorted(expected):
            child_mismatches, child_tolerance = _compare_values(
                expected[key],
                actual[key],
                tolerance=tolerance,
                path=f"{path}.{key}",
            )
            mismatches.extend(child_mismatches)
            used_tolerance = used_tolerance or child_tolerance
        return mismatches, used_tolerance
    if isinstance(expected, Sequence) and not isinstance(
        expected,
        (str, bytes),
    ) and isinstance(actual, Sequence) and not isinstance(
        actual,
        (str, bytes),
    ):
        if len(expected) != len(actual):
            return (
                [
                    ReproductionMismatch(
                        code="result.length_mismatch",
                        path=path,
                        expected=str(len(expected)),
                        actual=str(len(actual)),
                        message=(
                            "Accepted and reproduced collections differ in "
                            "length."
                        ),
                    )
                ],
                False,
            )
        mismatches = []
        used_tolerance = False
        for index, (expected_item, actual_item) in enumerate(
            zip(expected, actual, strict=True)
        ):
            child_mismatches, child_tolerance = _compare_values(
                expected_item,
                actual_item,
                tolerance=tolerance,
                path=f"{path}[{index}]",
            )
            mismatches.extend(child_mismatches)
            used_tolerance = used_tolerance or child_tolerance
        return mismatches, used_tolerance
    if expected == actual:
        return [], False
    field = path.rsplit(".", 1)[-1]
    if field in _TOLERANT_NUMERIC_FIELDS:
        try:
            expected_decimal = Decimal(str(expected))
            actual_decimal = Decimal(str(actual))
        except Exception:
            pass
        else:
            difference = abs(expected_decimal - actual_decimal)
            if difference <= tolerance:
                return [], True
            return (
                [
                    ReproductionMismatch(
                        code="result.numeric_tolerance_exceeded",
                        path=path,
                        expected=str(expected),
                        actual=str(actual),
                        message=(
                            f"Numeric difference {difference} exceeds declared "
                            f"tolerance {tolerance}."
                        ),
                    )
                ],
                False,
            )
    return (
        [
            ReproductionMismatch(
                code="result.value_mismatch",
                path=path,
                expected=str(expected),
                actual=str(actual),
                message="Accepted and reproduced values differ.",
            )
        ],
        False,
    )


def _invalid_report(
    manifest: ReproductionManifest,
    mismatches: tuple[ReproductionMismatch, ...],
    *,
    category: str,
    reproduced_run_id: str | None = None,
    reproduced_run_artifact_hash: str | None = None,
) -> ReproductionReport:
    return ReproductionReport(
        manifest_id=manifest.manifest_id,
        accepted_run_id=manifest.run_id,
        reproduced_run_id=reproduced_run_id,
        status="reproducibility_invalid",
        numeric_tolerance=manifest.numeric_tolerance,
        reproduced_run_artifact_hash=reproduced_run_artifact_hash,
        checks=(
            ReproductionCheck(
                category=category,
                status="mismatch",
                message="Reproduction stopped with visible mismatch reasons.",
            ),
        ),
        mismatches=mismatches,
    )


__all__ = [
    "DIAGNOSTIC_CODE_IDENTITY",
    "InMemoryReproductionRepository",
    "REPRODUCTION_MANIFEST_SCHEMA_VERSION",
    "ReproductionCheck",
    "ReproductionManifest",
    "ReproductionMismatch",
    "ReproductionReport",
    "ReproductionRepository",
    "ReproductionService",
]
