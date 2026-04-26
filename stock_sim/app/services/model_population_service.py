from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import random

from sqlalchemy.orm import Session

from stock_sim.persistence.models_training import ModelEpisodeResult

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
        rows = (
            self.s.query(ModelEpisodeResult)
            .filter(ModelEpisodeResult.episode_id == episode_id)
            .order_by(ModelEpisodeResult.score.desc(), ModelEpisodeResult.agent_id.asc())
            .all()
        )
        if not rows:
            return {"episode_id": episode_id, "checkpoints": [], "lineage": [], "hall_of_fame": []}
        gen = int(generation if generation is not None else max(row.generation for row in rows))
        top_n = max(1, int(round(len(rows) * cfg.top_fraction)))
        bottom_n = max(1, int(round(len(rows) * cfg.bottom_fraction))) if len(rows) > 1 else 0
        winners = rows[:top_n]
        losers = rows[-bottom_n:] if bottom_n else []

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
                                "model_id": updated.model_id,
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


__all__ = ["ModelPopulationService", "PopulationEvolutionConfig"]
