"""Shared desktop app composition root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

from app.event_bridge import EventBridge, start_frontend_bridge
from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringSelection,
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyRunId,
    StrategyUnderTestId,
    V1JourneySelector,
)
from app.state.settings_store import SettingsStore

if TYPE_CHECKING:
    from app.controllers.account_controller import AccountController
    from app.controllers.agent_controller import AgentController
    from app.controllers.clock_controller import ClockController
    from app.controllers.leaderboard_controller import LeaderboardController
    from app.controllers.market_controller import MarketController
    from app.controllers.trading_controller import TradingController
    from app.services.account_service import AccountService
    from app.services.agent_service import AgentService
    from app.services.arena_experiment_runner import ArenaExperimentRunner
    from app.services.clock_service import ClockService
    from app.services.leaderboard_service import LeaderboardService
    from app.services.market_data_service import MarketDataService
    from app.services.rollback_service import RollbackService
    from app.services.trading_service import TradingService
    from app.services.training_arena_service import TrainingArenaService


@dataclass
class AppContext:
    settings_store: SettingsStore
    runtime_gateway: Any

    market_data_service: MarketDataService | None
    market_controller: MarketController | None

    account_service: AccountService | None
    account_controller: AccountController | None

    trading_service: TradingService | None
    trading_controller: TradingController | None

    agent_service: AgentService | None
    agent_controller: AgentController | None

    clock_service: ClockService | None
    rollback_service: RollbackService | None
    clock_controller: ClockController | None

    leaderboard_service: LeaderboardService | None
    leaderboard_controller: LeaderboardController | None

    training_arena_service: TrainingArenaService | None
    arena_experiment_runner: ArenaExperimentRunner | None
    strategy_diagnostics_read_model: StrategyDiagnosticsV1ApplicationReadModel | None
    run_monitoring_feature: RunMonitoringFeature
    run_monitoring_context: RunMonitoringContext
    evidence_and_findings_feature: EvidenceAndFindingsFeature
    evidence_and_findings_context: EvidenceAndFindingsContext


def build_app_context(
    *,
    settings_path: str = "frontend_settings.json",
    run_monitoring_mode: str | None = None,
    event_bridge: EventBridge | None = None,
    runtime_gateway: Any | None = None,
    strategy_diagnostics_read_model: (
        StrategyDiagnosticsV1ApplicationReadModel | None
    ) = None,
    legacy_read_only: bool = False,
) -> AppContext:
    settings_store = SettingsStore(path=settings_path, auto_save=False)
    frontend_v2_enabled = _frontend_v2_enabled()
    if runtime_gateway is None:
        if frontend_v2_enabled or legacy_read_only:
            from app.diagnostics_runtime_gateway import (
                DiagnosticsRuntimeGateway,
            )

            runtime_gateway = DiagnosticsRuntimeGateway()
        else:
            from app.runtime_gateway import RuntimeGateway

            runtime_gateway = RuntimeGateway()
    if not frontend_v2_enabled and not legacy_read_only:
        runtime_gateway.ensure_desktop_run()
    if frontend_v2_enabled:
        market_data_service = None
        market_controller = None
        account_service = None
        account_controller = None
        trading_service = None
        trading_controller = None
        agent_service = None
        agent_controller = None
        clock_service = None
        rollback_service = None
        clock_controller = None
        leaderboard_service = None
        leaderboard_controller = None
        training_arena_service = None
        arena_experiment_runner = None
    else:
        _start_market_persistence_services()
        from app.controllers.account_controller import AccountController
        from app.controllers.agent_controller import AgentController
        from app.controllers.clock_controller import ClockController
        from app.controllers.leaderboard_controller import (
            LeaderboardController,
        )
        from app.controllers.market_controller import MarketController
        from app.services.account_service import AccountService
        from app.services.agent_service import AgentService
        from app.services.arena_experiment_runner import (
            ArenaExperimentRunner,
        )
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
        if legacy_read_only:
            trading_service = None
            trading_controller = None
        else:
            from app.controllers.trading_controller import (
                TradingController,
            )
            from app.services.trading_service import TradingService

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
        clock_controller = ClockController(
            clock_service,
            rollback_service,
        )
        leaderboard_service = LeaderboardService(
            use_runtime=True,
            runtime_gateway=runtime_gateway,
        )
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
        evidence_and_findings_feature: EvidenceAndFindingsFeature = (
            DeterministicFakeEvidenceAndFindingsAdapter()
        )
    else:
        live_bridge = event_bridge or start_frontend_bridge()
        if strategy_diagnostics_read_model is None:
            strategy_diagnostics_read_model = _build_strategy_diagnostics_read_model()
        run_monitoring_feature = LiveRunMonitoringAdapter(
            application_read_model=strategy_diagnostics_read_model,
            event_bridge=live_bridge,
            journey_selector=_v1_journey_selector_from_environment(
                run_monitoring_context
            ),
        )
        evidence_and_findings_feature = LiveEvidenceAndFindingsAdapter(
            runtime_gateway=runtime_gateway,
            event_bridge=live_bridge,
        )
    evidence_and_findings_context = _evidence_and_findings_context_from_environment(
        run_monitoring_context,
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
        strategy_diagnostics_read_model=strategy_diagnostics_read_model,
        run_monitoring_feature=run_monitoring_feature,
        run_monitoring_context=run_monitoring_context,
        evidence_and_findings_feature=evidence_and_findings_feature,
        evidence_and_findings_context=evidence_and_findings_context,
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
    runtime_gateway: Any | None = None,
    strategy_diagnostics_read_model: (
        StrategyDiagnosticsV1ApplicationReadModel | None
    ) = None,
    legacy_read_only: bool = False,
) -> AppContext:
    global _app_context
    with _lock:
        previous = _app_context
        _app_context = build_app_context(
            settings_path=settings_path,
            run_monitoring_mode=run_monitoring_mode,
            event_bridge=event_bridge,
            runtime_gateway=runtime_gateway,
            strategy_diagnostics_read_model=strategy_diagnostics_read_model,
            legacy_read_only=legacy_read_only,
        )
        if previous is not None:
            previous.run_monitoring_feature.close()
            previous.evidence_and_findings_feature.close()
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
        raise ValueError("Run Monitoring Adapter mode must be 'live' or 'fake'")
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


def _evidence_and_findings_context_from_environment(
    run_context: RunMonitoringContext,
) -> EvidenceAndFindingsContext:
    run_selection = run_context.selection
    if run_selection is None or run_selection.run_id is None:
        return EvidenceAndFindingsContext.no_selection()
    values = {
        "strategy": os.environ.get(
            "STOCKSIM_FRONTEND_V2_STRATEGY_ID",
            "",
        ).strip(),
        "scenario": os.environ.get(
            "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID",
            "",
        ).strip(),
        "recipe": os.environ.get(
            "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID",
            "",
        ).strip(),
        "manifest": os.environ.get(
            "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
            "",
        ).strip(),
    }
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=run_selection.campaign_id,
            run_id=run_selection.run_id,
            strategy_id=(
                StrategyUnderTestId(values["strategy"]) if values["strategy"] else None
            ),
            market_scenario_id=(
                MarketScenarioId(values["scenario"]) if values["scenario"] else None
            ),
            approved_recipe_id=(
                ApprovedScenarioRecipeId(values["recipe"]) if values["recipe"] else None
            ),
            reproduction_manifest_id=(
                ReproductionManifestId(values["manifest"])
                if values["manifest"]
                else None
            ),
        )
    )


def _v1_journey_selector_from_environment(
    run_context: RunMonitoringContext,
) -> V1JourneySelector | None:
    selection = run_context.selection
    if selection is None or selection.run_id is None:
        return None
    evidence_package_id = os.environ.get(
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID",
        "",
    ).strip()
    manifest_id = os.environ.get(
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
        "",
    ).strip()
    return V1JourneySelector(
        campaign_id=selection.campaign_id,
        run_id=selection.run_id,
        evidence_package_id=(
            DiagnosticEvidencePackageId(evidence_package_id)
            if evidence_package_id
            else None
        ),
        manifest_id=(ReproductionManifestId(manifest_id) if manifest_id else None),
    )


def _start_market_persistence_services() -> None:
    try:
        from stock_sim.services.bar_aggregator import ensure_bar_aggregator_started
        from stock_sim.services.snapshot_listener import (
            ensure_snapshot_listener_started,
        )

        ensure_snapshot_listener_started()
        ensure_bar_aggregator_started()
    except Exception:  # noqa: BLE001 - optional legacy services fail closed
        return


def _build_strategy_diagnostics_read_model() -> (
    LiveStrategyDiagnosticsV1ApplicationAdapter
):
    from persistence.models_imports import engine
    from strategy_diagnostics import create_diagnostics_application

    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    return LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine)


__all__ = ["AppContext", "build_app_context", "get_app_context", "reset_app_context"]
