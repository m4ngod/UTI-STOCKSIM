from app.controllers.agent_controller import AgentController
from app.panels.agents.panel import AgentsPanel
from app.services.agent_service import AgentService, BatchCreateConfig


class _FakeRuntimeAgent:
    def __init__(self, **_kwargs):
        self.started = False

    def start(self):
        self.started = True

    def pause(self):
        self.started = False

    def stop(self):
        self.started = False


def _panel():
    svc = AgentService(
        retail_agent_factory=lambda **kwargs: _FakeRuntimeAgent(**kwargs),
        model_agent_factory=lambda **kwargs: _FakeRuntimeAgent(**kwargs),
        account_bootstrapper=lambda *_args, **_kwargs: None,
    )
    ctl = AgentController(svc)
    return AgentsPanel(ctl, svc), ctl, svc


def test_agents_panel_filters_retail_and_model_views():
    panel, ctl, svc = _panel()
    svc.batch_create_retail(BatchCreateConfig(count=2, agent_type="Retail", strategies=["mean_revert", "noise"]))
    ctl.create_model_agent(agent_id="MODEL_ALPHA", model_id="hold_model_v1", mode="collect_only")

    view = panel.get_view()
    assert view["agents"]["total"] == 3
    assert view["agents"]["unfiltered_total"] == 3

    panel.set_agent_type_filter("Retail")
    retail_view = panel.get_view()
    assert retail_view["agents"]["filter"] == "Retail"
    assert [item["type"] for item in retail_view["agents"]["items"]] == ["Retail", "Retail"]

    panel.set_agent_type_filter("Model")
    model_view = panel.get_view()
    assert model_view["agents"]["filter"] == "Model"
    assert len(model_view["agents"]["items"]) == 1
    assert model_view["agents"]["items"][0]["family_model"] == "hold_model_v1"
    assert model_view["agents"]["items"][0]["mode"] == "collect_only"


def test_agent_controller_can_create_and_start_model_agent():
    _panel_obj, ctl, svc = _panel()
    meta = ctl.create_model_agent(agent_id="MODEL_BETA", model_id="random_weight_v1")

    assert meta.type == "Model"
    assert meta.model_id == "random_weight_v1"

    started = ctl.control("MODEL_BETA", "start")
    assert started.status == "RUNNING"
    assert svc.get("MODEL_BETA").last_heartbeat is not None
