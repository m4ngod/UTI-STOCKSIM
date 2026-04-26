import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.services.model_registry_service import ExternalPolicyAdapter, ModelRegistryService
from app.services.runtime_model_agent import RuntimeModelAgent


class _Gateway:
    def __init__(self):
        self.orders = []

    def list_instruments(self, *, active_only=True):
        return [{"symbol": "001", "initial_price": 10.0}]

    def get_recent_trades(self, symbol, *, limit=1):
        return []

    def get_bars(self, symbol, timeframe, *, limit):
        return [{"close": 10.0}]

    def get_account_snapshot(self, account_id):
        return {"account_id": account_id, "cash": 100_000.0, "equity": 100_000.0, "positions": []}

    def get_current_run_id(self):
        return "run-external-policy"

    def get_current_sim_day(self):
        return 7

    def clock_snapshot(self):
        return {"running": True}

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"ok": True, "order_id": f"order-{len(self.orders)}"}


class _TrainableStub:
    def __init__(self, model_id):
        self.model_id = model_id
        self.learn_calls = []

    def act(self, observation):
        return {
            "contract_version": "act.v1",
            "action_type": "target_weight",
            "target": {"symbols": ["001"]},
            "payload": {"weights": {"001": 0.2}},
            "constraints": {"clip_to_limits": True},
            "meta": {"source": "trainable_stub"},
        }

    def learn(self, transition):
        self.learn_calls.append(transition)
        return {"ok": True, "loss": 0.123}

    def save_checkpoint(self, path):
        return {"ok": True, "path": path, "kind": "stub"}


class _PolicyHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body or "{}")
        self.__class__.requests.append({"path": self.path, "payload": payload})
        if self.path == "/act":
            response = {
                "action": {
                    "contract_version": "act.v1",
                    "action_type": "target_weight",
                    "payload": {"weights": {"001": 0.35}},
                    "meta": {"remote": True},
                }
            }
        elif self.path == "/learn":
            response = {"ok": True, "loss": 0.456}
        elif self.path == "/checkpoint":
            response = {"ok": True, "remote_path": payload.get("path")}
        else:
            response = {"ok": False, "error": "unknown path"}
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return


class _PolicyServer:
    def __enter__(self):
        _PolicyHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _PolicyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def test_registry_persists_and_loads_static_external_policy(tmp_path):
    registry_path = tmp_path / "policies.json"
    registry = ModelRegistryService(session_factory=None, registry_path=registry_path)
    registry.register_external_policy(
        "external_static_v1",
        adapter_type="static_action",
        config={
            "action": {
                "contract_version": "act.v1",
                "action_type": "target_weight",
                "target": {"symbols": ["001"]},
                "payload": {"weights": {"001": 0.25}},
            }
        },
    )

    reloaded = ModelRegistryService(session_factory=None, registry_path=registry_path)
    policy = reloaded.create_policy("external_static_v1")
    action = policy.act({"contract_version": "obs.v1", "context": {"agent_id": "MODEL_EXT"}})

    assert registry_path.exists()
    assert "external_static_v1" in {spec.model_id for spec in reloaded.list_models()}
    assert isinstance(policy, ExternalPolicyAdapter)
    assert action["action_type"] == "target_weight"
    assert action["target"]["account_id"] == "MODEL_EXT"
    assert action["meta"]["model_id"] == "external_static_v1"
    assert action["meta"]["policy_type"] == "external"


def test_registry_wraps_injected_trainable_policy(tmp_path):
    created = {}

    def _factory(*, model_id, config, spec):
        created["policy"] = _TrainableStub(model_id)
        return created["policy"]

    registry = ModelRegistryService(
        session_factory=None,
        registry_path=tmp_path / "policies.json",
        external_policy_factories={"trainable_stub": _factory},
    )
    registry.register_external_policy(
        "trainable_stub_v1",
        adapter_type="callable",
        config={"factory": "trainable_stub"},
    )

    policy = registry.create_policy("trainable_stub_v1")
    action = policy.act({"contract_version": "obs.v1", "context": {"agent_id": "MODEL_TRAIN"}})
    learn_result = policy.learn({"reward": {"step_reward": 0.1}})
    checkpoint_result = policy.save_checkpoint(str(tmp_path / "stub.json"))

    assert action["meta"]["adapter_type"] == "callable"
    assert action["meta"]["source"] == "trainable_stub"
    assert learn_result["loss"] == 0.123
    assert checkpoint_result["kind"] == "stub"
    assert created["policy"].learn_calls


