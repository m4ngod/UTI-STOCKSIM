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
        artifact: dict[str, Any] | None = None,
        path: str | None = None,
        hall_of_fame: bool = False,
        write_artifact: bool = True,
    ) -> ModelCheckpoint:
        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:12]}"
        resolved_path = path or str(self.checkpoint_root / str(model_id) / f"{checkpoint_id}.json")
        created_at = datetime.utcnow()
        meta_payload = dict(meta or {})
        meta_payload.setdefault("artifact_schema", "stock_sim.model_checkpoint.v1")
        meta_payload["artifact_written"] = False
        if write_artifact:
            self._write_checkpoint_artifact(
                path=resolved_path,
                payload={
                    "schema": "stock_sim.model_checkpoint.v1",
                    "checkpoint_id": checkpoint_id,
                    "model_id": model_id,
                    "agent_id": agent_id,
                    "generation": int(generation),
                    "episode_id": episode_id,
                    "score": None if score is None else float(score),
                    "hall_of_fame": bool(hall_of_fame),
                    "created_at": created_at.isoformat(timespec="seconds") + "Z",
                    "meta": dict(meta or {}),
                    "artifact": artifact or {},
                },
            )
            meta_payload["artifact_written"] = True
        row = ModelCheckpoint(
            checkpoint_id=checkpoint_id,
            model_id=model_id,
            agent_id=agent_id,
            generation=int(generation),
            episode_id=episode_id,
            path=resolved_path,
            score=None if score is None else float(score),
            is_hall_of_fame=1 if hall_of_fame else 0,
            created_at=created_at,
            meta_json=_json_dumps(meta_payload),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def save_tensor_checkpoint(
        self,
        *,
        model_id: str,
        tensors: dict[str, Any],
        agent_id: str | None,
        generation: int,
        episode_id: str | None,
        score: float | None,
        meta: dict[str, Any] | None = None,
        path: str | None = None,
        hall_of_fame: bool = False,
    ) -> ModelCheckpoint:
        if not isinstance(tensors, dict) or not tensors:
            raise ValueError("tensors must be a non-empty dict")
        row = self.save_checkpoint(
            model_id=model_id,
            agent_id=agent_id,
            generation=generation,
            episode_id=episode_id,
            score=score,
            meta={**(meta or {}), "artifact_schema": "stock_sim.tensor_checkpoint.v1"},
            path=path,
            hall_of_fame=hall_of_fame,
            write_artifact=False,
        )
        manifest_path = Path(row.path)
        tensor_path = manifest_path.with_suffix(".npz")
        manifest = self._write_tensor_checkpoint_artifact(
            manifest_path=manifest_path,
            tensor_path=tensor_path,
            checkpoint_id=row.checkpoint_id,
            model_id=model_id,
            agent_id=agent_id,
            generation=int(generation),
            episode_id=episode_id,
            score=score,
            hall_of_fame=hall_of_fame,
            tensors=tensors,
            meta=meta or {},
        )
        meta_payload = _json_loads(row.meta_json) or {}
        meta_payload.update(
            {
                "artifact_schema": "stock_sim.tensor_checkpoint.v1",
                "artifact_written": True,
                "tensor_file": str(tensor_path),
                "tensor_count": len(manifest.get("tensors") or {}),
            }
        )
        row.meta_json = _json_dumps(meta_payload)
        self.s.flush()
        return row

    def load_tensor_checkpoint(self, checkpoint: str | ModelCheckpoint) -> dict[str, Any]:
        row: ModelCheckpoint | None
        if isinstance(checkpoint, ModelCheckpoint):
            row = checkpoint
        else:
            raw = str(checkpoint)
            row = self.s.get(ModelCheckpoint, raw)
            if row is None and Path(raw).exists():
                return self._read_tensor_checkpoint_artifact(Path(raw))
        if row is None:
            raise ValueError(f"checkpoint not found: {checkpoint}")
        return self._read_tensor_checkpoint_artifact(Path(row.path))

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

    @staticmethod
    def _write_checkpoint_artifact(*, path: str, payload: dict[str, Any]) -> None:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(_json_dumps(payload), encoding="utf-8")

    @staticmethod
    def _write_tensor_checkpoint_artifact(
        *,
        manifest_path: Path,
        tensor_path: Path,
        checkpoint_id: str,
        model_id: str,
        agent_id: str | None,
        generation: int,
        episode_id: str | None,
        score: float | None,
        hall_of_fame: bool,
        tensors: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        import numpy as np

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tensor_path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {str(name): np.asarray(value) for name, value in tensors.items()}
        np.savez_compressed(tensor_path, **arrays)
        manifest = {
            "schema": "stock_sim.tensor_checkpoint.v1",
            "checkpoint_id": checkpoint_id,
            "model_id": model_id,
            "agent_id": agent_id,
            "generation": int(generation),
            "episode_id": episode_id,
            "score": None if score is None else float(score),
            "hall_of_fame": bool(hall_of_fame),
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tensor_file": tensor_path.name,
            "tensors": {
                name: {
                    "shape": list(array.shape),
                    "dtype": str(array.dtype),
                }
                for name, array in arrays.items()
            },
            "meta": dict(meta or {}),
        }
        manifest_path.write_text(_json_dumps(manifest), encoding="utf-8")
        return manifest

    @staticmethod
    def _read_tensor_checkpoint_artifact(manifest_path: Path) -> dict[str, Any]:
        import numpy as np

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tensor_path = Path(str(manifest.get("tensor_file") or ""))
        if not tensor_path.is_absolute():
            tensor_path = manifest_path.parent / tensor_path
        with np.load(tensor_path, allow_pickle=False) as data:
            tensors = {name: data[name].copy() for name in data.files}
        return {"manifest": manifest, "tensors": tensors}


__all__ = ["ModelCheckpointService"]
