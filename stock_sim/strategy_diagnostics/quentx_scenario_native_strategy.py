"""Scenario-native adaptation of the frozen QuentX 5.2.3 decision system.

The external Legacy Candidate Cache is replaced by causal calculations over the
active Scenario Data World's Eligible Universe.  The frozen executor decisions
remain visible here: LEGACY-A intraday aggregation, structural state-machine
candidates, institution/persistence ranking, overheat penalties, industry
concentration, 5.2.3 retest soft sizing, risk exits, and weak-holding rotation.
Daily state and 180-bar holding evidence are derived only from completed
scenario-native sessions; LEGACY-A bars are used only for intraday confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Callable, Protocol, Sequence

from .market_paths import InstrumentState, MarketPathNode


STRATEGY_LINEAGE = "QuentX5_2_3_retest_soft_promoted_v20260721"
CANDIDATE_SOURCE = "active_scenario"
MAX_POSITIONS = 3
DAILY_LOSS_ENTRY_HALT = Decimal("0.05")
EARLY_FAILURE_FRACTION = Decimal("0.08")
ROTATION_DURABILITY_MARGIN = Decimal("0.15")
MIN_ORDER_VALUE = Decimal("5000")
LOT_SIZE = 100
LEGACY_A_INPUT_BARS = 480
LEGACY_A_OUTPUT_BARS = 64
DAILY_HISTORY_BARS = 180
MIN_STRUCTURE_BARS = 60
ROTATION_MIN_BARS = 20
ROTATION_COOLDOWN_DAYS = 30


class _Position(Protocol):
    instrument: str
    amount: int
    closeable_amount: int
    average_cost: Decimal
    market_price: Decimal
    market_value: Decimal


class _Portfolio(Protocol):
    available_cash: Decimal
    total_value: Decimal
    positions: tuple[_Position, ...]


class PTradeContext(Protocol):
    current_dt: datetime
    portfolio: _Portfolio
    state: dict[str, str]
    eligible_universe: tuple[str, ...]
    instrument_states: tuple[InstrumentState, ...]
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
class _StructuralMetrics:
    state: str
    ret3: Decimal
    ret5: Decimal
    ret10: Decimal
    ret20: Decimal
    close_position: Decimal
    day_close_position: Decimal
    late_close_position: Decimal
    long_relative_position: Decimal
    volume_ratio: Decimal
    ma20_slope: Decimal
    ma60_slope: Decimal
    ma20_vs_ma60: Decimal
    close_vs_ma20: Decimal
    box_width: Decimal
    accumulation: Decimal
    volume_consistency: Decimal
    distribution_risk: Decimal
    smoothness: Decimal
    atr14: Decimal
    defense_price: Decimal
    structural_score: Decimal
    amount: Decimal
    source_price: Decimal


@dataclass(frozen=True, slots=True)
class _SectorContext:
    industry: str
    ret5: Decimal
    ret20: Decimal
    breadth20: Decimal
    amount_share: Decimal
    persistence: Decimal
    mainline_score: Decimal


@dataclass(frozen=True, slots=True)
class _Candidate:
    instrument: str
    industry: str
    state: str
    price: Decimal
    score: Decimal
    structural_score: Decimal
    behavior_score: Decimal
    durability: Decimal
    defense_price: Decimal
    position_scale: Decimal
    sector: _SectorContext


@dataclass(frozen=True, slots=True)
class _IntradayAssessment:
    admitted: bool
    reason: str
    day_close_position: Decimal
    late_close_position: Decimal
    quality: Decimal


def initialize(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    set_universe(context.eligible_universe)
    set_slippage(Decimal("5"))
    set_commission(Decimal("3"))
    run_daily(
        scheduled_scan,
        cadence_minutes=context.decision_cadence_minutes,
    )
    context.state["quentx.candidate_source"] = CANDIDATE_SOURCE
    context.state["quentx.strategy_lineage"] = STRATEGY_LINEAGE
    context.state["quentx.history_contract"] = (
        "180x1d-state+480x1m->legacy-a->last64x5m-confirmation"
    )
    context.state["quentx.day"] = context.current_dt.date().isoformat()
    context.state["quentx.day_start_equity"] = _decimal_text(
        context.portfolio.total_value
    )
    context.state.setdefault("quentx.last_ranked_candidates", "[]")
    context.state.setdefault("quentx.last_candidate_rejections", "{}")
    log.info(
        "QuentX 5.2.3 initialized with scenario-native candidate generation."
    )


def scheduled_scan(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    set_universe(context.eligible_universe)
    one_minute_history = get_history(
        count=LEGACY_A_INPUT_BARS,
        unit="1m",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    daily_history = get_history(
        count=DAILY_HISTORY_BARS,
        unit="1d",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    intraday_history = {
        instrument: _legacy_a_five_minute_bars(rows)
        for instrument, rows in one_minute_history.items()
    }
    current = get_current_data()
    candidates = _generate_candidates(
        context,
        current,
        daily_history,
        intraday_history,
    )
    context.state["quentx.last_ranked_candidates"] = json.dumps(
        [
            {
                "instrument": item.instrument,
                "state": item.state,
                "structural_score": _decimal_text(item.structural_score),
                "behavior_score": _decimal_text(item.behavior_score),
                "durability": _decimal_text(item.durability),
                "position_scale": _decimal_text(item.position_scale),
            }
            for item in candidates
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    context.state["quentx.last_history_shape"] = json.dumps(
        {
            instrument: {
                "one_minute": len(one_minute_history.get(instrument, ())),
                "legacy_five_minute": len(rows),
                "completed_daily": len(daily_history.get(instrument, ())),
            }
            for instrument, rows in sorted(intraday_history.items())
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    _reset_day_boundary(context)
    positions = {
        item.instrument: item for item in context.portfolio.positions
    }
    exits = _risk_exit_orders(context, current, daily_history)
    for instrument, amount, reason in exits:
        order(instrument, amount)
        log.warning(
            f"QuentX risk exit instrument={instrument} reason={reason}"
        )
    if exits:
        log.info(
            "QuentX deferred all entries until submitted exits are reflected "
            "in a later portfolio snapshot."
        )
        return

    entries_halted = _daily_loss_halt(context)
    if entries_halted:
        log.warning("QuentX entries halted by the frozen 5% daily loss guard.")
        return

    held_after_exits = set(positions)
    new_candidates = tuple(
        item for item in candidates if item.instrument not in held_after_exits
    )
    if not exits and len(held_after_exits) >= MAX_POSITIONS and new_candidates:
        rotation = _rotation_order(
            context,
            current,
            daily_history,
            positions,
            new_candidates,
        )
        if rotation is not None:
            sell_instrument, sell_amount, candidate = rotation
            order(sell_instrument, sell_amount)
            context.state["quentx.last_rotation"] = (
                f"{sell_instrument}->{candidate.instrument}"
            )
            context.state["quentx.last_rotation_day"] = (
                context.current_dt.date().isoformat()
            )
            log.info(
                "QuentX weak-holding rotation "
                f"sell={sell_instrument} compare={candidate.instrument} "
                "action=sell_then_reassess_next_session"
            )
        return

    open_slots = max(0, MAX_POSITIONS - len(held_after_exits))
    if open_slots == 0:
        return
    industry_counts = _held_industry_counts(context, held_after_exits)
    available_cash = context.portfolio.available_cash
    for candidate in new_candidates:
        if open_slots == 0:
            break
        if industry_counts.get(candidate.industry, 0) >= _industry_position_limit(
            candidate
        ):
            continue
        amount = _buy_amount(
            context,
            candidate,
            available_cash=available_cash,
        )
        if amount <= 0:
            continue
        order(candidate.instrument, amount)
        available_cash -= candidate.price * amount
        open_slots -= 1
        industry_counts[candidate.industry] = (
            industry_counts.get(candidate.industry, 0) + 1
        )
        _remember_entry(context, candidate)
        log.info(
            "QuentX scenario-native entry "
            f"instrument={candidate.instrument} amount={amount} "
            f"state={candidate.state} scale={_decimal_text(candidate.position_scale)}"
        )


def handle_data(
    context: PTradeContext,
    data: dict[str, MarketPathNode],
) -> None:
    """Retain the optional PTrade lifecycle without duplicating scheduled scans."""

    global strategy_global_counter
    strategy_global_counter += 1
    if context.current_dt and data:
        log.info("QuentX handle_data observed the active scenario snapshot.")


def _legacy_a_five_minute_bars(
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Reproduce the frozen global five-row LEGACY-A aggregation contract."""

    output: list[dict[str, object]] = []
    for offset in range(0, len(rows), 5):
        group = rows[offset : offset + 5]
        if not group:
            continue
        output.append(
            {
                "simulation_time": group[-1].get("simulation_time"),
                "open": _row_decimal(group[0], "open"),
                "high": max(_row_decimal(item, "high") for item in group),
                "low": min(_row_decimal(item, "low") for item in group),
                "close": _row_decimal(group[-1], "close"),
                "volume": sum(
                    (_row_decimal(item, "volume") for item in group),
                    Decimal("0"),
                ),
                "amount": sum(
                    (_row_decimal(item, "amount") for item in group),
                    Decimal("0"),
                ),
            }
        )
    return tuple(output[-LEGACY_A_OUTPUT_BARS:])


