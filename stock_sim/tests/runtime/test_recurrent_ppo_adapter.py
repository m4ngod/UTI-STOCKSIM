import json

from app.services.model_registry_service import ModelRegistryService
from app.services.runtime_model_agent import RuntimeModelAgent
from rl.model_adapters.ppo_recurrent_adapter import RecurrentPPOPolicyAdapter


class _Gateway:
    def __init__(self):
        self.orders = []

    def list_instruments(self, *, active_only=True):
        return [
            {"symbol": "001", "initial_price": 10.0},
            {"symbol": "002", "initial_price": 20.0},
        ]

    def get_recent_trades(self, symbol, *, limit=1):
        return [{"price": 10.0 if symbol == "001" else 20.0, "qty": 1}]

    def get_bars(self, symbol, timeframe, *, limit):
        close = 10.0 if symbol == "001" else 20.0
        return [{"close": close * 0.99}, {"close": close}]

    def get_account_snapshot(self, account_id):
        return {"account_id": account_id, "cash": 100_000.0, "equity": 100_000.0, "positions": []}

    def get_current_run_id(self):
        return "run-ppo-lstm"

    def get_current_sim_day(self):
        return 3

    def clock_snapshot(self):
        return {"running": True}

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"ok": True, "order_id": f"order-{len(self.orders)}"}


def _observation():
    gateway = _Gateway()
    symbols = [row["symbol"] for row in gateway.list_instruments()]
    return {
        "contract_version": "obs.v1",
        "market": {
            "symbols": symbols,
            "snapshots": {symbol: {"recent_trades": gateway.get_recent_trades(symbol)} for symbol in symbols},
            "bars": {symbol: {"1d": gateway.get_bars(symbol, "1d", limit=8)} for symbol in symbols},
            "order_books": {},
        },
        "account": gateway.get_account_snapshot("MODEL_PPO"),
        "context": {
            "agent_id": "MODEL_PPO",
            "symbol_universe": symbols,
            "step_index": 0,
            "sim_day": 3,
            "clock_running": True,
        },
        "features": {},
    }


def test_registry_exposes_real_ppo_lstm_policy():
    registry = ModelRegistryService(session_factory=None, registry_path=None)

    policy = registry.create_policy("ppo_lstm_v1", seed=7)
    action = policy.act(_observation())

    assert "ppo_lstm_v1" in {spec.model_id for spec in registry.list_models()}
    assert action["action_type"] == "target_weight"
    assert action["meta"]["policy_type"] == "ppo_recurrent"
    assert action["payload"]["weights"]


def test_recurrent_ppo_policy_learns_and_saves_checkpoint(tmp_path):
    policy = RecurrentPPOPolicyAdapter(
        model_id="ppo_lstm_test",
        config={
            "max_symbols": 2,
            "embed_dim": 8,
            "lstm_hidden": 16,
            "min_update_steps": 2,
            "deterministic": True,
            "device": "cpu",
        },
        seed=11,
    )
    observation = _observation()
    action = policy.act(observation)
    transition = {
        "observation": observation,
        "action": action,
        "execution_result": {"orders": [], "trades": []},
        "reward": {"step_reward": 0.01},
    }

    first = policy.learn(transition)
    second = policy.learn(transition)
    checkpoint = policy.save_checkpoint(str(tmp_path / "ppo_lstm_test.json"))
    manifest = json.loads((tmp_path / "ppo_lstm_test.json").read_text(encoding="utf-8"))

    assert first["reason"] == "BUFFER_NOT_READY"
    assert second["ok"] is True
    assert second["update_count"] == 1
    assert checkpoint["ok"] is True
    assert (tmp_path / "ppo_lstm_test.pt").exists()
    assert manifest["schema"] == "stock_sim.ppo_recurrent_checkpoint_manifest.v1"


def test_runtime_model_agent_runs_ppo_lstm_and_online_train():
    gateway = _Gateway()
    policy = RecurrentPPOPolicyAdapter(
        model_id="ppo_lstm_runtime",
        config={
            "max_symbols": 2,
            "embed_dim": 8,
            "lstm_hidden": 16,
            "min_update_steps": 1,
            "deterministic": True,
            "device": "cpu",
        },
        seed=13,
    )
    agent = RuntimeModelAgent(
        agent_id="MODEL_PPO",
        model_id="ppo_lstm_runtime",
        mode="online_train",
        runtime_gateway=gateway,
        policy=policy,
        persist_transitions=False,
    )

    transition = agent.step_once()

    assert transition["action"]["meta"]["policy_type"] == "ppo_recurrent"
    assert transition["execution_result"]["status"] == "EXECUTED"
    assert transition["learn_result"]["ok"] is True
    assert gateway.orders
