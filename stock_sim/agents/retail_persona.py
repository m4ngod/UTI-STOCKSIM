from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal
import zlib


TradeAction = Literal["buy", "sell", "hold", "reduce", "exit"]


@dataclass(frozen=True)
class RetailPersona:
    agent_id: str
    strategy: str
    family: str
    loss_aversion_raw: float
    courage_raw: float
    thesis_horizon_bars: int
    entry_selectiveness: float
    target_conservatism: float
    execution_patience: float
    patience_seconds: float | None
    position_budget: float
    profit_realization_bias: float
    crowd_susceptibility: float


@dataclass
class RetailPersonaState:
    courage_delta: float = 0.0
    recent_pnl_pressure: float = 0.0
    drawdown_stress: float = 0.0
    thesis_validation_score: float = 0.5
    adverse_duration_bars: int = 0
    last_expected_price: float | None = None
    last_action: str | None = None


@dataclass(frozen=True)
class RetailMarketSnapshot:
    symbol: str
    current_price: float
    initial_price: float
    tick_size: float
    lot_size: int
    best_bid: float | None
    best_ask: float | None
    recent_prices: list[float]


@dataclass(frozen=True)
class RetailPositionSnapshot:
    quantity: int
    available_qty: int
    avg_price: float
    holding_time_s: float
    unrealized_pnl_norm: float


@dataclass(frozen=True)
class RetailDecisionPlan:
    action: TradeAction
    expected_price: float
    expected_edge: float
    conviction: float
    thesis_quality: float
    invalidation_score: float
    risk_multiplier: float
    quantity_lots: int
    aggressive: bool


FAMILY_ALIASES = {
    "momentum_chase": "trend_follow",
    "breakout": "trend_follow",
    "mean_revert": "mean_revert",
    "buy_the_dip": "buy_the_dip",
    "profit_taking": "profit_taking",
    "vol_scaling": "volatility_reactive",
    "liquidity_noise": "liquidity_noise",
    "noise": "noise",
    "slow_fundamental_allocator": "slow_fundamental_allocator",
    "trend_follow": "trend_follow",
}


def sample_retail_persona(agent_id: str, strategy: str, *, seed: int | None = None) -> RetailPersona:
    normalized_strategy = str(strategy or "noise").strip().lower() or "noise"
    family = FAMILY_ALIASES.get(normalized_strategy, normalized_strategy)
    rng = random.Random(seed if seed is not None else _stable_key(f"{agent_id}:{normalized_strategy}:persona"))
    params = _sample_family_params(family, rng)
    return RetailPersona(
        agent_id=agent_id,
        strategy=normalized_strategy,
        family=family,
        loss_aversion_raw=params["loss_aversion_raw"],
        courage_raw=params["courage_raw"],
        thesis_horizon_bars=params["thesis_horizon_bars"],
        entry_selectiveness=params["entry_selectiveness"],
        target_conservatism=params["target_conservatism"],
        execution_patience=params["execution_patience"],
        patience_seconds=params["patience_seconds"],
        position_budget=params["position_budget"],
        profit_realization_bias=params["profit_realization_bias"],
        crowd_susceptibility=params["crowd_susceptibility"],
    )


def transform_loss_aversion(lam: float, beta: float = 3.0) -> float:
    clipped = _clip(lam, 0.0, 1.0)
    return (math.exp(beta * clipped) - 1.0) / (math.exp(beta) - 1.0)


def loss_weight(lam: float, W: float = 2.5) -> float:
    return 1.0 + W * transform_loss_aversion(lam)


def utility(x: float, lam: float, *, W: float = 2.5, rho: float = 1.10, beta: float = 3.0) -> float:
    if x >= 0:
        return x
    s = transform_loss_aversion(lam, beta=beta)
    w = 1.0 + W * s
    return -w * ((-x) ** rho)


def courage_effective(c_raw: float, courage_delta: float = 0.0, gamma: float = 3.0) -> float:
    clipped = _clip(c_raw + courage_delta, 0.0, 1.0)
    return (math.exp(gamma * clipped) - 1.0) / (math.exp(gamma) - 1.0)