def _generate_candidates(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
    daily_history: dict[str, tuple[dict[str, object], ...]],
    intraday_history: dict[str, tuple[dict[str, object], ...]],
) -> tuple[_Candidate, ...]:
    state_by_instrument = {
        item.instrument: item for item in context.instrument_states
    }
    metrics_by_instrument: dict[str, _StructuralMetrics] = {}
    rejection_counts: dict[str, int] = {}
    for instrument in context.eligible_universe:
        state = state_by_instrument.get(instrument)
        node = current.get(instrument)
        rows = daily_history.get(instrument, ())
        if (
            state is None
            or node is None
            or not state.eligible
            or state.trading_status != "trading"
            or state.is_st
        ):
            _count_rejection(rejection_counts, "ineligible_or_untradeable")
            continue
        metrics = _structural_metrics(rows)
        if metrics is None:
            _count_rejection(
                rejection_counts,
                "insufficient_completed_daily_history",
            )
            continue
        metrics_by_instrument[instrument] = metrics

    sectors = _sector_contexts(
        context,
        current,
        state_by_instrument,
        metrics_by_instrument,
    )
    market_state = _market_trade_state(metrics_by_instrument)
    candidates: list[_Candidate] = []
    for instrument in context.eligible_universe:
        metrics = metrics_by_instrument.get(instrument)
        state = state_by_instrument.get(instrument)
        node = current.get(instrument)
        if metrics is None or state is None or node is None:
            continue
        intraday = _intraday_entry_assessment(
            intraday_history.get(instrument, ()),
            context.current_dt,
            node,
            metrics,
        )
        if not intraday.admitted:
            _count_rejection(rejection_counts, intraday.reason)
            continue
        sector = sectors.get(state.industry)
        if sector is None:
            _count_rejection(rejection_counts, "industry_context_missing")
            continue
        structural_rejection = _structural_rejection_reason(metrics)
        if structural_rejection:
            _count_rejection(rejection_counts, structural_rejection)
            continue
        sector_floor = (
            Decimal("0.62")
            if market_state == "strong"
            else Decimal("0.72")
        )
        if (
            market_state == "defensive"
            or sector.mainline_score < sector_floor
            or sector.persistence < Decimal("0.30")
        ):
            _count_rejection(rejection_counts, "not_persistent_market_mainline")
            continue
        structural_score = (
            metrics.structural_score * Decimal("0.70")
            + sector.mainline_score * Decimal("0.30")
        )
        opportunity_rejection = _entry_opportunity_rejection_reason(
            market_state,
            structural_score,
            metrics,
            sector,
        )
        if opportunity_rejection:
            _count_rejection(rejection_counts, opportunity_rejection)
            continue
        persistence_quality = _institutional_persistence_quality(metrics, sector)
        patience_rejection = _institutional_patience_rejection_reason(
            metrics,
            sector,
            structural_score,
            persistence_quality,
        )
        if patience_rejection:
            _count_rejection(rejection_counts, patience_rejection)
            continue
        support_broken, soft_reasons = _low_volume_retest_assessment(
            state=metrics.state,
            volume_ratio=metrics.volume_ratio,
            current_price=node.close,
            defense_price=metrics.defense_price,
            smoothness=metrics.smoothness,
            day_close_position=intraday.day_close_position,
            late_close_position=intraday.late_close_position,
        )
        if support_broken:
            _count_rejection(
                rejection_counts,
                "retest_low_volume_support_broken",
            )
            continue
        durability = _institutional_durability(metrics)
        behavior = _institutional_behavior_quality(
            metrics,
            sector,
            persistence_quality,
            durability,
        )
        daily_score = (
            structural_score
            + _candidate_rank_adjustment(metrics, sector)
            - _entry_overextension_penalty(metrics)
        )
        score = _bounded(
            daily_score * Decimal("0.94")
            + intraday.quality * Decimal("0.06")
        )
        position_scale = _entry_position_scale(
            market_state=market_state,
            industry_ret20=sector.ret20,
            retest_soft_reasons=soft_reasons,
        )
        candidates.append(
            _Candidate(
                instrument=instrument,
                industry=state.industry,
                state=metrics.state,
                price=node.close,
                score=score,
                structural_score=structural_score,
                behavior_score=behavior,
                durability=durability,
                defense_price=metrics.defense_price,
                position_scale=position_scale,
                sector=sector,
            )
        )
    context.state["quentx.last_candidate_rejections"] = json.dumps(
        rejection_counts,
        separators=(",", ":"),
        sort_keys=True,
    )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def _structural_metrics(
    rows: tuple[dict[str, object], ...],
) -> _StructuralMetrics | None:
    if len(rows) < MIN_STRUCTURE_BARS:
        return None
    bars = list(rows)
    closes = [_row_decimal(item, "close") for item in bars]
    opens = [_row_decimal(item, "open") for item in bars]
    highs = [_row_decimal(item, "high") for item in bars]
    lows = [_row_decimal(item, "low") for item in bars]
    volumes = [_row_decimal(item, "volume") for item in bars]
    amounts = [_row_decimal(item, "amount") for item in bars]
    if min((*closes, *opens, *highs, *lows, *volumes)) <= 0:
        return None
    latest_close = closes[-1]
    index = len(closes) - 1
    prior60_start = max(0, index - 60)
    prior20_start = max(0, index - 20)
    prior_closes = closes[prior60_start:index]
    prior_highs = highs[prior60_start:index]
    prior_lows = lows[prior60_start:index]
    prior20_lows = lows[prior20_start:index]
    prior20_volumes = volumes[prior20_start:index]
    if not prior_closes or not prior20_volumes:
        return None
    prior_high = max(prior_highs)
    prior_low = min(prior_lows)
    prior20_low = min(prior20_lows)
    average_volume20 = _mean(prior20_volumes)
    average_volume60 = _mean(volumes[prior60_start:index])
    if min(prior_high, prior_low, prior20_low, average_volume20) <= 0:
        return None
    ma20 = _mean(closes[max(0, index - 19) : index + 1])
    ma60 = _mean(closes[max(0, index - 59) : index + 1])
    ma20_prior = _shifted_mean(closes, window=20, shift=10)
    ma60_prior = _shifted_mean(closes, window=60, shift=20)
    ma20_slope = _safe_return(ma20, ma20_prior)
    ma60_slope = _safe_return(ma60, ma60_prior)
    ma20_vs_ma60 = _safe_return(ma20, ma60)
    close_vs_ma20 = _safe_return(latest_close, ma20)
    breakout_pct = _safe_return(latest_close, prior_high)
    box_width = _safe_return(prior_high, prior_low)
    volume_ratio = volumes[-1] / average_volume20
    pct_change = _safe_return(latest_close, closes[-2]) * Decimal("100")
    atr14 = _atr(highs, lows, closes)
    if atr14 <= 0:
        return None
    constructive_days = sum(
        1
        for offset in range(prior60_start, index)
        if closes[offset] >= opens[offset]
        and volumes[offset] >= average_volume60 * Decimal("1.15")
    )
    active_volume_days = sum(
        1
        for value in volumes[prior60_start:index]
        if value >= average_volume60 * Decimal("1.15")
    )
    up_volume = sum(
        (
            volumes[offset]
            for offset in range(prior60_start, index)
            if closes[offset] >= opens[offset]
        ),
        Decimal("0"),
    )
    down_volume = sum(
        (
            volumes[offset]
            for offset in range(prior60_start, index)
            if closes[offset] < opens[offset]
        ),
        Decimal("0"),
    )
    volume_consistency = min(
        Decimal("1"),
        Decimal(active_volume_days) / Decimal("12"),
    )
    accumulation = min(
        Decimal("1"),
        Decimal(constructive_days) / Decimal("8") * Decimal("0.55")
        + min(
            Decimal("1"),
            up_volume / down_volume if down_volume > 0 else Decimal("1"),
        )
        * Decimal("0.45"),
    )
    efficiency = _trend_efficiency(closes[prior60_start : index + 1])
    percentage_moves = [
        _safe_return(closes[offset], closes[offset - 1]) * Decimal("100")
        for offset in range(max(1, index - 40), index + 1)
    ]
    large_moves = [value for value in percentage_moves if abs(value) >= 6]
    large_down_days = sum(value <= -6 for value in large_moves)
    large_reversal_count = sum(
        large_moves[offset] * large_moves[offset - 1] < 0
        for offset in range(1, len(large_moves))
    )
    smoothness = _bounded(
        Decimal("0.55")
        + efficiency * Decimal("0.70")
        - Decimal(large_down_days) * Decimal("0.08")
        - Decimal(large_reversal_count) * Decimal("0.12")
    )
    distribution_risk = _distribution_risk(
        opens,
        highs,
        lows,
        closes,
        volumes,
        average_volume20,
    )
    history_low = min(lows)
    history_high = max(highs)
    long_position = _range_position(latest_close, history_low, history_high)
    recent_breakout = _recent_breakout(closes, highs)
    recent_high = max(highs[max(0, index - 15) : index + 1])
    pullback = _safe_return(latest_close, recent_high)
    retest_tolerance = max(
        Decimal("0.12"),
        min(
            Decimal("0.22"),
            atr14 * Decimal("3") / recent_high,
        ),
    )
    breakout_setup = (
        Decimal("0") < breakout_pct <= Decimal("0.055")
        and Decimal("1.15") <= volume_ratio <= Decimal("3.5")
        and pct_change < Decimal("9.5")
    )
    retest_setup = (
        recent_breakout
        and -retest_tolerance <= pullback <= Decimal("0.02")
        and Decimal("-4") <= pct_change <= Decimal("6.5")
        and Decimal("0.65") <= volume_ratio <= Decimal("2.5")
        and Decimal("0") <= close_vs_ma20 <= Decimal("0.10")
    )
    recent20_high = max(highs[max(0, index - 20) : index + 1])
    trend_pullback_setup = (
        Decimal("-0.10")
        <= _safe_return(latest_close, recent20_high)
        <= Decimal("0.01")
        and Decimal("-3.5") <= pct_change <= Decimal("4.5")
        and Decimal("0.55") <= volume_ratio <= Decimal("2.2")
        and Decimal("0") <= close_vs_ma20 <= Decimal("0.08")
    )
    state = (
        "institutional_mainline_breakout"
        if breakout_setup
        else "institutional_mainline_post_breakout_retest"
        if retest_setup
        else "institutional_mainline_trend_pullback"
        if trend_pullback_setup
        else "unconfirmed"
    )
    trend_score = min(
        Decimal("1"),
        Decimal("0.45")
        + min(Decimal("0.20"), ma20_slope * Decimal("4"))
        + min(Decimal("0.20"), ma60_slope * Decimal("4"))
        + min(
            Decimal("0.15"),
            max(Decimal("0"), ma20_vs_ma60) * Decimal("1.5"),
        ),
    )
    structural_score = (
        trend_score * Decimal("0.30")
        + accumulation * Decimal("0.25")
        + volume_consistency * Decimal("0.15")
        + smoothness * Decimal("0.20")
        + (Decimal("1") - distribution_risk) * Decimal("0.10")
    )
    initial_support = max(
        ma60 - atr14 * Decimal("1.5"),
        prior20_low - atr14 * Decimal("0.5"),
    )
    initial_support = min(initial_support, latest_close - atr14 * Decimal("0.5"))
    bar_position = _range_position(latest_close, lows[-1], highs[-1])
    day_position = _range_position(latest_close, min(lows), max(highs))
    late_position = _range_position(
        latest_close,
        min(lows[max(0, index - 9) : index + 1]),
        max(highs[max(0, index - 9) : index + 1]),
    )
    return _StructuralMetrics(
        state=state,
        ret3=_window_return(closes, 3),
        ret5=_window_return(closes, 5),
        ret10=_window_return(closes, 10),
        ret20=_window_return(closes, 20),
        close_position=bar_position,
        day_close_position=day_position,
        late_close_position=late_position,
        long_relative_position=long_position,
        volume_ratio=volume_ratio,
        ma20_slope=ma20_slope,
        ma60_slope=ma60_slope,
        ma20_vs_ma60=ma20_vs_ma60,
        close_vs_ma20=close_vs_ma20,
        box_width=box_width,
        accumulation=accumulation,
        volume_consistency=volume_consistency,
        distribution_risk=distribution_risk,
        smoothness=smoothness,
        atr14=atr14,
        defense_price=initial_support,
        structural_score=structural_score,
        amount=amounts[-1],
        source_price=latest_close,
    )


