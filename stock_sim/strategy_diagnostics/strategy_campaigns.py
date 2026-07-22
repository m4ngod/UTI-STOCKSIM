"""Comparable, isolated two-strategy Baseline Campaign execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Literal, Protocol

from .ptrade_host import PTRADE_SUBPROCESS_HOST_VERSION
from .strategy_runs import (
    EquityPoint,
    StrategyRunSnapshot,
    StrategyRunSpecification,
)


CampaignStatus = Literal["completed", "incomplete"]
RANDOM_SOURCE_VERSION = "materialization_seed+decision_index.v1"
BASELINE_CAMPAIGN_COMMISSION_BPS = Decimal("3")
BASELINE_CAMPAIGN_SLIPPAGE_BPS = Decimal("5")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


@dataclass(frozen=True, slots=True)
class BaselineCampaignSpecification:
    """Two strategy identities pinned to one controlled comparison world."""

    campaign_replica_id: str
    strategy_runs: tuple[StrategyRunSpecification, StrategyRunSpecification]

    def __post_init__(self) -> None:
        if not self.campaign_replica_id.strip():
            raise ValueError("campaign replica id must not be blank")
        first, second = self.strategy_runs
        if (first.strategy_id, first.strategy_version) == (
            second.strategy_id,
            second.strategy_version,
        ):
            raise ValueError("Baseline Campaign requires two different strategies")
        if first.replica_id == second.replica_id:
            raise ValueError("Baseline Campaign replica ids must be unique")
        if first.run_id == second.run_id:
            raise ValueError("Baseline Campaign run ids must be unique")
        if any(
            item.ptrade_host_adapter_version != PTRADE_SUBPROCESS_HOST_VERSION
            for item in self.strategy_runs
        ):
            raise ValueError(
                "Baseline Campaign requires production subprocess isolation"
            )
        comparisons: tuple[tuple[str, object, object], ...] = (
            ("recipe version", first.recipe_version_id, second.recipe_version_id),
            ("recipe content hash", first.recipe_content_hash, second.recipe_content_hash),
            ("materialization hash", first.materialization_hash, second.materialization_hash),
            ("source snapshot", first.source_snapshot_id, second.source_snapshot_id),
            (
                "controlled random source",
                first.materialization_seed,
                second.materialization_seed,
            ),
            (
                "transformation catalog",
                first.transformation_catalog_version,
                second.transformation_catalog_version,
            ),
            (
                "transformation implementations",
                first.transformation_implementation_versions,
                second.transformation_implementation_versions,
            ),
            (
                "Market Rule Profile",
                first.market_rule_profile_version,
                second.market_rule_profile_version,
            ),
            (
                "Execution Policy",
                first.execution_policy_version,
                second.execution_policy_version,
            ),
            (
                "decision cadence",
                first.decision_cadence_minutes,
                second.decision_cadence_minutes,
            ),
            ("initial cash", first.initial_cash, second.initial_cash),
            ("order shares", first.order_shares, second.order_shares),
            ("code identity", first.code_identity, second.code_identity),
            (
                "PTrade surface",
                first.ptrade_surface_version,
                second.ptrade_surface_version,
            ),
            (
                "PTrade host",
                first.ptrade_host_adapter_version,
                second.ptrade_host_adapter_version,
            ),
            ("commission", first.commission_bps, second.commission_bps),
            (
                "minimum commission",
                first.minimum_commission,
                second.minimum_commission,
            ),
            ("transfer fee", first.transfer_fee_bps, second.transfer_fee_bps),
            (
                "sell stamp duty",
                first.sell_stamp_duty_bps,
                second.sell_stamp_duty_bps,
            ),
            (
                "resolved execution conditions",
                first.resolved_execution_conditions,
                second.resolved_execution_conditions,
            ),
            ("run engine", first.engine_version, second.engine_version),
        )
        for label, first_value, second_value in comparisons:
            if first_value != second_value:
                raise ValueError(
                    f"Baseline Campaign requires the same {label} for both replicas"
                )
        conditions = first.resolved_execution_conditions
        if conditions is None:
            raise ValueError(
                "Baseline Campaign requires pinned requested execution conditions"
            )
        if (
            conditions.requested.commission_bps
            != BASELINE_CAMPAIGN_COMMISSION_BPS
            or conditions.requested.slippage_bps
            != BASELINE_CAMPAIGN_SLIPPAGE_BPS
        ):
            raise ValueError(
                "Baseline Campaign requires a recipe with requested slippage 5 bps "
                "and commission 3 bps; create, approve, and materialize a compatible "
                "recipe before launch"
            )

    @property
    def campaign_id(self) -> str:
        return f"baseline-campaign-{_canonical_hash(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_replica_id": self.campaign_replica_id,
            "strategy_runs": [item.to_dict() for item in self.strategy_runs],
        }


class _StrategyRunExecutor(Protocol):
    def get(self, run_id: str) -> StrategyRunSnapshot: ...

    def start(self, specification: StrategyRunSpecification) -> StrategyRunSnapshot: ...

    def resume(self, run_id: str) -> StrategyRunSnapshot: ...

    def run_to_completion(
        self,
        run_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> StrategyRunSnapshot: ...


@dataclass(frozen=True, slots=True)
class CampaignMemberResult:
    specification: StrategyRunSpecification
    snapshot: StrategyRunSnapshot | None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def status(self) -> str:
        if self.snapshot is not None:
            return str(self.snapshot.status)
        return "failed"

    def to_dict(self) -> dict[str, object]:
        if self.snapshot is not None:
            payload: dict[str, object] = dict(self.snapshot.to_dict())
        else:
            payload = {
                "run_id": self.specification.run_id,
                "status": "failed",
                "specification": self.specification.to_dict(),
                "materialization_hash": self.specification.materialization_hash,
                "decision_times": [],
                "orders": [],
                "fills": [],
                "portfolio": {
                    "cash": _decimal_text(self.specification.initial_cash),
                    "positions": [],
                },
                "equity_curve": [],
                "failure": {
                    "code": self.failure_code,
                    "message": self.failure_message,
                },
                "run_artifact_hash": None,
            }
        payload.update(
            {
                "strategy_id": self.specification.strategy_id,
                "strategy_version": self.specification.strategy_version,
                "replica_id": self.specification.replica_id,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class BaselineCampaignSnapshot:
    specification: BaselineCampaignSpecification
    members: tuple[CampaignMemberResult, CampaignMemberResult]

    @property
    def campaign_id(self) -> str:
        return self.specification.campaign_id

    @property
    def completed_count(self) -> int:
        return sum(item.status == "completed" for item in self.members)

    @property
    def identical_observed_timeline(self) -> bool:
        if self.completed_count != len(self.members):
            return False
        timelines = tuple(_equity_times(item.snapshot) for item in self.members)
        return bool(timelines[0]) and timelines[0] == timelines[1]

    @property
    def subprocess_isolation_verified(self) -> bool:
        for member in self.members:
            snapshot = member.snapshot
            if snapshot is None or snapshot.ptrade_audit is None:
                return False
            audit = snapshot.ptrade_audit
            specification = member.specification
            if (
                audit.surface_version != specification.ptrade_surface_version
                or audit.manifest_hash != specification.ptrade_manifest_hash
                or audit.strategy_id != specification.strategy_id
                or audit.strategy_version != specification.strategy_version
                or audit.host_adapter_versions
                != (PTRADE_SUBPROCESS_HOST_VERSION,)
            ):
                return False
        return True

    @property
    def status(self) -> CampaignStatus:
        if (
            self.completed_count == 2
            and self.identical_observed_timeline
            and self.subprocess_isolation_verified
        ):
            return "completed"
        return "incomplete"

    def to_dict(self) -> dict[str, object]:
        first = self.specification.strategy_runs[0]
        complete = self.status == "completed"
        label = f"{self.completed_count}/2 complete"
        if self.completed_count == 2 and not complete:
            label = "2/2 runs complete; comparison incomplete"
        timelines = tuple(_equity_times(item.snapshot) for item in self.members)
        observed_count = len(timelines[0]) if timelines[0] == timelines[1] else 0
        return {
            "campaign_id": self.campaign_id,
            "campaign_replica_id": self.specification.campaign_replica_id,
            "status": self.status,
            "completeness": {
                "completed_count": self.completed_count,
                "total_count": 2,
                "label": label,
                "is_complete": complete,
            },
            "pinned_conditions": {
                "materialization_hash": first.materialization_hash,
                "source_snapshot_id": first.source_snapshot_id,
                "materialization_seed": first.materialization_seed,
                "random_source": RANDOM_SOURCE_VERSION,
                "market_rule_profile_version": first.market_rule_profile_version,
                "execution_policy_version": first.execution_policy_version,
                "execution_conditions": (
                    first.resolved_execution_conditions.to_dict()
                    if first.resolved_execution_conditions is not None
                    else None
                ),
            },
            "shared_market_nodes": {
                "materialization_hash": first.materialization_hash,
                "identical_observed_timeline": self.identical_observed_timeline,
                "observed_node_count": observed_count,
                "simulation_times": (
                    [item.isoformat() for item in timelines[0]]
                    if timelines[0] == timelines[1]
                    else []
                ),
            },
            "isolation": {
                "execution_order": "sequential",
                "verification_status": (
                    "verified"
                    if self.subprocess_isolation_verified
                    else "unverified"
                ),
                "fresh_subprocess_per_callback": (
                    self.subprocess_isolation_verified
                ),
                "unique_run_ids": len(
                    {item.specification.run_id for item in self.members}
                )
                == 2,
                "unique_replica_ids": len(
                    {item.specification.replica_id for item in self.members}
                )
                == 2,
                "private_state_by_run_id": [
                    item.specification.run_id for item in self.members
                ],
                "isolated_surfaces": (
                    [
                        "strategy_process",
                        "strategy_globals",
                        "strategy_cache",
                        "orders",
                        "fills",
                        "account",
                        "failure",
                    ]
                    if self.subprocess_isolation_verified
                    else []
                ),
            },
            "members": [item.to_dict() for item in self.members],
            "equity_overlay": [
                _curve_series(item, drawdown=False) for item in self.members
            ],
            "drawdown_overlay": [
                _curve_series(item, drawdown=True) for item in self.members
            ],
        }


class BaselineCampaignRunner:
    """Run both isolated replicas in a deterministic sequential order."""

    def __init__(self, strategy_runs: _StrategyRunExecutor) -> None:
        self._strategy_runs = strategy_runs

    def run(
        self,
        specification: BaselineCampaignSpecification,
        *,
        nodes_per_batch: int = 10_000,
    ) -> BaselineCampaignSnapshot:
        if nodes_per_batch <= 0:
            raise ValueError("nodes per batch must be positive")
        members: list[CampaignMemberResult] = []
        for run_specification in specification.strategy_runs:
            try:
                try:
                    current = self._strategy_runs.get(
                        run_specification.run_id
                    )
                except (KeyError, ValueError):
                    current = self._strategy_runs.start(run_specification)
                if current.specification != run_specification:
                    raise ValueError(
                        "Existing Strategy Run does not belong to its campaign replica"
                    )
                if current.status == "paused":
                    current = self._strategy_runs.resume(current.run_id)
                completed = (
                    current
                    if current.status in ("completed", "failed", "cancelled")
                    else self._strategy_runs.run_to_completion(
                        current.run_id,
                        nodes_per_batch=nodes_per_batch,
                    )
                )
                if completed.specification != run_specification:
                    raise ValueError(
                        "Strategy Run result does not belong to its campaign replica"
                    )
                members.append(
                    CampaignMemberResult(run_specification, snapshot=completed)
                )
            except Exception as error:
                members.append(
                    CampaignMemberResult(
                        run_specification,
                        snapshot=None,
                        failure_code=type(error).__name__,
                        failure_message=str(error),
                    )
                )
        return BaselineCampaignSnapshot(
            specification=specification,
            members=(members[0], members[1]),
        )


def _equity_times(snapshot: StrategyRunSnapshot | None) -> tuple[datetime, ...]:
    if snapshot is None:
        return ()
    return tuple(item.simulation_time for item in snapshot.equity_curve)


def _curve_series(
    member: CampaignMemberResult,
    *,
    drawdown: bool,
) -> dict[str, object]:
    snapshot = member.snapshot
    points = snapshot.equity_curve if snapshot is not None else ()
    return {
        "strategy_id": member.specification.strategy_id,
        "strategy_version": member.specification.strategy_version,
        "run_id": member.specification.run_id,
        "replica_id": member.specification.replica_id,
        "points": (
            _drawdown_points(points)
            if drawdown
            else [
                {
                    "simulation_time": point.simulation_time.isoformat(),
                    "equity": _decimal_text(point.equity),
                }
                for point in points
            ]
        ),
    }


def _drawdown_points(points: tuple[EquityPoint, ...]) -> list[dict[str, str]]:
    peak: Decimal | None = None
    result: list[dict[str, str]] = []
    for point in points:
        peak = point.equity if peak is None else max(peak, point.equity)
        drawdown = Decimal("0") if peak <= 0 else (peak - point.equity) / peak
        result.append(
            {
                "simulation_time": point.simulation_time.isoformat(),
                "drawdown": _decimal_text(drawdown),
            }
        )
    return result


__all__ = [
    "BASELINE_CAMPAIGN_COMMISSION_BPS",
    "BASELINE_CAMPAIGN_SLIPPAGE_BPS",
    "BaselineCampaignRunner",
    "BaselineCampaignSnapshot",
    "BaselineCampaignSpecification",
    "CampaignMemberResult",
    "CampaignStatus",
    "RANDOM_SOURCE_VERSION",
]
