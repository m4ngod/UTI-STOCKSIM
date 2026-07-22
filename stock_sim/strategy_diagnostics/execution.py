"""Versioned, exact A-share cash-equity execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Final, Literal

from .market_paths import SessionPriceLimitReference
from .market_rules import (
    a_share_board_for_instrument,
    resolve_a_share_price_limit_rule,
)


A_SHARE_CASH_EQUITY_EXECUTION_POLICY_VERSION: Final = (
    "a-share-cash-equity-execution.v1"
)

ExecutionStatus = Literal["accepted", "rejected"]
TradingStatus = Literal["trading", "suspended", "inactive"]

_ZERO = Decimal("0")
_CENT = Decimal("0.01")
_BASIS_POINTS = Decimal("10000")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class AShareCashEquityPolicyConfiguration:
    """Pinned economics and market mechanics for one execution-policy version."""

    commission_bps: Decimal
    minimum_commission: Decimal = Decimal("5")
    transfer_fee_bps: Decimal = Decimal("0.1")
    sell_stamp_duty_bps: Decimal = Decimal("5")
    tick_size: Decimal = Decimal("0.01")
    board_lot_shares: int = 100
    policy_version: str = A_SHARE_CASH_EQUITY_EXECUTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != A_SHARE_CASH_EQUITY_EXECUTION_POLICY_VERSION:
            raise ValueError("unsupported A-share execution-policy version")
        for name, value in (
            ("commission_bps", self.commission_bps),
            ("minimum_commission", self.minimum_commission),
            ("transfer_fee_bps", self.transfer_fee_bps),
            ("sell_stamp_duty_bps", self.sell_stamp_duty_bps),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.board_lot_shares <= 0:
            raise ValueError("board_lot_shares must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "commission_bps": _decimal_text(self.commission_bps),
            "minimum_commission": _decimal_text(self.minimum_commission),
            "transfer_fee_bps": _decimal_text(self.transfer_fee_bps),
            "sell_stamp_duty_bps": _decimal_text(self.sell_stamp_duty_bps),
            "tick_size": _decimal_text(self.tick_size),
            "board_lot_shares": self.board_lot_shares,
            "rounding": "component-cents-half-up",
        }


@dataclass(frozen=True, slots=True)
class AShareCashEquityAccount:
    """Private account facts available at one activation node."""

    cash: Decimal
    position_shares: int
    sellable_shares: int

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError("cash must not be negative")
        if self.position_shares < 0:
            raise ValueError("position_shares must not be negative")
        if not 0 <= self.sellable_shares <= self.position_shares:
            raise ValueError("sellable_shares must lie within the private position")


@dataclass(frozen=True, slots=True)
class AShareExecutionRequest:
    instrument: str
    shares: int
    execution_price: Decimal
    simulation_time: datetime
    trading_status: TradingStatus
    account: AShareCashEquityAccount
    price_limit_reference: SessionPriceLimitReference | None
    instrument_is_st: bool = False

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument must not be empty")
        if self.shares == 0:
            raise ValueError("shares must not be zero")
        if self.execution_price <= 0:
            raise ValueError("execution_price must be positive")
        if self.simulation_time.tzinfo is not None:
            raise ValueError("Simulation Time must be timezone-naive market-local time")
        if self.trading_status not in {"trading", "suspended", "inactive"}:
            raise ValueError("unsupported trading status")


@dataclass(frozen=True, slots=True)
class ASharePriceLimits:
    lower: Decimal | None
    upper: Decimal | None
    rule_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "lower": _decimal_text(self.lower) if self.lower is not None else None,
            "upper": _decimal_text(self.upper) if self.upper is not None else None,
            "rule_code": self.rule_code,
        }


@dataclass(frozen=True, slots=True)
class ExecutionFeeBreakdown:
    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.transfer_fee + self.stamp_duty

    def to_dict(self) -> dict[str, str]:
        return {
            "commission": _decimal_text(self.commission),
            "transfer_fee": _decimal_text(self.transfer_fee),
            "stamp_duty": _decimal_text(self.stamp_duty),
            "total": _decimal_text(self.total),
        }


@dataclass(frozen=True, slots=True)
class ExecutionAccountEffect:
    cash_change: Decimal
    position_change: int
    sellable_shares_change: int

    def to_dict(self) -> dict[str, object]:
        return {
            "cash_change": _decimal_text(self.cash_change),
            "position_change": self.position_change,
            "sellable_shares_change": self.sellable_shares_change,
        }


@dataclass(frozen=True, slots=True)
class AShareExecutionResult:
    status: ExecutionStatus
    reason_code: str
    reason_message: str
    requested_shares: int
    accepted_shares: int
    execution_price: Decimal
    gross_value: Decimal
    price_limits: ASharePriceLimits | None
    fees: ExecutionFeeBreakdown
    account_effect: ExecutionAccountEffect
    policy_version: str = A_SHARE_CASH_EQUITY_EXECUTION_POLICY_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_message": self.reason_message,
            "requested_shares": self.requested_shares,
            "accepted_shares": self.accepted_shares,
            "execution_price": _decimal_text(self.execution_price),
            "gross_value": _decimal_text(self.gross_value),
            "price_limits": (
                self.price_limits.to_dict() if self.price_limits is not None else None
            ),
            "fees": self.fees.to_dict(),
            "account_effect": self.account_effect.to_dict(),
            "policy_version": self.policy_version,
        }


_REASON_MESSAGES: Final[dict[str, str]] = {
    "accepted": "Order accepted by the A-share Cash Equity Profile.",
    "market.closed": "Activation time is outside the supported A-share sessions.",
    "market.suspended": "Instrument is suspended at activation time.",
    "market.inactive": "Instrument is inactive at activation time.",
    "market.price_limit_reference_missing": (
        "Point-in-time session price-limit reference is missing."
    ),
    "market.price_limit_reference_mismatch": (
        "Price-limit reference does not match the instrument and session."
    ),
    "price.off_tick": "Execution price is not aligned to the A-share tick size.",
    "price.above_daily_limit": "Execution price exceeds the session upper limit.",
    "price.below_daily_limit": "Execution price is below the session lower limit.",
    "quantity.buy_board_lot": "Buy quantity is not a whole board lot.",
    "quantity.sell_odd_lot": (
        "An odd-lot sell must liquidate the entire private position."
    ),
    "position.no_short": "Sell quantity exceeds the private long position.",
    "position.t_plus_one": "Sell quantity exceeds shares available under T+1.",
    "account.insufficient_cash": "Cash cannot cover gross value and buy-side fees.",
}
A_SHARE_EXECUTION_REASON_CODES: Final = tuple(_REASON_MESSAGES)


class AShareCashEquityExecutionPolicy:
    """Pure fail-closed evaluator for the V1 ordinary A-share cash profile."""

    def __init__(self, configuration: AShareCashEquityPolicyConfiguration) -> None:
        self.configuration = configuration

    def price_limits(
        self,
        reference: SessionPriceLimitReference,
    ) -> ASharePriceLimits:
        if reference.limit_fraction is None:
            return ASharePriceLimits(
                lower=None,
                upper=None,
                rule_code=reference.rule_code,
            )
        return ASharePriceLimits(
            lower=self._round_to_tick(
                reference.previous_close * (Decimal("1") - reference.limit_fraction)
            ),
            upper=self._round_to_tick(
                reference.previous_close * (Decimal("1") + reference.limit_fraction)
            ),
            rule_code=reference.rule_code,
        )

    def evaluate(self, request: AShareExecutionRequest) -> AShareExecutionResult:
        if request.trading_status != "trading":
            return self._reject(request, f"market.{request.trading_status}")
        if not self._is_supported_session(request.simulation_time):
            return self._reject(request, "market.closed")
        reference = request.price_limit_reference
        if reference is None:
            return self._reject(request, "market.price_limit_reference_missing")
        if (
            reference.instrument != request.instrument
            or reference.session_date != request.simulation_time.date()
            or reference.effective_at > request.simulation_time
            or reference.is_st is not request.instrument_is_st
            or reference.board != a_share_board_for_instrument(request.instrument)
            or not self._price_limit_reference_matches_profile(reference)
        ):
            return self._reject(
                request,
                "market.price_limit_reference_mismatch",
            )
        if not self._is_on_tick(request.execution_price):
            return self._reject(request, "price.off_tick")

        requested_quantity = abs(request.shares)
        is_buy = request.shares > 0
        if is_buy and requested_quantity % self.configuration.board_lot_shares:
            return self._reject(request, "quantity.buy_board_lot")
        if not is_buy:
            if requested_quantity > request.account.position_shares:
                return self._reject(request, "position.no_short")
            if requested_quantity > request.account.sellable_shares:
                return self._reject(request, "position.t_plus_one")
            if (
                requested_quantity % self.configuration.board_lot_shares
                and requested_quantity != request.account.position_shares
            ):
                return self._reject(request, "quantity.sell_odd_lot")

        limits = self.price_limits(reference)
        if limits.upper is not None and request.execution_price > limits.upper:
            return self._reject(
                request,
                "price.above_daily_limit",
                price_limits=limits,
            )
        if limits.lower is not None and request.execution_price < limits.lower:
            return self._reject(
                request,
                "price.below_daily_limit",
                price_limits=limits,
            )

        gross_value = request.execution_price * requested_quantity
        fees = self._fees(gross_value, is_buy=is_buy)
        if is_buy and gross_value + fees.total > request.account.cash:
            return self._reject(
                request,
                "account.insufficient_cash",
                price_limits=limits,
            )
        cash_change = (
            -(gross_value + fees.total)
            if is_buy
            else gross_value - fees.total
        )
        return AShareExecutionResult(
            status="accepted",
            reason_code="accepted",
            reason_message=_REASON_MESSAGES["accepted"],
            requested_shares=request.shares,
            accepted_shares=request.shares,
            execution_price=request.execution_price,
            gross_value=gross_value,
            price_limits=limits,
            fees=fees,
            account_effect=ExecutionAccountEffect(
                cash_change=cash_change,
                position_change=request.shares,
                sellable_shares_change=request.shares if not is_buy else 0,
            ),
        )

    def _fees(self, gross_value: Decimal, *, is_buy: bool) -> ExecutionFeeBreakdown:
        configured_commission = _money(
            gross_value * self.configuration.commission_bps / _BASIS_POINTS
        )
        commission = (
            _ZERO
            if self.configuration.commission_bps == 0
            else max(configured_commission, _money(self.configuration.minimum_commission))
        )
        transfer_fee = _money(
            gross_value * self.configuration.transfer_fee_bps / _BASIS_POINTS
        )
        stamp_duty = (
            _ZERO
            if is_buy
            else _money(
                gross_value
                * self.configuration.sell_stamp_duty_bps
                / _BASIS_POINTS
            )
        )
        return ExecutionFeeBreakdown(
            commission=_money(commission),
            transfer_fee=transfer_fee,
            stamp_duty=_money(stamp_duty),
        )

    def _round_to_tick(self, value: Decimal) -> Decimal:
        ticks = (value / self.configuration.tick_size).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        return ticks * self.configuration.tick_size

    def _is_on_tick(self, price: Decimal) -> bool:
        return price % self.configuration.tick_size == 0

    @staticmethod
    def _price_limit_reference_matches_profile(
        reference: SessionPriceLimitReference,
    ) -> bool:
        try:
            expected = resolve_a_share_price_limit_rule(
                instrument=reference.instrument,
                session_date=reference.session_date,
                is_st=reference.is_st,
                listing_trading_day_number=(
                    1 if reference.listing_stage == "initial-unbounded" else None
                ),
            )
        except ValueError:
            return False
        return (
            reference.board == expected.board
            and reference.listing_stage == expected.listing_stage
            and reference.limit_fraction == expected.limit_fraction
            and reference.rule_code == expected.rule_code
        )

    @staticmethod
    def _is_supported_session(simulation_time: datetime) -> bool:
        local_time = simulation_time.time()
        return time(9, 30) <= local_time <= time(11, 30) or time(
            13,
        ) <= local_time <= time(15)

    @staticmethod
    def _reject(
        request: AShareExecutionRequest,
        reason_code: str,
        *,
        price_limits: ASharePriceLimits | None = None,
    ) -> AShareExecutionResult:
        return AShareExecutionResult(
            status="rejected",
            reason_code=reason_code,
            reason_message=_REASON_MESSAGES[reason_code],
            requested_shares=request.shares,
            accepted_shares=0,
            execution_price=request.execution_price,
            gross_value=_ZERO,
            price_limits=price_limits,
            fees=ExecutionFeeBreakdown(
                commission=_ZERO,
                transfer_fee=_ZERO,
                stamp_duty=_ZERO,
            ),
            account_effect=ExecutionAccountEffect(
                cash_change=_ZERO,
                position_change=0,
                sellable_shares_change=0,
            ),
        )


__all__ = [
    "A_SHARE_CASH_EQUITY_EXECUTION_POLICY_VERSION",
    "A_SHARE_EXECUTION_REASON_CODES",
    "AShareCashEquityAccount",
    "AShareCashEquityExecutionPolicy",
    "AShareCashEquityPolicyConfiguration",
    "AShareExecutionRequest",
    "AShareExecutionResult",
    "ASharePriceLimits",
    "ExecutionAccountEffect",
    "ExecutionFeeBreakdown",
]
