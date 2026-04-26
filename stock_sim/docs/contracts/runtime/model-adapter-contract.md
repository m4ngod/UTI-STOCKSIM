# Model Adapter Contract

_Last updated: 2026-04-26_

## Purpose

This contract defines how trainable or external model policies attach to UTI-STOCKSIM without becoming coupled to the desktop UI, matching engine, account service, or database internals.

A model adapter must expose a policy object compatible with:

```python
policy.act(observation: dict) -> dict
```

The returned action must follow `act.v1`.

## Supported Adapter Shapes

### `static_action`

The simplest adapter. It returns a configured `act.v1` action and is mainly used for smoke tests, deterministic baselines, and integration checks.

Registry config:

```json
{
  "action": {
    "contract_version": "act.v1",
    "action_type": "target_weight",
    "payload": {
      "weights": {
        "001": 0.25
      }
    }
  }
}
```

### `callable`

The service-layer registry can inject a local Python policy through a factory. This is the intended bridge for the first trainable in-process baseline.

Factory signature:

```python
factory(model_id: str, config: dict, spec: ModelSpec) -> ModelPolicy
```

The returned object should implement `act(...)`. If it also implements `learn(...)` and `save_checkpoint(...)`, `ExternalPolicyAdapter` will delegate to those methods.

## Optional Trainable Interface

Trainable policies may implement:

```python
learn(transition: dict) -> dict
save_checkpoint(path: str) -> dict
```

`learn(...)` receives a normalized transition payload from the runtime loop:

```python
{
  "observation": {...},
  "action": {...},
  "execution_result": {...},
  "reward": {...}
}
```

`save_checkpoint(...)` should materialize model state to the requested path and return a small status payload.

## Registry Persistence

External policy metadata is persisted in:

```text
output/model_registry/policies.json
```

Default schema:

```json
{
  "schema": "stock_sim.model_registry.v1",
  "models": [
    {
      "model_id": "external_static_v1",
      "policy_type": "external",
      "adapter_type": "static_action",
      "description": "...",
      "config": {}
    }
  ]
}
```

The registry file stores adapter metadata only. Heavy model tensors should be stored through checkpoint artifacts, not inline in the registry.

## Runtime Boundary

Adapters must not directly call:

- matching engines
- account services
- order services
- Qt widgets
- database sessions

They only receive observations and return `act.v1` actions. Runtime truth remains in the platform services.

## Current Limitations

- HTTP/process adapters are not implemented yet.
- Real neural-network tensor checkpoints are not implemented yet.
- The callable adapter is intentionally local and testable before a full training worker architecture is introduced.
