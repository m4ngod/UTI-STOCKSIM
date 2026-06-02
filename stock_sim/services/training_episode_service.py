from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any
import uuid

from sqlalchemy.orm import Session

from stock_sim.persistence.models_training import ModelEpisodeResult, ModelTransition, TrainingEpisode
from stock_sim.rl.reward_builder import execution_notional_metrics


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


@dataclass
class EpisodeAgentAccumulator:
    agent_id: str
    model_id: str
    equity_start: float | None = None
    equity_end: float | None = None
    peak_equity: float | None = None
    max_drawdown: float = 0.0
    reward_total: float = 0.0
    turnover: float = 0.0
    fee_total: float = 0.0
    trade_count: int = 0
    step_count: int = 0
    last_action: str | None = None
    extra_metrics: dict[str, Any] = field(default_factory=dict)

    def apply_step(
        self,
        *,
        account: dict[str, Any] | None,
        action: dict[str, Any] | None,
        execution_result: dict[str, Any] | None,
        reward: dict[str, Any] | None,
    ) -> None:
        equity = _equity(account)
        if equity is not None:
            if self.equity_start is None:
                self.equity_start = equity
            self.equity_end = equity
            self.peak_equity = max(self.peak_equity or equity, equity)
            if self.peak_equity and self.peak_equity > 0:
                self.max_drawdown = max(self.max_drawdown, max(0.0, (self.peak_equity - equity) / self.peak_equity))
        self.reward_total += float((reward or {}).get("step_reward") or 0.0)
        health = _execution_health(execution_result)
        self.turnover += float(health["filled_notional"])
        self.fee_total += _fee_total(execution_result)
        self.trade_count += int(health["trade_count"])
        self.step_count += 1
        self.last_action = (action or {}).get("action_type") or self.last_action
        self._accumulate_execution_health(health)

    def score(self) -> float:
        equity_return = 0.0
        if self.equity_start and self.equity_start > 0 and self.equity_end is not None:
            equity_return = (self.equity_end - self.equity_start) / self.equity_start
        return float(equity_return + self.reward_total - self.max_drawdown)

    def to_result_kwargs(self, *, episode_id: str, generation: int, rank: int | None = None) -> dict[str, Any]:
        equity_return = None
        if self.equity_start and self.equity_start > 0 and self.equity_end is not None:
            equity_return = (self.equity_end - self.equity_start) / self.equity_start
        return {
            "episode_id": episode_id,
            "agent_id": self.agent_id,
            "model_id": self.model_id,
            "generation": int(generation),
            "score": self.score(),
            "rank": rank,
            "equity_start": self.equity_start,
            "equity_end": self.equity_end,
            "equity_return": equity_return,
            "max_drawdown": self.max_drawdown,
            "turnover": self.turnover,
            "fee_total": self.fee_total,
            "trade_count": self.trade_count,
            "reward_total": self.reward_total,
            "metrics_json": _json_dumps(
                {
                    **self.extra_metrics,
                    "step_count": self.step_count,
                    "last_action": self.last_action,
                    "turnover_ratio": self.turnover / max(float(self.equity_start or 0.0), 1.0),
                }
            ),
        }

    def _accumulate_execution_health(self, health: dict[str, Any]) -> None:
        int_keys = (
            "submitted_order_count",
            "filled_order_count",
            "open_order_count",
            "rejected_order_count",
            "skipped_order_count",
            "noop_count",
            "trade_count",
        )
        float_keys = (
            "submitted_notional",
            "filled_notional",
            "open_order_notional",
        )
        for key in int_keys:
            self.extra_metrics[key] = int(self.extra_metrics.get(key, 0) or 0) + int(health.get(key, 0) or 0)
        for key in float_keys:
            self.extra_metrics[key] = float(self.extra_metrics.get(key, 0.0) or 0.0) + float(health.get(key, 0.0) or 0.0)
        rejected_reasons = health.get("rejected_reasons")
        if isinstance(rejected_reasons, dict):
            merged = self.extra_metrics.get("rejected_reasons")
            if not isinstance(merged, dict):
                merged = {}
            for reason, count in rejected_reasons.items():
                text = str(reason or "").strip()
                if not text:
                    continue
                merged[text] = int(merged.get(text, 0) or 0) + int(count or 0)
            self.extra_metrics["rejected_reasons"] = merged
            self.extra_metrics["rejected_reason_summary"] = _format_reason_summary(merged)
        last_reason = str(health.get("last_rejected_reason") or "").strip()
        if last_reason:
            self.extra_metrics["last_rejected_reason"] = last_reason
        submitted_orders = int(self.extra_metrics.get("submitted_order_count", 0) or 0)
        submitted_notional = float(self.extra_metrics.get("submitted_notional", 0.0) or 0.0)
        self.extra_metrics["fill_ratio"] = (
            float(self.extra_metrics.get("filled_order_count", 0) or 0) / submitted_orders
            if submitted_orders > 0
            else 0.0
        )
        self.extra_metrics["notional_fill_ratio"] = (
            float(self.extra_metrics.get("filled_notional", 0.0) or 0.0) / submitted_notional
            if submitted_notional > 0
            else 0.0
        )


