# Code Index

## Frontend structure

- Real main window: `app/ui/main_window.py`
- Product startup entry: `setup_frontend_entry.py`
- Headless frontend surface: `app/headless.py`
- App composition root: `app/app_context.py`
- UI bridge / dynamic page opening: `app/ui/ui_refresh.py`
- Dock host: `app/ui/docking.py`
- Panel registry: `app/panels/__init__.py`, `app/panels/registry.py`

## Strategy Diagnostics V1 + Frontend V2 Wave 1

- Typed Application read-model Interface: `app/features/strategy_diagnostics_v1_read_model.py`
- Persisted V1 Application adapter: `app/features/live_strategy_diagnostics_v1_application.py`
- Run Monitoring live adapter: `app/features/live_run_monitoring.py`
- Evidence & Findings live adapter: `app/features/live_evidence_and_findings.py`
- QML Journey host and Qt adapters: `app/ui/journey_workspace.py`
- Integration contract: `docs/contracts/integration/strategy-diagnostics-v1-frontend-v2-contract.md`
- Integration quality-gate runbook: `docs/testing/integration/strategy-diagnostics-v1-frontend-v2-runbook.md`
- Executable union gate: `stock_sim/release/strategy_diagnostics_v1_frontend_v2_gate.py`
- Shared fake/live conformance: `tests/frontend/contract/test_strategy_diagnostics_v1_feature_pair_conformance.py`
- File-backed Application-to-QML tracer: `tests/frontend/integration/test_live_run_to_evidence_journey.py`

## Market frontend

- Controller: `app/controllers/market_controller.py`
- Logic panel: `app/panels/market/panel.py`
- UI adapter: `app/ui/adapters/market_adapter.py`
- Bars/K-line cache service: `app/services/market_data_service.py`
- Market detail contract: `docs/contracts/market/market-detail-contract.md`
- Snapshot/event bridge: `app/event_bridge.py`

## Account frontend

- Controller: `app/controllers/account_controller.py`
- Logic panel: `app/panels/account/panel.py`
- App-layer account service: `app/services/account_service.py`

## Backend/runtime trading

- Order orchestration: `services/order_service.py`
- Order pre-trade policy: `services/order_pretrade_service.py`
- Order cancellation lifecycle: `services/order_cancel_service.py`
- Order engine routing: `services/order_engine_router.py`
- Order runtime sync bridge: `services/order_runtime_sync_service.py`
- Order post-trade settlement: `services/order_trade_settlement_service.py`
- Order auction reconciliation: `services/order_auction_reconciliation_service.py`
- Order day-boundary maintenance: `services/order_maintenance_service.py`
- Runtime account service: `services/account_service.py`
- Engine registry: `services/engine_registry.py`
- Instrument creation / engine registration: `services/instrument_service.py`
- Backend snapshot service: `services/market_data_service.py`

## Existing architecture note

- Storage layering / future runtime persistence direction: `docs/data/data-layering-design.md`
- Table-level storage mapping / migration blueprint: `docs/data/data-layering-table-plan.md`
- `simulation_runs` table design draft: `docs/data/simulation-runs-design.md`
- `account_equity_snapshots` table design draft: `docs/data/account-equity-snapshots-design.md`
- `run_id` migration / wiring blueprint: `docs/data/run-id-wiring-plan.md`
- runtime `RunContext` bridge design: `docs/data/run-context-design.md`
- PostgreSQL runtime migration status: `docs/data/postgresql-runtime-migration.md`

## Retail runtime persona

- Retail strategy registry / cold-start mix: `agents/retail_strategy.py`
- Retail persona sampling / expected-price model / loss-aversion / courage: `agents/retail_persona.py`
- Retail calibration defaults / family mix targets / market metric bands: `agents/retail_calibration.py`
- Retail episode calibration report collector: `agents/retail_calibration_report.py`
- Runtime retail executor: `app/services/runtime_retail_agent.py`
- Retail calibration episode runner: `scripts/run_retail_calibration_episode.py`
- Retail persona calibration blueprint: `docs/architecture/runtime/retail-persona-calibration-blueprint.md`

## Model training foundation

- Training design: `docs/design/model-training-design.md`
- Multi-agent roadmap: `docs/plan/multi-agent-training-roadmap.md`
- Model action contract: `docs/contracts/runtime/model-action-contract.md`
- Model observation contract: `docs/contracts/runtime/model-observation-contract.md`
- Model reward contract: `docs/contracts/runtime/model-reward-contract.md`
- Model adapter contract: `docs/contracts/runtime/model-adapter-contract.md`
- Model contract constants: `rl/contracts.py`
- Observation builder: `rl/observation_builder.py`
- Action parser: `rl/action_parser.py`
- In-process model bridge: `rl/model_bridge.py`
- Reward builder: `rl/reward_builder.py`
- Model registry, built-in placeholder policies, checkpoint-backed child loader, and external/callable/HTTP/subprocess policy adapters: `app/services/model_registry_service.py`
- Runtime model lifecycle MVP: `app/services/runtime_model_agent.py`
- Real recurrent PPO/LSTM policy adapter: `rl/model_adapters/ppo_recurrent_adapter.py`
- Training persistence models: `persistence/models_training.py`
- Training episode/result service: `services/training_episode_service.py`
- Training Arena service MVP: `app/services/training_arena_service.py`
- Arena experiment runner and report research-acceptance sections: `app/services/arena_experiment_runner.py`
- Evidence Runner WorldSpec, seed ledger, market metrics, and calibration scorecard core: `app/services/evidence_core.py`
- Evidence Runner separate calibration/baseline/hidden-eval artifact JSON writer: `app/services/evidence_artifact_writer.py`
- Evidence Runner frozen hidden-world evaluator: `app/services/hidden_world_runner.py`
- Evidence Runner paired fee/impact/latency sensitivity evaluator: `app/services/paired_sensitivity_runner.py`
- Evidence Runner exploit-test evaluator and required probes: `app/services/exploit_test_runner.py`
- Evidence Runner strict parent-gate v2 evaluator: `app/services/strict_parent_gate.py`
- Evidence Runner research acceptance lock v2: `app/services/research_acceptance_lock.py`
- Evidence Runner series evidence aggregate v1: `app/services/series_evidence_aggregate.py`
- Evidence Board view model builder: `app/services/evidence_board_service.py`
- Evidence Runner contract tests for schema/hash/seed/no-learning/bad-policy rejection: `tests/runtime/test_evidence_contracts.py`
- Long Arena dry-run evidence package builder: `app/services/long_arena_dry_run.py`
- Evidence Runner model-route escalation gate: `app/services/model_route_gate.py`
- Training Arena desktop panel and UI adapter: `app/panels/arena/panel.py`, `app/ui/adapters/arena_adapter.py`
- Model checkpoint/Hall-of-Fame service, JSON artifact writer, and tensor checkpoint adapter: `app/services/model_checkpoint_service.py`
- Model population/PBT service with optional live Agent inheritance application: `app/services/model_population_service.py`
- Model/Retail agent visibility: `app/panels/agents/panel.py`, `app/ui/adapters/agents_adapter.py`