def _intraday_entry_assessment(
    rows: tuple[dict[str, object], ...],
    timestamp: datetime,
    node: MarketPathNode,
    metrics: _StructuralMetrics,
) -> _IntradayAssessment:
    current_day = timestamp.date()
    day_rows = tuple(
        row
        for row in rows
        if _row_date(row) == current_day
    )
    if len(day_rows) < 20:
        return _IntradayAssessment(
            admitted=False,
            reason="minute_history_insufficient",
            day_close_position=Decimal("0"),
            late_close_position=Decimal("0"),
            quality=Decimal("0"),
        )
    day_open = _row_decimal(day_rows[0], "open")
    day_high = max(
        max(_row_decimal(row, "high") for row in day_rows),
        node.high,
        node.close,
    )
    day_low = min(
        min(_row_decimal(row, "low") for row in day_rows),
        node.low,
        node.close,
    )
    day_volume = sum(
        (_row_decimal(row, "volume") for row in day_rows),
        Decimal("0"),
    )
    if min(day_open, day_high, day_low, day_volume, node.close) <= 0:
        return _IntradayAssessment(
            admitted=False,
            reason="minute_snapshot_invalid",
            day_close_position=Decimal("0"),
            late_close_position=Decimal("0"),
            quality=Decimal("0"),
        )
    late_rows = day_rows[-6:]
    late_open = _row_decimal(late_rows[0], "open")
    late_high = max(
        max(_row_decimal(row, "high") for row in late_rows),
        node.high,
        node.close,
    )
    late_low = min(
        min(_row_decimal(row, "low") for row in late_rows),
        node.low,
        node.close,
    )
    day_close_position = _range_position(node.close, day_low, day_high)
    late_close_position = _range_position(node.close, late_low, late_high)
    day_return = _safe_return(node.close, day_open)
    source_return = _safe_return(node.close, metrics.source_price)
    late_return = _safe_return(node.close, late_open)
    fade_from_high = _safe_return(node.close, day_high)
    prior_rows = tuple(
        row
        for row in rows
        if (row_day := _row_date(row)) is not None and row_day < current_day
    )
    reference_rows = prior_rows[-20:] or day_rows[:-6]
    reference_volume = _mean(
        [_row_decimal(row, "volume") for row in reference_rows]
    )
    participation_ratio = (
        day_volume / (reference_volume * Decimal(len(day_rows)))
        if reference_volume > 0
        else Decimal("1")
    )
    day_high_index = max(
        range(len(day_rows)),
        key=lambda index: _row_decimal(day_rows[index], "high"),
    )
    early_peak = day_high_index < min(12, max(1, len(day_rows) // 3))
    late_closes = [_row_decimal(row, "close") for row in late_rows]
    down_steps = sum(
        current < previous
        for previous, current in zip(late_closes, late_closes[1:])
    )
    reason = ""
    if node.close < metrics.defense_price:
        reason = "intraday_breaks_daily_defense"
    elif node.close > metrics.source_price * Decimal("1.06") or day_return >= Decimal(
        "0.08"
    ):
        reason = "intraday_chase_overextended"
    elif day_close_position <= Decimal("0.15") and min(
        day_return,
        source_return,
    ) <= Decimal("-0.08"):
        reason = "intraday_extreme_session_breakdown"
    elif (
        early_peak
        and fade_from_high <= Decimal("-0.045")
        and day_close_position <= Decimal("0.22")
        and late_return <= Decimal("-0.010")
        and participation_ratio >= Decimal("1.10")
    ):
        reason = "intraday_early_spike_persistent_fade"
    elif (
        day_close_position <= Decimal("0.15")
        and late_return <= Decimal("-0.018")
        and down_steps >= max(3, len(late_rows) - 2)
        and participation_ratio >= Decimal("1")
    ):
        reason = "intraday_late_session_breakdown"
    quality = Decimal("0.42")
    quality += min(Decimal("0.18"), day_close_position * Decimal("0.18"))
    quality += min(Decimal("0.12"), late_close_position * Decimal("0.12"))
    if node.close >= day_open:
        quality += Decimal("0.10")
    if Decimal("0.65") <= participation_ratio <= Decimal("2.50"):
        quality += Decimal("0.08")
    if fade_from_high <= Decimal("-0.03"):
        quality -= Decimal("0.08")
    return _IntradayAssessment(
        admitted=not reason,
        reason=reason,
        day_close_position=day_close_position,
        late_close_position=late_close_position,
        quality=_bounded(quality),
    )


def _structural_rejection_reason(metrics: _StructuralMetrics) -> str:
    setup_structure_ok = (
        metrics.state == "institutional_mainline_breakout"
        and metrics.box_width <= Decimal("0.42")
    ) or (
        metrics.state
        in {
            "institutional_mainline_post_breakout_retest",
            "institutional_mainline_trend_pullback",
        }
        and metrics.atr14 > 0
    )
    if not setup_structure_ok:
        return "state_machine_setup_not_confirmed"
    if metrics.ma20_vs_ma60 <= 0 or metrics.ma20_slope <= 0:
        return "moving_average_trend_not_confirmed"
    if not Decimal("0") <= metrics.close_vs_ma20 <= Decimal("0.20"):
        return "price_not_supported_by_ma20"
    if metrics.accumulation < Decimal("0.48"):
        return "accumulation_persistence_below_floor"
    if metrics.volume_consistency < Decimal("0.33"):
        return "volume_consistency_below_floor"
    if metrics.distribution_risk >= Decimal("0.55"):
        return "distribution_risk_above_ceiling"
    if metrics.smoothness < Decimal("0.45"):
        return "structure_smoothness_below_floor"
    return ""


def _sector_contexts(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
    states: dict[str, InstrumentState],
    metrics: dict[str, _StructuralMetrics],
) -> dict[str, _SectorContext]:
    members: dict[str, list[str]] = {}
    for instrument in context.eligible_universe:
        state = states.get(instrument)
        if state is not None and instrument in metrics:
            members.setdefault(state.industry, []).append(instrument)
    ret5: dict[str, Decimal] = {}
    ret20: dict[str, Decimal] = {}
    breadth: dict[str, Decimal] = {}
    amounts: dict[str, Decimal] = {}
    for industry, instruments in members.items():
        ret5[industry] = _mean([metrics[item].ret5 for item in instruments])
        ret20[industry] = _mean([metrics[item].ret20 for item in instruments])
        breadth[industry] = Decimal(
            sum(metrics[item].ret20 > 0 for item in instruments)
        ) / Decimal(len(instruments))
        amounts[industry] = sum(
            (current[item].amount for item in instruments),
            Decimal("0"),
        )
    ranks5 = _rank(ret5)
    ranks20 = _rank(ret20)
    ranks_breadth = _rank(breadth)
    ranks_amount = _rank(amounts)
    total_amount = sum(amounts.values(), Decimal("0"))
    horizon_values = {
        3: {industry: _mean([metrics[item].ret3 for item in instruments]) for industry, instruments in members.items()},
        5: ret5,
        10: {industry: _mean([metrics[item].ret10 for item in instruments]) for industry, instruments in members.items()},
        20: ret20,
    }
    horizon_ranks = {
        horizon: _rank(values) for horizon, values in horizon_values.items()
    }
    result: dict[str, _SectorContext] = {}
    for industry, instruments in members.items():
        base_score = (
            ranks5[industry] * Decimal("0.25")
            + ranks20[industry] * Decimal("0.35")
            + ranks_breadth[industry] * Decimal("0.25")
            + ranks_amount[industry] * Decimal("0.15")
        )
        persistence = Decimal(
            sum(
                horizon_ranks[horizon][industry] >= Decimal("0.65")
                for horizon in horizon_ranks
            )
        ) / Decimal(len(horizon_ranks))
        breadth_hints = [
            dict(current[item].features).get("sector_breadth", Decimal("0"))
            for item in instruments
        ]
        if len(members) == 1:
            causal_breadth = _mean(breadth_hints)
            base_score = max(base_score, causal_breadth)
            persistence = max(persistence, causal_breadth)
            breadth[industry] = max(breadth[industry], causal_breadth)
        mainline = base_score * Decimal("0.80") + persistence * Decimal("0.20")
        result[industry] = _SectorContext(
            industry=industry,
            ret5=ret5[industry],
            ret20=ret20[industry],
            breadth20=breadth[industry],
            amount_share=(
                amounts[industry] / total_amount
                if total_amount > 0
                else Decimal("0")
            ),
            persistence=persistence,
            mainline_score=mainline,
        )
    return result


def _market_trade_state(metrics: dict[str, _StructuralMetrics]) -> str:
    if not metrics:
        return "defensive"
    values = tuple(metrics.values())
    close_vs_ma20 = _mean([item.close_vs_ma20 for item in values])
    ma20_vs_ma60 = _mean([item.ma20_vs_ma60 for item in values])
    ma20_slope = _mean([item.ma20_slope for item in values])
    if close_vs_ma20 >= 0 and ma20_vs_ma60 > 0 and ma20_slope > 0:
        return "strong"
    if close_vs_ma20 >= 0 or ma20_slope > 0:
        return "neutral"
    return "defensive"


def _entry_opportunity_rejection_reason(
    market_state: str,
    structural_score: Decimal,
    metrics: _StructuralMetrics,
    sector: _SectorContext,
) -> str:
    if market_state == "strong":
        if sector.mainline_score < Decimal("0.80"):
            return "strong_market_mainline_below_opportunity_hurdle"
        if structural_score < Decimal("0.82"):
            return "strong_market_structure_below_experiment_hurdle"
        if metrics.smoothness < Decimal("0.58"):
            return "strong_market_trend_too_oscillatory"
        return ""
    if market_state != "neutral":
        return "market_not_selective_entry_state"
    if sector.mainline_score < Decimal("0.80"):
        return "neutral_market_mainline_below_opportunity_hurdle"
    if structural_score < Decimal("0.82"):
        return "neutral_market_structure_below_opportunity_hurdle"
    if metrics.smoothness < Decimal("0.50"):
        return "neutral_market_trend_too_oscillatory"
    return ""


def _institutional_persistence_quality(
    metrics: _StructuralMetrics,
    sector: _SectorContext,
) -> Decimal:
    evidence = (
        sector.mainline_score >= Decimal("0.90")
        and sector.breadth20 >= Decimal("0.70"),
        sector.persistence >= Decimal("0.75"),
        metrics.ma20_slope >= Decimal("0.045")
        and metrics.ma20_vs_ma60 > 0,
        metrics.smoothness >= Decimal("0.58"),
        Decimal("0") < metrics.volume_ratio <= Decimal("1.45"),
        metrics.ret5 <= Decimal("0.12"),
    )
    weights = (
        Decimal("0.22"),
        Decimal("0.18"),
        Decimal("0.18"),
        Decimal("0.18"),
        Decimal("0.12"),
        Decimal("0.12"),
    )
    return sum(
        (weight for confirmed, weight in zip(evidence, weights, strict=True) if confirmed),
        Decimal("0"),
    )


def _institutional_patience_rejection_reason(
    metrics: _StructuralMetrics,
    sector: _SectorContext,
    structural_score: Decimal,
    persistence_quality: Decimal,
) -> str:
    stock_trend_confirmed = structural_score >= Decimal("0.86") or (
        metrics.ma20_slope >= Decimal("0.045")
        and metrics.ma20_vs_ma60 > 0
    )
    mainline_confirmed = (
        sector.mainline_score >= Decimal("0.93")
        and sector.breadth20 >= Decimal("0.75")
    )
    if metrics.state == "institutional_mainline_breakout":
        path = stock_trend_confirmed or mainline_confirmed
        durable_context = mainline_confirmed or (
            metrics.ma20_slope >= Decimal("0.045")
            and metrics.ma20_vs_ma60 > 0
        )
        if not path:
            return "institutional_first_wave_quality_not_confirmed"
        if persistence_quality < Decimal("0.64") or not durable_context:
            return "institutional_first_wave_persistence_not_confirmed"
        return ""
    calm_retest = metrics.volume_ratio <= Decimal("1.45")
    deep_early_structure = (
        metrics.long_relative_position <= Decimal("0.55")
        and metrics.ret5 <= Decimal("0.08")
        and metrics.volume_ratio <= Decimal("1.80")
    )
    slow_mainline_trend = (
        sector.mainline_score >= Decimal("0.90")
        and sector.breadth20 >= Decimal("0.70")
        and metrics.smoothness >= Decimal("0.58")
        and metrics.volume_ratio <= Decimal("1.25")
        and metrics.ma20_vs_ma60 > 0
    )
    path = (
        (stock_trend_confirmed and mainline_confirmed)
        or (stock_trend_confirmed and calm_retest)
        or (stock_trend_confirmed and deep_early_structure)
        or slow_mainline_trend
    )
    if not path:
        return "institutional_patience_setup_not_confirmed"
    if persistence_quality < Decimal("0.52"):
        return "institutional_retest_persistence_not_confirmed"
    return ""


def _low_volume_retest_assessment(
    *,
    state: str,
    volume_ratio: Decimal,
    current_price: Decimal,
    defense_price: Decimal,
    smoothness: Decimal,
    day_close_position: Decimal,
    late_close_position: Decimal,
) -> tuple[bool, tuple[str, ...]]:
    if (
        state != "institutional_mainline_post_breakout_retest"
        or volume_ratio >= Decimal("1")
    ):
        return False, ()
    support_broken = (
        current_price > 0
        and defense_price > 0
        and current_price < defense_price
    )
    soft_reasons: list[str] = []
    if smoothness < Decimal("0.62"):
        soft_reasons.append("structure_not_smooth")
    if Decimal("0") < day_close_position < Decimal("0.55"):
        soft_reasons.append("day_demand_weak")
    if Decimal("0") < late_close_position < Decimal("0.45"):
        soft_reasons.append("late_demand_weak")
    return support_broken, tuple(soft_reasons)


def _entry_position_scale(
    *,
    market_state: str,
    industry_ret20: Decimal,
    retest_soft_reasons: tuple[str, ...],
) -> Decimal:
    scale = Decimal("0.50") if retest_soft_reasons else Decimal("1")
    if market_state == "strong" and industry_ret20 >= Decimal("0.10"):
        scale = min(scale, Decimal("0.50"))
    return scale


def _institutional_durability(metrics: _StructuralMetrics) -> Decimal:
    ma20_quality = _bounded(metrics.ma20_slope / Decimal("0.08"))
    spread_quality = _bounded(metrics.ma20_vs_ma60 / Decimal("0.10"))
    slow_quality = _bounded(
        (metrics.ma60_slope + Decimal("0.005")) / Decimal("0.04")
    )
    stable_supply = (
        metrics.accumulation
        + metrics.volume_consistency
        + (Decimal("1") - metrics.distribution_risk)
    ) / Decimal("3")
    return _bounded(
        ma20_quality * Decimal("0.40")
        + spread_quality * Decimal("0.32")
        + slow_quality * Decimal("0.18")
        + stable_supply * Decimal("0.10")
    )


def _institutional_behavior_quality(
    metrics: _StructuralMetrics,
    sector: _SectorContext,
    persistence_quality: Decimal,
    durability: Decimal,
) -> Decimal:
    volume_quality = _institutional_volume_quality(metrics)
    moving_average_quality = (
        _bounded(metrics.ma20_slope / Decimal("0.045"))
        if metrics.ma20_vs_ma60 > 0
        else Decimal("0")
    )
    individual = _bounded(
        metrics.smoothness * Decimal("0.22")
        + metrics.accumulation * Decimal("0.18")
        + (Decimal("1") - metrics.distribution_risk) * Decimal("0.16")
        + volume_quality * Decimal("0.16")
        + moving_average_quality * Decimal("0.16")
        + sector.persistence * Decimal("0.08")
        + sector.amount_share * Decimal("0.04")
    )
    return _bounded(
        durability * Decimal("0.30")
        + individual * Decimal("0.25")
        + volume_quality * Decimal("0.20")
        + persistence_quality * Decimal("0.15")
        + sector.persistence * Decimal("0.10")
    )


def _institutional_volume_quality(metrics: _StructuralMetrics) -> Decimal:
    if metrics.state == "institutional_mainline_breakout":
        score = Decimal("0.35")
        if Decimal("1.15") <= metrics.volume_ratio <= Decimal("2.80"):
            score += Decimal("0.35")
        elif Decimal("0.90") <= metrics.volume_ratio <= Decimal("3.50"):
            score += Decimal("0.18")
        if metrics.close_position >= Decimal("0.55"):
            score += Decimal("0.20")
        if metrics.ret5 <= Decimal("0.12"):
            score += Decimal("0.10")
    else:
        score = Decimal("0.25")
        if Decimal("0.55") <= metrics.volume_ratio <= Decimal("1.45"):
            score += Decimal("0.35")
        elif Decimal("0.40") <= metrics.volume_ratio <= Decimal("1.80"):
            score += Decimal("0.18")
        if metrics.volume_ratio <= Decimal("1.15") and metrics.ret5 >= -Decimal("0.02"):
            score += Decimal("0.20")
        if metrics.close_position >= Decimal("0.45"):
            score += Decimal("0.10")
        if metrics.ret5 <= Decimal("0.12"):
            score += Decimal("0.10")
    effort_without_progress = (
        metrics.volume_ratio >= Decimal("1.60")
        and metrics.ret3 <= Decimal("0.02")
        and metrics.close_position <= Decimal("0.55")
    )
    if effort_without_progress:
        score -= Decimal("0.35")
    score -= metrics.distribution_risk * Decimal("0.35")
    return _bounded(score)


def _candidate_rank_adjustment(
    metrics: _StructuralMetrics,
    sector: _SectorContext,
) -> Decimal:
    adjustment = (
        (sector.persistence - Decimal("0.75")) * Decimal("0.12")
        + (sector.breadth20 - Decimal("0.60")) * Decimal("0.04")
    )
    recent_confirmation = max(
        metrics.ret3,
        metrics.ret5 * Decimal("0.60"),
    )
    recent_confirmation = max(
        Decimal("-0.04"),
        min(Decimal("0.05"), recent_confirmation),
    )
    low_retest = (
        metrics.state == "institutional_mainline_post_breakout_retest"
        and metrics.long_relative_position <= Decimal("0.55")
    )
    recent_weight = (
        Decimal("0.15")
        if low_retest and recent_confirmation < 0
        else Decimal("0.40")
    )
    adjustment += recent_confirmation * recent_weight
    retained_impulse = max(metrics.ret3, metrics.ret5 * Decimal("0.50"))
    if (
        not low_retest
        and metrics.long_relative_position >= Decimal("0.65")
        and metrics.ret10 > Decimal("0.08")
        and retained_impulse < Decimal("0.01")
    ):
        adjustment -= min(
            Decimal("0.05"),
            Decimal("0.015")
            + (metrics.ret10 - Decimal("0.08")) * Decimal("0.25"),
        )
    if metrics.long_relative_position > Decimal("0.78") and metrics.ret3 < Decimal("0.01"):
        adjustment -= min(
            Decimal("0.025"),
            (metrics.long_relative_position - Decimal("0.78")) * Decimal("0.12"),
        )
    return max(Decimal("-0.09"), min(Decimal("0.07"), adjustment))


def _entry_overextension_penalty(metrics: _StructuralMetrics) -> Decimal:
    penalty = Decimal("0")
    if metrics.box_width > Decimal("0.35"):
        penalty += Decimal("0.22")
    elif metrics.box_width > Decimal("0.28"):
        penalty += Decimal("0.10")
    sync_overheat = (
        Decimal("0.05") <= metrics.ret3 < Decimal("0.10")
        and abs(metrics.ret5 - metrics.ret3) <= Decimal("0.02")
    )
    if sync_overheat:
        penalty += Decimal("0.06")
    if metrics.ret5 >= Decimal("0.30"):
        penalty += Decimal("0.22")
    elif metrics.ret5 >= Decimal("0.22"):
        penalty += Decimal("0.14")
    elif metrics.ret5 >= Decimal("0.18"):
        penalty += Decimal("0.08")
    elif metrics.ret5 >= Decimal("0.12"):
        penalty += Decimal("0.04")
    return penalty


def _candidate_sort_key(
    candidate: _Candidate,
) -> tuple[int, int, Decimal, Decimal, Decimal, str]:
    band = Decimal("0.005")
    score_band = int(candidate.score / band)
    structural_band = int(candidate.structural_score / band)
    return (
        -score_band,
        -structural_band,
        -candidate.behavior_score,
        -candidate.score,
        -candidate.durability,
        candidate.instrument,
    )


def _risk_exit_orders(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
    history: dict[str, tuple[dict[str, object], ...]],
) -> tuple[tuple[str, int, str], ...]:
    results: list[tuple[str, int, str]] = []
    for position in context.portfolio.positions:
        if position.closeable_amount <= 0:
            continue
        node = current.get(position.instrument)
        if node is None:
            continue
        if (
            position.average_cost > 0
            and node.close
            <= position.average_cost * (Decimal("1") - EARLY_FAILURE_FRACTION)
        ):
            results.append(
                (
                    position.instrument,
                    -position.closeable_amount,
                    "early_failure_8pct",
                )
            )
            continue
        metrics = _structural_metrics(history.get(position.instrument, ()))
        unrealized = (
            node.close / position.average_cost - Decimal("1")
            if position.average_cost > 0
            else Decimal("0")
        )
        if (
            unrealized <= Decimal("-0.04")
            and metrics is not None
            and metrics.ret10 < 0
            and metrics.distribution_risk >= Decimal("0.36")
        ):
            results.append(
                (
                    position.instrument,
                    -position.closeable_amount,
                    "scenario_structure_deterioration",
                )
            )
    return tuple(results)


def _rotation_order(
    context: PTradeContext,
    current: dict[str, MarketPathNode],
    history: dict[str, tuple[dict[str, object], ...]],
    positions: dict[str, _Position],
    candidates: tuple[_Candidate, ...],
) -> tuple[str, int, _Candidate] | None:
    last_rotation = context.state.get("quentx.last_rotation_day", "")
    if last_rotation:
        try:
            rotation_day = date.fromisoformat(last_rotation)
        except ValueError:
            return None
        if (context.current_dt.date() - rotation_day).days < ROTATION_COOLDOWN_DAYS:
            return None
    assessed: list[tuple[Decimal, str, _Position]] = []
    for instrument, position in positions.items():
        if position.closeable_amount < position.amount or position.amount <= 0:
            continue
        node = current.get(instrument)
        rows = history.get(instrument, ())
        metrics = _structural_metrics(rows) if node is not None else None
        if node is None or metrics is None:
            continue
        entry_day_text = context.state.get(f"quentx.entry.{instrument}.day", "")
        try:
            entry_day = date.fromisoformat(entry_day_text)
        except ValueError:
            continue
        holding_rows = tuple(
            row
            for row in rows
            if (row_day := _row_date(row)) is not None and row_day >= entry_day
        )
        if len(holding_rows) < ROTATION_MIN_BARS:
            continue
        holding_closes = [_row_decimal(row, "close") for row in holding_rows]
        if position.average_cost <= 0 or not holding_closes:
            continue
        peak_return = _safe_return(max(holding_closes), position.average_cost)
        last_return = _safe_return(node.close, position.average_cost)
        observation_failed = (
            peak_return < Decimal("0.05")
            and last_return <= Decimal("0.01")
        )
        developing_failed = (
            peak_return < Decimal("0.18")
            and last_return <= Decimal("0.02")
            and peak_return - last_return >= Decimal("0.06")
        )
        if not (observation_failed or developing_failed):
            continue
        stored_defense = Decimal(
            context.state.get(
                f"quentx.entry_defense.{instrument}",
                _decimal_text(metrics.defense_price),
            )
        )
        support_broken = stored_defense > 0 and node.close < stored_defense
        weak = (
            support_broken
            and metrics.long_relative_position >= Decimal("0.60")
            and (
                metrics.ret10 < Decimal("0.01")
                or metrics.distribution_risk >= Decimal("0.36")
                or metrics.smoothness < Decimal("0.58")
            )
        )
        if weak:
            assessed.append((_institutional_durability(metrics), instrument, position))
    if not assessed:
        return None
    weakest_durability, weakest_instrument, weakest_position = min(assessed)
    candidate = next(
        (
            item
            for item in candidates
            if item.structural_score >= Decimal("0.84")
            and item.durability >= Decimal("0.72")
        ),
        None,
    )
    if candidate is None or (
        candidate.durability - weakest_durability
        < ROTATION_DURABILITY_MARGIN
    ):
        return None
    remaining = set(positions) - {weakest_instrument}
    counts = _held_industry_counts(context, remaining)
    if counts.get(candidate.industry, 0) >= _industry_position_limit(candidate):
        return None
    return (
        weakest_instrument,
        -weakest_position.closeable_amount,
        candidate,
    )


def _buy_amount(
    context: PTradeContext,
    candidate: _Candidate,
    *,
    available_cash: Decimal,
) -> int:
    if candidate.price <= 0 or available_cash <= 0:
        return 0
    target_value = min(
        available_cash,
        context.portfolio.total_value
        / Decimal(MAX_POSITIONS)
        * candidate.position_scale,
        candidate.price * context.order_shares,
    )
    if target_value < MIN_ORDER_VALUE:
        return 0
    amount = int(target_value / candidate.price)
    amount = amount // LOT_SIZE * LOT_SIZE
    return min(amount, context.order_shares // LOT_SIZE * LOT_SIZE)


def _industry_position_limit(candidate: _Candidate) -> int:
    full_concentration = (
        candidate.sector.persistence >= Decimal("0.90")
        and candidate.sector.breadth20 >= Decimal("0.65")
        and candidate.sector.mainline_score >= Decimal("0.82")
    )
    return MAX_POSITIONS if full_concentration else 2


def _held_industry_counts(
    context: PTradeContext,
    held_instruments: set[str],
) -> dict[str, int]:
    industry_by_instrument = {
        item.instrument: item.industry for item in context.instrument_states
    }
    counts: dict[str, int] = {}
    for instrument in held_instruments:
        industry = industry_by_instrument.get(instrument, "")
        if industry:
            counts[industry] = counts.get(industry, 0) + 1
    return counts


def _remember_entry(context: PTradeContext, candidate: _Candidate) -> None:
    prefix = f"quentx.entry.{candidate.instrument}"
    context.state[f"quentx.entry_defense.{candidate.instrument}"] = _decimal_text(
        candidate.defense_price
    )
    context.state[f"quentx.entry_score.{candidate.instrument}"] = _decimal_text(
        candidate.score
    )
    context.state[f"{prefix}.industry"] = candidate.industry
    context.state[f"{prefix}.state"] = candidate.state
    context.state[f"{prefix}.day"] = context.current_dt.date().isoformat()
    context.state[f"{prefix}.price"] = _decimal_text(candidate.price)
    context.state[f"{prefix}.durability"] = _decimal_text(candidate.durability)


def _reset_day_boundary(context: PTradeContext) -> None:
    current_day = context.current_dt.date().isoformat()
    if context.state.get("quentx.day") == current_day:
        return
    context.state["quentx.day"] = current_day
    context.state["quentx.day_start_equity"] = _decimal_text(
        context.portfolio.total_value
    )


def _daily_loss_halt(context: PTradeContext) -> bool:
    start = Decimal(context.state.get("quentx.day_start_equity", "0"))
    if start <= 0 or context.portfolio.total_value <= 0:
        return False
    drawdown = context.portfolio.total_value / start - Decimal("1")
    return drawdown <= -DAILY_LOSS_ENTRY_HALT


def _count_rejection(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _row_decimal(row: dict[str, object], field: str) -> Decimal:
    return Decimal(str(row[field]))


def _row_date(row: dict[str, object]) -> date | None:
    value = row.get("simulation_time")
    return value.date() if isinstance(value, datetime) else None


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _safe_return(new: Decimal, old: Decimal) -> Decimal:
    return new / old - Decimal("1") if new > 0 and old > 0 else Decimal("0")


def _window_return(values: Sequence[Decimal], window: int) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    reference = values[max(0, len(values) - window - 1)]
    return _safe_return(values[-1], reference)


def _shifted_mean(
    values: Sequence[Decimal],
    *,
    window: int,
    shift: int,
) -> Decimal:
    end = max(1, len(values) - min(shift, max(1, len(values) // 3)))
    start = max(0, end - window)
    return _mean(values[start:end])


def _trend_efficiency(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2 or min(values) <= 0:
        return Decimal("0")
    travelled = sum(
        (abs(values[index] - values[index - 1]) for index in range(1, len(values))),
        Decimal("0"),
    )
    if travelled <= 0:
        return Decimal("0")
    return _bounded((values[-1] - values[0]) / travelled)


def _atr(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
) -> Decimal:
    start = max(1, len(closes) - 14)
    values = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(start, len(closes))
    ]
    return _mean(values)


def _distribution_risk(
    opens: Sequence[Decimal],
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    volumes: Sequence[Decimal],
    average_volume: Decimal,
) -> Decimal:
    risk = Decimal("0")
    start = max(1, len(closes) - 21)
    for index in range(start, len(closes)):
        volume_ratio = (
            volumes[index] / average_volume
            if average_volume > 0
            else Decimal("0")
        )
        close_position = _range_position(
            closes[index],
            lows[index],
            highs[index],
        )
        if (
            closes[index] < opens[index]
            and volume_ratio >= Decimal("1.6")
            and close_position <= Decimal("0.40")
        ):
            risk += Decimal("0.18")
        if (
            _safe_return(closes[index], closes[index - 1])
            <= Decimal("-0.07")
            and volume_ratio >= Decimal("1.3")
        ):
            risk += Decimal("0.25")
    return min(Decimal("1"), risk)


def _recent_breakout(
    closes: Sequence[Decimal],
    highs: Sequence[Decimal],
) -> bool:
    start = max(1, len(closes) - 16)
    for index in range(start, len(closes) - 1):
        prior = highs[max(0, index - 60) : index]
        if prior and closes[index] > max(prior):
            return True
    return False


def _rank(values: dict[str, Decimal]) -> dict[str, Decimal]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) == 1:
        return {ordered[0][0]: Decimal("0")}
    denominator = Decimal(max(1, len(ordered) - 1))
    return {
        key: Decimal(index) / denominator
        for index, (key, _value) in enumerate(ordered)
    }


def _range_position(
    value: Decimal,
    lower: Decimal,
    upper: Decimal,
) -> Decimal:
    if upper <= lower:
        return Decimal("0.5")
    return _bounded((value - lower) / (upper - lower))


def _bounded(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("1"), value))


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")
