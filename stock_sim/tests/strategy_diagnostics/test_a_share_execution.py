from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from strategy_diagnostics.execution import (
    AShareCashEquityAccount,
    AShareCashEquityExecutionPolicy,
    AShareCashEquityPolicyConfiguration,
    AShareExecutionRequest,
)
from strategy_diagnostics.market_paths import SessionPriceLimitReference
from strategy_diagnostics.market_rules import resolve_a_share_price_limit_rule


def _reference(
    *,
    instrument: str = "sh.600000",
    board: str = "sh-main",
    previous_close: str = "10.00",
    is_st: bool = False,
    limit_fraction: str | None = "0.10",
    listing_stage: str = "continuous",
) -> SessionPriceLimitReference:
    resolved = resolve_a_share_price_limit_rule(
        instrument=instrument,
        session_date=date(2024, 1, 2),
        is_st=is_st,
        listing_trading_day_number=(
            1 if listing_stage == "initial-unbounded" else None
        ),
    )
    return SessionPriceLimitReference(
        instrument=instrument,
        session_date=date(2024, 1, 2),
        previous_close=Decimal(previous_close),
        effective_at=datetime(2024, 1, 2, 9, 25),
        provenance="hand-calculable-fixture",
        profile_version="a-share-cash-equity.v1",
        board=board,  # type: ignore[arg-type]
        is_st=is_st,
        listing_stage=listing_stage,  # type: ignore[arg-type]
        limit_fraction=(
            Decimal(limit_fraction) if limit_fraction is not None else None
        ),
        rule_code=resolved.rule_code,
    )


def _request(
    *,
    shares: int = 100,
    price: str = "10.00",
    simulation_time: datetime = datetime(2024, 1, 2, 10, 0, 30),
    trading_status: str = "trading",
    account: AShareCashEquityAccount | None = None,
    reference: SessionPriceLimitReference | None = None,
) -> AShareExecutionRequest:
    effective_reference = reference or _reference()
    return AShareExecutionRequest(
        instrument=effective_reference.instrument,
        shares=shares,
        execution_price=Decimal(price),
        simulation_time=simulation_time,
        trading_status=trading_status,
        account=account
        or AShareCashEquityAccount(
            cash=Decimal("100000"),
            position_shares=0,
            sellable_shares=0,
        ),
        price_limit_reference=effective_reference,
        instrument_is_st=effective_reference.is_st,
    )


@pytest.fixture
def policy() -> AShareCashEquityExecutionPolicy:
    return AShareCashEquityExecutionPolicy(
        AShareCashEquityPolicyConfiguration(
            commission_bps=Decimal("3"),
            minimum_commission=Decimal("5"),
            transfer_fee_bps=Decimal("0.1"),
            sell_stamp_duty_bps=Decimal("5"),
        )
    )


@pytest.mark.parametrize(
    ("simulation_time", "expected_code"),
    (
        (datetime(2024, 1, 2, 9, 29, 59), "market.closed"),
        (datetime(2024, 1, 2, 11, 30, 1), "market.closed"),
        (datetime(2024, 1, 2, 12, 59, 59), "market.closed"),
        (datetime(2024, 1, 2, 15, 0, 1), "market.closed"),
    ),
)
def test_a_share_sessions_reject_out_of_session_orders(
    policy: AShareCashEquityExecutionPolicy,
    simulation_time: datetime,
    expected_code: str,
) -> None:
    result = policy.evaluate(_request(simulation_time=simulation_time))

    assert result.status == "rejected"
    assert result.reason_code == expected_code
    assert result.accepted_shares == 0
    assert result.account_effect.cash_change == Decimal("0")


@pytest.mark.parametrize(
    "simulation_time",
    (
        datetime(2024, 1, 2, 9, 30),
        datetime(2024, 1, 2, 11, 30),
        datetime(2024, 1, 2, 13, 0),
        datetime(2024, 1, 2, 14, 57),
        datetime(2024, 1, 2, 15, 0),
    ),
)
def test_a_share_sessions_accept_supported_exchange_times(
    policy: AShareCashEquityExecutionPolicy,
    simulation_time: datetime,
) -> None:
    assert policy.evaluate(_request(simulation_time=simulation_time)).status == "accepted"


