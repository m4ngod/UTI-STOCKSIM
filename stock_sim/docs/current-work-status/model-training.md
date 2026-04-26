# Model Training Status

## Module

Multi-agent adversarial model training foundation

## Current state

in-progress

## Task 2026-04-26-model-training-01

### status

done

### goal

Start implementing the first work packages from `MODEL_TRAINING_DESIGN.md` and `MULTI_AGENT_TRAINING_ROADMAP.md`: make Model a visible first-class agent type and land the first contract-level closed-loop pieces.

### files involved

- `app/core_dto/agent.py`
- `app/services/agent_service.py`
- `app/services/model_registry_service.py`
- `app/services/runtime_model_agent.py`
- `app/controllers/agent_controller.py`
- `app/panels/agents/panel.py`
- `app/ui/adapters/agents_adapter.py`
- `rl/contracts.py`
- `rl/action_parser.py`
- `rl/observation_builder.py`
- `rl/model_bridge.py`
- `rl/reward_builder.py`
- `docs/contracts/runtime/model-reward-contract.md`
- `tests/frontend/unit/test_agents_model_view.py`
- `tests/runtime/test_model_action_target_weight.py`
- `tests/runtime/test_reward_builder.py`

### change summary

- Added model-oriented fields to `AgentMetaDTO`: `model_id`, `mode`, `episode_id`, `last_reward`, `equity`, `pnl`, and `last_action`.
- Added `AgentService.create_model_agent(...)` and controller support so the platform can create Model agents as first-class metadata objects.
- Added a small `ModelRegistryService` with `HoldModel` and `RandomWeightModel` placeholders.
- Added `RuntimeModelAgent`, a minimal service-layer lifecycle wrapper for observation -> action -> execution -> reward.
- Updated the Agent panel view to expose `All / Retail / Model` filtering and model-compatible columns.
- Extended `obs.v1` builder with a multi-symbol `build_many(...)` path while preserving the old single-symbol shape.
- Extended `act.v1` parsing to support `target_weight` and `target_position`.
- Implemented first target-weight translation in `ModelBridge`, converting model portfolio intent into runtime orders.
- Added `rew.v1` through `RewardBuilder`.

### verification

- `tests/frontend/unit/test_agents_model_view.py`
- `tests/runtime/test_model_action_target_weight.py`
- `tests/runtime/test_reward_builder.py`
- `tests/test_model_bridge.py`
- `tests/frontend/unit/test_agents_panel.py`
- `tests/frontend/unit/test_agents_adapter_control.py`
- `tests/frontend/unit/test_agent_service_runtime_gateway.py`
- `tests/frontend/unit/test_agent_service_runtime_authority.py`
- `tests/frontend/unit/test_agent_controller_batch.py`
- `tests/frontend/unit/test_agent_creation_controller_batch.py`
- `tests/frontend/unit/test_controllers_agents.py`
- `tests/frontend/integration/test_agents_flow.py`

### impact / risk

- Positive: the desktop platform can now represent model agents distinctly from retail agents.
- Positive: the first contract loop can parse `target_weight`, translate it into orders, and calculate a structured reward.
- Positive: the Agent panel has the first training-console affordance without requiring a full Arena panel yet.
- Risk: `RuntimeModelAgent` is still an MVP and does not yet persist transitions, episode reports, checkpoints, or lineage.
- Risk: target-weight execution currently uses a simple one-shot rebalance order plan; later versions should support slicing, slippage constraints, and richer risk feedback.

### next actions

- Persist `training_episodes` and `model_episode_results`.
- Record per-step transitions for model agents.
- Surface model reward/action metrics back into the Agent panel after each runtime step.
- Add Arena service orchestration for two or more model agents plus retail background agents.

## Task 2026-04-26-model-training-02

### status

done

### goal

Start Phase 3 by making model episodes produce persistent transition and result records, and surface live model metrics back into the Agent panel.

### files involved

- `persistence/models_training.py`
- `persistence/models_init.py`
- `services/training_episode_service.py`
- `app/services/runtime_model_agent.py`
- `app/services/agent_service.py`
- `MULTI_AGENT_TRAINING_ROADMAP.md`
- `tests/runtime/test_training_episode_report.py`
- `tests/frontend/unit/test_agents_model_view.py`

### change summary

