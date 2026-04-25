from app.services.agent_service import AgentService


class _RuntimeBindingGateway:
    def __init__(self):
        self.current_run_id = None
        self.rows = [
            {
                "agent_name": "mean_revert001",
                "agent_type": "RETAIL",
                "account_id": "mean_revert001",
                "meta": {
                    "strategy": "mean_revert",
                    "initial_cash": 100000.0,
                },
            },
            {
                "agent_name": "momentum_chase001",
                "agent_type": "RETAIL",
                "account_id": "momentum_chase001",
                "meta": {
                    "strategy": "momentum_chase",
                    "initial_cash": 100000.0,
                },
            },
        ]
        self.meta_updates = []

    def list_agent_bindings(self, *, include_all_runs=False):
        self.include_all_runs = include_all_runs
        return list(self.rows)

    def update_agent_binding_meta(self, agent_id: str, **updates):
        self.meta_updates.append((agent_id, dict(updates)))
        for row in self.rows:
            if row.get("agent_name") == agent_id:
                meta = dict(row.get("meta") or {})
                meta.update(updates)
                row["meta"] = meta
                break

    def get_current_run_id(self):
        return self.current_run_id


def test_agent_service_hydrates_agents_from_runtime_bindings():
    gateway = _RuntimeBindingGateway()
    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    agents = svc.list_agents()

    assert gateway.include_all_runs is True
    assert [agent.agent_id for agent in agents] == ["mean_revert001", "momentum_chase001"]
    assert [agent.strategy for agent in agents] == ["mean_revert", "momentum_chase"]
    assert all(agent.status == "STOPPED" for agent in agents)


def test_agent_service_runtime_hydration_preserves_live_status_fields():
    gateway = _RuntimeBindingGateway()
    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    svc.list_agents()
    svc._apply_runtime_state(
        "mean_revert001",
        status="RUNNING",
        heartbeat_ms=1234567890,
        start_time_ms=1234567000,
    )

    hydrated = svc.get("mean_revert001")

    assert hydrated is not None
    assert hydrated.status == "RUNNING"
    assert hydrated.last_heartbeat == 1234567890
    assert hydrated.start_time == 1234567000
    assert hydrated.strategy == "mean_revert"
    assert gateway.meta_updates[-1] == (
        "mean_revert001",
        {
            "status": "RUNNING",
            "start_time": 1234567000,
            "last_heartbeat": 1234567890,
        },
    )


def test_agent_service_recovers_persisted_runtime_status_from_binding_meta():
    gateway = _RuntimeBindingGateway()
    gateway.rows[0]["meta"].update(
        {
            "status": "PAUSED",
            "start_time": 2234567000,
            "last_heartbeat": 2234567890,
            "params_version": 7,
        }
    )

    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    hydrated = svc.get("mean_revert001")

    assert hydrated is not None
    assert hydrated.status == "PAUSED"
    assert hydrated.start_time == 2234567000
    assert hydrated.last_heartbeat == 2234567890
    assert hydrated.params_version == 7


def test_agent_service_restores_previous_run_agents_as_stopped():
    gateway = _RuntimeBindingGateway()
    gateway.current_run_id = "RUN-CURRENT"
    gateway.rows[0]["run_id"] = "RUN-OLD"
    gateway.rows[0]["meta"].update(
        {
            "run_id": "RUN-OLD",
            "status": "RUNNING",
            "start_time": 2234567000,
            "last_heartbeat": 2234567890,
        }
    )

    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    hydrated = svc.get("mean_revert001")

    assert hydrated is not None
    assert hydrated.status == "STOPPED"
    assert hydrated.start_time is None
    assert hydrated.last_heartbeat is None


def test_agent_service_persists_params_version_to_runtime_meta():
    gateway = _RuntimeBindingGateway()
    svc = AgentService(
        retail_agent_factory=lambda **_kwargs: None,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    svc.list_agents()
    updated = svc.update_params_version("mean_revert001", 9)

    assert updated.params_version == 9
    assert gateway.meta_updates[-1] == ("mean_revert001", {"params_version": 9})
    assert gateway.rows[0]["meta"]["params_version"] == 9


def test_agent_service_rehydrates_runtime_retail_executor_before_start():
    gateway = _RuntimeBindingGateway()
    created = {}

    class _FakeRuntimeRetail:
        def __init__(self, agent_id: str):
            self.agent_id = agent_id
            self.start_calls = 0

        def start(self):
            self.start_calls += 1

        def pause(self):
            return None

        def stop(self):
            return None

    def _factory(**kwargs):
        agent_id = kwargs["agent_id"]
        agent = _FakeRuntimeRetail(agent_id)
        created[agent_id] = agent
        return agent

    svc = AgentService(
        retail_agent_factory=_factory,
        account_bootstrapper=lambda *_args, **_kwargs: None,
        runtime_gateway=gateway,
    )

    svc.control("mean_revert001", "start")

    assert "mean_revert001" in created
    assert created["mean_revert001"].start_calls == 1
