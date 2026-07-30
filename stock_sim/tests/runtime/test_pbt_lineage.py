import json
import random

import numpy as np

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_training import ModelCheckpoint, ModelLineage
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService
from app.services.agent_service import AgentService
from app.services.model_checkpoint_service import ModelCheckpointService
from app.services.model_population_service import (
    ModelPopulationService,
    PopulationEvolutionConfig,
    _strict_parent_gate,
    _strict_parent_gate_passes,
)
from app.services.model_registry_service import CheckpointBackedModel, ModelRegistryService
from app.services.runtime_model_agent import RuntimeModelAgent


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


def test_checkpoint_service_writes_json_artifact(tmp_path):
    models_init.init_models()
    session = SessionLocal()
    try:
        service = ModelCheckpointService(session, checkpoint_root=tmp_path)
        checkpoint = service.save_checkpoint(
            model_id="random_weight_v1",
            agent_id="MODEL_TOP",
            generation=4,
            episode_id="episode-artifact",
            score=1.23,
            meta={"rank": 1},
            artifact={"weights_ref": "dummy-policy"},
            hall_of_fame=True,
        )
        session.commit()

        payload = json.loads((tmp_path / "random_weight_v1" / f"{checkpoint.checkpoint_id}.json").read_text(encoding="utf-8"))
        assert payload["schema"] == "stock_sim.model_checkpoint.v1"
        assert payload["checkpoint_id"] == checkpoint.checkpoint_id
        assert payload["artifact"]["weights_ref"] == "dummy-policy"
        assert json.loads(checkpoint.meta_json)["artifact_written"] is True
    finally:
        session.close()


def test_checkpoint_service_writes_and_loads_tensor_checkpoint(tmp_path):
    models_init.init_models()
    session = SessionLocal()
    try:
        service = ModelCheckpointService(session, checkpoint_root=tmp_path)
        checkpoint = service.save_tensor_checkpoint(
            model_id="ppo_lstm_v1",
            agent_id="MODEL_TOP",
            generation=6,
            episode_id="episode-tensor",
            score=2.5,
            meta={"rank": 1, "framework": "numpy"},
            tensors={
                "encoder.weight": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
                "policy.bias": np.array([0.1, -0.1], dtype=np.float32),
            },
            hall_of_fame=True,
        )
        session.commit()

        manifest_path = tmp_path / "ppo_lstm_v1" / f"{checkpoint.checkpoint_id}.json"
        tensor_path = tmp_path / "ppo_lstm_v1" / f"{checkpoint.checkpoint_id}.npz"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        loaded = service.load_tensor_checkpoint(checkpoint.checkpoint_id)

        assert manifest["schema"] == "stock_sim.tensor_checkpoint.v1"
        assert manifest["tensor_file"] == tensor_path.name
        assert manifest["tensors"]["encoder.weight"]["shape"] == [2, 2]
        assert tensor_path.exists()
        assert np.allclose(loaded["tensors"]["encoder.weight"], [[1.0, 2.0], [3.0, 4.0]])
        assert json.loads(checkpoint.meta_json)["tensor_count"] == 2
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


