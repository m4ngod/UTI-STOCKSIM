from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json
import random

from sqlalchemy.orm import Session

from persistence.models_training import ModelEpisodeResult

from app.services.model_checkpoint_service import ModelCheckpointService


@dataclass
class PopulationEvolutionConfig:
    top_fraction: float = 0.2
    bottom_fraction: float = 0.3
    mutation_scale: float = 0.05
    hall_of_fame_limit: int = 20
    inheritance_mode: str = "full_clone_mutation"
    apply_to_agents: bool = False
    mutation_keys: list[str] = field(default_factory=lambda: ["learning_rate", "entropy_coef", "action_noise"])
    excluded_model_ids: list[str] = field(default_factory=list)
    min_parent_trade_count: int = 0
    min_parent_notional_fill_ratio: float = 0.0
    strict_parent_eligibility: bool = False
    research_acceptance: dict[str, Any] | None = None


class ModelPopulationService:
    """Minimal PBT/Hall-of-Fame service for episode-ranked models."""

    def __init__(
        self,
        session: Session,
        *,
        checkpoint_service: ModelCheckpointService | None = None,
        agent_service: Any | None = None,
        rng: random.Random | None = None,
    ):
        self.s = session
        self.checkpoints = checkpoint_service or ModelCheckpointService(session)
        self.agent_service = agent_service
        self._rng = rng or random.Random()

    def evolve_from_episode(
        self,
        episode_id: str,
        *,
        generation: int | None = None,
        config: PopulationEvolutionConfig | None = None,
    ) -> dict[str, Any]:
        cfg = config or PopulationEvolutionConfig()
        all_rows = (
            self.s.query(ModelEpisodeResult)
            .filter(ModelEpisodeResult.episode_id == episode_id)
            .order_by(ModelEpisodeResult.score.desc(), ModelEpisodeResult.agent_id.asc())
            .all()
        )
        excluded_ids = {str(item) for item in cfg.excluded_model_ids}
        rows = [row for row in all_rows if str(row.model_id) not in excluded_ids]
        if not rows:
            return {
                "episode_id": episode_id,
                "checkpoints": [],
                "lineage": [],
                "hall_of_fame": [],
                "skipped": True,
                "reason": "no_eligible_models",
                "excluded_model_ids": sorted(excluded_ids),
            }
        gen = int(generation if generation is not None else max(row.generation for row in rows))
        parent_rows = [row for row in rows if _is_parent_eligible(row, cfg)]
        if not parent_rows:
            return {
                "episode_id": episode_id,
                "generation": gen,
                "checkpoints": [],
                "lineage": [],
                "hall_of_fame": self.checkpoints.list_hall_of_fame(limit=cfg.hall_of_fame_limit),
                "skipped": True,
                "reason": "no_parent_eligible_models",
                "eligible_agents": [row.agent_id for row in rows],
                "parent_eligible_agents": [],
                "excluded_model_ids": sorted(excluded_ids),
                "parent_activity_gate": _parent_activity_gate(cfg),
                "strict_parent_gate": _strict_parent_gate(cfg),
            }
        top_n = max(1, int(round(len(parent_rows) * cfg.top_fraction)))
        bottom_n = max(1, int(round(len(rows) * cfg.bottom_fraction))) if len(rows) > 1 else 0
        winners = parent_rows[:top_n]
        winner_ids = {row.agent_id for row in winners}
        losers = [row for row in rows[-bottom_n:] if row.agent_id not in winner_ids] if bottom_n else []

        checkpoint_rows = []
        for winner in winners:
            checkpoint_rows.append(
                self.checkpoints.save_checkpoint(
                    model_id=winner.model_id,
                    agent_id=winner.agent_id,
                    generation=gen,
                    episode_id=episode_id,
                    score=winner.score,
                    meta={
                        "rank": winner.rank,
                        "equity_return": winner.equity_return,
                        "reward_total": winner.reward_total,
                    },
                    artifact={
                        "source": "model_episode_results",
                        "episode_id": winner.episode_id,
                        "agent_id": winner.agent_id,
                        "model_id": winner.model_id,
                        "generation": winner.generation,
                        "rank": winner.rank,
                        "score": winner.score,
                        "equity_start": winner.equity_start,
                        "equity_end": winner.equity_end,
                        "equity_return": winner.equity_return,
                        "max_drawdown": winner.max_drawdown,
                        "turnover": winner.turnover,
                        "fee_total": winner.fee_total,
                        "trade_count": winner.trade_count,
                        "reward_total": winner.reward_total,
                    },
                    hall_of_fame=True,
                )
            )
        lineage_rows = []
        applied_agents = []
        if checkpoint_rows:
            for idx, loser in enumerate(losers):
                parent = checkpoint_rows[idx % len(checkpoint_rows)]
                if loser.agent_id == parent.agent_id:
                    continue
                child_model_id = f"{parent.model_id}.gen{gen + 1}.{loser.agent_id}"
                mutation = self._mutation_payload(cfg)
                lineage_rows.append(
                    self.checkpoints.record_lineage(
                        child_model_id=child_model_id,
                        child_agent_id=loser.agent_id,
                        parent_model_id=parent.model_id,
                        parent_checkpoint_id=parent.checkpoint_id,
                        generation=gen + 1,
                        inheritance_mode=cfg.inheritance_mode,
                        mutation=mutation,
                        episode_id=episode_id,
                    )
                )
                if cfg.apply_to_agents and self.agent_service is not None:
                    try:
                        updated = self.agent_service.apply_model_inheritance(
                            loser.agent_id,
                            child_model_id=child_model_id,
                            parent_model_id=parent.model_id,
                            parent_checkpoint_id=parent.checkpoint_id,
                            generation=gen + 1,
                            mutation=mutation,
                            inheritance_mode=cfg.inheritance_mode,
                            episode_id=episode_id,
                        )
                        applied_agents.append(
                            {
                                "agent_id": updated.agent_id,
                                "model_id": child_model_id,
                                "params_version": updated.params_version,
                            }
                        )
                    except Exception as exc:
                        applied_agents.append(
                            {
                                "agent_id": loser.agent_id,
                                "model_id": child_model_id,
                                "error": str(exc),
                            }
                        )
        self.s.flush()
        return {
            "episode_id": episode_id,
            "generation": gen,
            "eligible_agents": [row.agent_id for row in rows],
            "parent_eligible_agents": [row.agent_id for row in parent_rows],
            "excluded_model_ids": sorted(excluded_ids),
            "parent_activity_gate": _parent_activity_gate(cfg),
            "strict_parent_gate": _strict_parent_gate(cfg),
            "winners": [row.agent_id for row in winners],
            "losers": [row.agent_id for row in losers],
            "checkpoints": [
                {
                    "checkpoint_id": row.checkpoint_id,
                    "model_id": row.model_id,
                    "agent_id": row.agent_id,
                    "score": row.score,
                    "is_hall_of_fame": bool(row.is_hall_of_fame),
                }
                for row in checkpoint_rows
            ],
            "lineage": [
                {
                    "child_model_id": row.child_model_id,
                    "child_agent_id": row.child_agent_id,
                    "parent_model_id": row.parent_model_id,
                    "parent_checkpoint_id": row.parent_checkpoint_id,
                    "generation": row.generation,
                    "inheritance_mode": row.inheritance_mode,
                }
                for row in lineage_rows
            ],
            "applied_agents": applied_agents,
            "hall_of_fame": self.checkpoints.list_hall_of_fame(limit=cfg.hall_of_fame_limit),
        }

    def _mutation_payload(self, cfg: PopulationEvolutionConfig) -> dict[str, Any]:
        return {
            key: round(self._rng.uniform(-cfg.mutation_scale, cfg.mutation_scale), 6)
            for key in cfg.mutation_keys
        }


