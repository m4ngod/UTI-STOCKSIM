from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
import uuid

from app.services.agent_service import AgentService, BatchCreateConfig

try:
    from stock_sim.persistence.models_imports import SessionLocal
    from stock_sim.services.training_episode_service import TrainingEpisodeService
except Exception:  # pragma: no cover
    SessionLocal = None  # type: ignore
    TrainingEpisodeService = None  # type: ignore


ARENA_STATES = {
    "CREATED",
    "READY",
    "RUNNING",
    "PAUSED",
    "EVALUATING",
    "EVOLVING",
    "STOPPED",
    "FAILED",
}


@dataclass
class ArenaModelSpec:
    agent_id: str | None = None
    model_id: str = "hold_model_v1"
    mode: str = "collect_only"
    initial_cash: float = 100_000.0


@dataclass
class TrainingArenaConfig:
    arena_id: str | None = None
    model_specs: list[ArenaModelSpec] = field(default_factory=list)
    retail_count: int = 0
    retail_initial_cash: float = 100_000.0
    symbols: list[str] = field(default_factory=list)
    generation: int = 0
    episode_prefix: str = "episode"
    reward_profile: str = "relative_equity_risk_adjusted_v1"


@dataclass
class TrainingArenaState:
    arena_id: str
    status: str
    config: TrainingArenaConfig
    model_agent_ids: list[str] = field(default_factory=list)
    retail_agent_ids: list[str] = field(default_factory=list)
    current_episode_id: str | None = None
    last_summary: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arena_id": self.arena_id,
            "status": self.status,
            "model_agent_ids": list(self.model_agent_ids),
            "retail_agent_ids": list(self.retail_agent_ids),
            "current_episode_id": self.current_episode_id,
            "generation": self.config.generation,
            "symbols": list(self.config.symbols),
            "last_summary": self.last_summary,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TrainingArenaService:
    """Service-layer Arena MVP for multi-model training episodes."""

    def __init__(
        self,
        *,
        agent_service: AgentService,
        session_factory: Callable[[], Any] | None = None,
    ):
        self._agent_service = agent_service
        self._session_factory = session_factory or SessionLocal
        self._arenas: dict[str, TrainingArenaState] = {}

    def create_arena(self, config: TrainingArenaConfig | dict[str, Any]) -> dict[str, Any]:
        cfg = _coerce_config(config)
        arena_id = cfg.arena_id or f"arena-{uuid.uuid4().hex[:10]}"
        if arena_id in self._arenas:
            raise ValueError(f"arena already exists: {arena_id}")
        state = TrainingArenaState(
            arena_id=arena_id,
            status="READY" if cfg.model_specs else "CREATED",
            config=cfg,
        )
        self._arenas[arena_id] = state
        return state.to_dict()

    def start_arena(self, arena_id: str, *, episode_id: str | None = None) -> dict[str, Any]:
        state = self._require_arena(arena_id)
        if state.status == "RUNNING":
            return state.to_dict()
        if not state.config.model_specs:
            state.status = "FAILED"
            state.updated_at = datetime.utcnow()
            raise ValueError("arena requires at least one model")
        episode_id = episode_id or f"{state.config.episode_prefix}-{arena_id}-{uuid.uuid4().hex[:8]}"
        state.current_episode_id = episode_id
        self._ensure_episode(state)
        self._ensure_model_agents(state)
        self._ensure_retail_agents(state)
        for agent_id in state.model_agent_ids + state.retail_agent_ids:
            try:
                self._agent_service.control(agent_id, "start")
            except Exception:
                pass
        state.status = "RUNNING"
        state.updated_at = datetime.utcnow()
        return state.to_dict()

    def stop_arena(self, arena_id: str) -> dict[str, Any]:
        state = self._require_arena(arena_id)
        for agent_id in state.model_agent_ids + state.retail_agent_ids:
            try:
                self._agent_service.control(agent_id, "stop")
            except Exception:
                pass
        state.status = "STOPPED"
        state.updated_at = datetime.utcnow()
        return state.to_dict()

    def evaluate_arena(self, arena_id: str, *, complete_episode: bool = True) -> dict[str, Any]:
        state = self._require_arena(arena_id)
        if not state.current_episode_id:
            raise ValueError("arena has no active episode")
        state.status = "EVALUATING"
        state.updated_at = datetime.utcnow()
        if self._session_factory is None or TrainingEpisodeService is None:
            summary = {"episode": {"episode_id": state.current_episode_id}, "results": []}
        else:
            session = self._session_factory()
            try:
                service = TrainingEpisodeService(session)
                ranked = service.rank_episode(state.current_episode_id)
                if complete_episode:
                    service.complete_episode(
                        state.current_episode_id,
                        summary={"result_count": len(ranked), "arena_id": arena_id},
                    )
                summary = service.get_episode_summary(state.current_episode_id)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        state.last_summary = summary
        state.status = "STOPPED" if complete_episode else "READY"
        state.updated_at = datetime.utcnow()
        return state.to_dict()

    def get_arena(self, arena_id: str) -> dict[str, Any]:
        return self._require_arena(arena_id).to_dict()

    def list_arenas(self) -> list[dict[str, Any]]:
        return [state.to_dict() for state in self._arenas.values()]

    def _ensure_episode(self, state: TrainingArenaState) -> None:
        if self._session_factory is None or TrainingEpisodeService is None:
            return
        session = self._session_factory()
        try:
            service = TrainingEpisodeService(session)
            service.create_episode(
                episode_id=state.current_episode_id,
                arena_id=state.arena_id,
                run_id=_safe_call(getattr(self._agent_service, "_active_runtime_run_id", None)),
                generation=state.config.generation,
                config={
                    "symbols": list(state.config.symbols),
                    "model_count": len(state.config.model_specs),
                    "retail_count": state.config.retail_count,
                    "reward_profile": state.config.reward_profile,
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _ensure_model_agents(self, state: TrainingArenaState) -> None:
        if state.model_agent_ids:
            return
        for idx, spec in enumerate(state.config.model_specs, start=1):
            agent_id = spec.agent_id or f"{state.arena_id}_MODEL_{idx:02d}"
            existing = self._agent_service.get(agent_id)
            if existing is None:
                meta = self._agent_service.create_model_agent(
                    agent_id=agent_id,
                    model_id=spec.model_id,
                    mode=spec.mode,
                    initial_cash=spec.initial_cash,
                    episode_id=state.current_episode_id,
                )
                agent_id = meta.agent_id
            state.model_agent_ids.append(agent_id)

    def _ensure_retail_agents(self, state: TrainingArenaState) -> None:
        if state.config.retail_count <= 0 or state.retail_agent_ids:
            return
        result = self._agent_service.batch_create_retail(
            BatchCreateConfig(
                count=state.config.retail_count,
                agent_type="Retail",
                initial_cash=state.config.retail_initial_cash,
            )
        )
        state.retail_agent_ids = list(result.get("success_ids") or [])

    def _require_arena(self, arena_id: str) -> TrainingArenaState:
        state = self._arenas.get(arena_id)
        if state is None:
            raise KeyError(f"arena not found: {arena_id}")
        return state


def _safe_call(fn: Any) -> Any:
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def _coerce_config(value: TrainingArenaConfig | dict[str, Any]) -> TrainingArenaConfig:
    if isinstance(value, TrainingArenaConfig):
        return value
    raw_specs = list(value.get("model_specs") or [])
    specs = [
        spec
        if isinstance(spec, ArenaModelSpec)
        else ArenaModelSpec(
            agent_id=spec.get("agent_id"),
            model_id=spec.get("model_id", "hold_model_v1"),
            mode=spec.get("mode", "collect_only"),
            initial_cash=float(spec.get("initial_cash", 100_000.0)),
        )
        for spec in raw_specs
    ]
    return TrainingArenaConfig(
        arena_id=value.get("arena_id"),
        model_specs=specs,
        retail_count=int(value.get("retail_count", 0) or 0),
        retail_initial_cash=float(value.get("retail_initial_cash", 100_000.0) or 100_000.0),
        symbols=list(value.get("symbols") or []),
        generation=int(value.get("generation", 0) or 0),
        episode_prefix=str(value.get("episode_prefix", "episode") or "episode"),
        reward_profile=str(value.get("reward_profile", "relative_equity_risk_adjusted_v1") or "relative_equity_risk_adjusted_v1"),
    )


__all__ = [
    "ARENA_STATES",
    "ArenaModelSpec",
    "TrainingArenaConfig",
    "TrainingArenaService",
    "TrainingArenaState",
]
