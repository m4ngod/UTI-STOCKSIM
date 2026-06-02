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


class _FakeExperimentRunner:
    def __init__(self):
        self.configs = []

    def run(self, config):
        self.configs.append(config)
        return {
            "arena_id": config.arena_id or "arena-experiment-ui",
            "episode_id": config.episode_id or "episode-experiment-ui",
            "report_path": "output/arena_experiments/episode-experiment-ui.json",
            "episode": {
                "transition_count": 12,
                "results": [
                    {
                        "rank": 1,
                        "agent_id": "MODEL_PPO_LSTM_V1",
                        "model_id": "ppo_lstm_v1",
                        "score": 1.5,
                        "equity_return": 0.02,
                        "reward_total": 0.1,
                    }
                ],
            },
            "pbt": {
                "checkpoints": [{"checkpoint_id": "ckpt-ui"}],
                "lineage": [{"child_model_id": "ppo_lstm_v1.gen1.MODEL_LOW"}],
            },
            "series_evidence_aggregate": {
                "go_no_go": "no_go",
                "status_counts": {"pass": 5, "fail": 1, "missing": 1, "not_available": 1},
                "blocking_candidates": ["MODEL_PPO_LSTM_V1"],
                "candidate_summaries": [
                    {
                        "candidate_id": "MODEL_PPO_LSTM_V1",
                        "checkpoint_hash": "k" * 64,
                        "evidence_status": {
                            "baseline_artifact": "pass",
                            "calibration_artifact": "pass",
                            "hidden_eval_artifact": "fail",
                            "exploit_test_artifact": "missing",
                            "paired_sensitivity_artifact": "not_available",
                            "parent_gate_artifact": "fail",
                            "research_acceptance_lock": "fail",
                        },
                        "parent_eligible": False,
                        "research_claim_eligible": False,
                        "research_accepted": False,
                        "overall_status": "fail",
                        "failed_evidence": ["hidden_eval_artifact", "parent_gate_artifact", "research_acceptance_lock"],
                        "missing_evidence": ["exploit_test_artifact"],
                        "not_available_evidence": ["paired_sensitivity_artifact"],
                    }
                ],
            },
        }


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
            execution_result={"status": "NOOP", "orders": [], "trades": []},
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

    assert evaluated["status"] == "RUNNING"
    assert view["leaderboard"][0]["agent_id"] == "MODEL_PANEL_B"
    assert view["leaderboard"][0]["rank"] == 1
    assert view["leaderboard"][0]["noop"] == 1
    assert view["leaderboard"][0]["submitted"] == 0
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
    assert adapter._run_exp_btn._enabled is False


def test_arena_panel_run_experiment_updates_report_view():
    runner = _FakeExperimentRunner()
    panel = ArenaPanel(
        TrainingArenaService(agent_service=_agent_service(), session_factory=None),
        experiment_runner=runner,
    )

    report = panel.run_experiment(duration_seconds=0, retail_count=0, symbols=["001"])
    view = panel.get_view()

    assert report["episode_id"] == "episode-experiment-ui"
    assert runner.configs[0].symbols == ["001"]
    assert runner.configs[0].model_specs[0].model_id == "ppo_lstm_v1"
    assert view["experiment"]["transition_count"] == 12
    assert view["experiment"]["pbt_checkpoint_count"] == 1
    assert view["experiment"]["evidence_board"]["rows"][0]["hidden"] == "fail"
    assert view["experiment"]["evidence_board"]["rows"][0]["fee_impact_sensitivity"] == "not_available"
    assert view["controls"]["can_run_experiment"] is True


def test_arena_adapter_headless_renders_experiment_summary():
    runner = _FakeExperimentRunner()
    panel = ArenaPanel(
        TrainingArenaService(agent_service=_agent_service(), session_factory=None),
        experiment_runner=runner,
    )
    panel.run_experiment(duration_seconds=0, retail_count=0)
    adapter = ArenaPanelAdapter().bind(panel)

    adapter.widget()
    adapter.refresh()

    assert adapter._run_exp_btn._enabled is True
    assert "transitions=12" in adapter._experiment_label.text()
    assert adapter._evidence_table.rowCount() == 1
    assert adapter._evidence_table.item(0, 0).text() == "MODEL_PPO_LSTM_V1"
    assert adapter._evidence_table.item(0, 3).text() == "fail"


def view_agent_ids(agent_service):
    return {agent.agent_id for agent in agent_service.list_agents()}