def _parent_activity_gate(cfg: PopulationEvolutionConfig) -> dict[str, Any]:
    return {
        "min_parent_trade_count": max(0, int(cfg.min_parent_trade_count or 0)),
        "min_parent_notional_fill_ratio": max(0.0, float(cfg.min_parent_notional_fill_ratio or 0.0)),
    }


def _is_parent_eligible(row: ModelEpisodeResult, cfg: PopulationEvolutionConfig) -> bool:
    if not _strict_parent_gate_passes(cfg):
        return False
    metrics = _result_metrics(row)
    filled_activity_count = max(
        int(getattr(row, "trade_count", 0) or 0),
        int(metrics.get("filled_order_count", 0) or 0),
    )
    if filled_activity_count < max(0, int(cfg.min_parent_trade_count or 0)):
        return False
    min_fill_ratio = max(0.0, float(cfg.min_parent_notional_fill_ratio or 0.0))
    if min_fill_ratio <= 0:
        return True
    return float(metrics.get("notional_fill_ratio", 0.0) or 0.0) >= min_fill_ratio


def _strict_parent_gate(cfg: PopulationEvolutionConfig) -> dict[str, Any]:
    report = cfg.research_acceptance if isinstance(cfg.research_acceptance, dict) else {}
    sections = report.get("required_sections") if isinstance(report.get("required_sections"), dict) else {}
    lock = report.get("acceptance_lock") if isinstance(report.get("acceptance_lock"), dict) else {}
    blocking_reasons = _strict_parent_gate_blocking_reasons(cfg)
    passes = not blocking_reasons
    return {
        "enabled": bool(cfg.strict_parent_eligibility),
        "is_research_accepted": bool(report.get("is_research_accepted", False)),
        "strict_parent_eligibility_allowed": bool(report.get("strict_parent_eligibility_allowed", False)),
        "acceptance_lock": {
            "status": lock.get("status"),
            "blocking_sections": lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {},
            "reason": lock.get("reason"),
        },
        "required_sections": {
            "baseline_suite": sections.get("baseline_suite"),
            "hidden_evaluation": sections.get("hidden_evaluation"),
            "exploit_detector": sections.get("exploit_detector"),
        },
        "blocking_reasons": blocking_reasons,
        "reason": _strict_parent_gate_reason(cfg, passes),
        "passes": passes,
    }


