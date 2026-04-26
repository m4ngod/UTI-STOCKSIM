# Code Index

## Frontend structure

- Real main window: `app/ui/main_window.py`
- Product startup entry: `setup_frontend_entry.py`
- Headless frontend surface: `app/headless.py`
- App composition root: `app/app_context.py`
- UI bridge / dynamic page opening: `app/ui/ui_refresh.py`
- Dock host: `app/ui/docking.py`
- Panel registry: `app/panels/__init__.py`, `app/panels/registry.py`

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

- Training design: `MODEL_TRAINING_DESIGN.md`
- Multi-agent roadmap: `MULTI_AGENT_TRAINING_ROADMAP.md`
- Model action contract: `docs/contracts/runtime/model-action-contract.md`
- Model observation contract: `docs/contracts/runtime/model-observation-contract.md`
- Model reward contract: `docs/contracts/runtime/model-reward-contract.md`
- Model contract constants: `rl/contracts.py`
- Observation builder: `rl/observation_builder.py`
- Action parser: `rl/action_parser.py`
- In-process model bridge: `rl/model_bridge.py`
- Reward builder: `rl/reward_builder.py`
- Model registry and built-in placeholder policies: `app/services/model_registry_service.py`
- Runtime model lifecycle MVP: `app/services/runtime_model_agent.py`
- Training persistence models: `persistence/models_training.py`
- Training episode/result service: `services/training_episode_service.py`
- Model/Retail agent visibility: `app/panels/agents/panel.py`, `app/ui/adapters/agents_adapter.py`
