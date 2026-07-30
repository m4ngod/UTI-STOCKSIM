from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from strategy_diagnostics.market_rules import resolve_a_share_price_limit_rule


@pytest.mark.parametrize(
    (
        "instrument",
        "session_date",
        "is_st",
        "listing_day",
        "expected_board",
        "expected_limit",
    ),
    (
        ("sh.600000", date(2024, 1, 2), False, None, "sh-main", Decimal("0.10")),
        ("sh.600000", date(2024, 1, 2), True, None, "sh-main", Decimal("0.05")),
        ("sz.000001", date(2024, 1, 2), False, None, "sz-main", Decimal("0.10")),
        ("sz.000001", date(2024, 1, 2), True, None, "sz-main", Decimal("0.05")),
        ("sh.688001", date(2024, 1, 2), False, None, "star", Decimal("0.20")),
        ("sh.688001", date(2024, 1, 2), True, None, "star", Decimal("0.20")),
        ("sz.300001", date(2024, 1, 2), False, None, "chinext", Decimal("0.20")),
        ("sz.300001", date(2024, 1, 2), True, None, "chinext", Decimal("0.20")),
        ("bj.430001", date(2024, 1, 2), False, None, "beijing", Decimal("0.30")),
        ("bj.430001", date(2024, 1, 2), True, None, "beijing", Decimal("0.30")),
        ("sh.600000", date(2026, 7, 6), True, None, "sh-main", Decimal("0.10")),
        ("sz.000001", date(2026, 7, 6), True, None, "sz-main", Decimal("0.10")),
    ),
)
def test_a_share_price_limit_profile_resolves_board_st_and_rule_date(
    instrument: str,
    session_date: date,
    is_st: bool,
    listing_day: int | None,
    expected_board: str,
    expected_limit: Decimal,
) -> None:
    rule = resolve_a_share_price_limit_rule(
        instrument=instrument,
        session_date=session_date,
        is_st=is_st,
        listing_trading_day_number=listing_day,
    )

    assert rule.board == expected_board
    assert rule.is_st is is_st
    assert rule.listing_stage == "continuous"
    assert rule.limit_fraction == expected_limit
    assert rule.profile_version == "a-share-cash-equity.v1"


@pytest.mark.parametrize(
    ("instrument", "session_date", "listing_day"),
    (
        ("sh.600000", date(2024, 1, 2), 1),
        ("sh.600000", date(2024, 1, 2), 5),
        ("sh.688001", date(2024, 1, 2), 1),
        ("sh.688001", date(2024, 1, 2), 5),
        ("sz.300001", date(2024, 1, 2), 1),
        ("sz.300001", date(2024, 1, 2), 5),
        ("bj.430001", date(2024, 1, 2), 1),
    ),
)
def test_a_share_price_limit_profile_marks_initial_unbounded_sessions(
    instrument: str,
    session_date: date,
    listing_day: int,
) -> None:
    rule = resolve_a_share_price_limit_rule(
        instrument=instrument,
        session_date=session_date,
        is_st=False,
        listing_trading_day_number=listing_day,
    )

    assert rule.listing_stage == "initial-unbounded"
    assert rule.limit_fraction is None
    assert "unbounded" in rule.rule_code


def test_beijing_profile_restores_thirty_percent_limit_after_listing_day() -> None:
    rule = resolve_a_share_price_limit_rule(
        instrument="bj.430001",
        session_date=date(2024, 1, 3),
        is_st=True,
        listing_trading_day_number=2,
    )

    assert rule.listing_stage == "continuous"
    assert rule.limit_fraction == Decimal("0.30")


@pytest.mark.parametrize("instrument", ("hk.00001", "sh.900901", "sz.200001"))
def test_a_share_price_limit_profile_fails_closed_for_unknown_boards(
    instrument: str,
) -> None:
    with pytest.raises(ValueError, match="board"):
        resolve_a_share_price_limit_rule(
            instrument=instrument,
            session_date=date(2024, 1, 2),
            is_st=False,
            listing_trading_day_number=None,
        )


def test_legacy_ipo_session_with_asymmetric_limit_fails_closed() -> None:
    with pytest.raises(ValueError, match="legacy initial-session"):
        resolve_a_share_price_limit_rule(
            instrument="sh.600000",
            session_date=date(2020, 1, 2),
            is_st=False,
            listing_trading_day_number=1,
        )
