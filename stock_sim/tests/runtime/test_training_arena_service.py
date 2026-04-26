from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService
from app.services.agent_service import AgentService
from app.services.training_arena_service import ArenaModelSpec, TrainingArenaConfig, TrainingArenaService


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


def test_training_arena_start_creates_episode_and_model_agents():
    models_init.init_models()
    svc = _agent_service()
    arena = TrainingArenaService(agent_service=svc)

    created = arena.create_arena(
        TrainingArenaConfig(
            arena_id="arena-basic",
            model_specs=[
                ArenaModelSpec(agent_id="MODEL_A", model_id="hold_model_v1"),
                ArenaModelSpec(agent_id="MODEL_B", model_id="random_weight_v1"),
            ],
            symbols=["001", "002"],
            generation=3,
        )
    )
    started = arena.start_arena("arena-basic", episode_id="episode-basic")

    session = SessionLocal()
    try:
        episode = TrainingEpisodeService(session).get_episode_summary("episode-basic")["episode"]
        agents = {agent.agent_id: agent for agent in svc.list_agents()}

        assert created["status"] == "READY"
        assert started["status"] == "RUNNING"
        assert started["model_agent_ids"] == ["MODEL_A", "MODEL_B"]
        assert episode["arena_id"] == "arena-basic"
        assert episode["generation"] == 3
        assert agents["MODEL_A"].episode_id == "episode-basic"
        assert agents["MODEL_A"].status == "RUNNING"
    finally:
        session.close()


def test_training_arena_evaluate_ranks_episode_results_and_stops():
    models_init.init_models()
    svc = _agent_service()
    arena = TrainingArenaService(agent_service=svc)
    arena.create_arena(
        {
            "arena_id": "arena-eval",
            "model_specs": [
                {"agent_id": "MODEL_TOP", "model_id": "random_weight_v1"},
                {"agent_id": "MODEL_LOW", "model_id": "hold_model_v1"},
            ],
            "generation": 1,
        }
    )
    arena.start_arena("arena-eval", episode_id="episode-eval")

    session = SessionLocal()
    try:
        service = TrainingEpisodeService(session)
        top = EpisodeAgentAccumulator(agent_id="MODEL_TOP", model_id="random_weight_v1")
        top.apply_step(account={"equity": 101_000.0}, action={"action_type": "hold"}, execution_result={}, reward={"step_reward": 0.02})
        low = EpisodeAgentAccumulator(agent_id="MODEL_LOW", model_id="hold_model_v1")
        low.apply_step(account={"equity": 100_000.0}, action={"action_type": "hold"}, execution_result={}, reward={"step_reward": 0.0})
        service.upsert_result(top, episode_id="episode-eval", generation=1)
        service.upsert_result(low, episode_id="episode-eval", generation=1)
        session.commit()
    finally:
        session.close()

    evaluated = arena.evaluate_arena("arena-eval")

    assert evaluated["status"] == "STOPPED"
    assert evaluated["last_summary"]["episode"]["status"] == "completed"
    assert [row["agent_id"] for row in evaluated["last_summary"]["results"]] == ["MODEL_TOP", "MODEL_LOW"]
    assert [row["rank"] for row in evaluated["last_summary"]["results"]] == [1, 2]