def test_population_service_requires_active_parent_when_configured():
    models_init.init_models()
    session = SessionLocal()
    try:
        episode_id = "episode-pbt-active-parent"
        service = TrainingEpisodeService(session)
        service.create_episode(episode_id=episode_id, run_id="run-pbt", generation=1)
        specs = [
            ("MODEL_IDLE_TOP", "ppo_lstm_v1", 0.10, {}),
            (
                "MODEL_ACTIVE_MID",
                "ppo_lstm_v1",
                0.02,
                {
                    "orders": [
                        {
                            "qty": 100,
                            "price": 10.0,
                            "result": {"ok": True, "status": "FILLED", "filled": 100},
                        }
                    ],
                    "trades": [],
                },
            ),
            ("MODEL_IDLE_LOW", "ppo_lstm_v1", -0.05, {}),
        ]
        for agent_id, model_id, reward, execution_result in specs:
            acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id=model_id)
            acc.apply_step(
                account={"equity": 100_000.0},
                action={"action_type": "target_weight"},
                execution_result=execution_result,
                reward={"step_reward": reward},
            )
            service.upsert_result(acc, episode_id=episode_id, generation=1)
        service.rank_episode(episode_id)

        population = ModelPopulationService(session, rng=random.Random(3))
        result = population.evolve_from_episode(
            episode_id,
            generation=1,
            config=PopulationEvolutionConfig(
                top_fraction=0.34,
                bottom_fraction=0.34,
                min_parent_trade_count=1,
            ),
        )
        session.commit()

        assert result["winners"] == ["MODEL_ACTIVE_MID"]
        assert result["parent_eligible_agents"] == ["MODEL_ACTIVE_MID"]
        assert result["losers"] == ["MODEL_IDLE_LOW"]
        assert result["lineage"][0]["parent_model_id"] == "ppo_lstm_v1"
    finally:
        session.close()


def test_population_service_strict_parent_gate_is_opt_in():
    models_init.init_models()
    session = SessionLocal()
    try:
        episode_id = "episode-pbt-strict-parent"
        service = TrainingEpisodeService(session)
        service.create_episode(episode_id=episode_id, run_id="run-pbt-strict", generation=1)
        for agent_id, reward in [
            ("MODEL_TOP", 0.10),
            ("MODEL_LOW", -0.05),
        ]:
            acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id="ppo_lstm_v1")
            acc.apply_step(
                account={"equity": 100_000.0},
                action={"action_type": "target_weight"},
                execution_result={
                    "orders": [
                        {
                            "qty": 100,
                            "price": 10.0,
                            "result": {"ok": True, "status": "FILLED", "filled": 100},
                        }
                    ],
                    "trades": [],
                },
                reward={"step_reward": reward},
            )
            service.upsert_result(acc, episode_id=episode_id, generation=1)
        service.rank_episode(episode_id)

        population = ModelPopulationService(session, rng=random.Random(5))
        default_result = population.evolve_from_episode(
            episode_id,
            generation=1,
            config=PopulationEvolutionConfig(
                top_fraction=0.5,
                bottom_fraction=0.5,
                min_parent_trade_count=1,
            ),
        )
        strict_result = population.evolve_from_episode(
            episode_id,
            generation=1,
            config=PopulationEvolutionConfig(
                top_fraction=0.5,
                bottom_fraction=0.5,
                min_parent_trade_count=1,
                strict_parent_eligibility=True,
                research_acceptance={
                    "is_research_accepted": False,
                    "strict_parent_eligibility_allowed": False,
                    "acceptance_lock": {
                        "status": "locked",
                        "blocking_sections": {
                            "hidden_evaluation": "not_available",
                            "exploit_detector": "partial",
                        },
                        "reason": "required_sections_not_complete",
                    },
                    "required_sections": {
                        "baseline_suite": "complete",
                        "hidden_evaluation": "not_available",
                        "exploit_detector": "partial",
                    },
                },
            ),
        )

        assert default_result["winners"] == ["MODEL_TOP"]
        assert default_result["strict_parent_gate"]["enabled"] is False
        assert default_result["strict_parent_gate"]["passes"] is True
        assert default_result["strict_parent_gate"]["reason"] == "strict_parent_gate_disabled"
        assert default_result["strict_parent_gate"]["blocking_reasons"] == []
        assert strict_result["skipped"] is True
        assert strict_result["reason"] == "no_parent_eligible_models"
        assert strict_result["parent_eligible_agents"] == []
        assert strict_result["strict_parent_gate"]["enabled"] is True
        assert strict_result["strict_parent_gate"]["passes"] is False
        assert strict_result["strict_parent_gate"]["reason"] == "strict_parent_gate_blocked"
        assert strict_result["strict_parent_gate"]["strict_parent_eligibility_allowed"] is False
        assert strict_result["strict_parent_gate"]["acceptance_lock"]["status"] == "locked"
        assert strict_result["strict_parent_gate"]["acceptance_lock"]["blocking_sections"] == {
            "hidden_evaluation": "not_available",
            "exploit_detector": "partial",
        }
        assert strict_result["strict_parent_gate"]["blocking_reasons"] == [
            "research_acceptance_not_true",
            "strict_parent_eligibility_not_allowed",
            "acceptance_lock_not_open",
            "acceptance_lock_has_blocking_sections",
            "hidden_evaluation_not_complete",
            "exploit_detector_not_complete",
        ]
        assert strict_result["strict_parent_gate"]["required_sections"]["hidden_evaluation"] == "not_available"
    finally:
        session.close()


