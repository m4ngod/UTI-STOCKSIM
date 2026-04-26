from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService

from app.panels import list_panels, register_builtin_panels, reset_registry
from app.panels.arena.panel import ArenaPanel
from app.services.agent_service import AgentService
from app.services.training_arena_service import ArenaModelSpec, TrainingArenaService
from app.ui.adapters.arena_adapter import ArenaPanelAdapter


class _FakeRuntimeAgent:
    def __init__(self, **_kwargs):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def pause(self):
        self.started = False

    def stop(self):
        self.stopped = True
        self.started = False


def _agent_service():
    return AgentService(
        retail_agent_factory=lambda **kwargs: _FakeRuntimeAgent(**kwargs),
        model_agent_factory=lambda **kwargs: _FakeRuntimeAgent(**kwargs),
        account_bootstrapper=lambda *_args, **_kwargs: None,
    )


def test_builtin_panel_registry_includes_arena():
    reset_registry()
    register_builtin_panels()

    names = {row["name"] for row in list_panels()}

    assert "arena" in names


def test_arena_panel_create_start_evaluate_view():
    models_init.init_models()
    agent_service = _agent_service()
    arena_service = TrainingArenaService(agent_service=agent_service)
    panel = ArenaPanel(arena_service)

    created = panel.create_arena(
        arena_id="arena-panel",
        model_specs=[
            ArenaModelSpec(agent_id="MODEL_PANEL_A", model_id="hold_model_v1"),
            ArenaModelSpec(agent_id="MODEL_PANEL_B", model_id="random_weight_v1"),
        ],
        retail_count=0,
        symbols=["001", "002"],
        generation=5,
    )
    view = panel.get_view()

    assert created["status"] == "READY"
    assert view["arena"]["selected"] == "arena-panel"
    assert view["controls"]["can_start"] is True
    assert view["arena"]["items"][0]["symbols"] == ["001", "002"]

    started = panel.start_arena("arena-panel", episode_id="episode-panel")
    assert started["status"] == "RUNNING"
    assert view_agent_ids(agent_service) == {"MODEL_PANEL_A", "MODEL_PANEL_B"}

    session = SessionLocal()
    try:
        service = TrainingEpisodeService(session)
        top = EpisodeAgentAccumulator(agent_id="MODEL_PANEL_B", model_id="random_weight_v1")
        top.apply_step(
            account={"equity": 102_000.0},
            action={"action_type": "hold"},
            execution_result={},
            reward={"step_reward": 0.03},
        )
        low = EpisodeAgentAccumulator(agent_id="MODEL_PANEL_A", model_id="hold_model_v1")
        low.apply_step(
            account={"equity": 100_000.0},
            action={"action_type": "hold"},
            execution_result={},
            reward={"step_reward": 0.0},
        )
        service.upsert_result(top, episode_id="episode-panel", generation=5)
        service.upsert_result(low, episode_id="episode-panel", generation=5)
        session.commit()
    finally:
        session.close()

    evaluated = panel.evaluate_arena("arena-panel")
    view = panel.get_view()

    assert evaluated["status"] == "STOPPED"
    assert view["leaderboard"][0]["agent_id"] == "MODEL_PANEL_B"
    assert view["leaderboard"][0]["rank"] == 1
    assert view["summary"]["episode"]["status"] == "completed"


def test_arena_adapter_headless_renders_rows_and_controls():
    panel = ArenaPanel(TrainingArenaService(agent_service=_agent_service(), session_factory=None))
    panel.create_arena(arena_id="arena-adapter", retail_count=0)
    adapter = ArenaPanelAdapter().bind(panel)

    adapter.widget()
    adapter.refresh()

    assert adapter._arena_table.rowCount() == 1
    assert adapter._arena_table.item(0, 0).text() == "arena-adapter"
    assert adapter._start_btn._enabled is True


def view_agent_ids(agent_service):
    return {agent.agent_id for agent in agent_service.list_agents()}