def update_persona_state(
    persona: RetailPersona,
    state: RetailPersonaState,
    position: RetailPositionSnapshot,
    *,
    thesis_quality: float,
    invalidation_score: float,
) -> RetailPersonaState:
    state.thesis_validation_score = _clip(0.7 * state.thesis_validation_score + 0.3 * thesis_quality, 0.0, 1.0)
    pnl_norm = float(position.unrealized_pnl_norm or 0.0)
    state.recent_pnl_pressure = (0.82 * state.recent_pnl_pressure) + (0.18 * pnl_norm)
    state.drawdown_stress = _clip(0.85 * state.drawdown_stress + 0.35 * max(0.0, -pnl_norm), 0.0, 1.0)
    if pnl_norm < 0:
        state.adverse_duration_bars += 1
    else:
        state.adverse_duration_bars = 0

    target_shift = 0.0
    if pnl_norm > 0.008:
        target_shift += 0.06
    elif pnl_norm < -0.008:
        target_shift -= 0.08 * (1.0 + transform_loss_aversion(persona.loss_aversion_raw))
    target_shift += 0.05 * (thesis_quality - 0.5)
    target_shift -= 0.09 * max(0.0, invalidation_score - 0.35)
    state.courage_delta = _clip((0.88 * state.courage_delta) + target_shift, -0.35, 0.35)
    return state


def plan_retail_decision(
    persona: RetailPersona,
    market: RetailMarketSnapshot,
    position: RetailPositionSnapshot,
    state: RetailPersonaState,
    *,
    rng: random.Random,
) -> RetailDecisionPlan | None:
    expected_price, thesis_quality, invalidation_score = _expected_price_triplet(persona, market, position, rng=rng)
    expected_edge = _relative_edge(
        current_price=market.current_price,
        expected_price=expected_price,
        has_inventory=(position.available_qty > 0),
    )
    risk_multiplier = _position_risk_multiplier(persona, market)
    subjective_edge = utility(expected_edge, persona.loss_aversion_raw)

    if position.available_qty > 0:
        hold_plan = _plan_position_action(
            persona,
            market,
            position,
            state,
            expected_price=expected_price,
            expected_edge=expected_edge,
            thesis_quality=thesis_quality,
            invalidation_score=invalidation_score,
            risk_multiplier=risk_multiplier,
            rng=rng,
        )
        if hold_plan is not None:
            return hold_plan

    entry_threshold = _entry_threshold(persona, market)
    if subjective_edge <= entry_threshold:
        return None
    if expected_edge <= 0:
        return None

    conviction = _clip((expected_edge - entry_threshold) * 36.0, 0.0, 1.0)
    quantity_lots = _quantity_lots(persona, risk_multiplier, conviction)
    aggressive = conviction >= (0.62 + 0.18 * persona.execution_patience)
    return RetailDecisionPlan(
        action="buy",
        expected_price=expected_price,
        expected_edge=expected_edge,
        conviction=conviction,
        thesis_quality=thesis_quality,
        invalidation_score=invalidation_score,
        risk_multiplier=risk_multiplier,
        quantity_lots=quantity_lots,
        aggressive=aggressive,
    )


