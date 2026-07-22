"""Scenario-native adaptation of QuentX's live-minute strategy shell.

The source strategy composes a candidate provider with ``LiveTradingCore`` and
``LiveRiskManager``.  This formal adapter preserves that materially different
shape as a compact intraday scanner plus a serialized daily risk ledger.  It
derives every candidate from the active Scenario Data World's Eligible
Universe and completed point-in-time minute bars; external candidate caches,
files, databases, and network data are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Callable, Protocol, Sequence

from .market_paths import MarketPathNode


STRATEGY_LINEAGE = "ptrade/live_minute_strategy.py"
SOURCE_SCAN_INTERVAL_SECONDS = 300
HISTORY_BARS = 20
MIN_HISTORY_BARS = 8
MAX_POSITIONS = 5
MAX_NEW_BUYS_PER_DAY = 5
MAX_SINGLE_POSITION_FRACTION = Decimal("0.20")
STOP_LOSS_FRACTION = Decimal("0.08")
MIN_DISLOCATION_FRACTION = Decimal("0.008")
MIN_REBOUND_FRACTION = Decimal("0.003")
MIN_ORDER_VALUE = Decimal("5000")
LOT_SIZE = 100


class _Position(Protocol):
    instrument: str
    amount: int
    closeable_amount: int
    average_cost: Decimal


class _Portfolio(Protocol):
    available_cash: Decimal
    total_value: Decimal
    positions: tuple[_Position, ...]


class PTradeContext(Protocol):
    current_dt: datetime
    portfolio: _Portfolio
    state: dict[str, str]
    eligible_universe: tuple[str, ...]
    decision_cadence_minutes: int
    order_shares: int


class _RunDaily(Protocol):
    def __call__(
        self,
        callback: Callable[[PTradeContext], None],
        *,
        cadence_minutes: int,
    ) -> None: ...


class _GetHistory(Protocol):
    def __call__(
        self,
        *,
        count: int,
        unit: str,
        fields: tuple[str, ...],
    ) -> dict[str, tuple[dict[str, object], ...]]: ...


class _Logger(Protocol):
    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


set_universe: Callable[[Sequence[str]], None]
set_slippage: Callable[[Decimal], None]
set_commission: Callable[[Decimal], None]
run_daily: _RunDaily
get_history: _GetHistory
get_current_data: Callable[[], dict[str, MarketPathNode]]
order: Callable[[str, int], None]
log: _Logger


strategy_global_counter = 0


@dataclass(frozen=True, slots=True)
class _Candidate:
    signal_id: str
    instrument: str
    score: Decimal
    price: Decimal
    drawdown: Decimal
    rebound: Decimal


def initialize(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    set_universe(context.eligible_universe)
    set_slippage(Decimal("0"))
    set_commission(Decimal("3"))
    run_daily(
        scheduled_scan,
        cadence_minutes=context.decision_cadence_minutes,
    )
    context.state["live_minute.strategy_lineage"] = STRATEGY_LINEAGE
    context.state["live_minute.source_scan_interval_seconds"] = str(
        SOURCE_SCAN_INTERVAL_SECONDS
    )
    context.state["live_minute.config"] = _json(
        {
            "candidate_model": "intraday_dislocation_rebound",
            "history_bars": HISTORY_BARS,
            "host_cadence_minutes": context.decision_cadence_minutes,
            "max_new_buys_per_day": MAX_NEW_BUYS_PER_DAY,
            "max_positions": MAX_POSITIONS,
            "max_single_position_fraction": _decimal_text(
                MAX_SINGLE_POSITION_FRACTION
            ),
            "source_scan_interval_seconds": SOURCE_SCAN_INTERVAL_SECONDS,
            "stop_loss_fraction": _decimal_text(STOP_LOSS_FRACTION),
        }
    )
    context.state["live_minute.daily_ledger"] = _json(
        _empty_daily_ledger(context.current_dt)
    )
    context.state.setdefault("live_minute.last_scan", "{}")
    log.info(
        "QuentX live-minute core initialized with a scenario-native "
        "candidate provider and serialized risk ledger."
    )


def scheduled_scan(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    set_universe(context.eligible_universe)
    history = get_history(
        count=HISTORY_BARS,
        unit="1m",
        fields=("close", "volume", "amount"),
    )
    current = get_current_data()
    ledger = _load_daily_ledger(context)
    ledger["scan_count"] = _ledger_count(ledger, "scan_count") + 1
    candidates, rejection_counts = _candidate_provider(
        context,
        current,
        history,
    )
    submitted_orders: list[dict[str, object]] = []
    exits = _risk_exit_orders(context, current)
    for instrument, amount in exits:
        order(instrument, amount)
        submitted_orders.append(
            {"amount": amount, "instrument": instrument, "side": "sell"}
        )
        log.warning(
            "QuentX live-minute stop-loss exit "
            f"instrument={instrument} amount={amount}"
        )
    if exits:
        _record_scan(
            context,
            candidates,
            rejection_counts,
            submitted_orders,
            ledger,
            history,
        )
        log.info(
            "QuentX live-minute deferred entries until submitted exits are "
            "reflected in a later portfolio snapshot."
        )
        return

    held = {
        position.instrument
        for position in context.portfolio.positions
        if position.amount > 0
    }
    bought_today = {
        str(item) for item in _as_list(ledger.get("bought_instruments"))
    }
    open_slots = max(0, MAX_POSITIONS - len(held))
    remaining_buys = max(
        0,
        MAX_NEW_BUYS_PER_DAY - _ledger_count(ledger, "buy_count"),
    )
    available_cash = context.portfolio.available_cash
    for candidate in candidates:
        if open_slots == 0 or remaining_buys == 0:
            break
        if candidate.instrument in held or candidate.instrument in bought_today:
            continue
        amount = _buy_amount(
            context,
            candidate.price,
            available_cash=available_cash,
        )
        if amount <= 0:
            continue
        order(candidate.instrument, amount)
        submitted_orders.append(
            {
                "amount": amount,
                "instrument": candidate.instrument,
                "side": "buy",
            }
        )
        available_cash -= candidate.price * amount
        open_slots -= 1
        remaining_buys -= 1
        ledger["buy_count"] = _ledger_count(ledger, "buy_count") + 1
        bought_today.add(candidate.instrument)
        log.info(
            "QuentX live-minute scenario-native entry "
            f"instrument={candidate.instrument} amount={amount} "
            f"signal_id={candidate.signal_id}"
        )
    ledger["bought_instruments"] = sorted(bought_today)
    _record_scan(
        context,
        candidates,
        rejection_counts,
        submitted_orders,
        ledger,
        history,
    )


def handle_data(
    context: PTradeContext,
    data: dict[str, MarketPathNode],
) -> None:
    """Retain the source strategy's bar-callback lifecycle without rescanning."""

    global strategy_global_counter
    strategy_global_counter += 1
    if context.current_dt and data:
        log.info("QuentX live-minute handle_data observed the active snapshot.")


