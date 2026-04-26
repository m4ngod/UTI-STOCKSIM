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
