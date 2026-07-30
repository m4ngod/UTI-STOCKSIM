"""Resolve requested execution assumptions against scenario-owned overrides."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Final, Literal, Mapping, cast


EXECUTION_STRESS_TRANSFORMATION_ID: Final = "execution-stress.v1"
EXECUTION_STRESS_IMPLEMENTATION_VERSION: Final = "execution-stress.v1"
SCENARIO_OVERRIDE_REASON: Final = "scenario execution-stress.v1 override"

RejectionMode = Literal["none", "reject-all"]

_CONDITION_NAMES: Final = (
    "allow_partial_fills",
    "commission_bps",
    "latency_nodes",
    "max_fill_fraction",
    "rejection_mode",
    "slippage_bps",
)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


@dataclass(frozen=True, slots=True)
class RequestedExecutionAssumptions:
    commission_bps: Decimal
    slippage_bps: Decimal
    max_fill_fraction: Decimal
    latency_nodes: int
    allow_partial_fills: bool

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.commission_bps <= Decimal("100"):
            raise ValueError("commission_bps must be between 0 and 100")
        if not Decimal("0") <= self.slippage_bps <= Decimal("1000"):
            raise ValueError("slippage_bps must be between 0 and 1000")
        if not Decimal("0") < self.max_fill_fraction <= Decimal("1"):
            raise ValueError("max_fill_fraction must be greater than 0 and at most 1")
        if not 0 <= self.latency_nodes <= 120:
            raise ValueError("latency_nodes must be between 0 and 120")

    def to_dict(self) -> dict[str, object]:
        return {
            "commission_bps": _decimal_text(self.commission_bps),
            "slippage_bps": _decimal_text(self.slippage_bps),
            "max_fill_fraction": _decimal_text(self.max_fill_fraction),
            "latency_nodes": self.latency_nodes,
            "allow_partial_fills": self.allow_partial_fills,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "RequestedExecutionAssumptions":
        return cls(
            commission_bps=Decimal(str(payload["commission_bps"])),
            slippage_bps=Decimal(str(payload["slippage_bps"])),
            max_fill_fraction=Decimal(str(payload["max_fill_fraction"])),
            latency_nodes=int(str(payload["latency_nodes"])),
            allow_partial_fills=_parse_bool(payload["allow_partial_fills"]),
        )


@dataclass(frozen=True, slots=True)
class EffectiveExecutionConditions:
    commission_bps: Decimal
    slippage_bps: Decimal
    max_fill_fraction: Decimal
    latency_nodes: int
    allow_partial_fills: bool
    rejection_mode: RejectionMode

    def __post_init__(self) -> None:
        RequestedExecutionAssumptions(
            commission_bps=self.commission_bps,
            slippage_bps=self.slippage_bps,
            max_fill_fraction=self.max_fill_fraction,
            latency_nodes=self.latency_nodes,
            allow_partial_fills=self.allow_partial_fills,
        )
        if self.rejection_mode not in ("none", "reject-all"):
            raise ValueError("unsupported execution rejection mode")

    def to_dict(self) -> dict[str, object]:
        return {
            "commission_bps": _decimal_text(self.commission_bps),
            "slippage_bps": _decimal_text(self.slippage_bps),
            "max_fill_fraction": _decimal_text(self.max_fill_fraction),
            "latency_nodes": self.latency_nodes,
            "allow_partial_fills": self.allow_partial_fills,
            "rejection_mode": self.rejection_mode,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "EffectiveExecutionConditions":
        rejection_mode = str(payload["rejection_mode"])
        if rejection_mode not in ("none", "reject-all"):
            raise ValueError("unsupported execution rejection mode")
        return cls(
            commission_bps=Decimal(str(payload["commission_bps"])),
            slippage_bps=Decimal(str(payload["slippage_bps"])),
            max_fill_fraction=Decimal(str(payload["max_fill_fraction"])),
            latency_nodes=int(str(payload["latency_nodes"])),
            allow_partial_fills=_parse_bool(payload["allow_partial_fills"]),
            rejection_mode=cast(RejectionMode, rejection_mode),
        )


@dataclass(frozen=True, slots=True)
class ExecutionConditionResolution:
    name: str
    requested_value: str
    effective_value: str
    override_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "requested_value": self.requested_value,
            "effective_value": self.effective_value,
            "override_reason": self.override_reason,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ExecutionConditionResolution":
        return cls(
            name=str(payload["name"]),
            requested_value=str(payload["requested_value"]),
            effective_value=str(payload["effective_value"]),
            override_reason=(
                str(payload["override_reason"])
                if payload.get("override_reason") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedExecutionConditions:
    requested: RequestedExecutionAssumptions
    effective: EffectiveExecutionConditions
    resolutions: tuple[ExecutionConditionResolution, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested.to_dict(),
            "effective": self.effective.to_dict(),
            "resolutions": [item.to_dict() for item in self.resolutions],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ResolvedExecutionConditions":
        requested = cast(Mapping[str, object], payload["requested"])
        effective = cast(Mapping[str, object], payload["effective"])
        resolutions = cast(list[Mapping[str, object]], payload["resolutions"])
        return cls(
            requested=RequestedExecutionAssumptions.from_dict(requested),
            effective=EffectiveExecutionConditions.from_dict(effective),
            resolutions=tuple(
                ExecutionConditionResolution.from_dict(item)
                for item in resolutions
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedExecutionRequest:
    status: Literal["proceed", "rejected"]
    reason_code: str
    reason_message: str
    requested_shares: int
    executable_shares: int
    unfilled_shares: int
    reference_price: Decimal
    execution_price: Decimal
    slippage_bps: Decimal


def resolve_execution_conditions(
    requested: RequestedExecutionAssumptions,
    scenario_overrides: Mapping[str, object],
) -> ResolvedExecutionConditions:
    unknown = sorted(set(scenario_overrides) - set(_CONDITION_NAMES))
    if unknown:
        raise ValueError(f"unknown execution condition overrides: {unknown!r}")
    requested_values = {
        "allow_partial_fills": _bool_text(requested.allow_partial_fills),
        "commission_bps": _decimal_text(requested.commission_bps),
        "latency_nodes": str(requested.latency_nodes),
        "max_fill_fraction": _decimal_text(requested.max_fill_fraction),
        "rejection_mode": "none",
        "slippage_bps": _decimal_text(requested.slippage_bps),
    }
    effective_values = dict(requested_values)
    for name, raw_value in scenario_overrides.items():
        effective_values[name] = _canonical_override(name, raw_value)
    effective = EffectiveExecutionConditions(
        commission_bps=Decimal(effective_values["commission_bps"]),
        slippage_bps=Decimal(effective_values["slippage_bps"]),
        max_fill_fraction=Decimal(effective_values["max_fill_fraction"]),
        latency_nodes=int(effective_values["latency_nodes"]),
        allow_partial_fills=_parse_bool(
            effective_values["allow_partial_fills"]
        ),
        rejection_mode=cast(RejectionMode, effective_values["rejection_mode"]),
    )
    return ResolvedExecutionConditions(
        requested=requested,
        effective=effective,
        resolutions=tuple(
            ExecutionConditionResolution(
                name=name,
                requested_value=requested_values[name],
                effective_value=effective_values[name],
                override_reason=(
                    SCENARIO_OVERRIDE_REASON
                    if name in scenario_overrides
                    else None
                ),
            )
            for name in _CONDITION_NAMES
        ),
    )


def prepare_execution_request(
    *,
    requested_shares: int,
    reference_price: Decimal,
    node_volume: int,
    conditions: EffectiveExecutionConditions,
    tick_size: Decimal = Decimal("0.01"),
    board_lot_shares: int = 100,
) -> PreparedExecutionRequest:
    if requested_shares == 0:
        raise ValueError("requested_shares must not be zero")
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    if node_volume < 0:
        raise ValueError("node_volume must not be negative")
    if tick_size <= 0 or board_lot_shares <= 0:
        raise ValueError("tick size and board lot must be positive")
    if conditions.rejection_mode == "reject-all":
        return _rejected_preparation(
            requested_shares=requested_shares,
            reference_price=reference_price,
            reason_code="execution.scenario_rejection",
            reason_message="Scenario execution stress rejected the order.",
            slippage_bps=conditions.slippage_bps,
        )
    if requested_shares > 0 and requested_shares % board_lot_shares:
        return _rejected_preparation(
            requested_shares=requested_shares,
            reference_price=reference_price,
            reason_code="quantity.buy_board_lot",
            reason_message=(
                "Requested buy quantity is not a whole A-share board lot."
            ),
            slippage_bps=conditions.slippage_bps,
        )

    requested_quantity = abs(requested_shares)
    raw_capacity = int(
        (
            Decimal(node_volume) * conditions.max_fill_fraction
        ).to_integral_value(rounding=ROUND_FLOOR)
    )
    capacity = (raw_capacity // board_lot_shares) * board_lot_shares
    executable_quantity = min(requested_quantity, capacity)
    if executable_quantity < requested_quantity:
        if not conditions.allow_partial_fills or executable_quantity == 0:
            return _rejected_preparation(
                requested_shares=requested_shares,
                reference_price=reference_price,
                reason_code="execution.fill_cap",
                reason_message=(
                    "Effective fill cap cannot execute the full order and "
                    "partial fills are unavailable."
                ),
                slippage_bps=conditions.slippage_bps,
            )
        reason_code = "execution.partial_fill"
        reason_message = "Effective fill cap produced a private partial fill."
    else:
        reason_code = "accepted"
        reason_message = "Order passed the effective execution conditions."
    sign = 1 if requested_shares > 0 else -1
    executable_shares = sign * executable_quantity
    slippage_sign = Decimal("1") if sign > 0 else Decimal("-1")
    desired_price = reference_price * (
        Decimal("1")
        + slippage_sign * conditions.slippage_bps / Decimal("10000")
    )
    execution_price = _round_to_tick(desired_price, tick_size)
    return PreparedExecutionRequest(
        status="proceed",
        reason_code=reason_code,
        reason_message=reason_message,
        requested_shares=requested_shares,
        executable_shares=executable_shares,
        unfilled_shares=requested_shares - executable_shares,
        reference_price=reference_price,
        execution_price=execution_price,
        slippage_bps=conditions.slippage_bps,
    )


def _rejected_preparation(
    *,
    requested_shares: int,
    reference_price: Decimal,
    reason_code: str,
    reason_message: str,
    slippage_bps: Decimal,
) -> PreparedExecutionRequest:
    return PreparedExecutionRequest(
        status="rejected",
        reason_code=reason_code,
        reason_message=reason_message,
        requested_shares=requested_shares,
        executable_shares=0,
        unfilled_shares=requested_shares,
        reference_price=reference_price,
        execution_price=reference_price,
        slippage_bps=slippage_bps,
    )


def _round_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    ticks = (value / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return ticks * tick_size


def _canonical_override(name: str, value: object) -> str:
    if name in {"commission_bps", "slippage_bps", "max_fill_fraction"}:
        return _decimal_text(Decimal(str(value)))
    if name == "latency_nodes":
        parsed_latency = Decimal(str(value))
        if parsed_latency != parsed_latency.to_integral_value():
            raise ValueError("latency_nodes override must be an integer")
        return str(int(parsed_latency))
    if name == "allow_partial_fills":
        return _bool_text(_parse_bool(value))
    if name == "rejection_mode":
        parsed_rejection = str(value).strip().lower()
        if parsed_rejection not in ("none", "reject-all"):
            raise ValueError("unsupported execution rejection mode")
        return parsed_rejection
    raise ValueError(f"unsupported execution condition override {name!r}")


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("boolean execution condition must be true or false")


__all__ = [
    "EXECUTION_STRESS_IMPLEMENTATION_VERSION",
    "EXECUTION_STRESS_TRANSFORMATION_ID",
    "EffectiveExecutionConditions",
    "ExecutionConditionResolution",
    "PreparedExecutionRequest",
    "RequestedExecutionAssumptions",
    "ResolvedExecutionConditions",
    "SCENARIO_OVERRIDE_REASON",
    "prepare_execution_request",
    "resolve_execution_conditions",
]