def _candidate_provider(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
    history: dict[str, tuple[dict[str, object], ...]],
) -> tuple[tuple[_Candidate, ...], dict[str, int]]:
    candidates: list[_Candidate] = []
    rejections: dict[str, int] = {}
    for instrument in context.eligible_universe:
        rows = history.get(instrument, ())
        if len(rows) < MIN_HISTORY_BARS:
            _count(rejections, "insufficient_completed_minute_history")
            continue
        closes = tuple(_row_decimal(row, "close") for row in rows)
        price = current[instrument].close
        peak = max(closes)
        recent_trough = min(closes[-MIN_HISTORY_BARS:])
        if peak <= 0 or recent_trough <= 0 or price <= 0:
            _count(rejections, "invalid_point_in_time_price")
            continue
        drawdown = price / peak - Decimal("1")
        rebound = price / recent_trough - Decimal("1")
        if drawdown > -MIN_DISLOCATION_FRACTION:
            _count(rejections, "dislocation_too_shallow")
            continue
        if rebound < MIN_REBOUND_FRACTION or price <= closes[-1]:
            _count(rejections, "rebound_not_confirmed")
            continue
        if current[instrument].volume <= 0 or current[instrument].amount <= 0:
            _count(rejections, "non_liquid_current_bar")
            continue
        score = -drawdown + rebound
        candidates.append(
            _Candidate(
                signal_id=(
                    f"{context.current_dt.isoformat()}:{instrument}:"
                    "intraday_dislocation_rebound"
                ),
                instrument=instrument,
                score=score,
                price=price,
                drawdown=drawdown,
                rebound=rebound,
            )
        )
    candidates.sort(key=lambda item: (-item.score, item.instrument))
    return tuple(candidates), dict(sorted(rejections.items()))


