"""Shared desktop app composition root."""
from __future__ import annotations

from dataclasses import dataclass
import os
from threading import RLock

from app.event_bridge import EventBridge, start_frontend_bridge
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
from app.services.arena_experiment_runner import ArenaExperimentRunner
from app.services.training_arena_service import TrainingArenaService
from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    FormalDiagnosticCampaignId,
    LiveRunMonitoringAdapter,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringSelection,
    StrategyRunId,
)


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
    arena_experiment_runner: ArenaExperimentRunner
    run_monitoring_feature: RunMonitoringFeature
    run_monitoring_context: RunMonitoringContext


def build_app_context(
    *,
    settings_path: str = "frontend_settings.json",
    run_monitoring_mode: str | None = None,
    event_bridge: EventBridge | None = None,
) -> AppContext:
    settings_store = SettingsStore(path=settings_path, auto_save=False)
    runtime_gateway = RuntimeGateway()
    if not _frontend_v2_enabled():
        runtime_gateway.ensure_desktop_run()
    _start_market_persistence_services()

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
    arena_experiment_runner = ArenaExperimentRunner(
        arena_service=training_arena_service,
        clock_service=clock_service,
        agent_service=agent_service,
        runtime_gateway=runtime_gateway,
    )
    run_monitoring_context = _run_monitoring_context_from_environment()
    resolved_mode = _run_monitoring_mode(run_monitoring_mode)
    if resolved_mode == "fake":
        run_monitoring_feature: RunMonitoringFeature = (
            DeterministicFakeRunMonitoringAdapter()
        )
    else:
        live_bridge = event_bridge or start_frontend_bridge()
        run_monitoring_feature = LiveRunMonitoringAdapter(
            runtime_gateway=runtime_gateway,
            event_bridge=live_bridge,
            diagnostic_tasks=training_arena_service,
        )

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
        arena_experiment_runner=arena_experiment_runner,
        run_monitoring_feature=run_monitoring_feature,
        run_monitoring_context=run_monitoring_context,
    )


_lock = RLock()
_app_context: AppContext | None = None


def get_app_context(*, settings_path: str = "frontend_settings.json") -> AppContext:
    global _app_context
    with _lock:
        if _app_context is None:
            _app_context = build_app_context(settings_path=settings_path)
        return _app_context


def reset_app_context(
    *,
    settings_path: str = "frontend_settings.json",
    run_monitoring_mode: str | None = None,
    event_bridge: EventBridge | None = None,
) -> AppContext:
    global _app_context
    with _lock:
        previous = _app_context
        _app_context = build_app_context(
            settings_path=settings_path,
            run_monitoring_mode=run_monitoring_mode,
            event_bridge=event_bridge,
        )
        if previous is not None:
            previous.run_monitoring_feature.close()
        return _app_context


def _frontend_v2_enabled() -> bool:
    return os.environ.get("STOCKSIM_FRONTEND_V2", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_monitoring_mode(explicit: str | None) -> str:
    value = (
        explicit
        or os.environ.get("STOCKSIM_FRONTEND_V2_ADAPTER")
        or ("live" if _frontend_v2_enabled() else "fake")
    )
    normalized = value.strip().lower()
    if normalized not in {"live", "fake"}:
        raise ValueError(
            "Run Monitoring Adapter mode must be 'live' or 'fake'"
        )
    return normalized


def _run_monitoring_context_from_environment() -> RunMonitoringContext:
    campaign_id = os.environ.get(
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "",
    ).strip()
    run_id = os.environ.get("STOCKSIM_FRONTEND_V2_RUN_ID", "").strip()
    if not campaign_id and not run_id:
        return RunMonitoringContext.no_selection()
    if not campaign_id:
        raise ValueError(
            "An existing Run Monitoring route requires a campaign identity"
        )
    if not run_id:
        return RunMonitoringContext.for_campaign(
            FormalDiagnosticCampaignId(campaign_id)
        )
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId(campaign_id),
            run_id=StrategyRunId(run_id),
        )
    )


def _start_market_persistence_services() -> None:
    try:
        from stock_sim.services.snapshot_listener import ensure_snapshot_listener_started
        from stock_sim.services.bar_aggregator import ensure_bar_aggregator_started

        ensure_snapshot_listener_started()
        ensure_bar_aggregator_started()
    except Exception:
        pass


__all__ = ["AppContext", "build_app_context", "get_app_context", "reset_app_context"]
