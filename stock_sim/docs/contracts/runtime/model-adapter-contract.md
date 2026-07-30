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

### `http`

The adapter can call an out-of-process model service over HTTP. This is the preferred boundary when a model needs its own Python environment, GPU process, or training loop.

Registry config:

```json
{
  "base_url": "http://127.0.0.1:9001",
  "timeout_s": 2.0
}
```

Default endpoints:

```text
POST /act
POST /learn
POST /checkpoint
```

Explicit endpoints can override the defaults:

```json
{
  "endpoint": "http://127.0.0.1:9001/policy/act",
  "learn_endpoint": "http://127.0.0.1:9001/policy/learn",
  "checkpoint_endpoint": "http://127.0.0.1:9001/policy/checkpoint"
}
```

`/act` request:

```json
{
  "model_id": "remote_policy_v1",
  "observation": {}
}
```

`/act` may return either an `act.v1` action directly or wrap it:

```json
{
  "action": {
    "contract_version": "act.v1",
    "action_type": "hold",
    "target": {},
    "payload": {},
    "constraints": {},
    "meta": {}
  }
}
```

If the HTTP adapter cannot reach the endpoint, it returns a safe `hold` action with error metadata.

### `subprocess`

The adapter can launch a short-lived local process and exchange JSON through stdin/stdout. This is useful when a model should run in a separate Python environment but does not need a long-running HTTP service.

Registry config:

```json
{
  "command": ["python", "path/to/policy_worker.py"],
  "timeout_s": 2.0
}
```

The process receives one JSON request on stdin:

```json
{
  "op": "act",
  "model_id": "process_policy_v1",
  "observation": {}
}
```

For learning:

```json
{
  "op": "learn",
  "model_id": "process_policy_v1",
  "transition": {}
}
```

For checkpointing:

```json
{
  "op": "checkpoint",
  "model_id": "process_policy_v1",
  "path": "output/model_checkpoints/process_policy_v1/ckpt.json"
}
```

The process must print one JSON object to stdout. For `act`, it may return either an `act.v1` action directly or `{ "action": ... }`.

If the process exits non-zero, times out, or returns invalid JSON, the adapter returns a safe `hold` action with error metadata.

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

- Real neural-network tensor checkpoints are not implemented yet.
- The callable, HTTP, and subprocess adapters are intentionally minimal before a full training worker architecture is introduced.