def test_external_policy_adapter_can_materialize_checkpoint(tmp_path):
    policy = ExternalPolicyAdapter(
        model_id="external_static_v1",
        adapter_type="static_action",
        config={"action": {"contract_version": "act.v1", "action_type": "hold"}},
    )
    result = policy.save_checkpoint(str(tmp_path / "external.json"))
    payload = json.loads((tmp_path / "external.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert payload["schema"] == "stock_sim.external_policy_checkpoint.v1"
    assert payload["model_id"] == "external_static_v1"


def test_runtime_model_agent_runs_registered_external_policy(tmp_path):
    registry = ModelRegistryService(session_factory=None, registry_path=tmp_path / "policies.json")
    registry.register_external_policy(
        "external_runtime_v1",
        adapter_type="static_action",
        config={
            "action": {
                "contract_version": "act.v1",
                "action_type": "target_weight",
                "payload": {"weights": {"001": 0.15}},
            }
        },
    )
    gateway = _Gateway()
    agent = RuntimeModelAgent(
        agent_id="MODEL_EXT",
        model_id="external_runtime_v1",
        runtime_gateway=gateway,
        registry=registry,
        persist_transitions=False,
    )

    transition = agent.step_once()

    assert transition["action"]["meta"]["policy_type"] == "external"
    assert transition["execution_result"]["status"] == "EXECUTED"
    assert gateway.orders[0]["account_id"] == "MODEL_EXT"


def test_http_policy_adapter_calls_remote_act_learn_and_checkpoint(tmp_path):
    with _PolicyServer() as server:
        policy = ExternalPolicyAdapter(
            model_id="remote_policy_v1",
            adapter_type="http",
            config={"base_url": server.base_url, "timeout_s": 1.0},
        )
        action = policy.act({"contract_version": "obs.v1", "context": {"agent_id": "MODEL_HTTP"}})
        learn_result = policy.learn({"reward": {"step_reward": 0.2}})
        checkpoint_result = policy.save_checkpoint(str(tmp_path / "remote.json"))

    assert action["action_type"] == "target_weight"
    assert action["target"]["account_id"] == "MODEL_HTTP"
    assert action["meta"]["model_id"] == "remote_policy_v1"
    assert action["meta"]["adapter_type"] == "http"
    assert action["meta"]["remote"] is True
    assert learn_result["loss"] == 0.456
    assert checkpoint_result["remote_path"].endswith("remote.json")
    assert [item["path"] for item in _PolicyHandler.requests] == ["/act", "/learn", "/checkpoint"]


def test_runtime_model_agent_runs_registered_http_policy(tmp_path):
    with _PolicyServer() as server:
        registry = ModelRegistryService(session_factory=None, registry_path=tmp_path / "policies.json")
        registry.register_external_policy(
            "remote_runtime_v1",
            adapter_type="http",
            config={"base_url": server.base_url, "timeout_s": 1.0},
        )
        gateway = _Gateway()
        agent = RuntimeModelAgent(
            agent_id="MODEL_HTTP",
            model_id="remote_runtime_v1",
            runtime_gateway=gateway,
            registry=registry,
            persist_transitions=False,
        )
        transition = agent.step_once()

    assert transition["action"]["meta"]["adapter_type"] == "http"
    assert transition["execution_result"]["status"] == "EXECUTED"
    assert gateway.orders[0]["account_id"] == "MODEL_HTTP"


def test_http_policy_adapter_falls_back_to_hold_on_remote_error():
    policy = ExternalPolicyAdapter(
        model_id="remote_down_v1",
        adapter_type="http",
        config={"endpoint": "http://127.0.0.1:1/act", "timeout_s": 0.1},
    )

    action = policy.act({"contract_version": "obs.v1", "context": {"agent_id": "MODEL_DOWN"}})

    assert action["action_type"] == "hold"
    assert action["target"]["account_id"] == "MODEL_DOWN"
    assert action["meta"]["fallback"] == "hold"