def test_tick_size_and_board_lot_fail_closed(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    off_tick = policy.evaluate(_request(price="10.001"))
    odd_buy = policy.evaluate(_request(shares=150))

    assert off_tick.reason_code == "price.off_tick"
    assert odd_buy.reason_code == "quantity.buy_board_lot"


def test_sell_allows_a_full_odd_lot_but_not_a_partial_odd_lot(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    account = AShareCashEquityAccount(
        cash=Decimal("1000"),
        position_shares=150,
        sellable_shares=150,
    )

    full = policy.evaluate(_request(shares=-150, account=account))
    partial = policy.evaluate(_request(shares=-50, account=account))

    assert full.status == "accepted"
    assert full.accepted_shares == -150
    assert partial.status == "rejected"
    assert partial.reason_code == "quantity.sell_odd_lot"


def test_no_short_and_t_plus_one_have_distinct_reason_codes(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    no_short = policy.evaluate(
        _request(
            shares=-200,
            account=AShareCashEquityAccount(
                cash=Decimal("0"),
                position_shares=100,
                sellable_shares=100,
            ),
        )
    )
    t_plus_one = policy.evaluate(
        _request(
            shares=-100,
            account=AShareCashEquityAccount(
                cash=Decimal("0"),
                position_shares=100,
                sellable_shares=0,
            ),
        )
    )

    assert no_short.reason_code == "position.no_short"
    assert t_plus_one.reason_code == "position.t_plus_one"


@pytest.mark.parametrize("trading_status", ("suspended", "inactive"))
def test_suspension_and_inactive_instruments_reject_deterministically(
    policy: AShareCashEquityExecutionPolicy,
    trading_status: str,
) -> None:
    result = policy.evaluate(_request(trading_status=trading_status))

    assert result.status == "rejected"
    assert result.reason_code == f"market.{trading_status}"


@pytest.mark.parametrize(
    ("reference", "upper", "lower"),
    (
        (_reference(board="sh-main", limit_fraction="0.10"), "11.00", "9.00"),
        (_reference(board="sh-main", is_st=True, limit_fraction="0.05"), "10.50", "9.50"),
        (
            _reference(
                instrument="sh.688001",
                board="star",
                limit_fraction="0.20",
            ),
            "12.00",
            "8.00",
        ),
        (
            _reference(
                instrument="sz.300001",
                board="chinext",
                limit_fraction="0.20",
            ),
            "12.00",
            "8.00",
        ),
        (
            _reference(
                instrument="bj.430001",
                board="beijing",
                limit_fraction="0.30",
            ),
            "13.00",
            "7.00",
        ),
    ),
)
def test_daily_price_limits_are_hand_calculable_for_supported_boards(
    policy: AShareCashEquityExecutionPolicy,
    reference: SessionPriceLimitReference,
    upper: str,
    lower: str,
) -> None:
    limits = policy.price_limits(reference)

    assert limits.upper == Decimal(upper)
    assert limits.lower == Decimal(lower)
    assert policy.evaluate(_request(price=upper, reference=reference)).status == (
        "accepted"
    )
    above_limit = Decimal(upper) + Decimal("0.01")
    assert policy.evaluate(
        _request(price=str(above_limit), reference=reference)
    ).reason_code == "price.above_daily_limit"


def test_price_limit_rounding_uses_profile_tick_and_half_up() -> None:
    policy = AShareCashEquityExecutionPolicy(
        AShareCashEquityPolicyConfiguration(commission_bps=Decimal("0"))
    )

    limits = policy.price_limits(
        _reference(previous_close="10.05", limit_fraction="0.10")
    )

    assert limits.upper == Decimal("11.06")
    assert limits.lower == Decimal("9.05")


def test_orders_outside_daily_limits_are_rejected_and_unbounded_stage_is_allowed(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    above = policy.evaluate(_request(price="11.01"))
    below = policy.evaluate(_request(price="8.99"))
    unbounded = policy.evaluate(
        _request(
            price="25.00",
            reference=_reference(
                listing_stage="initial-unbounded",
                limit_fraction=None,
            ),
        )
    )

    assert above.reason_code == "price.above_daily_limit"
    assert below.reason_code == "price.below_daily_limit"
    assert unbounded.status == "accepted"


def test_missing_or_wrong_session_price_limit_reference_fails_closed(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    missing = policy.evaluate(
        AShareExecutionRequest(
            instrument="sh.600000",
            shares=100,
            execution_price=Decimal("10"),
            simulation_time=datetime(2024, 1, 2, 10),
            trading_status="trading",
            account=AShareCashEquityAccount(
                cash=Decimal("100000"),
                position_shares=0,
                sellable_shares=0,
            ),
            price_limit_reference=None,
        )
    )
    wrong_session = policy.evaluate(
        _request(
            reference=SessionPriceLimitReference(
                instrument="sh.600000",
                session_date=date(2024, 1, 3),
                previous_close=Decimal("10"),
                effective_at=datetime(2024, 1, 2, 15),
                provenance="fixture",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="fixture",
            )
        )
    )
    wrong_board = policy.evaluate(_request(reference=_reference(board="star")))
    wrong_fraction = policy.evaluate(
        _request(reference=_reference(limit_fraction="0.20"))
    )
    wrong_st_state = policy.evaluate(
        AShareExecutionRequest(
            instrument="sh.600000",
            shares=100,
            execution_price=Decimal("10"),
            simulation_time=datetime(2024, 1, 2, 10),
            trading_status="trading",
            account=AShareCashEquityAccount(
                cash=Decimal("100000"),
                position_shares=0,
                sellable_shares=0,
            ),
            price_limit_reference=_reference(is_st=True, limit_fraction="0.05"),
            instrument_is_st=False,
        )
    )

    assert missing.reason_code == "market.price_limit_reference_missing"
    assert wrong_session.reason_code == "market.price_limit_reference_mismatch"
    assert wrong_board.reason_code == "market.price_limit_reference_mismatch"
    assert wrong_fraction.reason_code == "market.price_limit_reference_mismatch"
    assert wrong_st_state.reason_code == "market.price_limit_reference_mismatch"


def test_buy_fee_arithmetic_and_account_effect_are_exact_and_auditable(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    result = policy.evaluate(_request(shares=1000, price="10.00"))

    assert result.status == "accepted"
    assert result.reason_code == "accepted"
    assert result.requested_shares == 1000
    assert result.accepted_shares == 1000
    assert result.gross_value == Decimal("10000.00")
    assert result.fees.commission == Decimal("5.00")
    assert result.fees.transfer_fee == Decimal("0.10")
    assert result.fees.stamp_duty == Decimal("0.00")
    assert result.fees.total == Decimal("5.10")
    assert result.account_effect.cash_change == Decimal("-10005.10")
    assert result.account_effect.position_change == 1000
    assert result.account_effect.sellable_shares_change == 0


def test_sell_fee_arithmetic_and_account_effect_are_exact_and_auditable(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    result = policy.evaluate(
        _request(
            shares=-1000,
            price="10.00",
            account=AShareCashEquityAccount(
                cash=Decimal("0"),
                position_shares=1000,
                sellable_shares=1000,
            ),
        )
    )

    assert result.status == "accepted"
    assert result.fees.commission == Decimal("5.00")
    assert result.fees.transfer_fee == Decimal("0.10")
    assert result.fees.stamp_duty == Decimal("5.00")
    assert result.fees.total == Decimal("10.10")
    assert result.account_effect.cash_change == Decimal("9989.90")
    assert result.account_effect.position_change == -1000
    assert result.account_effect.sellable_shares_change == -1000


def test_commission_minimum_is_only_applied_when_commission_is_configured() -> None:
    no_commission = AShareCashEquityExecutionPolicy(
        AShareCashEquityPolicyConfiguration(
            commission_bps=Decimal("0"),
            minimum_commission=Decimal("5"),
            transfer_fee_bps=Decimal("0"),
            sell_stamp_duty_bps=Decimal("0"),
        )
    )
    result = no_commission.evaluate(_request())

    assert result.fees.commission == Decimal("0.00")
    assert result.fees.total == Decimal("0.00")


def test_cash_check_includes_all_buy_side_fees(
    policy: AShareCashEquityExecutionPolicy,
) -> None:
    result = policy.evaluate(
        _request(
            account=AShareCashEquityAccount(
                cash=Decimal("1005.00"),
                position_shares=0,
                sellable_shares=0,
            )
        )
    )

    assert result.status == "rejected"
    assert result.reason_code == "account.insufficient_cash"
    assert result.accepted_shares == 0
    assert result.fees.total == Decimal("0")
    assert result.account_effect.cash_change == Decimal("0")
