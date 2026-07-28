"""Composition root for the legacy Qt Widgets panel stack."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LegacyPanelContext:
    settings_store: Any
    runtime_gateway: Any
    market_data_service: Any
    market_controller: Any
    account_service: Any
    account_controller: Any
    trading_service: Any | None
    trading_controller: Any | None
    agent_service: Any
    agent_controller: Any
    clock_service: Any
    rollback_service: Any
    clock_controller: Any
    leaderboard_service: Any
    leaderboard_controller: Any
    training_arena_service: Any
    arena_experiment_runner: Any


def build_legacy_panel_context(
    *,
    settings_store: Any,
    runtime_gateway: Any,
    include_trading: bool,
) -> LegacyPanelContext:
    """Build the shared legacy panel dependencies without Frontend V2."""

    from app.controllers.account_controller import AccountController
    from app.controllers.agent_controller import AgentController
    from app.controllers.clock_controller import ClockController
    from app.controllers.leaderboard_controller import LeaderboardController
    from app.controllers.market_controller import MarketController
    from app.services.account_service import AccountService
    from app.services.agent_service import AgentService
    from app.services.arena_experiment_runner import ArenaExperimentRunner
    from app.services.clock_service import ClockService
    from app.services.leaderboard_service import LeaderboardService
    from app.services.market_data_service import MarketDataService
    from app.services.rollback_service import RollbackService
    from app.services.training_arena_service import TrainingArenaService

    market_data_service = MarketDataService(
        enable_runtime_holdings=True,
        allow_synthetic_fallback=False,
        runtime_gateway=runtime_gateway,
    )
    market_controller = MarketController(
        market_data_service,
        runtime_gateway=runtime_gateway,
    )
    account_service = AccountService(
        allow_synthetic_fallback=False,
        runtime_gateway=runtime_gateway,
    )
    account_controller = AccountController(account_service)
    if include_trading:
        from app.controllers.trading_controller import TradingController
        from app.services.trading_service import TradingService

        trading_service = TradingService(runtime_gateway=runtime_gateway)
        trading_controller = TradingController(trading_service)
    else:
        trading_service = None
        trading_controller = None
    agent_service = AgentService(runtime_gateway=runtime_gateway)
    agent_controller = AgentController(agent_service)
    clock_service = ClockService(runtime_gateway=runtime_gateway)
    rollback_service = RollbackService(
        clock_service,
        account_service=account_service,
        agent_service=agent_service,
    )
    clock_controller = ClockController(clock_service, rollback_service)
    leaderboard_service = LeaderboardService(
        use_runtime=True,
        runtime_gateway=runtime_gateway,
    )
    leaderboard_controller = LeaderboardController(leaderboard_service)
    training_arena_service = TrainingArenaService(
        agent_service=agent_service,
    )
    arena_experiment_runner = ArenaExperimentRunner(
        arena_service=training_arena_service,
        clock_service=clock_service,
        agent_service=agent_service,
        runtime_gateway=runtime_gateway,
    )
    return LegacyPanelContext(
        settings_store=settings_store,
        runtime_gateway=runtime_gateway,
        market_data_service=market_data_service,
        market_controller=market_controller,
        account_service=account_service,
        account_controller=account_controller,
        trading_service=trading_service,
        trading_controller=trading_controller,
        agent_service=agent_service,
        agent_controller=agent_controller,
        clock_service=clock_service,
        rollback_service=rollback_service,
        clock_controller=clock_controller,
        leaderboard_service=leaderboard_service,
        leaderboard_controller=leaderboard_controller,
        training_arena_service=training_arena_service,
        arena_experiment_runner=arena_experiment_runner,
    )


__all__ = [
    "LegacyPanelContext",
    "build_legacy_panel_context",
]