def test_population_strict_parent_gate_requires_open_acceptance_lock():
    locked_cfg = PopulationEvolutionConfig(
        strict_parent_eligibility=True,
        research_acceptance={
            "is_research_accepted": True,
            "strict_parent_eligibility_allowed": True,
            "acceptance_lock": {
                "status": "locked",
                "blocking_sections": {"hidden_evaluation": "not_available"},
                "reason": "required_sections_not_complete",
            },
            "required_sections": {
                "baseline_suite": "complete",
                "hidden_evaluation": "complete",
                "exploit_detector": "complete",
            },
        },
    )
    allowed_cfg = PopulationEvolutionConfig(
        strict_parent_eligibility=True,
        research_acceptance={
            "is_research_accepted": True,
            "strict_parent_eligibility_allowed": True,
            "acceptance_lock": {
                "status": "open",
                "blocking_sections": {},
                "reason": "required_sections_complete",
            },
            "required_sections": {
                "baseline_suite": "complete",
                "hidden_evaluation": "complete",
                "exploit_detector": "complete",
            },
        },
    )

    assert _strict_parent_gate_passes(locked_cfg) is False
    assert _strict_parent_gate(locked_cfg)["reason"] == "strict_parent_gate_blocked"
    assert _strict_parent_gate(locked_cfg)["blocking_reasons"] == [
        "acceptance_lock_not_open",
        "acceptance_lock_has_blocking_sections",
    ]
    assert _strict_parent_gate_passes(allowed_cfg) is True
    assert _strict_parent_gate(allowed_cfg)["reason"] == "strict_parent_gate_passed"
    assert _strict_parent_gate(allowed_cfg)["blocking_reasons"] == []
    assert _strict_parent_gate(PopulationEvolutionConfig())["reason"] == "strict_parent_gate_disabled"


class _FakeRuntimeGateway:
    def __init__(self):
        self.meta_updates = {}

    def list_agent_bindings(self, include_all_runs=True):
        return []

    def update_agent_binding_meta(self, agent_id, **updates):
        self.meta_updates.setdefault(agent_id, {}).update(updates)


class _PolicyRuntimeGateway:
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
        return "run-policy-test"

    def get_current_sim_day(self):
        return 5

    def clock_snapshot(self):
        return {"running": True}

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"ok": True, "order_id": f"order-{len(self.orders)}"}


def test_population_service_applies_inheritance_to_model_agent():
    models_init.init_models()
    session = SessionLocal()
    try:
        episode_id = "episode-pbt-apply"
        _seed_episode_results(session, episode_id=episode_id)
        gateway = _FakeRuntimeGateway()
        agent_service = AgentService(
            account_bootstrapper=lambda account_id, initial_cash: None,
            runtime_gateway=gateway,
        )
        agent_service.create_model_agent(agent_id="MODEL_TOP", model_id="random_weight_v1")
        agent_service.create_model_agent(agent_id="MODEL_LOW", model_id="hold_model_v1")

        service = ModelPopulationService(session, agent_service=agent_service, rng=random.Random(7))
        result = service.evolve_from_episode(
            episode_id,
            config=PopulationEvolutionConfig(
                top_fraction=0.34,
                bottom_fraction=0.34,
                mutation_scale=0.02,
                apply_to_agents=True,
            ),
        )
        session.commit()

        low = agent_service.get("MODEL_LOW")
        assert low is not None
        assert low.model_id == result["lineage"][0]["child_model_id"]
        assert low.params_version == 1
        assert low.last_action == "inheritance"
        assert result["applied_agents"][0]["agent_id"] == "MODEL_LOW"
        assert gateway.meta_updates["MODEL_LOW"]["parent_checkpoint_id"] == result["lineage"][0]["parent_checkpoint_id"]
    finally:
        session.close()