def _plan_position_action(
    persona: RetailPersona,
    market: RetailMarketSnapshot,
    position: RetailPositionSnapshot,
    state: RetailPersonaState,
    *,
    expected_price: float,
    expected_edge: float,
    thesis_quality: float,
    invalidation_score: float,
    risk_multiplier: float,
    rng: random.Random,
) -> RetailDecisionPlan | None:
    if position.available_qty <= 0:
        return None

    entry_price = max(position.avg_price, market.tick_size)
    m_adv = max(0.0, (entry_price - market.current_price) / max(_atr_like(market.recent_prices), market.tick_size))
    v_adv = max(0.0, -_ema_return(market.recent_prices, span=4)) / max(_vol_norm(market.recent_prices), 1e-6)
    tau_u = float(state.adverse_duration_bars)
    max_loss_budget = 0.012 + (1.0 - persona.position_budget) * 0.01
    k_stop = max(0.0, -position.unrealized_pnl_norm) / max(max_loss_budget, 1e-6)

    p_hold = hold_probability(
        courage_raw=persona.courage_raw,
        courage_delta=state.courage_delta,
        q_thesis=thesis_quality,
        i_invalid=invalidation_score,
        m_adv=m_adv,
        v_adv=v_adv,
        tau_u=tau_u,
        k_stop=k_stop,
    )

    if invalidation_score >= 0.92 or k_stop >= 1.0:
        return RetailDecisionPlan(
            action="exit",
            expected_price=expected_price,
            expected_edge=expected_edge,
            conviction=1.0,
            thesis_quality=thesis_quality,
            invalidation_score=invalidation_score,
            risk_multiplier=risk_multiplier,
            quantity_lots=max(1, position.available_qty // max(market.lot_size, 1)),
            aggressive=True,
        )

    patience_p = patience_exit_probability(
        persona,
        position,
        expected_edge=expected_edge,
        thesis_quality=thesis_quality,
    )
    if patience_p > 0.0 and rng.random() < patience_p:
        quantity_lots = max(1, position.available_qty // max(market.lot_size, 1))
        reduce_only = patience_p < 0.72 and position.available_qty > market.lot_size
        return RetailDecisionPlan(
            action="reduce" if reduce_only else "exit",
            expected_price=expected_price,
            expected_edge=expected_edge,
            conviction=max(0.45, patience_p),
            thesis_quality=thesis_quality,
            invalidation_score=invalidation_score,
            risk_multiplier=risk_multiplier,
            quantity_lots=max(1, quantity_lots // (2 if reduce_only else 1)),
            aggressive=patience_p >= 0.55,
        )

    favorable_inventory_edge = max(0.0, (market.current_price - entry_price) / entry_price)
    take_profit_pressure = favorable_inventory_edge * (1.0 + persona.profit_realization_bias)
    if expected_edge < 0 and favorable_inventory_edge > 0.004:
        p_hold *= max(0.15, 1.0 - take_profit_pressure * 6.0)

    if rng.random() < p_hold:
        add_to_loser_prob = max(
            0.0,
            0.35 * (1.0 - 0.7 * transform_loss_aversion(persona.loss_aversion_raw)) * thesis_quality,
        )
        if expected_edge > (_entry_threshold(persona, market) * 1.6) and rng.random() < add_to_loser_prob:
            return RetailDecisionPlan(
                action="buy",
                expected_price=expected_price,
                expected_edge=expected_edge,
                conviction=_clip(expected_edge * 30.0, 0.0, 1.0),
                thesis_quality=thesis_quality,
                invalidation_score=invalidation_score,
                risk_multiplier=risk_multiplier,
                quantity_lots=1,
                aggressive=False,
            )
        return RetailDecisionPlan(
            action="hold",
            expected_price=expected_price,
            expected_edge=expected_edge,
            conviction=p_hold,
            thesis_quality=thesis_quality,
            invalidation_score=invalidation_score,
            risk_multiplier=risk_multiplier,
            quantity_lots=0,
            aggressive=False,
        )

    p_reduce = (1.0 - p_hold) * _sigmoid(0.2 + 1.0 * v_adv + 0.8 * k_stop - 0.8 * thesis_quality)
    quantity_lots = max(1, position.available_qty // max(market.lot_size, 1))
    return RetailDecisionPlan(
        action="reduce" if rng.random() < p_reduce else "exit",
        expected_price=expected_price,
        expected_edge=expected_edge,
        conviction=max(0.5, 1.0 - p_hold),
        thesis_quality=thesis_quality,
        invalidation_score=invalidation_score,
        risk_multiplier=risk_multiplier,
        quantity_lots=max(1, quantity_lots // (2 if p_reduce > 0.25 else 1)),
        aggressive=True,
    )


def hold_probability(
    *,
    courage_raw: float,
    courage_delta: float,
    q_thesis: float,
    i_invalid: float,
    m_adv: float,
    v_adv: float,
    tau_u: float,
    k_stop: float,
    theta0: float = -0.6,
    alpha_c: float = 2.0,
    alpha_q: float = 1.6,
    w_m: float = 1.0,
    w_v: float = 1.4,
    w_t: float = 0.5,
    w_k: float = 1.2,
    w_i: float = 2.5,
    tau0: float = 6.0,
) -> float:
    b = courage_effective(courage_raw, courage_delta=courage_delta)
    pressure = (
        w_m * m_adv
        + w_v * v_adv
        + w_t * math.log(1.0 + max(tau_u, 0.0) / max(tau0, 1e-6))
        + w_k * k_stop
        + w_i * i_invalid
    )
    z_hold = theta0 + alpha_c * b + alpha_q * q_thesis - pressure
    return _sigmoid(z_hold)


def patience_exit_probability(
    persona: RetailPersona,
    position: RetailPositionSnapshot,
    *,
    expected_edge: float,
    thesis_quality: float,
) -> float:
    """Return impatience-driven exit pressure for stale held positions.

    `None` patience means the persona does not add an extra time-based exit
    motive; loss aversion, courage, thesis quality, and invalidation still drive
    the ordinary hold/reduce/exit path.
    """

    patience_s = persona.patience_seconds
    if patience_s is None or patience_s <= 0 or position.available_qty <= 0:
        return 0.0
    age_s = max(0.0, float(position.holding_time_s or 0.0))
    if age_s <= patience_s:
        return 0.0
    overdue_ratio = age_s / max(patience_s, 1e-6) - 1.0
    thesis_buffer = 1.25 * _clip(thesis_quality, 0.0, 1.0)
    edge_buffer = 36.0 * max(0.0, expected_edge)
    courage_buffer = 0.55 * courage_effective(persona.courage_raw)
    pressure = -1.15 + (1.45 * overdue_ratio) - thesis_buffer - edge_buffer - courage_buffer
    return _clip(_sigmoid(pressure), 0.0, 0.95)


def _expected_price_triplet(
    persona: RetailPersona,
    market: RetailMarketSnapshot,
    position: RetailPositionSnapshot,
    *,
    rng: random.Random,
) -> tuple[float, float, float]:
    prices = market.recent_prices or [market.current_price]
    current = market.current_price
    tick = max(market.tick_size, 1e-6)
    ma_fast = _mean_tail(prices, 5)
    ma_mid = _mean_tail(prices, 10)
    ma_slow = _mean_tail(prices, max(12, persona.thesis_horizon_bars))
    atr = _atr_like(prices)
    family = persona.family

    if family == "mean_revert":
        anchor = ma_mid
        gap = anchor - current
        capture = 0.32 + (1.0 - persona.target_conservatism) * 0.38
        expected = current + gap * capture
        thesis = _clip(abs(gap) / max(atr * 2.4, tick), 0.0, 1.0)
        invalid = _clip(max(0.0, -gap * _ema_return(prices, span=4)) / max(atr, tick), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    if family == "trend_follow":
        trend = (ma_fast - ma_mid) + (current - ma_fast) * (0.5 + 0.5 * persona.crowd_susceptibility)
        continuation = max(-2.5 * atr, min(2.5 * atr, trend * (1.1 + persona.crowd_susceptibility)))
        expected = current + continuation
        thesis = _clip(abs(continuation) / max(atr * 1.8, tick), 0.0, 1.0)
        invalid = _clip(max(0.0, -(current - ma_fast) * trend) / max(atr, tick), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    if family == "buy_the_dip":
        anchor = 0.6 * ma_mid + 0.4 * ma_fast
        gap = anchor - current
        rebound_capture = 0.24 + (1.0 - persona.target_conservatism) * 0.34
        expected = current + max(0.0, gap) * rebound_capture
        thesis = _clip(max(0.0, gap) / max(atr * 2.1, tick), 0.0, 1.0)
        invalid = _clip(max(0.0, current - anchor) / max(atr * 2.2, tick), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    if family == "profit_taking":
        anchor = position.avg_price if position.avg_price > 0 else ma_fast
        excess = current - anchor
        expected = current - max(0.0, excess) * (0.18 + 0.24 * persona.profit_realization_bias)
        thesis = _clip(max(0.0, excess) / max(atr * 1.6, tick), 0.0, 1.0)
        invalid = _clip(max(0.0, anchor - current) / max(atr * 1.8, tick), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    if family == "slow_fundamental_allocator":
        fair_anchor = (0.52 * market.initial_price) + (0.48 * ma_slow)
        mispricing = fair_anchor - current
        capture = 0.20 + (1.0 - persona.target_conservatism) * 0.28
        expected = current + mispricing * capture
        thesis = _clip(abs(mispricing) / max(atr * 3.0, tick), 0.0, 1.0)
        invalid = _clip(max(0.0, -mispricing * _ema_return(prices, span=6)) / max(atr, tick), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    if family == "volatility_reactive":
        ema_ret = _ema_return(prices, span=4)
        vol = _vol_norm(prices)
        swing = atr * (0.6 + vol * 40.0)
        expected = current + swing * (1.0 if ema_ret >= 0 else -1.0)
        thesis = _clip((vol * 45.0), 0.0, 1.0)
        invalid = _clip(max(0.0, -ema_ret) / max(vol, 1e-6), 0.0, 1.0) if expected > current else _clip(max(0.0, ema_ret) / max(vol, 1e-6), 0.0, 1.0)
        return _clamp_expected(expected, current, tick), thesis, invalid

    # liquidity_noise / noise fallback
    micro_bias = (rng.random() - 0.5) * max(atr * 0.4, tick * 2.0)
    if family == "liquidity_noise":
        micro_bias *= 0.8
    expected = current + micro_bias
    thesis = _clip(abs(micro_bias) / max(atr * 0.9, tick), 0.0, 0.55)
    invalid = 0.18
    return _clamp_expected(expected, current, tick), thesis, invalid


def _entry_threshold(persona: RetailPersona, market: RetailMarketSnapshot) -> float:
    vol_norm = _vol_norm(market.recent_prices)
    s = transform_loss_aversion(persona.loss_aversion_raw)
    base = 0.0018 * persona.entry_selectiveness
    return base * (1.0 + 0.8 * s + 0.6 * vol_norm * 40.0)


def _position_risk_multiplier(persona: RetailPersona, market: RetailMarketSnapshot) -> float:
    vol_norm = _vol_norm(market.recent_prices)
    s = transform_loss_aversion(persona.loss_aversion_raw)
    return persona.position_budget * math.exp(-0.6 * s * vol_norm * 50.0)


def _quantity_lots(persona: RetailPersona, risk_multiplier: float, conviction: float) -> int:
    size_score = max(0.45, risk_multiplier) * (0.7 + conviction)
    if persona.family == "slow_fundamental_allocator":
        size_score *= 1.3
    if size_score >= 1.8:
        return 3
    if size_score >= 1.15:
        return 2
    return 1


def _relative_edge(*, current_price: float, expected_price: float, has_inventory: bool) -> float:
    if current_price <= 0:
        return 0.0
    buy_edge = (expected_price - current_price) / current_price
    sell_edge = (current_price - expected_price) / current_price if has_inventory else float("-inf")
    return max(buy_edge, sell_edge)


def _sample_family_params(family: str, rng: random.Random) -> dict[str, float | int | None]:
    base = {
        "loss_aversion_raw": rng.uniform(0.18, 0.72),
        "courage_raw": rng.uniform(0.28, 0.78),
        "thesis_horizon_bars": rng.randint(6, 16),
        "entry_selectiveness": rng.uniform(0.85, 1.2),
        "target_conservatism": rng.uniform(0.28, 0.72),
        "execution_patience": rng.uniform(0.25, 0.78),
        "patience_seconds": _sample_patience_seconds(rng, 10.0, 80.0, patient_tail_prob=0.12),
        "position_budget": rng.uniform(0.85, 1.2),
        "profit_realization_bias": rng.uniform(0.85, 1.18),
        "crowd_susceptibility": rng.uniform(0.18, 0.82),
    }
    if family == "trend_follow":
        base.update(
            courage_raw=rng.uniform(0.45, 0.9),
            loss_aversion_raw=rng.uniform(0.12, 0.55),
            entry_selectiveness=rng.uniform(0.8, 1.12),
            target_conservatism=rng.uniform(0.22, 0.58),
            execution_patience=rng.uniform(0.12, 0.58),
            patience_seconds=_sample_patience_seconds(rng, 4.0, 34.0, patient_tail_prob=0.08),
            crowd_susceptibility=rng.uniform(0.55, 0.96),
        )
    elif family == "mean_revert":
        base.update(
            loss_aversion_raw=rng.uniform(0.28, 0.82),
            courage_raw=rng.uniform(0.32, 0.72),
            entry_selectiveness=rng.uniform(0.95, 1.35),
            target_conservatism=rng.uniform(0.42, 0.82),
            execution_patience=rng.uniform(0.35, 0.82),
            patience_seconds=_sample_patience_seconds(rng, 14.0, 95.0, patient_tail_prob=0.15),
        )
    elif family == "buy_the_dip":
        base.update(
            courage_raw=rng.uniform(0.38, 0.82),
            entry_selectiveness=rng.uniform(0.88, 1.18),
            target_conservatism=rng.uniform(0.3, 0.68),
            execution_patience=rng.uniform(0.22, 0.62),
            patience_seconds=_sample_patience_seconds(rng, 6.0, 48.0, patient_tail_prob=0.10),
            position_budget=rng.uniform(0.92, 1.28),
        )
    elif family == "profit_taking":
        base.update(
            loss_aversion_raw=rng.uniform(0.42, 0.88),
            courage_raw=rng.uniform(0.2, 0.58),
            profit_realization_bias=rng.uniform(1.05, 1.35),
            entry_selectiveness=rng.uniform(1.02, 1.32),
            target_conservatism=rng.uniform(0.52, 0.88),
            patience_seconds=_sample_patience_seconds(rng, 5.0, 36.0, patient_tail_prob=0.08),
        )
    elif family == "slow_fundamental_allocator":
        base.update(
            loss_aversion_raw=rng.uniform(0.2, 0.62),
            courage_raw=rng.uniform(0.4, 0.78),
            thesis_horizon_bars=rng.randint(12, 24),
            entry_selectiveness=rng.uniform(1.02, 1.38),
            target_conservatism=rng.uniform(0.5, 0.88),
            execution_patience=rng.uniform(0.48, 0.92),
            patience_seconds=_sample_patience_seconds(rng, 60.0, 240.0, patient_tail_prob=0.45),
            position_budget=rng.uniform(1.0, 1.45),
            crowd_susceptibility=rng.uniform(0.05, 0.35),
        )
    elif family in {"liquidity_noise", "noise"}:
        base.update(
            loss_aversion_raw=rng.uniform(0.16, 0.6),
            courage_raw=rng.uniform(0.3, 0.74),
            thesis_horizon_bars=rng.randint(4, 10),
            entry_selectiveness=rng.uniform(0.7, 1.05),
            target_conservatism=rng.uniform(0.18, 0.56),
            execution_patience=rng.uniform(0.15, 0.76),
            patience_seconds=_sample_patience_seconds(rng, 2.5, 24.0, patient_tail_prob=0.06),
            position_budget=rng.uniform(0.8, 1.1),
        )
    return base


def _sample_patience_seconds(
    rng: random.Random,
    low: float,
    high: float,
    *,
    patient_tail_prob: float,
) -> float | None:
    if rng.random() < patient_tail_prob:
        return None
    return rng.uniform(float(low), float(high))


def _mean_tail(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    tail = values[-max(1, min(window, len(values))):]
    return sum(tail) / len(tail)


def _atr_like(values: list[float]) -> float:
    if len(values) < 2:
        return max(values[-1] * 0.002, 0.01) if values else 0.01
    diffs = [abs(values[idx] - values[idx - 1]) for idx in range(1, len(values))]
    return max(sum(diffs[-8:]) / max(1, min(8, len(diffs))), 0.01)


def _vol_norm(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    returns = []
    for idx in range(1, len(values)):
        prev = values[idx - 1]
        curr = values[idx]
        if prev > 0:
            returns.append((curr - prev) / prev)
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    variance = sum((item - mean_ret) ** 2 for item in returns) / max(1, len(returns) - 1)
    return math.sqrt(max(variance, 0.0))


def _ema_return(values: list[float], *, span: int) -> float:
    if len(values) < 2:
        return 0.0
    alpha = 2.0 / (max(span, 1) + 1.0)
    ema = 0.0
    seeded = False
    for idx in range(1, len(values)):
        prev = values[idx - 1]
        curr = values[idx]
        ret = 0.0 if prev <= 0 else (curr - prev) / prev
        if not seeded:
            ema = ret
            seeded = True
        else:
            ema = alpha * ret + (1.0 - alpha) * ema
    return ema


def _clamp_expected(expected_price: float, current_price: float, tick_size: float) -> float:
    tick = max(tick_size, 1e-6)
    if abs(expected_price - current_price) < tick:
        expected_price = current_price + (tick if expected_price >= current_price else -tick)
    return max(tick, expected_price)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _clip(value: float, lo: float, hi: float) -> float:
    return min(max(float(value), lo), hi)


def _stable_key(value: str) -> int:
    return zlib.crc32(str(value or "").encode("utf-8")) & 0xFFFFFFFF


__all__ = [
    "RetailPersona",
    "RetailPersonaState",
    "RetailMarketSnapshot",
    "RetailPositionSnapshot",
    "RetailDecisionPlan",
    "sample_retail_persona",
    "transform_loss_aversion",
    "loss_weight",
    "utility",
    "courage_effective",
    "hold_probability",
    "patience_exit_probability",
    "update_persona_state",
    "plan_retail_decision",
]