def _risk_exit_orders(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
) -> tuple[tuple[str, int], ...]:
    exits: list[tuple[str, int]] = []
    for position in sorted(
        context.portfolio.positions,
        key=lambda item: item.instrument,
    ):
        node = current.get(position.instrument)
        if (
            node is None
            or position.amount <= 0
            or position.closeable_amount <= 0
            or position.average_cost <= 0
        ):
            continue
        stop_price = position.average_cost * (Decimal("1") - STOP_LOSS_FRACTION)
        if node.close <= stop_price:
            exits.append((position.instrument, -position.closeable_amount))
    return tuple(exits)


def _buy_amount(
    context: PTradeContext,
    price: Decimal,
    *,
    available_cash: Decimal,
) -> int:
    if price <= 0:
        return 0
    target_value = min(
        available_cash,
        context.portfolio.total_value * MAX_SINGLE_POSITION_FRACTION,
        price * context.order_shares,
    )
    amount = int(target_value / price) // LOT_SIZE * LOT_SIZE
    if amount <= 0 or price * amount < MIN_ORDER_VALUE:
        return 0
    return amount


def _load_daily_ledger(context: PTradeContext) -> dict[str, object]:
    current_date = context.current_dt.date()
    raw = context.state.get("live_minute.daily_ledger")
    if raw is None:
        raise ValueError(
            "QuentX live-minute daily risk ledger is missing; refusing to trade"
        )
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "QuentX live-minute daily risk ledger is corrupt; refusing to trade"
        ) from error
    if not isinstance(value, dict):
        raise ValueError(
            "QuentX live-minute daily risk ledger is invalid; refusing to trade"
        )
    raw_trade_date = value.get("trade_date")
    if not isinstance(raw_trade_date, str):
        raise ValueError(
            "QuentX live-minute daily risk ledger date is invalid; "
            "refusing to trade"
        )
    try:
        ledger_date = date.fromisoformat(raw_trade_date)
    except ValueError as error:
        raise ValueError(
            "QuentX live-minute daily risk ledger date is invalid; "
            "refusing to trade"
        ) from error
    if ledger_date < current_date:
        return _empty_daily_ledger(context.current_dt)
    if ledger_date > current_date:
        raise ValueError(
            "QuentX live-minute daily risk ledger is from the future; "
            "refusing to trade"
        )
    buy_count = value.get("buy_count")
    scan_count = value.get("scan_count")
    bought = value.get("bought_instruments")
    if (
        type(buy_count) is not int
        or type(scan_count) is not int
        or not isinstance(bought, list)
        or any(not isinstance(item, str) for item in bought)
        or buy_count < 0
        or buy_count > MAX_NEW_BUYS_PER_DAY
        or scan_count < 0
        or len(bought) != len(set(bought))
        or buy_count < len(bought)
    ):
        raise ValueError(
            "QuentX live-minute daily risk ledger fields are inconsistent; "
            "refusing to trade"
        )
    return {
        "bought_instruments": sorted(set(bought)),
        "buy_count": buy_count,
        "scan_count": scan_count,
        "trade_date": current_date.isoformat(),
    }


def _empty_daily_ledger(now: datetime) -> dict[str, object]:
    return {
        "bought_instruments": [],
        "buy_count": 0,
        "scan_count": 0,
        "trade_date": now.date().isoformat(),
    }


def _record_scan(
    context: PTradeContext,
    candidates: tuple[_Candidate, ...],
    rejection_counts: dict[str, int],
    submitted_orders: list[dict[str, object]],
    ledger: dict[str, object],
    history: dict[str, tuple[dict[str, object], ...]],
) -> None:
    context.state["live_minute.daily_ledger"] = _json(ledger)
    context.state["live_minute.last_history_shape"] = _json(
        {
            instrument: len(history.get(instrument, ()))
            for instrument in sorted(context.eligible_universe)
        }
    )
    context.state["live_minute.last_scan"] = _json(
        {
            "candidate_instruments": [item.instrument for item in candidates],
            "candidates": [
                {
                    "drawdown": _decimal_text(item.drawdown),
                    "instrument": item.instrument,
                    "rebound": _decimal_text(item.rebound),
                    "score": _decimal_text(item.score),
                    "signal_id": item.signal_id,
                }
                for item in candidates
            ],
            "decision_time": context.current_dt.isoformat(),
            "rejection_counts": rejection_counts,
            "submitted_orders": submitted_orders,
        }
    )


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _ledger_count(ledger: dict[str, object], field: str) -> int:
    value = ledger.get(field)
    return value if type(value) is int else 0


def _count(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _row_decimal(row: dict[str, object], field: str) -> Decimal:
    return Decimal(str(row[field]))


def _json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")
