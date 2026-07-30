import json

from app.services import runtime_model_agent as runtime_model_agent_module
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


class _StaticPolicy:
    def __init__(self, action):
        self._action = action

    def act(self, _observation):
        return self._action


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


def test_episode_result_tracks_execution_health_separately_from_open_orders():
    models_init.init_models()
    session = SessionLocal()
    try:
        service = TrainingEpisodeService(session)
        service.create_episode(episode_id="episode-execution-health", run_id="run-health", generation=1)

        acc = EpisodeAgentAccumulator(agent_id="MODEL_HEALTH", model_id="ppo_lstm_v1")
        acc.apply_step(
            account={"equity": 100_000.0},
            action={"action_type": "target_weight"},
            execution_result={
                "orders": [
                    {
                        "qty": 5000,
                        "price": 10.0,
                        "result": {"ok": True, "status": "NEW", "filled": 0, "trades": []},
                    }
                ],
                "trades": [],
            },
            reward={"step_reward": -0.0005},
        )
        row = service.upsert_result(acc, episode_id="episode-execution-health", generation=1)
        session.commit()

        metrics = json.loads(row.metrics_json)
        assert row.turnover == 0.0
        assert row.trade_count == 0
        assert metrics["submitted_order_count"] == 1
        assert metrics["open_order_count"] == 1
        assert metrics["submitted_notional"] == 50_000.0
        assert metrics["filled_notional"] == 0.0
        assert metrics["fill_ratio"] == 0.0
    finally:
        session.close()


def test_episode_result_tracks_noop_and_rejected_reasons():
    acc = EpisodeAgentAccumulator(agent_id="MODEL_REASON", model_id="random_weight_v1")
    acc.apply_step(
        account={"equity": 100_000.0},
        action={"action_type": "hold"},
        execution_result={"status": "NOOP", "orders": [], "trades": []},
        reward={"step_reward": 0.0},
    )
    acc.apply_step(
        account={"equity": 100_000.0},
        action={"action_type": "target_weight"},
        execution_result={
            "orders": [
                {
                    "qty": 100,
                    "price": 10.0,
                    "result": {"ok": False, "status": "REJECTED", "reason": "T+1 restriction"},
                },
                {
                    "qty": 0,
                    "requested_qty": 50,
                    "price": 10.0,
                    "status": "SKIPPED",
                    "skip_reason": "NO_SELLABLE_QTY",
                    "result": {"ok": True, "status": "SKIPPED", "reason": "NO_SELLABLE_QTY"},
                },
            ],
            "trades": [],
        },
        reward={"step_reward": 0.0},
    )

    metrics = acc.extra_metrics
    assert metrics["noop_count"] == 1
    assert metrics["submitted_order_count"] == 1
    assert metrics["rejected_order_count"] == 1
    assert metrics["skipped_order_count"] == 1
    assert metrics["rejected_reasons"]["T+1 restriction"] == 1
    assert metrics["rejected_reasons"]["NO_SELLABLE_QTY"] == 1
    assert "NO_SELLABLE_QTY" in metrics["rejected_reason_summary"]


def test_episode_score_uses_normalized_reward_not_absolute_turnover_penalty():
    acc = EpisodeAgentAccumulator(agent_id="MODEL_FILLED", model_id="ppo_lstm_v1")
    acc.apply_step(
        account={"equity": 100_000.0},
        action={"action_type": "target_weight"},
        execution_result={
            "orders": [
                {
                    "qty": 1000,
                    "price": 10.0,
                    "result": {"ok": True, "status": "FILLED", "filled": 1000},
                }
            ],
            "trades": [],
        },
        reward={"step_reward": -0.002},
    )

    assert acc.turnover == 10_000.0
    assert acc.score() == -0.002


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
        assert result["reward"]["components"]["delta_equity"] == 0.0
        assert result["reward"]["components"]["relative_alpha"] == 0.0
        assert metrics[0][0] == "MODEL_EP"
        assert metrics[0][1]["last_action"] == "hold"
    finally:
        session.close()