- Added persistence models for `training_episodes`, `model_episode_results`, and `model_transitions`.
- Added `TrainingEpisodeService` to create episodes, record model transitions, upsert model results, rank episode results, and return episode summaries.
- Added a lightweight `EpisodeAgentAccumulator` for reward total, equity return, drawdown, turnover, fee, and trade-count aggregation.
- Extended `RuntimeModelAgent` so each `step_once()` can persist a transition and update a per-agent episode result when `episode_id` is present.
- Added model metrics callback wiring from `RuntimeModelAgent` to `AgentService`.
- Agent metadata now receives live `last_reward`, `last_action`, `equity`, and `pnl` updates after model steps.
- Added an implementation progress ledger to `MULTI_AGENT_TRAINING_ROADMAP.md` so completed work is clearly marked and not repeated.

### verification

- `tests/runtime/test_training_episode_report.py`
- `tests/frontend/unit/test_agents_model_view.py`

### impact / risk

- Positive: model-agent runs now produce persistent episode artifacts instead of only transient in-memory step output.
- Positive: the Agent panel can observe model behavior through current metrics without taking ownership of training logic.
- Positive: later Arena and PBT services can build on durable episode/result rows.
- Risk: episode result aggregation is still MVP-level and does not yet include benchmark-relative scoring, checkpoint lineage, or complete slippage/risk diagnostics.

### next actions

- Add `TrainingArenaService` to orchestrate multiple model agents plus retail background agents under one episode.
- Add checkpoint and lineage tables/services before implementing PBT inheritance.
- Promote episode summaries into a future Arena panel instead of overloading the Agent panel.

## Task 2026-04-26-model-training-03

### status

done

### goal

Start Phase 4 by adding a service-layer Arena MVP that can create, start, stop, and evaluate multi-model episodes without placing training orchestration in the UI.

### files involved

- `app/services/training_arena_service.py`
- `MULTI_AGENT_TRAINING_ROADMAP.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_training_arena_service.py`

### change summary

- Added `TrainingArenaService` with in-process Arena state and the standard Arena states from the roadmap.
- Added `TrainingArenaConfig`, `ArenaModelSpec`, and `TrainingArenaState`.
- `create_arena(...)` registers a model/retail training container.
- `start_arena(...)` creates a training episode, creates or binds model agents, optionally creates retail background agents, and starts all participants.
- `stop_arena(...)` stops all model and retail participants known to the Arena.
- `evaluate_arena(...)` ranks `model_episode_results`, completes the training episode, and stores the latest summary on the Arena state.
- Updated the roadmap progress ledger so round 1, round 2, and round 3 completed items are explicitly marked.

### verification

- `tests/runtime/test_training_arena_service.py`

### impact / risk

- Positive: multi-model episodes now have a service-level owner instead of being a loose manual sequence.
- Positive: future Arena UI can call a small service API instead of owning orchestration logic.
- Positive: PBT and checkpoint work now has a clear place to hook into after `evaluate_arena(...)`.
- Risk: Arena state is still in-process. Durable Arena rows should be added before long-running or restart-resilient training workflows.

### next actions

- Add checkpoint and lineage persistence.
- Add a minimal model population service for Hall-of-Fame and PBT mutation.
- Add Arena panel only after the service API stabilizes.

## Task 2026-04-26-model-training-04

### status

done

### goal

Start Phase 5 by adding checkpoint, Hall-of-Fame, lineage, and PBT inheritance records before connecting real neural-network checkpoint files.

### files involved

- `persistence/models_training.py`
- `persistence/models_init.py`
- `app/services/model_checkpoint_service.py`
- `app/services/model_population_service.py`
- `MULTI_AGENT_TRAINING_ROADMAP.md`
- `docs/code-index.md`
- `docs/current-work-status/model-training.md`
- `tests/runtime/test_pbt_lineage.py`

### change summary

- Added `model_checkpoints` persistence for model checkpoint metadata.
- Added `model_lineage` persistence for parent/child model inheritance records.
- Added `ModelCheckpointService` to save checkpoints, mark/list Hall-of-Fame entries, and record lineage.
- Added `ModelPopulationService` MVP that reads ranked episode results, saves top models as Hall-of-Fame checkpoints, and creates full-clone-plus-mutation lineage records for bottom models.
- Updated the roadmap progress ledger with round 4 completion markers.

### verification

- `tests/runtime/test_pbt_lineage.py`

### impact / risk

- Positive: the platform now has a durable audit trail for "winner teaches loser" cycles.
- Positive: Hall-of-Fame and lineage can be queried before real model weights are introduced.
- Positive: PBT can now be layered onto Arena evaluation without inventing storage later.
- Risk: checkpoint rows currently describe intended checkpoint artifacts; real neural-network weight materialization is still future work.

### next actions

- Add real checkpoint file writing/copying once a true policy adapter is connected.
- Add a population adapter that updates live model agents after lineage creation.
- Add Arena UI only after checkpoint/PBT service APIs settle.
