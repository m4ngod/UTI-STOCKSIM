from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_training import ModelEpisodeResult, ModelTransition, TrainingEpisode
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService
from app.services.runtime_model_agent import RuntimeModelAgent


class _FakeGateway:
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
        return "run-training-test"

    def get_current_sim_day(self):
        return 3

    def clock_snapshot(self):
        return {"running": True}

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"ok": True, "order_id": f"order-{len(self.orders)}"}


def test_training_episode_service_ranks_model_results():
    models_init.init_models()
    session = SessionLocal()
    try:
        service = TrainingEpisodeService(session)
        service.create_episode(episode_id="episode-rank", run_id="run1", generation=2)

        strong = EpisodeAgentAccumulator(agent_id="MODEL_A", model_id="random_weight_v1")
        strong.apply_step(
            account={"equity": 101_000.0},
            action={"action_type": "hold"},
            execution_result={},
            reward={"step_reward": 0.02},
        )
        weak = EpisodeAgentAccumulator(agent_id="MODEL_B", model_id="hold_model_v1")
        weak.apply_step(
            account={"equity": 99_000.0},
            action={"action_type": "hold"},
            execution_result={},
            reward={"step_reward": -0.01},
        )

        service.upsert_result(strong, episode_id="episode-rank", generation=2)
        service.upsert_result(weak, episode_id="episode-rank", generation=2)
        ranked = service.rank_episode("episode-rank")
        session.commit()

        assert [row.agent_id for row in ranked] == ["MODEL_A", "MODEL_B"]
        assert [row.rank for row in ranked] == [1, 2]
    finally:
        session.close()


def test_runtime_model_agent_persists_transition_and_result():
    models_init.init_models()
    metrics = []
    agent = RuntimeModelAgent(
        agent_id="MODEL_EP",
        model_id="hold_model_v1",
        runtime_gateway=_FakeGateway(),
        episode_id="episode-runtime",
        arena_id="arena-runtime",
        generation=1,
        metrics_callback=lambda agent_id, payload: metrics.append((agent_id, payload)),
    )

    result = agent.step_once()

    session = SessionLocal()
    try:
        episode = session.get(TrainingEpisode, "episode-runtime")
        transitions = session.query(ModelTransition).filter(ModelTransition.episode_id == "episode-runtime").all()
        results = session.query(ModelEpisodeResult).filter(ModelEpisodeResult.episode_id == "episode-runtime").all()

        assert result["action"]["action_type"] == "hold"
        assert episode is not None
        assert episode.run_id == "run-training-test"
        assert len(transitions) == 1
        assert transitions[0].agent_id == "MODEL_EP"
        assert len(results) == 1
        assert results[0].rank == 1
        assert metrics[0][0] == "MODEL_EP"
        assert metrics[0][1]["last_action"] == "hold"
    finally:
        session.close()