def test_runtime_model_agent_reports_open_order_health_for_unfilled_orders():
    gateway = _FakeGateway()
    agent = RuntimeModelAgent(
        agent_id="MODEL_OPEN_HEALTH",
        model_id="random_weight_v1",
        runtime_gateway=gateway,
        persist_transitions=False,
    )

    transition = agent.step_once()
    health = transition["execution_result"]["execution_health"]

    assert transition["execution_result"]["orders"]
    assert transition["execution_result"]["trades"] == []
    assert health["submitted_order_count"] >= 1
    assert health["open_order_count"] >= 1
    assert health["filled_notional"] == 0.0
    assert transition["reward"]["components"]["turnover_penalty"] == 0.0
    assert transition["reward"]["components"]["open_order_pressure_penalty"] < 0


def test_runtime_model_agent_clips_buys_to_available_cash():
    class _CashClipGateway(_FakeGateway):
        def get_account_snapshot(self, account_id):
            return {"account_id": account_id, "cash": 1_000.0, "equity": 10_000.0, "positions": []}

    gateway = _CashClipGateway()
    agent = RuntimeModelAgent(
        agent_id="MODEL_CASH_CLIP",
        model_id="cash_clip_policy",
        runtime_gateway=gateway,
        policy=_StaticPolicy(
            {
                "contract_version": "act.v1",
                "action_type": "target_weight",
                "target": {"account_id": "MODEL_CASH_CLIP", "symbols": ["001"]},
                "payload": {"weights": {"001": 1.0}, "cash_buffer_ratio": 0.0},
                "constraints": {"clip_to_limits": True},
            }
        ),
        persist_transitions=False,
    )

    transition = agent.step_once()

    assert gateway.orders[0]["qty"] == 100
    assert transition["execution_result"]["orders"][0]["requested_qty"] == 1000
    assert transition["execution_result"]["orders"][0]["clip_reason"] == "INSUFFICIENT_CASH"
    assert transition["execution_result"]["execution_health"]["submitted_order_count"] == 1


def test_runtime_model_agent_clips_sells_to_unfrozen_position_without_tplus():
    class _SellClipGateway(_FakeGateway):
        def get_account_snapshot(self, account_id):
            return {
                "account_id": account_id,
                "cash": 0.0,
                "equity": 1_000.0,
                "positions": [{"symbol": "001", "quantity": 50, "frozen_qty": 30, "avg_price": 10.0}],
            }

    gateway = _SellClipGateway()
    agent = RuntimeModelAgent(
        agent_id="MODEL_SELL_CLIP",
        model_id="sell_clip_policy",
        runtime_gateway=gateway,
        policy=_StaticPolicy(
            {
                "contract_version": "act.v1",
                "action_type": "target_weight",
                "target": {"account_id": "MODEL_SELL_CLIP", "symbols": ["001"]},
                "payload": {"weights": {"001": 0.0}, "cash_buffer_ratio": 0.0},
                "constraints": {"clip_to_limits": True},
            }
        ),
        persist_transitions=False,
    )

    transition = agent.step_once()

    assert gateway.orders[0]["side"] == "sell"
    assert gateway.orders[0]["qty"] == 20
    assert transition["execution_result"]["orders"][0]["requested_qty"] == 50
    assert transition["execution_result"]["orders"][0]["clip_reason"] == "NO_SELLABLE_QTY"


def test_runtime_model_agent_reads_unpublished_live_book_top():
    class _Order:
        is_active = True

        def __init__(self, remaining):
            self.remaining = remaining

    class _Book:
        bids = {9.99: [_Order(100)]}
        asks = {10.01: [_Order(200)]}

    class _Engine:
        def get_book(self, symbol):
            assert symbol == "001"
            return _Book()

    top = runtime_model_agent_module._book_top_from_live_book(_Engine(), "001")

    assert top == {"best_bid": 9.99, "best_ask": 10.01}
