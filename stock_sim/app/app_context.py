"""Shared desktop app composition root."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Any

from app.event_bridge import EventBridge, start_frontend_bridge
from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeScenarioLabAdapter,
    DeterministicFakeStrategyLibraryAdapter,
    DeterministicFakeSystemHealthAdapter,
    DiagnosticEvidencePackageId,
    DiagnosticsApplicationOwned,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    LiveDiagnosticTasksAdapter,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveScenarioLabAdapter,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveStrategyLibraryAdapter,
    LiveSystemHealthAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringSelection,
    ScenarioLabContext,
    ScenarioLabFeature,
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyDiagnosticsV1ScenarioLabApplication,
    StrategyDiagnosticsV1SystemHealthApplication,
    StrategyLibraryContext,
    StrategyLibraryFeature,
    SystemHealthContext,
    SystemHealthFeature,
    StrategySelectionBookmark,
    StrategyRunId,
    StrategyUnderTestId,
    V1JourneySelector,
    diagnostics_application_identity,
    decode_strategy_selection_bookmark,
    encode_strategy_selection_bookmark,
)
from app.features.diagnostic_setup import DiagnosticSetupSelectionCoordinator
from app.journey_recovery import (
    JourneyWorkspaceBookmark,
    decode_journey_workspace_bookmark,
    encode_journey_workspace_bookmark,
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
    from strategy_diagnostics.application import DiagnosticsApplication


@dataclass
class AppContext:
    settings_store: SettingsStore
    runtime_gateway: Any
    journey_workspace_bookmark: JourneyWorkspaceBookmark

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
    strategy_diagnostics_application: DiagnosticsApplication | None
    strategy_diagnostics_read_model: StrategyDiagnosticsV1ApplicationReadModel | None
    strategy_diagnostics_tasks_application: (
        StrategyDiagnosticsV1DiagnosticTasksApplication | None
    )
    strategy_diagnostics_library_application: (
        StrategyDiagnosticsV1StrategyLibraryApplication | None
    )
    strategy_diagnostics_scenario_lab_application: (
        StrategyDiagnosticsV1ScenarioLabApplication | None
    )
    strategy_diagnostics_system_health_application: (
        StrategyDiagnosticsV1SystemHealthApplication | None
    )
    diagnostic_setup_selection_coordinator: (
        DiagnosticSetupSelectionCoordinator
    )
    strategy_library_feature: StrategyLibraryFeature
    strategy_library_context: StrategyLibraryContext
    scenario_lab_feature: ScenarioLabFeature
    scenario_lab_context: ScenarioLabContext
    diagnostic_tasks_feature: DiagnosticTasksFeature
    diagnostic_tasks_context: DiagnosticTasksContext
    run_monitoring_feature: RunMonitoringFeature
    run_monitoring_context: RunMonitoringContext
    evidence_and_findings_feature: EvidenceAndFindingsFeature
    evidence_and_findings_context: EvidenceAndFindingsContext
    system_health_feature: SystemHealthFeature
    system_health_context: SystemHealthContext
    _journey_workspace_bookmark_lock: RLock = field(
        default_factory=RLock,
        init=False,
        repr=False,
    )

    def persist_strategy_library_bookmark(
        self,
        bookmark: StrategySelectionBookmark,
    ) -> None:
        """Persist the exact formal set through the sole composition root."""

        self.settings_store.update(
            strategy_library_bookmark_json=(
                encode_strategy_selection_bookmark(bookmark)
            )
        )
        self.settings_store.get_state().save()

    def persist_journey_workspace_bookmark(
        self,
        bookmark: JourneyWorkspaceBookmark,
    ) -> None:
        """Persist only typed recovery hints, never durable configuration truth."""

        with self._journey_workspace_bookmark_lock:
            self.settings_store.update(
                journey_workspace_bookmark_json=(
                    encode_journey_workspace_bookmark(bookmark)
                )
            )
            self.settings_store.get_state().save()
            self.journey_workspace_bookmark = bookmark


def build_app_context(
    *,
    settings_path: str = "frontend_settings.json",
    run_monitoring_mode: str | None = None,
    event_bridge: EventBridge | None = None,
    runtime_gateway: Any | None = None,
    strategy_diagnostics_application: DiagnosticsApplication | None = None,
    strategy_diagnostics_read_model: (
        StrategyDiagnosticsV1ApplicationReadModel | None
    ) = None,
    strategy_diagnostics_tasks_application: (
        StrategyDiagnosticsV1DiagnosticTasksApplication | None
    ) = None,
    strategy_diagnostics_library_application: (
        StrategyDiagnosticsV1StrategyLibraryApplication | None
    ) = None,
    strategy_diagnostics_scenario_lab_application: (
        StrategyDiagnosticsV1ScenarioLabApplication | None
    ) = None,
    strategy_diagnostics_system_health_application: (
        StrategyDiagnosticsV1SystemHealthApplication | None
    ) = None,
    diagnostic_setup_selection_coordinator: (
        DiagnosticSetupSelectionCoordinator | None
    ) = None,
    legacy_read_only: bool = False,
) -> AppContext:
    setup_coordinator = (
        diagnostic_setup_selection_coordinator
        or DiagnosticSetupSelectionCoordinator()
    )
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
        from app.legacy_panel_context import build_legacy_panel_context

        _start_market_persistence_services()
        legacy_context = build_legacy_panel_context(
            settings_store=settings_store,
            runtime_gateway=runtime_gateway,
            include_trading=not legacy_read_only,
        )
        market_data_service = legacy_context.market_data_service
        market_controller = legacy_context.market_controller
        account_service = legacy_context.account_service
        account_controller = legacy_context.account_controller
        trading_service = legacy_context.trading_service
        trading_controller = legacy_context.trading_controller
        agent_service = legacy_context.agent_service
        agent_controller = legacy_context.agent_controller
        clock_service = legacy_context.clock_service
        rollback_service = legacy_context.rollback_service
        clock_controller = legacy_context.clock_controller
        leaderboard_service = legacy_context.leaderboard_service
        leaderboard_controller = legacy_context.leaderboard_controller
        training_arena_service = legacy_context.training_arena_service
        arena_experiment_runner = legacy_context.arena_experiment_runner
    run_monitoring_context = _run_monitoring_context_from_environment()
    resolved_mode = _run_monitoring_mode(run_monitoring_mode)
    journey_workspace_bookmark = (
        decode_journey_workspace_bookmark(
            settings_store.get_state().journey_workspace_bookmark_json
        )
        or JourneyWorkspaceBookmark()
    )
    diagnostic_tasks_context = DiagnosticTasksContext(
        task_id=journey_workspace_bookmark.diagnostic_task_id
    )
    strategy_library_bookmark = decode_strategy_selection_bookmark(
        settings_store.get_state().strategy_library_bookmark_json
    )
    strategy_library_context = StrategyLibraryContext(
        focus_strategy_id=(
            None
            if strategy_library_bookmark is None
            else strategy_library_bookmark.focus_strategy_id
        ),
        selection_bookmark=strategy_library_bookmark,
    )
    scenario_lab_context = ScenarioLabContext(
        focus_target=journey_workspace_bookmark.scenario_focus_target,
        focus_identity=journey_workspace_bookmark.scenario_focus_identity,
    )
    system_health_context = SystemHealthContext()
    if resolved_mode == "fake":
        strategy_library_feature: StrategyLibraryFeature = (
            DeterministicFakeStrategyLibraryAdapter()
        )
        scenario_lab_feature: ScenarioLabFeature = (
            DeterministicFakeScenarioLabAdapter()
        )
        diagnostic_tasks_feature: DiagnosticTasksFeature = (
            DeterministicFakeDiagnosticTasksAdapter(
                setup_selection_provider=setup_coordinator.current,
            )
        )
        run_monitoring_feature: RunMonitoringFeature = (
            DeterministicFakeRunMonitoringAdapter()
        )
        evidence_and_findings_feature: EvidenceAndFindingsFeature = (
            DeterministicFakeEvidenceAndFindingsAdapter()
        )
        system_health_feature: SystemHealthFeature = (
            DeterministicFakeSystemHealthAdapter()
        )
    else:
        live_bridge = event_bridge or start_frontend_bridge()
        if (
            strategy_diagnostics_read_model is None
            and strategy_diagnostics_tasks_application is None
            and strategy_diagnostics_library_application is None
            and strategy_diagnostics_scenario_lab_application is None
            and strategy_diagnostics_system_health_application is None
        ):
            (
                strategy_diagnostics_application,
                strategy_diagnostics_read_model,
                strategy_diagnostics_tasks_application,
                strategy_diagnostics_library_application,
                strategy_diagnostics_scenario_lab_application,
                strategy_diagnostics_system_health_application,
            ) = _build_strategy_diagnostics_adapters(
                setup_coordinator,
                application=strategy_diagnostics_application,
            )
        else:
            if strategy_diagnostics_application is None:
                raise ValueError(
                    "Injected Strategy Diagnostics interfaces require an "
                    "explicit shared DiagnosticsApplication"
                )
            (
                strategy_diagnostics_read_model,
                strategy_diagnostics_tasks_application,
                strategy_diagnostics_library_application,
                strategy_diagnostics_scenario_lab_application,
                strategy_diagnostics_system_health_application,
            ) = _complete_strategy_diagnostics_adapters(
                setup_coordinator=setup_coordinator,
                application=strategy_diagnostics_application,
                read_model=strategy_diagnostics_read_model,
                tasks_application=strategy_diagnostics_tasks_application,
                library_application=strategy_diagnostics_library_application,
                scenario_lab_application=(
                    strategy_diagnostics_scenario_lab_application
                ),
                system_health_application=(
                    strategy_diagnostics_system_health_application
                ),
            )
        strategy_library_feature = LiveStrategyLibraryAdapter(
            application=strategy_diagnostics_library_application,
            event_bridge=live_bridge,
        )
        scenario_lab_feature = LiveScenarioLabAdapter(
            application=strategy_diagnostics_scenario_lab_application,
            event_bridge=live_bridge,
        )
        diagnostic_tasks_feature = LiveDiagnosticTasksAdapter(
            application=strategy_diagnostics_tasks_application,
            event_bridge=live_bridge,
        )
        journey_selector = _v1_journey_selector_from_environment(
            run_monitoring_context
        )
        run_monitoring_feature = LiveRunMonitoringAdapter(
            application_read_model=strategy_diagnostics_read_model,
            event_bridge=live_bridge,
            journey_selector=journey_selector,
        )
        evidence_and_findings_feature = LiveEvidenceAndFindingsAdapter(
            application_read_model=strategy_diagnostics_read_model,
            event_bridge=live_bridge,
            journey_selector=journey_selector,
        )
        system_health_feature = LiveSystemHealthAdapter(
            application_health=(
                strategy_diagnostics_system_health_application
            ),
            diagnostic_tasks_application=strategy_diagnostics_tasks_application,
            application_read_model=strategy_diagnostics_read_model,
            event_bridge=live_bridge,
        )
    evidence_and_findings_context = _evidence_and_findings_context_from_environment(
        run_monitoring_context,
    )

    return AppContext(
        settings_store=settings_store,
        runtime_gateway=runtime_gateway,
        journey_workspace_bookmark=journey_workspace_bookmark,
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
        strategy_diagnostics_application=strategy_diagnostics_application,
        strategy_diagnostics_read_model=strategy_diagnostics_read_model,
        strategy_diagnostics_tasks_application=(
            strategy_diagnostics_tasks_application
        ),
        strategy_diagnostics_library_application=(
            strategy_diagnostics_library_application
        ),
        strategy_diagnostics_scenario_lab_application=(
            strategy_diagnostics_scenario_lab_application
        ),
        strategy_diagnostics_system_health_application=(
            strategy_diagnostics_system_health_application
        ),
        diagnostic_setup_selection_coordinator=setup_coordinator,
        strategy_library_feature=strategy_library_feature,
        strategy_library_context=strategy_library_context,
        scenario_lab_feature=scenario_lab_feature,
        scenario_lab_context=scenario_lab_context,
        diagnostic_tasks_feature=diagnostic_tasks_feature,
        diagnostic_tasks_context=diagnostic_tasks_context,
        run_monitoring_feature=run_monitoring_feature,
        run_monitoring_context=run_monitoring_context,
        evidence_and_findings_feature=evidence_and_findings_feature,
        evidence_and_findings_context=evidence_and_findings_context,
        system_health_feature=system_health_feature,
        system_health_context=system_health_context,
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
    strategy_diagnostics_application: DiagnosticsApplication | None = None,
    strategy_diagnostics_read_model: (
        StrategyDiagnosticsV1ApplicationReadModel | None
    ) = None,
    strategy_diagnostics_tasks_application: (
        StrategyDiagnosticsV1DiagnosticTasksApplication | None
    ) = None,
    strategy_diagnostics_library_application: (
        StrategyDiagnosticsV1StrategyLibraryApplication | None
    ) = None,
    strategy_diagnostics_scenario_lab_application: (
        StrategyDiagnosticsV1ScenarioLabApplication | None
    ) = None,
    strategy_diagnostics_system_health_application: (
        StrategyDiagnosticsV1SystemHealthApplication | None
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
            strategy_diagnostics_application=strategy_diagnostics_application,
            strategy_diagnostics_read_model=strategy_diagnostics_read_model,
            strategy_diagnostics_tasks_application=(
                strategy_diagnostics_tasks_application
            ),
            strategy_diagnostics_library_application=(
                strategy_diagnostics_library_application
            ),
            strategy_diagnostics_scenario_lab_application=(
                strategy_diagnostics_scenario_lab_application
            ),
            strategy_diagnostics_system_health_application=(
                strategy_diagnostics_system_health_application
            ),
            legacy_read_only=legacy_read_only,
        )
        if previous is not None:
            previous.strategy_library_feature.close()
            previous.scenario_lab_feature.close()
            previous.diagnostic_tasks_feature.close()
            previous.run_monitoring_feature.close()
            previous.evidence_and_findings_feature.close()
            previous.system_health_feature.close()
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


def _complete_strategy_diagnostics_adapters(
    *,
    setup_coordinator: DiagnosticSetupSelectionCoordinator,
    application: DiagnosticsApplication,
    read_model: StrategyDiagnosticsV1ApplicationReadModel | None,
    tasks_application: StrategyDiagnosticsV1DiagnosticTasksApplication | None,
    library_application: StrategyDiagnosticsV1StrategyLibraryApplication | None,
    scenario_lab_application: StrategyDiagnosticsV1ScenarioLabApplication | None,
    system_health_application: StrategyDiagnosticsV1SystemHealthApplication | None,
) -> tuple[
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyDiagnosticsV1ScenarioLabApplication,
    StrategyDiagnosticsV1SystemHealthApplication,
]:
    """Fill partial injection from the explicit canonical application."""

    from persistence.models_imports import engine

    expected_identity = diagnostics_application_identity(application)
    injected = {
        "read_model": read_model,
        "tasks_application": tasks_application,
        "library_application": library_application,
        "scenario_lab_application": scenario_lab_application,
        "system_health_application": system_health_application,
    }
    for name, adapter in injected.items():
        if adapter is None:
            continue
        if (
            not isinstance(adapter, DiagnosticsApplicationOwned)
            or adapter.application_identity != expected_identity
        ):
            raise ValueError(
                f"Injected {name} does not belong to the explicit shared "
                "DiagnosticsApplication"
            )
    application.start()
    persistence_commands_available = _persistence_commands_are_available(
        application
    )
    if read_model is None:
        persistence_commands_available = _initialize_diagnostics_persistence(
            application,
            engine,
        )
        read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
            application,
            engine,
        )
    if tasks_application is None:
        tasks_application = (
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                application,
                setup_selection_provider=setup_coordinator.current,
                commands_available=persistence_commands_available,
            )
        )
    if library_application is None:
        library_application = (
            LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
                application
            )
        )
    if scenario_lab_application is None:
        scenario_lab_application = (
            LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
                application,
                commands_available=persistence_commands_available,
            )
        )
    if system_health_application is None:
        system_health_application = (
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(application)
        )
    return (
        read_model,
        tasks_application,
        library_application,
        scenario_lab_application,
        system_health_application,
    )


def _build_strategy_diagnostics_adapters(
    setup_coordinator: DiagnosticSetupSelectionCoordinator,
    *,
    application: DiagnosticsApplication | None = None,
) -> tuple[
    DiagnosticsApplication,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
]:
    from persistence.models_imports import engine
    from strategy_diagnostics import create_diagnostics_application

    application = application or create_diagnostics_application()
    application.start()
    persistence_commands_available = _initialize_diagnostics_persistence(
        application,
        engine,
    )
    return (
        application,
        LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine),
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application,
            setup_selection_provider=setup_coordinator.current,
            commands_available=persistence_commands_available,
        ),
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(application),
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application,
            commands_available=persistence_commands_available,
        ),
        LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(application),
    )


def _initialize_diagnostics_persistence(
    application: DiagnosticsApplication,
    engine: Any,
) -> bool:
    """Continue only for migration/open failures System Health can reobserve."""

    try:
        application.initialize_persistence(engine)
    except Exception:  # noqa: BLE001 - re-raise non-observable partial init
        from strategy_diagnostics.persistence import (
            DiagnosticPersistenceAvailability,
            DiagnosticPersistenceCompatibility,
        )

        observation = application.read_diagnostic_persistence_health()
        if (
            observation.availability
            is DiagnosticPersistenceAvailability.UNAVAILABLE
            or observation.compatibility
            is DiagnosticPersistenceCompatibility.INCOMPATIBLE
        ):
            return False
        raise
    return True


def _persistence_commands_are_available(
    application: DiagnosticsApplication,
) -> bool:
    from strategy_diagnostics.persistence import (
        DiagnosticPersistenceAvailability,
        DiagnosticPersistenceCompatibility,
    )

    try:
        observation = application.read_diagnostic_persistence_health()
    except Exception:  # noqa: BLE001 - fail closed for command composition
        return False
    return (
        observation.availability is DiagnosticPersistenceAvailability.AVAILABLE
        and observation.compatibility
        is DiagnosticPersistenceCompatibility.COMPATIBLE
    )


__all__ = ["AppContext", "build_app_context", "get_app_context", "reset_app_context"]
