"""Versioned point-in-time A-share cash-equity market-rule resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


A_SHARE_MARKET_RULE_PROFILE_VERSION = "a-share-cash-equity.v1"
_CHINEXT_REFORM_EFFECTIVE = date(2020, 8, 24)
_MAIN_BOARD_REGISTRATION_EFFECTIVE = date(2023, 4, 10)
_MAIN_BOARD_ST_TEN_PERCENT_EFFECTIVE = date(2026, 7, 6)

AShareBoard = Literal["sh-main", "sz-main", "star", "chinext", "beijing"]
ListingStage = Literal["continuous", "initial-unbounded"]


@dataclass(frozen=True, slots=True)
class ResolvedPriceLimitRule:
    """One resolved session rule, ready to pin beside source data."""

    profile_version: str
    board: AShareBoard
    is_st: bool
    listing_stage: ListingStage
    limit_fraction: Decimal | None
    rule_code: str


def resolve_a_share_price_limit_rule(
    *,
    instrument: str,
    session_date: date,
    is_st: bool,
    listing_trading_day_number: int | None,
) -> ResolvedPriceLimitRule:
    """Resolve board, risk-warning, rule-date, and listing-stage semantics."""

    board = _a_share_board(instrument)
    if (
        listing_trading_day_number is not None
        and listing_trading_day_number < 1
    ):
        raise ValueError("listing trading-day number must be positive")

    if _is_initial_unbounded_session(
        board=board,
        session_date=session_date,
        listing_trading_day_number=listing_trading_day_number,
    ):
        return ResolvedPriceLimitRule(
            profile_version=A_SHARE_MARKET_RULE_PROFILE_VERSION,
            board=board,
            is_st=is_st,
            listing_stage="initial-unbounded",
            limit_fraction=None,
            rule_code=f"{board}.ipo-initial-unbounded.v1",
        )

    if _is_unsupported_legacy_initial_session(
        board=board,
        session_date=session_date,
        listing_trading_day_number=listing_trading_day_number,
    ):
        raise ValueError(
            "The market rule profile cannot resolve this legacy initial-session "
            "asymmetric price limit from previous close alone"
        )

    limit_fraction = _continuous_limit_fraction(
        board=board,
        session_date=session_date,
        is_st=is_st,
    )
    status = "risk-warning" if is_st else "ordinary"
    return ResolvedPriceLimitRule(
        profile_version=A_SHARE_MARKET_RULE_PROFILE_VERSION,
        board=board,
        is_st=is_st,
        listing_stage="continuous",
        limit_fraction=limit_fraction,
        rule_code=(
            f"{board}.{status}.{_decimal_code(limit_fraction)}."
            f"effective-{session_date.isoformat()}"
        ),
    )


def _a_share_board(instrument: str) -> AShareBoard:
    normalized = instrument.strip().lower()
    if normalized.startswith("sh.688") or normalized.startswith("sh.689"):
        return "star"
    if normalized.startswith("sh.60"):
        return "sh-main"
    if normalized.startswith("sz.300") or normalized.startswith("sz.301"):
        return "chinext"
    if normalized.startswith("sz.00"):
        return "sz-main"
    if normalized.startswith("bj."):
        return "beijing"
    raise ValueError(
        f"Instrument {instrument!r} is outside the supported A-share board map"
    )


def _is_initial_unbounded_session(
    *,
    board: AShareBoard,
    session_date: date,
    listing_trading_day_number: int | None,
) -> bool:
    if listing_trading_day_number is None:
        return False
    if board == "star":
        return listing_trading_day_number <= 5
    if board == "chinext":
        return (
            session_date >= _CHINEXT_REFORM_EFFECTIVE
            and listing_trading_day_number <= 5
        )
    if board in {"sh-main", "sz-main"}:
        return (
            session_date >= _MAIN_BOARD_REGISTRATION_EFFECTIVE
            and listing_trading_day_number <= 5
        )
    return board == "beijing" and listing_trading_day_number == 1


def _is_unsupported_legacy_initial_session(
    *,
    board: AShareBoard,
    session_date: date,
    listing_trading_day_number: int | None,
) -> bool:
    if listing_trading_day_number != 1:
        return False
    if board in {"sh-main", "sz-main"}:
        return session_date < _MAIN_BOARD_REGISTRATION_EFFECTIVE
    return board == "chinext" and session_date < _CHINEXT_REFORM_EFFECTIVE


def _continuous_limit_fraction(
    *,
    board: AShareBoard,
    session_date: date,
    is_st: bool,
) -> Decimal:
    if board == "star":
        return Decimal("0.20")
    if board == "chinext":
        if session_date >= _CHINEXT_REFORM_EFFECTIVE:
            return Decimal("0.20")
        return Decimal("0.05") if is_st else Decimal("0.10")
    if board == "beijing":
        return Decimal("0.30")
    if is_st and session_date < _MAIN_BOARD_ST_TEN_PERCENT_EFFECTIVE:
        return Decimal("0.05")
    return Decimal("0.10")


def _decimal_code(value: Decimal) -> str:
    return f"{int(value * 100)}pct"


__all__ = [
    "A_SHARE_MARKET_RULE_PROFILE_VERSION",
    "AShareBoard",
    "ListingStage",
    "ResolvedPriceLimitRule",
    "resolve_a_share_price_limit_rule",
]