def _strict_parent_gate_passes(cfg: PopulationEvolutionConfig) -> bool:
    return not _strict_parent_gate_blocking_reasons(cfg)


def _strict_parent_gate_blocking_reasons(cfg: PopulationEvolutionConfig) -> list[str]:
    if not bool(cfg.strict_parent_eligibility):
        return []
    reasons: list[str] = []
    report = cfg.research_acceptance if isinstance(cfg.research_acceptance, dict) else {}
    if not bool(report.get("is_research_accepted", False)):
        reasons.append("research_acceptance_not_true")
    if not bool(report.get("strict_parent_eligibility_allowed", False)):
        reasons.append("strict_parent_eligibility_not_allowed")
    lock = report.get("acceptance_lock") if isinstance(report.get("acceptance_lock"), dict) else {}
    if lock.get("status") != "open":
        reasons.append("acceptance_lock_not_open")
    blocking_sections = lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {}
    if blocking_sections:
        reasons.append("acceptance_lock_has_blocking_sections")
    sections = report.get("required_sections") if isinstance(report.get("required_sections"), dict) else {}
    for key in ("baseline_suite", "hidden_evaluation", "exploit_detector"):
        if sections.get(key) != "complete":
            reasons.append(f"{key}_not_complete")
    return reasons


def _strict_parent_gate_reason(cfg: PopulationEvolutionConfig, passes: bool) -> str:
    if not bool(cfg.strict_parent_eligibility):
        return "strict_parent_gate_disabled"
    return "strict_parent_gate_passed" if passes else "strict_parent_gate_blocked"


def _result_metrics(row: ModelEpisodeResult) -> dict[str, Any]:
    try:
        parsed = json.loads(getattr(row, "metrics_json", None) or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["ModelPopulationService", "PopulationEvolutionConfig"]
