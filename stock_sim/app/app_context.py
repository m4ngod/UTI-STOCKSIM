"""Shared desktop app composition root."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from app.runtime_gateway import RuntimeGateway
from app.state.settings_store import SettingsStore

from app.services.market_data_service import MarketDataService
from app.controllers.market_controller import MarketController

from app.services.account_service import AccountService
from app.controllers.account_controller import AccountController

from app.services.trading_service import TradingService
from app.controllers.trading_controller import TradingController

from app.services.agent_service import AgentService
from app.controllers.agent_controller import AgentController

from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.controllers.clock_controller import ClockController

from app.services.leaderboard_service import LeaderboardService
from app.controllers.leaderboard_controller import LeaderboardController
from app.services.training_arena_service import TrainingArenaService


@dataclass
class AppContext:
    settings_store: SettingsStore
    runtime_gateway: RuntimeGateway

    market_data_service: MarketDataService
    market_controller: MarketController

    account_service: AccountService
    account_controller: AccountController

    trading_service: TradingService
    trading_controller: TradingController

    agent_service: AgentService
    agent_controller: AgentController

    clock_service: ClockService
    rollback_service: RollbackService
    clock_controller: ClockController

    leaderboard_service: LeaderboardService
    leaderboard_controller: LeaderboardController

    training_arena_service: TrainingArenaService


def build_app_context(*, settings_path: str = "frontend_settings.json") -> AppContext:
    settings_store = SettingsStore(path=settings_path, auto_save=False)
    runtime_gateway = RuntimeGateway()
    runtime_gateway.ensure_desktop_run()

    market_data_service = MarketDataService(
        enable_runtime_holdings=True,
        allow_synthetic_fallback=False,
        runtime_gateway=runtime_gateway,
    )
    market_controller = MarketController(market_data_service, runtime_gateway=runtime_gateway)

    account_service = AccountService(allow_synthetic_fallback=False, runtime_gateway=runtime_gateway)
    account_controller = AccountController(account_service)

    trading_service = TradingService(runtime_gateway=runtime_gateway)
    trading_controller = TradingController(trading_service)

    agent_service = AgentService(runtime_gateway=runtime_gateway)
    agent_controller = AgentController(agent_service)

    clock_service = ClockService(runtime_gateway=runtime_gateway)
    rollback_service = RollbackService(
        clock_service,
        account_service=account_service,
        agent_service=agent_service,
    )
    clock_controller = ClockController(clock_service, rollback_service)

    leaderboard_service = LeaderboardService(use_runtime=True, runtime_gateway=runtime_gateway)
    leaderboard_controller = LeaderboardController(leaderboard_service)
    training_arena_service = TrainingArenaService(agent_service=agent_service)

    return AppContext(
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
    )


_lock = RLock()
_app_context: AppContext | None = None


def get_app_context(*, settings_path: str = "frontend_settings.json") -> AppContext:
    global _app_context
    with _lock:
        if _app_context is None:
            _app_context = build_app_context(settings_path=settings_path)
        return _app_context


def reset_app_context(*, settings_path: str = "frontend_settings.json") -> AppContext:
    global _app_context
    with _lock:
        _app_context = build_app_context(settings_path=settings_path)
        return _app_context


__all__ = ["AppContext", "build_app_context", "get_app_context", "reset_app_context"]