class TrainingEpisodeService:
    def __init__(self, session: Session):
        self.s = session

    def create_episode(
        self,
        *,
        episode_id: str | None = None,
        arena_id: str | None = None,
        run_id: str | None = None,
        generation: int = 0,
        config: dict[str, Any] | None = None,
        sim_day_start: int | None = None,
        status: str = "running",
    ) -> TrainingEpisode:
        episode_id = episode_id or f"episode-{uuid.uuid4().hex[:12]}"
        row = self.s.get(TrainingEpisode, episode_id)
        now = datetime.utcnow()
        if row is None:
            row = TrainingEpisode(
                episode_id=episode_id,
                arena_id=arena_id,
                run_id=run_id,
                generation=int(generation),
                status=status,
                started_at=now if status == "running" else None,
                created_at=now,
                updated_at=now,
                sim_day_start=sim_day_start,
                config_json=_json_dumps(config or {}),
            )
            self.s.add(row)
            self.s.flush()
            return row
        if not (row.status == "completed" and status == "running"):
            row.status = status
        row.updated_at = now
        row.started_at = row.started_at or (now if status == "running" else None)
        return row

    def record_transition(
        self,
        *,
        run_id: str | None,
        episode_id: str | None,
        arena_id: str | None,
        agent_id: str,
        model_id: str | None,
        step_index: int,
        observation: dict[str, Any] | None,
        action: dict[str, Any] | None,
        execution_result: dict[str, Any] | None,
        reward: dict[str, Any] | None,
    ) -> ModelTransition:
        row = ModelTransition(
            run_id=run_id,
            episode_id=episode_id,
            arena_id=arena_id,
            agent_id=agent_id,
            model_id=model_id,
            step_index=int(step_index),
            observation_json=_json_dumps(observation or {}),
            action_json=_json_dumps(action or {}),
            execution_json=_json_dumps(execution_result or {}),
            reward_json=_json_dumps(reward or {}),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def upsert_result(self, accumulator: EpisodeAgentAccumulator, *, episode_id: str, generation: int) -> ModelEpisodeResult:
        existing = (
            self.s.query(ModelEpisodeResult)
            .filter(ModelEpisodeResult.episode_id == episode_id, ModelEpisodeResult.agent_id == accumulator.agent_id)
            .one_or_none()
        )
        values = accumulator.to_result_kwargs(episode_id=episode_id, generation=generation)
        now = datetime.utcnow()
        if existing is None:
            row = ModelEpisodeResult(**values)
            row.created_at = now
            row.updated_at = now
            self.s.add(row)
        else:
            row = existing
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = now
        self.s.flush()
        return row

    def rank_episode(self, episode_id: str) -> list[ModelEpisodeResult]:
        rows = (
            self.s.query(ModelEpisodeResult)
            .filter(ModelEpisodeResult.episode_id == episode_id)
            .order_by(ModelEpisodeResult.score.desc(), ModelEpisodeResult.agent_id.asc())
            .all()
        )
        for idx, row in enumerate(rows, start=1):
            row.rank = idx
            row.updated_at = datetime.utcnow()
        self.s.flush()
        return rows

    def complete_episode(self, episode_id: str, *, summary: dict[str, Any] | None = None, sim_day_end: int | None = None) -> TrainingEpisode:
        row = self.s.get(TrainingEpisode, episode_id)
        if row is None:
            raise ValueError(f"training episode not found: {episode_id}")
        now = datetime.utcnow()
        row.status = "completed"
        row.ended_at = now
        row.updated_at = now
        row.sim_day_end = sim_day_end
        row.summary_json = _json_dumps(summary or {})
        return row

    def get_episode_summary(self, episode_id: str) -> dict[str, Any]:
        episode = self.s.get(TrainingEpisode, episode_id)
        results = (
            self.s.query(ModelEpisodeResult)
            .filter(ModelEpisodeResult.episode_id == episode_id)
            .order_by(ModelEpisodeResult.rank.asc().nullslast(), ModelEpisodeResult.score.desc())
            .all()
        )
        return {
            "episode": None
            if episode is None
            else {
                "episode_id": episode.episode_id,
                "arena_id": episode.arena_id,
                "run_id": episode.run_id,
                "generation": episode.generation,
                "status": episode.status,
                "summary": _json_loads(episode.summary_json),
            },
            "results": [
                {
                    "agent_id": row.agent_id,
                    "model_id": row.model_id,
                    "score": row.score,
                    "rank": row.rank,
                    "equity_return": row.equity_return,
                    "reward_total": row.reward_total,
                    "metrics": _json_loads(row.metrics_json) or {},
                }
                for row in results
            ],
        }


def _equity(account: dict[str, Any] | None) -> float | None:
    if not account:
        return None
    if account.get("equity") is not None:
        return float(account.get("equity") or 0.0)
    if account.get("cash") is not None:
        return float(account.get("cash") or 0.0)
    return None


def _execution_health(execution_result: dict[str, Any] | None) -> dict[str, Any]:
    metrics = execution_notional_metrics(execution_result)
    submitted_order_count = 0
    filled_order_count = 0
    open_order_count = 0
    rejected_order_count = 0
    skipped_order_count = 0
    noop_count = 1 if str((execution_result or {}).get("status") or "").upper() == "NOOP" else 0
    rejected_reasons: dict[str, int] = {}
    last_rejected_reason: str | None = None
    trade_count = len((execution_result or {}).get("trades") or [])
    for order in (execution_result or {}).get("orders") or []:
        result = order.get("result") if isinstance(order.get("result"), dict) else {}
        status = str(result.get("status") or order.get("status") or "").upper()
        if status == "SKIPPED":
            skipped_order_count += 1
            reason = _order_reject_reason(order, result)
            if reason:
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                last_rejected_reason = reason
            continue
        submitted_order_count += 1
        ok = bool(result.get("ok", True))
        if not ok or status == "REJECTED":
            rejected_order_count += 1
            reason = _order_reject_reason(order, result)
            if reason:
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                last_rejected_reason = reason
        filled_qty = float(result.get("filled") or order.get("filled") or 0.0)
        nested_trades = result.get("trades") or []
        if filled_qty > 0 or nested_trades:
            filled_order_count += 1
        if ok and status not in {"FILLED", "REJECTED", "CANCELED", "CANCELLED"} and not (filled_qty > 0 or nested_trades):
            open_order_count += 1
    return {
        "submitted_order_count": submitted_order_count,
        "filled_order_count": filled_order_count,
        "open_order_count": open_order_count,
        "rejected_order_count": rejected_order_count,
        "skipped_order_count": skipped_order_count,
        "noop_count": noop_count,
        "trade_count": trade_count,
        "rejected_reasons": rejected_reasons,
        "last_rejected_reason": last_rejected_reason,
        **metrics,
    }


def _fee_total(execution_result: dict[str, Any] | None) -> float:
    total = float((execution_result or {}).get("fee_total") or 0.0)
    for trade in (execution_result or {}).get("trades") or []:
        total += float(trade.get("fee") or trade.get("fees") or 0.0)
    return total


def _order_reject_reason(order: dict[str, Any], result: dict[str, Any]) -> str | None:
    for value in (
        result.get("reason"),
        result.get("error"),
        order.get("skip_reason"),
        order.get("clip_reason"),
        result.get("status"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return None


def _format_reason_summary(reasons: dict[str, Any]) -> str:
    ranked = sorted(
        ((str(reason), int(count or 0)) for reason, count in reasons.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return ", ".join(f"{reason} x{count}" for reason, count in ranked[:3] if count > 0)


__all__ = ["EpisodeAgentAccumulator", "TrainingEpisodeService"]
