import random

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_training import ModelCheckpoint, ModelLineage
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService
from app.services.model_checkpoint_service import ModelCheckpointService
from app.services.model_population_service import ModelPopulationService, PopulationEvolutionConfig


def _seed_episode_results(session, episode_id="episode-pbt"):
    service = TrainingEpisodeService(session)
    service.create_episode(episode_id=episode_id, run_id="run-pbt", generation=4)
    specs = [
        ("MODEL_TOP", "random_weight_v1", 103_000.0, 0.03),
        ("MODEL_MID", "hold_model_v1", 101_000.0, 0.01),
        ("MODEL_LOW", "hold_model_v1", 98_000.0, -0.02),
    ]
    for agent_id, model_id, equity, reward in specs:
        acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id=model_id)
        acc.apply_step(
            account={"equity": equity},
            action={"action_type": "hold"},
            execution_result={},
            reward={"step_reward": reward},
        )
        service.upsert_result(acc, episode_id=episode_id, generation=4)
    service.rank_episode(episode_id)


def test_checkpoint_service_saves_hall_of_fame_and_lineage():
    models_init.init_models()
    session = SessionLocal()
    try:
        service = ModelCheckpointService(session)
        checkpoint = service.save_checkpoint(
            model_id="random_weight_v1",
            agent_id="MODEL_TOP",
            generation=4,
            episode_id="episode-x",
            score=1.23,
            meta={"rank": 1},
            hall_of_fame=True,
        )
        lineage = service.record_lineage(
            child_model_id="random_weight_v1.gen5.MODEL_LOW",
            child_agent_id="MODEL_LOW",
            parent_model_id="random_weight_v1",
            parent_checkpoint_id=checkpoint.checkpoint_id,
            generation=5,
            mutation={"learning_rate": 0.01},
            episode_id="episode-x",
        )
        session.commit()

        hof = service.list_hall_of_fame()
        chain = service.get_lineage(lineage.child_model_id)
        assert hof[0]["checkpoint_id"] == checkpoint.checkpoint_id
        assert hof[0]["meta"]["rank"] == 1
        assert chain[0]["parent_checkpoint_id"] == checkpoint.checkpoint_id
        assert chain[0]["mutation"]["learning_rate"] == 0.01
    finally:
        session.close()


def test_population_service_evolves_bottom_models_from_episode_winner():
    models_init.init_models()
    session = SessionLocal()
    try:
        _seed_episode_results(session)
        service = ModelPopulationService(session, rng=random.Random(7))
        result = service.evolve_from_episode(
            "episode-pbt",
            config=PopulationEvolutionConfig(top_fraction=0.34, bottom_fraction=0.34, mutation_scale=0.02),
        )
        session.commit()

        checkpoints = session.query(ModelCheckpoint).all()
        lineage = session.query(ModelLineage).all()
        assert result["winners"] == ["MODEL_TOP"]
        assert result["losers"] == ["MODEL_LOW"]
        assert len(checkpoints) == 1
        assert checkpoints[0].is_hall_of_fame == 1
        assert len(lineage) == 1
        assert lineage[0].child_agent_id == "MODEL_LOW"
        assert lineage[0].parent_model_id == "random_weight_v1"
        assert result["hall_of_fame"][0]["agent_id"] == "MODEL_TOP"
    finally:
        session.close()
