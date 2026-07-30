from agents.retail_strategy import allocate_retail_strategies, cold_start_profile
from app.services.agent_service import AgentService, BatchCreateConfig
import threading
import time


class _FakeRuntimeRetailAgent:
    def __init__(self, *, agent_id, strategy, initial_cash, state_callback=None):
        self.agent_id = agent_id
        self.strategy = strategy
        self.initial_cash = initial_cash
        self._state_callback = state_callback
        self.actions = []

    def start(self):
        self.actions.append("start")
        if callable(self._state_callback):
            self._state_callback(self.agent_id, "RUNNING", 123456, 123000)

    def pause(self):
        self.actions.append("pause")
        if callable(self._state_callback):
            self._state_callback(self.agent_id, "PAUSED", 123556, 123000)

    def stop(self):
        self.actions.append("stop")
        if callable(self._state_callback):
            self._state_callback(self.agent_id, "STOPPED", None, 123000)


class _FakeRuntimeGateway:
    def __init__(self, bindings=None):
        self._bindings = list(bindings or [])

    def list_agent_bindings(self, include_all_runs=True):
        return list(self._bindings)

    def get_current_run_id(self):
        return "RUN-TEST"

    def update_agent_binding_meta(self, *_args, **_kwargs):
        return None


class _NoBindingRuntimeGateway:
    def list_agent_bindings(self):
        return []


def _build_service():
    return AgentService(
        retail_agent_factory=lambda **kwargs: _FakeRuntimeRetailAgent(**kwargs),
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=_NoBindingRuntimeGateway(),
    )


def test_allocate_retail_strategies_uses_explicit_list_round_robin():
    assigned = allocate_retail_strategies(5, ["mean_revert", "buy_the_dip"], seed=1)
    assert assigned == [
        "mean_revert",
        "buy_the_dip",
        "mean_revert",
        "buy_the_dip",
        "mean_revert",
    ]


def test_agent_service_assigns_visible_strategy_and_strategy_names_to_retail_agents():
    svc = _build_service()
    res = svc.batch_create_retail(
        BatchCreateConfig(
            count=2,
            agent_type="Retail",
            strategies=["mean_revert"],
        )
    )
    assert res["success_ids"] == ["mean_revert001", "mean_revert002"]
    assert res["strategies"] == ["mean_revert", "mean_revert"]

    agents = svc.list_agents()
    assert [agent.name for agent in agents] == ["mean_revert001", "mean_revert002"]
    assert [agent.strategy for agent in agents] == ["mean_revert", "mean_revert"]


def test_agent_service_advances_retail_counters_from_persisted_bindings():
    svc = AgentService(
        retail_agent_factory=lambda **kwargs: _FakeRuntimeRetailAgent(**kwargs),
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=_FakeRuntimeGateway(
            [
                {
                    "agent_name": "mean_revert017",
                    "agent_type": "RETAIL",
                    "account_id": "mean_revert017",
                    "run_id": "RUN-TEST",
                    "meta": {
                        "name": "mean_revert017",
                        "type": "Retail",
                        "strategy": "mean_revert",
                        "status": "STOPPED",
                    },
                }
            ]
        ),
    )

    svc.list_agents()
    res = svc.batch_create_retail(
        BatchCreateConfig(
            count=2,
            agent_type="Retail",
            strategies=["mean_revert"],
        )
    )

    assert res["success_ids"] == ["mean_revert018", "mean_revert019"]


def test_agent_service_respects_explicit_multi_strategy_batch_configuration():
    svc = _build_service()
    res = svc.batch_create_retail(
        BatchCreateConfig(
            count=3,
            agent_type="MultiStrategyRetail",
            name_prefix="msr",
            strategies=["mean_revert", "momentum_chase"],
        )
    )
    assert res["strategies"] == ["mean_revert", "momentum_chase", "mean_revert"]
    assert [agent.strategy for agent in svc.list_agents()] == ["mean_revert", "momentum_chase", "mean_revert"]


def test_agent_service_controls_runtime_retail_agents():
    svc = _build_service()
    svc.batch_create_retail(BatchCreateConfig(count=1, agent_type="Retail", strategies=["liquidity_noise"]))
    retail = svc.list_agents()[0]

    started = svc.control(retail.agent_id, "start")
    assert started.status == "RUNNING"
    assert started.last_heartbeat == 123456

    paused = svc.control(retail.agent_id, "pause")
    assert paused.status == "PAUSED"
    assert paused.last_heartbeat == 123556

    stopped = svc.control(retail.agent_id, "stop")
    assert stopped.status == "STOPPED"


def test_agent_service_stop_does_not_block_on_slow_runtime_agent():
    stop_started = threading.Event()
    stop_finished = threading.Event()

    class _SlowRuntimeRetailAgent(_FakeRuntimeRetailAgent):
        def stop(self):
            self.actions.append("stop")
            stop_started.set()
            time.sleep(0.25)
            if callable(self._state_callback):
                self._state_callback(self.agent_id, "STOPPED", None, 123000)
            stop_finished.set()

    svc = AgentService(
        retail_agent_factory=lambda **kwargs: _SlowRuntimeRetailAgent(**kwargs),
        account_bootstrapper=lambda *_args, **_kwargs: None,
    )
    svc.batch_create_retail(BatchCreateConfig(count=1, agent_type="Retail", strategies=["liquidity_noise"]))
    retail = svc.list_agents()[0]

    t0 = time.perf_counter()
    stopped = svc.control(retail.agent_id, "stop")
    elapsed = time.perf_counter() - t0

    assert stopped.status == "STOPPED"
    assert elapsed < 0.15
    assert stop_started.wait(0.2)
    assert stop_finished.wait(0.5)


def test_cold_start_profile_exposes_post_ipo_mix():
    profile = cold_start_profile()
    assert profile["mode"] == "post_ipo_cold_start"
    assert "liquidity_noise" in profile["strategy_mix"]
    assert "momentum_chase" in profile["strategy_mix"]
    assert "profit_taking" in profile["strategy_mix"]
    assert "profit_taking" in profile["bootstrap_template"]


def test_allocate_retail_strategies_uses_balanced_bootstrap_for_small_post_ipo_batches():
    assigned = allocate_retail_strategies(4, seed=1, mode="post_ipo_cold_start")
    assert assigned == [
        "mean_revert",
        "momentum_chase",
        "liquidity_noise",
        "buy_the_dip",
    ]
