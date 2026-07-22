"""Reference strategy written against the published ``ptrade_surface.v1`` globals."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Callable, Protocol, Sequence

from .market_paths import MarketPathNode


class _Portfolio(Protocol):
    @property
    def positions(self) -> tuple[object, ...]: ...


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


# The host injects these globals before invoking any lifecycle callback.
set_universe: Callable[[Sequence[str]], None]
set_slippage: Callable[[Decimal], None]
set_commission: Callable[[Decimal], None]
run_daily: _RunDaily
get_history: _GetHistory
get_current_data: Callable[[], dict[str, MarketPathNode]]
order: Callable[[str, int], None]
log: _Logger


strategy_global_counter = 0


def initialize(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    set_universe(context.eligible_universe)
    set_slippage(Decimal("0"))
    set_commission(Decimal("3"))
    run_daily(rebalance, cadence_minutes=context.decision_cadence_minutes)
    context.state.setdefault("submitted", "false")
    log.info("Reference PTrade strategy initialized on the active scenario universe.")


def rebalance(context: PTradeContext) -> None:
    global strategy_global_counter
    strategy_global_counter += 1
    get_history(count=2, unit="30s", fields=("close", "volume"))
    current_data = get_current_data()
    if context.state.get("submitted") == "true":
        return
    if context.portfolio.positions:
        context.state["submitted"] = "true"
        return
    ranked: list[tuple[Decimal, str]] = []
    for instrument in context.eligible_universe:
        rank = dict(current_data[instrument].features).get("candidate_rank")
        if rank is not None:
            ranked.append((rank, instrument))
    if {instrument for _rank, instrument in ranked} != set(
        context.eligible_universe
    ):
        raise ValueError(
            "Reference strategy requires a candidate ranking for every eligible "
            "instrument at Decision Time"
        )
    ranks = [rank for rank, _instrument in ranked]
    if len(ranks) != len(set(ranks)):
        raise ValueError("Reference strategy candidate ranking contains duplicate ranks")
    if not ranked:
        return
    order(min(ranked)[1], context.order_shares)
    context.state["submitted"] = "true"


def handle_data(
    context: PTradeContext,
    data: dict[str, MarketPathNode],
) -> None:
    """Optional lifecycle shape retained for strategies that use bar callbacks."""

    global strategy_global_counter
    strategy_global_counter += 1
    if context.current_dt and data:
        log.info("Reference PTrade handle_data callback completed.")
