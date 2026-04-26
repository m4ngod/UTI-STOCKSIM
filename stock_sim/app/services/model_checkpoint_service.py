from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
import uuid

from sqlalchemy.orm import Session

from stock_sim.persistence.models_training import ModelCheckpoint, ModelLineage


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


class ModelCheckpointService:
    def __init__(self, session: Session, *, checkpoint_root: str | Path = "output/model_checkpoints"):
        self.s = session
        self.checkpoint_root = Path(checkpoint_root)

    def save_checkpoint(
        self,
        *,
        model_id: str,
        agent_id: str | None,
        generation: int,
        episode_id: str | None,
        score: float | None,
        meta: dict[str, Any] | None = None,
        path: str | None = None,
        hall_of_fame: bool = False,
    ) -> ModelCheckpoint:
        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:12]}"
        resolved_path = path or str(self.checkpoint_root / str(model_id) / f"{checkpoint_id}.json")
        row = ModelCheckpoint(
            checkpoint_id=checkpoint_id,
            model_id=model_id,
            agent_id=agent_id,
            generation=int(generation),
            episode_id=episode_id,
            path=resolved_path,
            score=None if score is None else float(score),
            is_hall_of_fame=1 if hall_of_fame else 0,
            created_at=datetime.utcnow(),
            meta_json=_json_dumps(meta or {}),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def mark_hall_of_fame(self, checkpoint_id: str) -> ModelCheckpoint:
        row = self.s.get(ModelCheckpoint, checkpoint_id)
        if row is None:
            raise ValueError(f"checkpoint not found: {checkpoint_id}")
        row.is_hall_of_fame = 1
        self.s.flush()
        return row

    def list_hall_of_fame(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = (
            self.s.query(ModelCheckpoint)
            .filter(ModelCheckpoint.is_hall_of_fame == 1)
            .order_by(ModelCheckpoint.score.desc().nullslast(), ModelCheckpoint.created_at.desc())
            .limit(int(limit))
            .all()
        )
        return [self._checkpoint_to_dict(row) for row in rows]

    def record_lineage(
        self,
        *,
        child_model_id: str,
        child_agent_id: str | None,
        parent_model_id: str,
        parent_checkpoint_id: str | None,
        generation: int,
        inheritance_mode: str = "full_clone_mutation",
        mutation: dict[str, Any] | None = None,
        episode_id: str | None = None,
    ) -> ModelLineage:
        row = ModelLineage(
            child_model_id=child_model_id,
            child_agent_id=child_agent_id,
            parent_model_id=parent_model_id,
            parent_checkpoint_id=parent_checkpoint_id,
            generation=int(generation),
            inheritance_mode=inheritance_mode,
            mutation_json=_json_dumps(mutation or {}),
            episode_id=episode_id,
            created_at=datetime.utcnow(),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def get_lineage(self, child_model_id: str) -> list[dict[str, Any]]:
        rows = (
            self.s.query(ModelLineage)
            .filter(ModelLineage.child_model_id == child_model_id)
            .order_by(ModelLineage.created_at.asc())
            .all()
        )
        return [
            {
                "child_model_id": row.child_model_id,
                "child_agent_id": row.child_agent_id,
                "parent_model_id": row.parent_model_id,
                "parent_checkpoint_id": row.parent_checkpoint_id,
                "generation": row.generation,
                "inheritance_mode": row.inheritance_mode,
                "mutation": _json_loads(row.mutation_json) or {},
                "episode_id": row.episode_id,
            }
            for row in rows
        ]

    @staticmethod
    def _checkpoint_to_dict(row: ModelCheckpoint) -> dict[str, Any]:
        return {
            "checkpoint_id": row.checkpoint_id,
            "model_id": row.model_id,
            "agent_id": row.agent_id,
            "generation": row.generation,
            "episode_id": row.episode_id,
            "path": row.path,
            "score": row.score,
            "is_hall_of_fame": bool(row.is_hall_of_fame),
            "meta": _json_loads(row.meta_json) or {},
        }


__all__ = ["ModelCheckpointService"]