def test_registry_loads_checkpoint_backed_child_policy(tmp_path):
    models_init.init_models()
    session = SessionLocal()
    try:
        episode_id = "episode-pbt-loader"
        _seed_episode_results(session, episode_id=episode_id)
        checkpoint_service = ModelCheckpointService(session, checkpoint_root=tmp_path)
        population = ModelPopulationService(session, checkpoint_service=checkpoint_service, rng=random.Random(9))
        result = population.evolve_from_episode(
            episode_id,
            config=PopulationEvolutionConfig(top_fraction=0.34, bottom_fraction=0.34, mutation_scale=0.02),
        )
        session.commit()

        child_model_id = result["lineage"][0]["child_model_id"]
        registry = ModelRegistryService()
        specs = registry.list_models()
        policy = registry.create_policy(child_model_id, seed=13)
        action = policy.act(
            {
                "contract_version": "obs.v1",
                "context": {"agent_id": "MODEL_LOW", "symbol_universe": ["001"]},
            }
        )

        assert child_model_id in {spec.model_id for spec in specs}
        assert isinstance(policy, CheckpointBackedModel)
        assert action["action_type"] == "target_weight"
        assert action["meta"]["model_id"] == child_model_id
        assert action["meta"]["parent_model_id"] == "random_weight_v1"
        assert action["meta"]["checkpoint_id"] == result["lineage"][0]["parent_checkpoint_id"]
    finally:
        session.close()


def test_runtime_model_agent_can_run_checkpoint_backed_child(tmp_path):
    models_init.init_models()
    session = SessionLocal()
    try:
        episode_id = "episode-pbt-runtime-loader"
        _seed_episode_results(session, episode_id=episode_id)
        checkpoint_service = ModelCheckpointService(session, checkpoint_root=tmp_path)
        population = ModelPopulationService(session, checkpoint_service=checkpoint_service, rng=random.Random(11))
        result = population.evolve_from_episode(
            episode_id,
            config=PopulationEvolutionConfig(top_fraction=0.34, bottom_fraction=0.34, mutation_scale=0.02),
        )
        session.commit()

        gateway = _PolicyRuntimeGateway()
        agent = RuntimeModelAgent(
            agent_id="MODEL_LOW",
            model_id=result["lineage"][0]["child_model_id"],
            runtime_gateway=gateway,
            persist_transitions=False,
        )
        transition = agent.step_once()

        assert transition["action"]["meta"]["policy_type"] == "checkpoint_backed"
        assert transition["action"]["meta"]["parent_model_id"] == "random_weight_v1"
        assert transition["execution_result"]["status"] == "EXECUTED"
        assert gateway.orders
    finally:
        session.close()


def test_registry_falls_back_for_known_parent_child_id_without_lineage():
    registry = ModelRegistryService(session_factory=None)
    policy = registry.create_policy("random_weight_v1.gen99.MODEL_X", seed=17)

    action = policy.act(
        {
            "contract_version": "obs.v1",
            "context": {"agent_id": "MODEL_X", "symbol_universe": ["001"]},
        }
    )

    assert isinstance(policy, CheckpointBackedModel)
    assert action["action_type"] == "target_weight"
    assert action["meta"]["model_id"] == "random_weight_v1.gen99.MODEL_X"
    assert action["meta"]["parent_model_id"] == "random_weight_v1"
